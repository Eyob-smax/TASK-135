"""
API integration tests for /api/v1/resources/ endpoints.
"""
from __future__ import annotations

import io
import uuid

import pytest
from sqlalchemy import select

from district_console.infrastructure.orm import UserORM


async def _user_id_by_username(db_session, username: str) -> str:
    result = await db_session.execute(
        select(UserORM.id).where(UserORM.username == username)
    )
    user_id = result.scalar_one_or_none()
    assert user_id is not None
    return user_id


class TestResourceRoutes:
    async def test_list_resources_returns_paginated(self, http_client, admin_headers):
        response = await http_client.get(
            "/api/v1/resources/", headers=admin_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert "items" in body
        assert "total" in body

    async def test_list_resources_without_auth_returns_401(self, http_client):
        response = await http_client.get("/api/v1/resources/")
        assert response.status_code == 401

    async def test_get_resource_not_found_returns_404(self, http_client, admin_headers):
        fake_id = str(uuid.uuid4())
        response = await http_client.get(
            f"/api/v1/resources/{fake_id}", headers=admin_headers
        )
        assert response.status_code == 404

    async def test_create_resource_returns_201(self, http_client, librarian_headers):
        response = await http_client.post(
            "/api/v1/resources/",
            headers=librarian_headers,
            json={"title": "New Book", "resource_type": "BOOK"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["title"] == "New Book"
        assert body["status"] == "DRAFT"

    async def test_create_resource_without_permission_returns_403(
        self, http_client, auth_headers
    ):
        # testuser has no roles, so no resources.create permission
        response = await http_client.post(
            "/api/v1/resources/",
            headers=auth_headers,
            json={"title": "Forbidden", "resource_type": "BOOK"},
        )
        assert response.status_code == 403

    async def test_import_file_creates_resource(self, http_client, librarian_headers):
        content = b"PDF content bytes for import test"
        response = await http_client.post(
            "/api/v1/resources/import/file",
            headers=librarian_headers,
            data={"resource_type": "BOOK", "title": "Imported Book"},
            files={"file": ("book.pdf", content, "application/pdf")},
        )
        assert response.status_code == 201
        body = response.json()
        assert "resource_id" in body
        assert body["is_duplicate"] is False

    async def test_import_file_duplicate_returns_409(self, http_client, librarian_headers):
        content = b"duplicate content bytes"
        # First import
        await http_client.post(
            "/api/v1/resources/import/file",
            headers=librarian_headers,
            data={"resource_type": "BOOK", "title": "Dup Book"},
            files={"file": ("dup.pdf", content, "application/pdf")},
        )
        # Second import with same content
        response = await http_client.post(
            "/api/v1/resources/import/file",
            headers=librarian_headers,
            data={"resource_type": "BOOK", "title": "Dup Book"},
            files={"file": ("dup2.pdf", content, "application/pdf")},
        )
        assert response.status_code == 409

    async def test_submit_for_review_transitions_to_in_review(
        self, http_client, db_session, librarian_headers, reviewer_headers
    ):
        # Create resource
        create_resp = await http_client.post(
            "/api/v1/resources/",
            headers=librarian_headers,
            json={"title": "Review Me", "resource_type": "ARTICLE"},
        )
        assert create_resp.status_code == 201
        resource_id = create_resp.json()["resource_id"]

        reviewer_id = await _user_id_by_username(db_session, "reviewer_user")
        submit_resp = await http_client.post(
            f"/api/v1/resources/{resource_id}/submit-review",
            headers=librarian_headers,
            json={"reviewer_id": reviewer_id},
        )
        assert submit_resp.status_code == 200
        assert submit_resp.json()["status"] == "IN_REVIEW"

    async def test_publish_requires_reviewer_notes_non_empty(
        self, http_client, db_session, librarian_headers, reviewer_headers
    ):
        create_resp = await http_client.post(
            "/api/v1/resources/",
            headers=librarian_headers,
            json={"title": "Publish Test", "resource_type": "BOOK"},
        )
        resource_id = create_resp.json()["resource_id"]
        reviewer_id = await _user_id_by_username(db_session, "reviewer_user")
        await http_client.post(
            f"/api/v1/resources/{resource_id}/submit-review",
            headers=librarian_headers,
            json={"reviewer_id": reviewer_id},
        )
        response = await http_client.post(
            f"/api/v1/resources/{resource_id}/publish",
            headers=reviewer_headers,
            json={"reviewer_notes": "  "},
        )
        assert response.status_code in (400, 422)

    async def test_list_revisions_returns_history(self, http_client, admin_headers):
        create_resp = await http_client.post(
            "/api/v1/resources/",
            headers=admin_headers,
            json={"title": "Revision Book", "resource_type": "BOOK"},
        )
        resource_id = create_resp.json()["resource_id"]
        rev_resp = await http_client.get(
            f"/api/v1/resources/{resource_id}/revisions",
            headers=admin_headers,
        )
        assert rev_resp.status_code == 200
        revisions = rev_resp.json()
        assert len(revisions) == 1
        assert revisions[0]["revision_number"] == 1

    async def test_update_resource_draft_returns_200(
        self, http_client, admin_headers
    ):
        """PUT on a DRAFT resource updates the title."""
        create_resp = await http_client.post(
            "/api/v1/resources/",
            headers=admin_headers,
            json={"title": "Original Title", "resource_type": "BOOK"},
        )
        assert create_resp.status_code == 201
        resource_id = create_resp.json()["resource_id"]

        update_resp = await http_client.put(
            f"/api/v1/resources/{resource_id}",
            headers=admin_headers,
            json={"title": "Updated Title"},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["title"] == "Updated Title"

    async def test_update_resource_non_draft_returns_409(
        self, http_client, db_session, admin_headers, reviewer_headers
    ):
        """PUT on an IN_REVIEW resource must be rejected (INVALID_STATE_TRANSITION)."""
        create_resp = await http_client.post(
            "/api/v1/resources/",
            headers=admin_headers,
            json={"title": "Review Me", "resource_type": "BOOK"},
        )
        resource_id = create_resp.json()["resource_id"]

        # Transition to IN_REVIEW
        await http_client.post(
            f"/api/v1/resources/{resource_id}/submit-review",
            headers=admin_headers,
            json={"reviewer_id": await _user_id_by_username(db_session, "reviewer_user")},
        )

        update_resp = await http_client.put(
            f"/api/v1/resources/{resource_id}",
            headers=admin_headers,
            json={"title": "Should Fail"},
        )
        assert update_resp.status_code == 409

    async def test_update_resource_not_found_returns_404(
        self, http_client, admin_headers
    ):
        resp = await http_client.put(
            f"/api/v1/resources/{uuid.uuid4()}",
            headers=admin_headers,
            json={"title": "Ghost"},
        )
        assert resp.status_code == 404

    async def test_unpublish_resource_returns_200(
        self, http_client, db_session, librarian_headers, reviewer_headers
    ):
        """Full happy path: DRAFT → IN_REVIEW → PUBLISHED → UNPUBLISHED."""
        create_resp = await http_client.post(
            "/api/v1/resources/",
            headers=librarian_headers,
            json={"title": "Unpublish Me", "resource_type": "BOOK"},
        )
        resource_id = create_resp.json()["resource_id"]

        await http_client.post(
            f"/api/v1/resources/{resource_id}/submit-review",
            headers=librarian_headers,
            json={"reviewer_id": await _user_id_by_username(db_session, "reviewer_user")},
        )
        await http_client.post(
            f"/api/v1/resources/{resource_id}/publish",
            headers=reviewer_headers,
            json={"reviewer_notes": "Looks good"},
        )

        unpublish_resp = await http_client.post(
            f"/api/v1/resources/{resource_id}/unpublish",
            headers=reviewer_headers,
            json={"reviewer_notes": "Archiving for update"},
        )
        assert unpublish_resp.status_code == 200
        assert unpublish_resp.json()["status"] == "UNPUBLISHED"

    async def test_publish_draft_without_review_returns_409(
        self, http_client, librarian_headers, reviewer_headers
    ):
        """Publishing a DRAFT resource (skipping review) must return 409
        INVALID_STATE_TRANSITION because DRAFT → PUBLISHED is not allowed."""
        create_resp = await http_client.post(
            "/api/v1/resources/",
            headers=librarian_headers,
            json={"title": "Skip Review", "resource_type": "BOOK"},
        )
        assert create_resp.status_code == 201
        resource_id = create_resp.json()["resource_id"]

        # Attempt to publish a DRAFT (bypassing IN_REVIEW)
        publish_resp = await http_client.post(
            f"/api/v1/resources/{resource_id}/publish",
            headers=reviewer_headers,
            json={"reviewer_notes": "Trying to skip review"},
        )
        # Must reject — DRAFT cannot transition directly to PUBLISHED
        assert publish_resp.status_code in (409, 422)

    async def test_import_csv_creates_multiple_resources(
        self, http_client, librarian_headers
    ):
        """CSV bulk import should return created/duplicate counts."""
        csv_content = (
            "title,resource_type,isbn\n"
            "CSV Book One,BOOK,978-0-000000-01-0\n"
            "CSV Book Two,ARTICLE,\n"
        ).encode("utf-8")

        resp = await http_client.post(
            "/api/v1/resources/import/csv",
            headers=librarian_headers,
            files={"file": ("batch.csv", csv_content, "text/csv")},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "created" in body
        assert "duplicates" in body
        assert "errors" in body
        assert len(body["created"]) >= 1

    async def test_list_resources_with_status_filter(
        self, http_client, admin_headers
    ):
        """List resources filtered by status returns only matching items."""
        # Create a DRAFT resource first
        await http_client.post(
            "/api/v1/resources/",
            headers=admin_headers,
            json={"title": "Filtered Resource", "resource_type": "BOOK"},
        )

        resp = await http_client.get(
            "/api/v1/resources/",
            headers=admin_headers,
            params={"status": "DRAFT"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert all(r["status"] == "DRAFT" for r in body["items"])

    async def test_revisions_not_found_returns_404(
        self, http_client, admin_headers
    ):
        resp = await http_client.get(
            f"/api/v1/resources/{uuid.uuid4()}/revisions",
            headers=admin_headers,
        )
        assert resp.status_code == 404

    async def test_publish_not_found_returns_404(
        self, http_client, reviewer_headers
    ):
        resp = await http_client.post(
            f"/api/v1/resources/{uuid.uuid4()}/publish",
            headers=reviewer_headers,
            json={"reviewer_notes": "Some notes"},
        )
        assert resp.status_code == 404

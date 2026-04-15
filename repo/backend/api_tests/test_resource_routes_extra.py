"""
Additional integration tests for /api/v1/resources/ error branches.
"""
from __future__ import annotations

import io
import uuid


async def test_get_resource_not_found_returns_404(http_client, admin_headers):
    resp = await http_client.get(
        f"/api/v1/resources/{uuid.uuid4()}",
        headers=admin_headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "NOT_FOUND"


async def test_get_resource_success_returns_200(
    http_client, admin_headers, seeded_resource
):
    resp = await http_client.get(
        f"/api/v1/resources/{seeded_resource.id}",
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["resource_id"] == seeded_resource.id


async def test_update_resource_not_found_returns_404(http_client, admin_headers):
    resp = await http_client.put(
        f"/api/v1/resources/{uuid.uuid4()}",
        headers=admin_headers,
        json={"title": "X"},
    )
    assert resp.status_code == 404


async def test_update_resource_success_when_draft(
    http_client, admin_headers, seeded_resource
):
    resp = await http_client.put(
        f"/api/v1/resources/{seeded_resource.id}",
        headers=admin_headers,
        json={"title": "Renamed Title", "isbn": "NEW-ISBN-123"},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Renamed Title"


async def test_list_revisions_not_found_returns_404(http_client, admin_headers):
    resp = await http_client.get(
        f"/api/v1/resources/{uuid.uuid4()}/revisions",
        headers=admin_headers,
    )
    assert resp.status_code == 404


async def test_submit_for_review_not_found_returns_404(http_client, admin_headers, seeded_user_orm):
    resp = await http_client.post(
        f"/api/v1/resources/{uuid.uuid4()}/submit-review",
        headers=admin_headers,
        json={"reviewer_id": seeded_user_orm.id},
    )
    assert resp.status_code == 404


async def test_publish_resource_not_found_returns_404(http_client, admin_headers):
    resp = await http_client.post(
        f"/api/v1/resources/{uuid.uuid4()}/publish",
        headers=admin_headers,
        json={"reviewer_notes": "ok"},
    )
    assert resp.status_code == 404


async def test_unpublish_resource_not_found_returns_404(http_client, admin_headers):
    resp = await http_client.post(
        f"/api/v1/resources/{uuid.uuid4()}/unpublish",
        headers=admin_headers,
        json={"reviewer_notes": "ok"},
    )
    assert resp.status_code == 404


async def test_classify_resource_not_found_returns_404(http_client, admin_headers):
    resp = await http_client.post(
        f"/api/v1/resources/{uuid.uuid4()}/classify",
        headers=admin_headers,
        json={"min_age": 6, "max_age": 12, "timeliness_type": "EVERGREEN"},
    )
    assert resp.status_code == 404


async def test_classify_resource_success_returns_204(
    http_client, admin_headers, seeded_resource
):
    resp = await http_client.post(
        f"/api/v1/resources/{seeded_resource.id}/classify",
        headers=admin_headers,
        json={"min_age": 8, "max_age": 10, "timeliness_type": "EVERGREEN"},
    )
    assert resp.status_code == 204


async def test_request_allocation_not_found_returns_404(http_client, admin_headers):
    resp = await http_client.post(
        f"/api/v1/resources/{uuid.uuid4()}/request-allocation",
        headers=admin_headers,
    )
    assert resp.status_code == 404


async def test_request_allocation_success_returns_204(
    http_client, admin_headers, seeded_resource
):
    resp = await http_client.post(
        f"/api/v1/resources/{seeded_resource.id}/request-allocation",
        headers=admin_headers,
    )
    assert resp.status_code == 204


async def test_create_resource_success(http_client, admin_headers):
    resp = await http_client.post(
        "/api/v1/resources/",
        headers=admin_headers,
        json={
            "title": "Brand New Book",
            "resource_type": "BOOK",
            "isbn": "978-0-99-123456-7",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Brand New Book"
    assert body["status"] == "DRAFT"


async def test_create_resource_duplicate_returns_409(http_client, admin_headers):
    # Same title and ISBN twice → same fingerprint → dedup triggers
    payload = {
        "title": "Same Book",
        "resource_type": "BOOK",
        "isbn": "978-0-DUP-XX",
    }
    first = await http_client.post("/api/v1/resources/", headers=admin_headers, json=payload)
    assert first.status_code == 201
    second = await http_client.post("/api/v1/resources/", headers=admin_headers, json=payload)
    assert second.status_code == 409


async def test_import_csv_returns_200(http_client, admin_headers):
    csv_payload = (
        "title,resource_type,isbn\n"
        "CSV Book 1,BOOK,CSV-001\n"
        "CSV Book 2,BOOK,CSV-002\n"
    )
    resp = await http_client.post(
        "/api/v1/resources/import/csv",
        headers=admin_headers,
        files={"file": ("import.csv", io.BytesIO(csv_payload.encode()), "text/csv")},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert len(body["created"]) == 2


async def test_list_resources_filters_by_status(
    http_client, admin_headers, seeded_resource
):
    resp = await http_client.get(
        "/api/v1/resources/",
        headers=admin_headers,
        params={"status": "DRAFT"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1


async def test_create_resource_with_owner_scope_persists_scope_fields(
    http_client, admin_headers, seeded_school
):
    resp = await http_client.post(
        "/api/v1/resources/",
        headers=admin_headers,
        json={
            "title": "Scoped Owner Resource",
            "resource_type": "BOOK",
            "owner_scope_type": "SCHOOL",
            "owner_scope_ref_id": seeded_school.id,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["owner_scope_type"] == "SCHOOL"
    assert body["owner_scope_ref_id"] == seeded_school.id


async def test_get_resource_with_no_scope_assignments_returns_403(
    http_client, admin_headers, librarian_headers, seeded_school
):
    create_resp = await http_client.post(
        "/api/v1/resources/",
        headers=admin_headers,
        json={
            "title": "Scope Guard Resource",
            "resource_type": "BOOK",
            "owner_scope_type": "SCHOOL",
            "owner_scope_ref_id": seeded_school.id,
        },
    )
    assert create_resp.status_code == 201
    resource_id = create_resp.json()["resource_id"]

    get_resp = await http_client.get(
        f"/api/v1/resources/{resource_id}",
        headers=librarian_headers,
    )
    assert get_resp.status_code == 403
    assert get_resp.json()["error"]["code"] == "SCOPE_VIOLATION"


async def test_classify_resource_invalid_age_range_returns_400(
    http_client, admin_headers, seeded_resource
):
    resp = await http_client.post(
        f"/api/v1/resources/{seeded_resource.id}/classify",
        headers=admin_headers,
        json={"min_age": 13, "max_age": 6, "timeliness_type": "EVERGREEN"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "VALIDATION_ERROR"

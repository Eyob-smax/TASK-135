"""
True no-mock HTTP tests.

Unlike the rest of the API test suite (which uses httpx.AsyncClient with
ASGITransport), these tests spin up a real uvicorn server on a loopback TCP
port and exercise the full HTTP stack — real socket, real TCP transport, no
ASGI short-circuit.

The ``real_http_url`` fixture (defined in conftest.py) manages the server
lifecycle within the same asyncio event loop, avoiding cross-loop SQLAlchemy
issues.

Token cross-transport note
--------------------------
``admin_headers``, ``librarian_headers``, and ``auth_headers`` all create
sessions via ASGI transport.  Because both the ASGI client and the uvicorn
server use the *same* FastAPI app object (and therefore the same in-memory
``AuthService`` session store), tokens obtained through ASGI login are
accepted by the real TCP server.  This is intentional: it lets us test
the full TCP path for every endpoint class without duplicating the user
seeding machinery.
"""
from __future__ import annotations

import uuid

import httpx


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------

async def test_health_check_via_real_http(real_http_url):
    """API is reachable over a real TCP connection."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.get("/api/v1/auth/whoami")
    assert resp.status_code == 401


async def test_login_via_real_http(real_http_url, sample_password):
    """POST /auth/login returns a token over a real TCP connection."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "testuser", "password": sample_password},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "token" in body
    assert isinstance(body["token"], str)
    assert len(body["token"]) > 20


async def test_whoami_requires_auth_via_real_http(real_http_url):
    """GET /auth/whoami without a token returns 401 over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.get("/api/v1/auth/whoami")
    assert resp.status_code == 401


async def test_auth_workflow_via_real_http(real_http_url, sample_password):
    """Full login → whoami round-trip over a real TCP socket."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "testuser", "password": sample_password},
        )
        assert login_resp.status_code == 200
        token = login_resp.json()["token"]

        whoami_resp = await client.get(
            "/api/v1/auth/whoami",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert whoami_resp.status_code == 200
    body = whoami_resp.json()
    assert body["username"] == "testuser"


async def test_invalid_credentials_via_real_http(real_http_url):
    """Wrong password returns 401 over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "testuser", "password": "wrong_password_123!"},
        )
    assert resp.status_code == 401


async def test_logout_via_real_http(real_http_url, sample_password):
    """POST /auth/logout invalidates a session over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        login_resp = await client.post(
            "/api/v1/auth/login",
            json={"username": "testuser", "password": sample_password},
        )
        token = login_resp.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        logout_resp = await client.post("/api/v1/auth/logout", headers=headers)
        assert logout_resp.status_code == 204

        # Token is now invalid
        whoami_resp = await client.get("/api/v1/auth/whoami", headers=headers)
    assert whoami_resp.status_code == 401


# ---------------------------------------------------------------------------
# Admin config endpoints
# ---------------------------------------------------------------------------

async def test_list_config_with_valid_token_via_real_http(real_http_url, sample_password):
    """GET /admin/config/ requires auth and returns pagination envelope over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        token = (await client.post(
            "/api/v1/auth/login",
            json={"username": "testuser", "password": sample_password},
        )).json()["token"]

        resp = await client.get(
            "/api/v1/admin/config/",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "total" in body


async def test_upsert_config_via_real_http(real_http_url, admin_headers):
    """PUT /admin/config/{category}/{key} creates an entry over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.put(
            "/api/v1/admin/config/runtime/real_http_key",
            json={"value": "tcp_value", "description": "Created via real TCP"},
            headers=admin_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["category"] == "runtime"
    assert body["key"] == "real_http_key"
    assert body["value"] == "tcp_value"


async def test_upsert_template_via_real_http(real_http_url, admin_headers):
    """PUT /admin/config/templates/{name} reaches the specific route over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.put(
            "/api/v1/admin/config/templates/tcp_welcome",
            json={
                "name": "tcp_welcome",
                "event_type": "user.created",
                "subject_template": "Welcome {{name}}",
                "body_template": "Hello {{name}}",
                "is_active": True,
            },
            headers=admin_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "tcp_welcome"
    assert body["event_type"] == "user.created"


async def test_upsert_descriptor_via_real_http(real_http_url, admin_headers):
    """PUT /admin/config/descriptors/{key} reaches the specific route over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.put(
            "/api/v1/admin/config/descriptors/school_name_tcp",
            json={
                "value": "TCP School",
                "description": "Set via real TCP",
                "region": None,
            },
            headers=admin_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["key"] == "school_name_tcp"
    assert body["value"] == "TCP School"


async def test_list_workflow_nodes_via_real_http(real_http_url, auth_headers):
    """GET /admin/config/workflow-nodes/ returns a list over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.get(
            "/api/v1/admin/config/workflow-nodes/",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_list_templates_via_real_http(real_http_url, auth_headers):
    """GET /admin/config/templates/ returns a list over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.get(
            "/api/v1/admin/config/templates/",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_list_descriptors_via_real_http(real_http_url, auth_headers):
    """GET /admin/config/descriptors/ returns a list over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.get(
            "/api/v1/admin/config/descriptors/",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# Admin audit endpoints
# ---------------------------------------------------------------------------

async def test_list_audit_events_via_real_http(real_http_url, admin_headers):
    """GET /admin/audit/events/ returns paginated events over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.get(
            "/api/v1/admin/audit/events/",
            headers=admin_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "total" in body


async def test_list_audit_events_requires_admin_via_real_http(real_http_url, auth_headers):
    """GET /admin/audit/events/ with non-admin token returns 403 over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.get(
            "/api/v1/admin/audit/events/",
            headers=auth_headers,
        )
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"]["code"] == "INSUFFICIENT_PERMISSION"


async def test_list_checkpoints_via_real_http(real_http_url, admin_headers):
    """GET /admin/audit/checkpoints/ returns a list over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.get(
            "/api/v1/admin/audit/checkpoints/",
            headers=admin_headers,
        )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# Admin taxonomy endpoints
# ---------------------------------------------------------------------------

async def test_list_categories_via_real_http(real_http_url, auth_headers):
    """GET /admin/taxonomy/categories/ returns a list over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.get(
            "/api/v1/admin/taxonomy/categories/",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_create_category_via_real_http(real_http_url, admin_headers):
    """POST /admin/taxonomy/categories/ creates a category over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.post(
            "/api/v1/admin/taxonomy/categories/",
            json={"name": "RealHTTPCategory"},
            headers=admin_headers,
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "RealHTTPCategory"
    assert body["depth"] == 0
    assert body["path_slug"] == "realhttpcategory"


async def test_list_taxonomy_rules_via_real_http(real_http_url, auth_headers):
    """GET /admin/taxonomy/rules/ returns a list over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.get(
            "/api/v1/admin/taxonomy/rules/",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ---------------------------------------------------------------------------
# Admin update endpoints
# ---------------------------------------------------------------------------

async def test_list_update_packages_via_real_http(real_http_url, admin_headers):
    """GET /admin/updates/ returns paginated packages over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.get(
            "/api/v1/admin/updates/",
            headers=admin_headers,
        )
    assert resp.status_code == 200
    assert "items" in resp.json()


async def test_update_packages_requires_admin_via_real_http(real_http_url, auth_headers):
    """GET /admin/updates/ with non-admin token returns 403 over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.get(
            "/api/v1/admin/updates/",
            headers=auth_headers,
        )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "INSUFFICIENT_PERMISSION"


# ---------------------------------------------------------------------------
# Inventory endpoints
# ---------------------------------------------------------------------------

async def test_create_inventory_item_via_real_http(real_http_url, admin_headers):
    """POST /inventory/items/ creates an item over real TCP."""
    sku = f"TCP-{uuid.uuid4().hex[:8].upper()}"
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.post(
            "/api/v1/inventory/items/",
            json={
                "sku": sku,
                "name": "Real HTTP Item",
                "description": "Created over real TCP",
                "unit_cost": "9.99",
            },
            headers=admin_headers,
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["sku"] == sku
    assert body["name"] == "Real HTTP Item"


async def test_list_warehouses_via_real_http(real_http_url, admin_headers):
    """GET /inventory/warehouses/ returns paginated warehouses over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.get(
            "/api/v1/inventory/warehouses/",
            headers=admin_headers,
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body


# ---------------------------------------------------------------------------
# Resource endpoints
# ---------------------------------------------------------------------------

async def test_create_resource_via_real_http(real_http_url, librarian_headers):
    """POST /resources/ creates a resource over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.post(
            "/api/v1/resources/",
            json={"title": "Real HTTP Resource", "resource_type": "BOOK"},
            headers=librarian_headers,
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Real HTTP Resource"
    assert body["status"] == "DRAFT"


async def test_resource_not_found_returns_404_via_real_http(real_http_url, admin_headers):
    """GET /resources/{nonexistent_id} returns 404 over real TCP (admin bypasses scope)."""
    nonexistent = str(uuid.uuid4())
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.get(
            f"/api/v1/resources/{nonexistent}",
            headers=admin_headers,
        )
    assert resp.status_code == 404


async def test_create_resource_requires_auth_via_real_http(real_http_url):
    """POST /resources/ without auth returns 401 over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.post(
            "/api/v1/resources/",
            json={"title": "No Auth Resource", "resource_type": "BOOK"},
        )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Integration clients (non-HMAC) over real TCP
# ---------------------------------------------------------------------------

async def test_list_integrations_via_real_http(real_http_url, admin_headers):
    """GET /integrations/ returns integration clients over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.get(
            "/api/v1/integrations/",
            headers=admin_headers,
        )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_create_integration_client_via_real_http(real_http_url, admin_headers):
    """POST /integrations/ creates a client and returns 201 over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.post(
            "/api/v1/integrations/",
            json={"name": f"tcp-client-{uuid.uuid4().hex[:6]}", "description": "Via real TCP"},
            headers=admin_headers,
        )
    assert resp.status_code == 201
    body = resp.json()
    # Response: {"client": {"client_id": "...", ...}, "initial_key": {...}}
    assert "client" in body
    assert "client_id" in body["client"]
    assert body["client"]["is_active"] is True


# ---------------------------------------------------------------------------
# 422 validation error shape over real TCP
# ---------------------------------------------------------------------------

async def test_validation_error_shape_via_real_http(real_http_url, admin_headers):
    """422 responses contain the standard error envelope over real TCP."""
    async with httpx.AsyncClient(base_url=real_http_url) as client:
        resp = await client.put(
            "/api/v1/admin/config/display/bad_val",
            json={"value": "   ", "description": ""},  # whitespace-only value
            headers=admin_headers,
        )
    assert resp.status_code == 422
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == "VALIDATION_ERROR"

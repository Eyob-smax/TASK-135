"""
Local REST API client for the District Console UI.

Provides a synchronous wrapper around httpx for use inside QThread workers.
All methods raise ApiError on non-2xx HTTP responses so callers handle a
single exception type rather than raw httpx / HTTP status codes.

The client is state-aware: call set_token() after login so subsequent
requests include the Authorization header automatically.
"""
from __future__ import annotations

from typing import Any, Optional

import httpx


class ApiError(Exception):
    """Raised by ApiClient when the server returns a non-2xx status."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message

    @classmethod
    def from_response(cls, response: httpx.Response) -> "ApiError":
        try:
            body = response.json()
            err = body.get("error", {})
            code = err.get("code", "UNKNOWN")
            message = err.get("message", response.text)
        except Exception:
            code = "PARSE_ERROR"
            message = response.text
        return cls(response.status_code, code, message)


class ApiClient:
    """
    Synchronous HTTP client bound to the local FastAPI service.

    Intended to be called from QThread workers, never from the Qt main thread.
    Thread-safe: each worker creates its own httpx.Client via context manager
    or uses the shared client sequentially (safe because workers are
    single-shot threads).
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8765",
                 token: Optional[str] = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._client = httpx.Client(base_url=self._base_url, timeout=30.0)

    # ------------------------------------------------------------------ #
    # Auth management                                                     #
    # ------------------------------------------------------------------ #

    def set_token(self, token: Optional[str]) -> None:
        self._token = token

    def _headers(self, extra: Optional[dict] = None) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        if extra:
            h.update(extra)
        return h

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code >= 400:
            raise ApiError.from_response(response)

    # ------------------------------------------------------------------ #
    # Auth endpoints                                                      #
    # ------------------------------------------------------------------ #

    def login(self, username: str, password: str) -> dict:
        r = self._client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        self._raise_for_status(r)
        return r.json()

    def logout(self) -> None:
        if not self._token:
            return
        r = self._client.post("/api/v1/auth/logout", headers=self._headers())
        # 204 is success; ignore session-already-expired errors
        if r.status_code not in (204, 401):
            self._raise_for_status(r)
        self._token = None

    def whoami(self) -> dict:
        r = self._client.get("/api/v1/auth/whoami", headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    # ------------------------------------------------------------------ #
    # Resource endpoints                                                  #
    # ------------------------------------------------------------------ #

    def list_resources(self, offset: int = 0, limit: int = 50,
                       status: Optional[str] = None,
                       resource_type: Optional[str] = None,
                       keyword: Optional[str] = None) -> dict:
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        if status:
            params["status"] = status
        if resource_type:
            params["resource_type"] = resource_type
        if keyword:
            params["keyword"] = keyword
        r = self._client.get("/api/v1/resources/", params=params,
                             headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def get_resource(self, resource_id: str) -> dict:
        r = self._client.get(f"/api/v1/resources/{resource_id}",
                             headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def create_resource(self, title: str, resource_type: str,
                        isbn: Optional[str] = None) -> dict:
        body: dict[str, Any] = {"title": title, "resource_type": resource_type}
        if isbn:
            body["isbn"] = isbn
        r = self._client.post("/api/v1/resources/", json=body,
                              headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def update_resource(self, resource_id: str, **fields: Any) -> dict:
        r = self._client.put(f"/api/v1/resources/{resource_id}",
                             json={k: v for k, v in fields.items() if v is not None},
                             headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def list_revisions(self, resource_id: str) -> dict:
        r = self._client.get(f"/api/v1/resources/{resource_id}/revisions",
                             headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def submit_for_review(self, resource_id: str, reviewer_id: str) -> dict:
        r = self._client.post(
            f"/api/v1/resources/{resource_id}/submit-review",
            json={"reviewer_id": reviewer_id},
            headers=self._headers(),
        )
        self._raise_for_status(r)
        return r.json()

    def publish_resource(self, resource_id: str, reviewer_notes: str) -> dict:
        r = self._client.post(
            f"/api/v1/resources/{resource_id}/publish",
            json={"reviewer_notes": reviewer_notes},
            headers=self._headers(),
        )
        self._raise_for_status(r)
        return r.json()

    def unpublish_resource(self, resource_id: str, reviewer_notes: str) -> dict:
        r = self._client.post(
            f"/api/v1/resources/{resource_id}/unpublish",
            json={"reviewer_notes": reviewer_notes},
            headers=self._headers(),
        )
        self._raise_for_status(r)
        return r.json()

    def classify_resource(self, resource_id: str, min_age: int,
                          max_age: int, timeliness_type: str) -> None:
        r = self._client.post(
            f"/api/v1/resources/{resource_id}/classify",
            json={"min_age": min_age, "max_age": max_age,
                  "timeliness_type": timeliness_type},
            headers=self._headers(),
        )
        self._raise_for_status(r)

    def request_allocation(self, resource_id: str) -> None:
        r = self._client.post(
            f"/api/v1/resources/{resource_id}/request-allocation",
            headers=self._headers(),
        )
        self._raise_for_status(r)

    def import_file(self, filename: str, content: bytes,
                    resource_type: str, title: str,
                    isbn: Optional[str] = None) -> dict:
        files = {"file": (filename, content, "application/octet-stream")}
        data: dict[str, Any] = {"resource_type": resource_type, "title": title}
        if isbn:
            data["isbn"] = isbn
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        r = self._client.post("/api/v1/resources/import/file",
                              files=files, data=data, headers=headers)
        self._raise_for_status(r)
        return r.json()

    # ------------------------------------------------------------------ #
    # Inventory endpoints                                                 #
    # ------------------------------------------------------------------ #

    def list_inventory_items(self, offset: int = 0, limit: int = 50) -> dict:
        r = self._client.get("/api/v1/inventory/items/",
                             params={"offset": offset, "limit": limit},
                             headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def get_inventory_item(self, item_id: str) -> dict:
        r = self._client.get(f"/api/v1/inventory/items/{item_id}",
                             headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def create_inventory_item(self, sku: str, name: str,
                               description: str, unit_cost: str) -> dict:
        r = self._client.post(
            "/api/v1/inventory/items/",
            json={"sku": sku, "name": name, "description": description,
                  "unit_cost": unit_cost},
            headers=self._headers(),
        )
        self._raise_for_status(r)
        return r.json()

    def list_stock(self, item_id: Optional[str] = None,
                   location_id: Optional[str] = None,
                   offset: int = 0, limit: int = 50) -> dict:
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        if item_id:
            params["item_id"] = item_id
        if location_id:
            params["location_id"] = location_id
        r = self._client.get("/api/v1/inventory/stock/",
                             params=params, headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def freeze_stock(self, balance_id: str, reason: str) -> dict:
        r = self._client.post(
            f"/api/v1/inventory/stock/{balance_id}/freeze",
            json={"reason": reason},
            headers=self._headers(),
        )
        self._raise_for_status(r)
        return r.json()

    def unfreeze_stock(self, balance_id: str) -> dict:
        r = self._client.post(
            f"/api/v1/inventory/stock/{balance_id}/unfreeze",
            headers=self._headers(),
        )
        self._raise_for_status(r)
        return r.json()

    def list_ledger(self, item_id: Optional[str] = None,
                    location_id: Optional[str] = None,
                    offset: int = 0, limit: int = 50) -> dict:
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        if item_id:
            params["item_id"] = item_id
        if location_id:
            params["location_id"] = location_id
        r = self._client.get("/api/v1/inventory/ledger/",
                             params=params, headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def add_adjustment(self, item_id: str, location_id: str,
                       quantity_delta: int, reason_code: str) -> dict:
        r = self._client.post(
            "/api/v1/inventory/ledger/adjustment",
            json={"item_id": item_id, "location_id": location_id,
                  "quantity_delta": quantity_delta, "reason_code": reason_code},
            headers=self._headers(),
        )
        self._raise_for_status(r)
        return r.json()

    def add_correction(self, entry_id: str, reason_code: str) -> dict:
        r = self._client.post(
            f"/api/v1/inventory/ledger/correction/{entry_id}",
            json={"reason_code": reason_code},
            headers=self._headers(),
        )
        self._raise_for_status(r)
        return r.json()

    def list_warehouses(self) -> dict:
        r = self._client.get("/api/v1/inventory/warehouses/",
                             headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def list_locations(self, warehouse_id: Optional[str] = None) -> dict:
        params: dict[str, Any] = {}
        if warehouse_id:
            params["warehouse_id"] = warehouse_id
        r = self._client.get("/api/v1/inventory/locations/",
                             params=params, headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def list_relocations(self, item_id: Optional[str] = None,
                         offset: int = 0, limit: int = 50) -> dict:
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        if item_id:
            params["item_id"] = item_id
        r = self._client.get("/api/v1/inventory/relocations/",
                             params=params, headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def create_relocation(self, item_id: str, from_location_id: str,
                          to_location_id: str, quantity: int,
                          device_source: str = "MANUAL") -> dict:
        r = self._client.post(
            "/api/v1/inventory/relocations/",
            json={"item_id": item_id, "from_location_id": from_location_id,
                  "to_location_id": to_location_id, "quantity": quantity,
                  "device_source": device_source},
            headers=self._headers(),
        )
        self._raise_for_status(r)
        return r.json()

    # ------------------------------------------------------------------ #
    # Count session endpoints                                             #
    # ------------------------------------------------------------------ #

    def list_count_sessions(self, status: Optional[str] = None,
                            offset: int = 0, limit: int = 50) -> dict:
        params: dict[str, Any] = {"offset": offset, "limit": limit}
        if status:
            params["status"] = status
        r = self._client.get("/api/v1/inventory/count-sessions/",
                             params=params, headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def open_count_session(self, mode: str, warehouse_id: str) -> dict:
        r = self._client.post(
            "/api/v1/inventory/count-sessions/",
            json={"mode": mode, "warehouse_id": warehouse_id},
            headers=self._headers(),
        )
        self._raise_for_status(r)
        return r.json()

    def get_count_session(self, session_id: str) -> dict:
        r = self._client.get(
            f"/api/v1/inventory/count-sessions/{session_id}",
            headers=self._headers(),
        )
        self._raise_for_status(r)
        return r.json()

    def add_count_line(self, session_id: str, item_id: str,
                       location_id: str, counted_qty: int,
                       reason_code: Optional[str] = None) -> dict:
        body: dict[str, Any] = {
            "item_id": item_id,
            "location_id": location_id,
            "counted_qty": counted_qty,
        }
        if reason_code:
            body["reason_code"] = reason_code
        r = self._client.post(
            f"/api/v1/inventory/count-sessions/{session_id}/line",
            json=body,
            headers=self._headers(),
        )
        self._raise_for_status(r)
        return r.json()

    def update_count_line(self, session_id: str, line_id: str,
                          counted_qty: int) -> dict:
        r = self._client.put(
            f"/api/v1/inventory/count-sessions/{session_id}/lines/{line_id}",
            json={"counted_qty": counted_qty},
            headers=self._headers(),
        )
        self._raise_for_status(r)
        return r.json()

    def close_count_session(self, session_id: str) -> dict:
        r = self._client.post(
            f"/api/v1/inventory/count-sessions/{session_id}/close",
            headers=self._headers(),
        )
        self._raise_for_status(r)
        return r.json()

    def approve_count_session(self, session_id: str, notes: str) -> dict:
        r = self._client.post(
            f"/api/v1/inventory/count-sessions/{session_id}/approve",
            json={"notes": notes},
            headers=self._headers(),
        )
        self._raise_for_status(r)
        return r.json()

    # ------------------------------------------------------------------
    # Configuration center
    # ------------------------------------------------------------------

    def list_config(self, category: str = None, offset: int = 0, limit: int = 100) -> dict:
        params = {"offset": offset, "limit": limit}
        if category:
            params["category"] = category
        r = self._client.get("/api/v1/admin/config/", params=params, headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def upsert_config(self, category: str, key: str, value: str, description: str = "") -> dict:
        r = self._client.put(
            f"/api/v1/admin/config/{category}/{key}",
            json={"value": value, "description": description},
            headers=self._headers(),
        )
        self._raise_for_status(r)
        return r.json()

    def delete_config(self, entry_id: str) -> None:
        r = self._client.delete(f"/api/v1/admin/config/{entry_id}", headers=self._headers())
        self._raise_for_status(r)

    def list_workflow_nodes(self, workflow_name: str = None) -> list:
        params = {}
        if workflow_name:
            params["workflow_name"] = workflow_name
        r = self._client.get("/api/v1/admin/config/workflow-nodes/", params=params, headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def create_workflow_node(self, workflow_name: str, from_state: str, to_state: str,
                             required_role: str, condition_json: str = None) -> dict:
        body = {"workflow_name": workflow_name, "from_state": from_state,
                "to_state": to_state, "required_role": required_role,
                "condition_json": condition_json}
        r = self._client.post("/api/v1/admin/config/workflow-nodes/", json=body, headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def delete_workflow_node(self, node_id: str) -> None:
        r = self._client.delete(f"/api/v1/admin/config/workflow-nodes/{node_id}", headers=self._headers())
        self._raise_for_status(r)

    def list_notification_templates(self) -> list:
        r = self._client.get("/api/v1/admin/config/templates/", headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def upsert_notification_template(self, name: str, event_type: str,
                                     subject_template: str, body_template: str,
                                     is_active: bool = True) -> dict:
        r = self._client.put(
            f"/api/v1/admin/config/templates/{name}",
            json={"name": name, "event_type": event_type,
                  "subject_template": subject_template,
                  "body_template": body_template, "is_active": is_active},
            headers=self._headers(),
        )
        self._raise_for_status(r)
        return r.json()

    def list_district_descriptors(self) -> list:
        r = self._client.get("/api/v1/admin/config/descriptors/", headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def upsert_district_descriptor(self, key: str, value: str, description: str = "",
                                   region: str = None) -> dict:
        r = self._client.put(
            f"/api/v1/admin/config/descriptors/{key}",
            json={"value": value, "description": description, "region": region},
            headers=self._headers(),
        )
        self._raise_for_status(r)
        return r.json()

    # ------------------------------------------------------------------
    # Taxonomy
    # ------------------------------------------------------------------

    def list_categories(self, parent_id: str = None, flat: bool = False) -> list:
        params = {"flat": flat}
        if parent_id:
            params["parent_id"] = parent_id
        r = self._client.get("/api/v1/admin/taxonomy/categories/", params=params, headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def create_category(self, name: str, parent_id: str = None) -> dict:
        body = {"name": name}
        if parent_id:
            body["parent_id"] = parent_id
        r = self._client.post("/api/v1/admin/taxonomy/categories/", json=body, headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def deactivate_category(self, category_id: str) -> None:
        r = self._client.delete(f"/api/v1/admin/taxonomy/categories/{category_id}", headers=self._headers())
        self._raise_for_status(r)

    def list_taxonomy_rules(self, field: str = None) -> list:
        params = {}
        if field:
            params["field"] = field
        r = self._client.get("/api/v1/admin/taxonomy/rules/", params=params, headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def create_taxonomy_rule(self, field: str, rule_type: str, rule_value: str,
                             description: str = None) -> dict:
        body = {"field": field, "rule_type": rule_type, "rule_value": rule_value,
                "description": description}
        r = self._client.post("/api/v1/admin/taxonomy/rules/", json=body, headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def delete_taxonomy_rule(self, rule_id: str) -> None:
        r = self._client.delete(f"/api/v1/admin/taxonomy/rules/{rule_id}", headers=self._headers())
        self._raise_for_status(r)

    # ------------------------------------------------------------------
    # Integrations
    # ------------------------------------------------------------------

    def list_integration_clients(self) -> list:
        r = self._client.get("/api/v1/integrations/", headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def create_integration_client(self, name: str, description: str = "") -> dict:
        r = self._client.post("/api/v1/integrations/",
                              json={"name": name, "description": description},
                              headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def deactivate_integration_client(self, client_id: str) -> None:
        r = self._client.delete(f"/api/v1/integrations/{client_id}", headers=self._headers())
        self._raise_for_status(r)

    def rotate_integration_key(self, client_id: str) -> dict:
        r = self._client.post(f"/api/v1/integrations/{client_id}/rotate-key", headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def commit_integration_key_rotation(self, client_id: str) -> dict:
        r = self._client.post(f"/api/v1/integrations/{client_id}/commit-rotation", headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def list_outbound_events(self, client_id: str = None, status: str = None,
                             offset: int = 0, limit: int = 50) -> dict:
        params = {"offset": offset, "limit": limit}
        if client_id:
            params["client_id"] = client_id
        if status:
            params["event_status"] = status
        r = self._client.get("/api/v1/integrations/events/", params=params, headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def retry_outbound_events(self) -> dict:
        r = self._client.post("/api/v1/integrations/events/retry", headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    # ------------------------------------------------------------------
    # Update packages
    # ------------------------------------------------------------------

    def list_update_packages(self, offset: int = 0, limit: int = 20) -> dict:
        r = self._client.get("/api/v1/admin/updates/",
                             params={"offset": offset, "limit": limit},
                             headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def import_update_package(self, file_content: bytes, filename: str) -> dict:
        r = self._client.post(
            "/api/v1/admin/updates/import",
            files={"file": (filename, file_content, "application/zip")},
            headers=self._headers(),
        )
        self._raise_for_status(r)
        return r.json()

    def apply_update_package(self, package_id: str) -> dict:
        r = self._client.post(f"/api/v1/admin/updates/{package_id}/apply", headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def rollback_update_package(self, package_id: str) -> dict:
        r = self._client.post(f"/api/v1/admin/updates/{package_id}/rollback", headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    # ------------------------------------------------------------------
    # Audit / admin
    # ------------------------------------------------------------------

    def list_audit_events(self, entity_type: str = None, action: str = None,
                          actor_id: str = None, offset: int = 0, limit: int = 50) -> dict:
        params = {"offset": offset, "limit": limit}
        if entity_type:
            params["entity_type"] = entity_type
        if action:
            params["action"] = action
        if actor_id:
            params["actor_id"] = actor_id
        r = self._client.get("/api/v1/admin/audit/events/", params=params, headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def list_security_audit_events(self, offset: int = 0, limit: int = 50) -> dict:
        r = self._client.get("/api/v1/admin/audit/events/security/",
                             params={"offset": offset, "limit": limit},
                             headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def list_approval_queue(self) -> list:
        r = self._client.get("/api/v1/admin/audit/approval-queue/", headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def list_checkpoint_status(self) -> list:
        r = self._client.get("/api/v1/admin/audit/checkpoints/", headers=self._headers())
        self._raise_for_status(r)
        return r.json()

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._client.close()

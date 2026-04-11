"""
API tests for update package routes (/api/v1/admin/updates).
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile


def _make_zip_bytes(
    version: str = "1.0.0",
    *,
    checksum_override: str | None = None,
    path_override: str = "data/config.json",
) -> bytes:
    config_payload = b"{}"
    checksum = checksum_override or hashlib.sha256(config_payload).hexdigest()
    manifest = {
        "version": version,
        "build_id": "build-001",
        "file_list": [path_override],
        "checksums": {path_override: checksum},
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr(path_override, config_payload)
    return buf.getvalue()


async def test_list_packages_requires_auth(http_client):
    resp = await http_client.get("/api/v1/admin/updates/")
    assert resp.status_code == 401


async def test_list_packages_with_non_admin_returns_403(http_client, auth_headers):
    resp = await http_client.get("/api/v1/admin/updates/", headers=auth_headers)
    assert resp.status_code == 403


async def test_list_packages_with_admin_returns_200(http_client, admin_headers):
    resp = await http_client.get("/api/v1/admin/updates/", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data


async def test_import_package_requires_admin(http_client, librarian_headers):
    resp = await http_client.post(
        "/api/v1/admin/updates/import",
        files={"file": ("v1.zip", _make_zip_bytes(), "application/zip")},
        headers=librarian_headers,
    )
    assert resp.status_code == 403


async def test_import_package_with_admin_creates_pending(http_client, admin_headers):
    resp = await http_client.post(
        "/api/v1/admin/updates/import",
        files={"file": ("v1.0.0.zip", _make_zip_bytes("1.0.0"), "application/zip")},
        headers=admin_headers,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["version"] == "1.0.0"
    assert data["status"] == "PENDING"


async def test_import_invalid_zip_returns_422(http_client, admin_headers):
    resp = await http_client.post(
        "/api/v1/admin/updates/import",
        files={"file": ("bad.zip", b"not a zip", "application/zip")},
        headers=admin_headers,
    )
    assert resp.status_code == 422


async def test_apply_package_transitions_to_applied(http_client, admin_headers):
    # Import first
    import_resp = await http_client.post(
        "/api/v1/admin/updates/import",
        files={"file": ("v2.0.0.zip", _make_zip_bytes("2.0.0"), "application/zip")},
        headers=admin_headers,
    )
    assert import_resp.status_code == 201
    pkg_id = import_resp.json()["package_id"]

    apply_resp = await http_client.post(
        f"/api/v1/admin/updates/{pkg_id}/apply", headers=admin_headers
    )
    assert apply_resp.status_code == 200
    assert apply_resp.json()["status"] == "APPLIED"


async def test_apply_package_checksum_mismatch_returns_422(http_client, admin_headers):
    import_resp = await http_client.post(
        "/api/v1/admin/updates/import",
        files={
            "file": (
                "v2.1.0.zip",
                _make_zip_bytes("2.1.0", checksum_override="0" * 64),
                "application/zip",
            )
        },
        headers=admin_headers,
    )
    assert import_resp.status_code == 201
    pkg_id = import_resp.json()["package_id"]

    apply_resp = await http_client.post(
        f"/api/v1/admin/updates/{pkg_id}/apply", headers=admin_headers
    )
    assert apply_resp.status_code == 422


async def test_apply_package_path_traversal_returns_422(http_client, admin_headers):
    import_resp = await http_client.post(
        "/api/v1/admin/updates/import",
        files={
            "file": (
                "v2.2.0.zip",
                _make_zip_bytes("2.2.0", path_override="../escape.txt"),
                "application/zip",
            )
        },
        headers=admin_headers,
    )
    assert import_resp.status_code == 201
    pkg_id = import_resp.json()["package_id"]

    apply_resp = await http_client.post(
        f"/api/v1/admin/updates/{pkg_id}/apply", headers=admin_headers
    )
    assert apply_resp.status_code == 422


async def test_import_package_file_list_checksum_mismatch_returns_422(http_client, admin_headers):
    """Import must reject a manifest where file_list and checksums keys differ."""
    import io as _io
    import json as _json
    import zipfile as _zipfile

    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w") as zf:
        manifest = {
            "version": "9.0.0",
            "build_id": "build-mismatch-api",
            "file_list": ["only_in_list.txt"],
            "checksums": {"only_in_checksums.txt": "a" * 64},
        }
        zf.writestr("manifest.json", _json.dumps(manifest))
        zf.writestr("only_in_list.txt", b"x")
        zf.writestr("only_in_checksums.txt", b"y")

    resp = await http_client.post(
        "/api/v1/admin/updates/import",
        files={"file": ("mismatch.zip", buf.getvalue(), "application/zip")},
        headers=admin_headers,
    )
    assert resp.status_code == 422


async def test_apply_package_extra_unlisted_member_returns_422(http_client, admin_headers):
    """apply must reject a ZIP whose archive contains files beyond the declared file_list."""
    import hashlib as _hashlib
    import io as _io
    import json as _json
    import zipfile as _zipfile

    payload = b"clean content"
    checksum = _hashlib.sha256(payload).hexdigest()
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w") as zf:
        manifest = {
            "version": "9.1.0",
            "build_id": "build-extra-api",
            "file_list": ["data/clean.json"],
            "checksums": {"data/clean.json": checksum},
        }
        zf.writestr("manifest.json", _json.dumps(manifest))
        zf.writestr("data/clean.json", payload)
        zf.writestr("injected/bad.py", b"evil()")  # not in file_list

    import_resp = await http_client.post(
        "/api/v1/admin/updates/import",
        files={"file": ("extra.zip", buf.getvalue(), "application/zip")},
        headers=admin_headers,
    )
    assert import_resp.status_code == 201
    pkg_id = import_resp.json()["package_id"]

    apply_resp = await http_client.post(
        f"/api/v1/admin/updates/{pkg_id}/apply", headers=admin_headers
    )
    assert apply_resp.status_code == 422

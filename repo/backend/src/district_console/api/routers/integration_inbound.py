"""
Integration client inbound endpoints — HMAC-signed requests only.

These routes are called by registered integration clients using HMAC-SHA256
request signing. Bearer token auth is NOT accepted here; all requests must
carry the X-DC-Client-ID / X-DC-Signature / X-DC-Timestamp header triple.

Prefix: /api/v1/integrations/inbound
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from district_console.api.dependencies import verify_hmac_auth

router = APIRouter()


@router.get("/status")
async def integration_status(
    client_id: Annotated[str, Depends(verify_hmac_auth)],
) -> dict:
    """
    Health-check endpoint for integration clients.

    Verifies the HMAC signature, applies the per-client rate limit, and
    returns a success payload containing the verified client identity.

    Errors:
        401 SIGNATURE_INVALID  — missing/invalid signature headers
        429 RATE_LIMIT_EXCEEDED — client exceeded 60 req/min
    """
    return {"status": "ok", "client_id": client_id}

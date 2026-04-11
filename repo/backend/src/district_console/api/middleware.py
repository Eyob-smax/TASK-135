"""
ASGI middleware for the District Console local REST API.

ErrorHandlerMiddleware:
  Catches all unhandled exceptions and converts them to the standard
  ErrorEnvelope JSON response. No raw exception details (stack traces,
  internal module paths) ever reach the client — only the safe .code
  and .message from domain exceptions.

Error → HTTP status mapping:
  See _ERROR_HTTP_MAP below. Unmapped DistrictConsoleError codes default to
  500. Non-DistrictConsoleError exceptions always map to 500 INTERNAL_ERROR.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi.exceptions import HTTPException as FastAPIHTTPException
from pydantic import ValidationError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from district_console.domain.exceptions import DistrictConsoleError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Error code → HTTP status map
# ---------------------------------------------------------------------------

_ERROR_HTTP_MAP: dict[str, int] = {
    "UNAUTHENTICATED": 401,
    "INVALID_CREDENTIALS": 401,
    "SESSION_EXPIRED": 401,
    "PASSWORD_TOO_SHORT": 401,
    "SIGNATURE_INVALID": 401,
    "ACCOUNT_LOCKED": 423,
    "INSUFFICIENT_PERMISSION": 403,
    "SCOPE_VIOLATION": 403,
    "NOT_FOUND": 404,
    "RECORD_LOCKED": 409,
    "INVALID_STATE_TRANSITION": 409,
    "DUPLICATE_RESOURCE": 409,
    "APPEND_ONLY_VIOLATION": 409,
    "REVISION_LIMIT_REACHED": 409,
    "INSUFFICIENT_STOCK": 409,
    "STOCK_FROZEN": 409,
    "VALIDATION_ERROR": 422,
    "RATE_LIMIT_EXCEEDED": 429,
    "INTERNAL_ERROR": 500,
}

_DEFAULT_STATUS = 500


def _make_error_response(code: str, message: str, details: Any = None) -> JSONResponse:
    status_code = _ERROR_HTTP_MAP.get(code, _DEFAULT_STATUS)
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(content=body, status_code=status_code)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """
    Converts exceptions to ErrorEnvelope JSON responses.

    Handles:
    - DistrictConsoleError subclasses → mapped HTTP status + domain code/message
    - pydantic.ValidationError (request body parsing) → 422 VALIDATION_ERROR
    - All other exceptions → 500 INTERNAL_ERROR (no internal details exposed)
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        try:
            return await call_next(request)
        except FastAPIHTTPException as exc:
            # Wrap HTTPException with dict detail into the standard error envelope
            if isinstance(exc.detail, dict):
                code = exc.detail.get("code", "INTERNAL_ERROR")
                message = exc.detail.get("message", str(exc.detail))
                details = exc.detail.get("details")
                body: dict = {"error": {"code": code, "message": message}}
                if details is not None:
                    body["error"]["details"] = details
                return JSONResponse(content=body, status_code=exc.status_code)
            return JSONResponse(
                content={"error": {"code": "INTERNAL_ERROR", "message": str(exc.detail)}},
                status_code=exc.status_code,
            )
        except DistrictConsoleError as exc:
            return _make_error_response(exc.code, exc.message)
        except ValidationError as exc:
            errors = [
                {
                    "field": ".".join(str(loc) for loc in err["loc"]),
                    "message": err["msg"],
                    "type": err["type"],
                }
                for err in exc.errors()
            ]
            return _make_error_response(
                "VALIDATION_ERROR",
                "Request validation failed.",
                details=errors,
            )
        except Exception as exc:  # pragma: no cover — unexpected errors
            logger.exception("Unhandled exception in request %s %s", request.method, request.url)
            return _make_error_response(
                "INTERNAL_ERROR",
                "An unexpected internal error occurred.",
            )

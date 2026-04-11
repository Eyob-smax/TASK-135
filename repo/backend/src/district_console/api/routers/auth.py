"""
Authentication endpoints for the District Console API.

Routes:
  POST /api/v1/auth/login    Verify credentials, return session token
  POST /api/v1/auth/logout   Invalidate session token
  GET  /api/v1/auth/whoami   Return current user info

These routes are mounted at /api/v1/auth by api/app.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from district_console.api.dependencies import (
    get_auth_service,
    get_current_user,
    get_db_session,
    security,
)
from district_console.api.schemas import LoginRequest, LoginResponse, WhoAmIResponse
from district_console.application.auth_service import SESSION_TTL_HOURS, AuthService
from district_console.domain.entities.role import Role
from district_console.domain.exceptions import SessionExpiredError
from district_console.infrastructure.repositories import ScopeRepository, UserRepository

router = APIRouter()


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> LoginResponse:
    """
    Authenticate with username and password.

    Returns a session token valid for 8 hours.
    Errors:
      - 401 INVALID_CREDENTIALS — wrong username or password
      - 423 ACCOUNT_LOCKED     — too many failed attempts
    """
    now = datetime.utcnow()
    user, roles = await auth_service.authenticate(session, body.username, body.password, now)
    token = auth_service.create_session(user.id, roles)
    expires_at = now + timedelta(hours=SESSION_TTL_HOURS)
    return LoginResponse(
        user_id=str(user.id),
        username=user.username,
        roles=[role.role_type.value for role in roles],
        token=token,
        expires_at=expires_at.isoformat(),
    )


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    """
    Invalidate the current session token.

    Requires a valid Bearer token in the Authorization header.
    Always returns 204, even if the token was already invalidated.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise SessionExpiredError()
    token = auth_header.split(" ", 1)[1].strip()
    # Validate first to ensure the request is authenticated
    result = auth_service.validate_session(token, datetime.utcnow())
    if result is None:
        raise SessionExpiredError()
    auth_service.invalidate_session(token)


@router.get("/whoami", response_model=WhoAmIResponse)
async def whoami(
    current_user: Annotated[
        tuple[uuid.UUID, list[Role]], Depends(get_current_user)
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WhoAmIResponse:
    """
    Return information about the currently authenticated user.

    Requires a valid Bearer token.
    """
    user_id, roles = current_user
    user_repo = UserRepository()
    user = await user_repo.get_by_id(session, user_id)
    scope_repo = ScopeRepository()
    scopes = await scope_repo.get_user_scopes(session, user_id)
    return WhoAmIResponse(
        user_id=str(user_id),
        username=user.username if user else "",
        roles=[role.role_type.value for role in roles],
        scopes=[
            {
                "scope_type": sa.scope_type.value,
                "scope_ref_id": str(sa.scope_ref_id),
            }
            for sa in scopes
        ],
    )

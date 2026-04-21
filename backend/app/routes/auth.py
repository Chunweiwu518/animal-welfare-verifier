"""LINE OAuth + session routes."""
from __future__ import annotations

import logging
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.config import Settings, get_request_settings
from app.services.auth_service import AuthService, AuthUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _db_connect(settings: Settings) -> sqlite3.Connection:
    conn = sqlite3.connect(Path(settings.database_path))
    conn.row_factory = sqlite3.Row
    return conn


def current_user(
    request: Request,
    settings: Settings = Depends(get_request_settings),
) -> AuthUser | None:
    """Resolve current user from session cookie, or None if anonymous."""
    cookie_name = settings.session_cookie_name or "aw_session"
    token = request.cookies.get(cookie_name)
    if not token:
        return None
    service = AuthService(settings)
    with _db_connect(settings) as conn:
        return service.resolve_session(conn, token)


def require_user(
    user: AuthUser | None = Depends(current_user),
) -> AuthUser:
    if user is None:
        raise HTTPException(status_code=401, detail="Login required")
    return user


@router.get("/line/login")
async def line_login(
    request: Request,
    redirect_to: str = "/",
    settings: Settings = Depends(get_request_settings),
) -> RedirectResponse:
    service = AuthService(settings)
    if not service.line_is_configured():
        raise HTTPException(status_code=503, detail="LINE login not configured")
    state = secrets.token_urlsafe(16)
    # Keep redirect_to in cookie so callback can return user home
    response = RedirectResponse(service.build_line_authorize_url(state))
    response.set_cookie(
        "aw_oauth_state",
        f"{state}|{redirect_to}",
        max_age=600,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return response


@router.get("/line/callback")
async def line_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    settings: Settings = Depends(get_request_settings),
    aw_oauth_state: str | None = Cookie(default=None),
) -> RedirectResponse:
    if error:
        return RedirectResponse(f"/?login_error={error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code/state")
    if not aw_oauth_state or "|" not in aw_oauth_state:
        raise HTTPException(status_code=400, detail="Missing OAuth state")
    expected_state, redirect_to = aw_oauth_state.split("|", 1)
    if not secrets.compare_digest(expected_state, state):
        raise HTTPException(status_code=400, detail="State mismatch")

    service = AuthService(settings)
    try:
        profile = await service.exchange_line_code(code)
    except Exception as exc:  # noqa: BLE001
        logger.exception("LINE token exchange failed")
        return RedirectResponse(f"/?login_error=token_exchange_failed")

    provider_user_id = str(profile.get("userId") or "")
    display_name = str(profile.get("displayName") or "LINE user")
    avatar_url = str(profile.get("pictureUrl") or "")
    if not provider_user_id:
        return RedirectResponse("/?login_error=missing_user_id")

    with _db_connect(settings) as conn:
        user_id = service.upsert_user(
            conn,
            provider="line",
            provider_user_id=provider_user_id,
            display_name=display_name,
            avatar_url=avatar_url,
        )
        token, expires = service.issue_session(conn, user_id)

    response = RedirectResponse(redirect_to or "/")
    cookie_name = settings.session_cookie_name or "aw_session"
    response.set_cookie(
        cookie_name,
        token,
        expires=int(expires.timestamp()),
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    response.delete_cookie("aw_oauth_state")
    return response


@router.get("/me")
async def auth_me(
    user: AuthUser | None = Depends(current_user),
) -> dict:
    if user is None:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "id": user.id,
        "provider": user.provider,
        "display_name": user.display_name,
        "avatar_url": user.avatar_url,
    }


@router.post("/logout")
async def logout(
    request: Request,
    settings: Settings = Depends(get_request_settings),
) -> JSONResponse:
    cookie_name = settings.session_cookie_name or "aw_session"
    token = request.cookies.get(cookie_name)
    if token:
        service = AuthService(settings)
        with _db_connect(settings) as conn:
            service.revoke_session(conn, token)
    response = JSONResponse({"ok": True})
    response.delete_cookie(cookie_name, path="/")
    return response

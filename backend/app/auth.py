"""Admin token auth — protects endpoints that consume paid APIs or mutate data."""
from __future__ import annotations

import hmac

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_request_settings


def require_admin_token(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    settings: Settings = Depends(get_request_settings),
) -> None:
    """Reject requests lacking the admin token.

    If `admin_token` is not configured (local dev without the env var), allow
    the request through — this matches existing test fixtures that omit the token.
    """
    expected = (settings.admin_token or "").strip()
    if not expected:
        return

    provided = (x_admin_token or "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid admin token",
            headers={"WWW-Authenticate": "X-Admin-Token"},
        )

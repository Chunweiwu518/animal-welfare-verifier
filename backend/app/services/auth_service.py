"""LINE OAuth login + cookie-based session management."""
from __future__ import annotations

import logging
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

LINE_AUTHORIZE_URL = "https://access.line.me/oauth2/v2.1/authorize"
LINE_TOKEN_URL = "https://api.line.me/oauth2/v2.1/token"
LINE_PROFILE_URL = "https://api.line.me/v2/profile"


@dataclass(frozen=True)
class AuthUser:
    id: int
    provider: str
    display_name: str
    avatar_url: str


class AuthService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def line_is_configured(self) -> bool:
        return bool(
            self.settings.line_channel_id
            and self.settings.line_channel_secret
            and self.settings.line_redirect_uri
        )

    def build_line_authorize_url(self, state: str) -> str:
        assert self.settings.line_channel_id and self.settings.line_redirect_uri
        params = {
            "response_type": "code",
            "client_id": self.settings.line_channel_id,
            "redirect_uri": self.settings.line_redirect_uri,
            "state": state,
            "scope": "profile openid",
        }
        from urllib.parse import urlencode

        return f"{LINE_AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_line_code(self, code: str) -> dict[str, Any]:
        """Exchange auth code for access token + fetch profile."""
        assert self.line_is_configured()
        async with httpx.AsyncClient(timeout=15.0) as client:
            token_resp = await client.post(
                LINE_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self.settings.line_redirect_uri,
                    "client_id": self.settings.line_channel_id,
                    "client_secret": self.settings.line_channel_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            token_resp.raise_for_status()
            token_data = token_resp.json()
            access_token = token_data.get("access_token")
            if not access_token:
                raise RuntimeError("LINE token exchange returned no access_token")

            profile_resp = await client.get(
                LINE_PROFILE_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            profile_resp.raise_for_status()
            return profile_resp.json()

    def upsert_user(
        self,
        conn: sqlite3.Connection,
        *,
        provider: str,
        provider_user_id: str,
        display_name: str,
        avatar_url: str = "",
        email: str = "",
    ) -> int:
        conn.execute(
            """
            INSERT INTO users (provider, provider_user_id, display_name, avatar_url, email)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(provider, provider_user_id) DO UPDATE SET
              display_name = excluded.display_name,
              avatar_url = excluded.avatar_url,
              email = CASE WHEN excluded.email != '' THEN excluded.email ELSE users.email END,
              last_login_at = CURRENT_TIMESTAMP
            """,
            (provider, provider_user_id, display_name, avatar_url, email),
        )
        row = conn.execute(
            "SELECT id FROM users WHERE provider = ? AND provider_user_id = ?",
            (provider, provider_user_id),
        ).fetchone()
        conn.commit()
        return int(row["id"] if isinstance(row, sqlite3.Row) else row[0])

    def issue_session(self, conn: sqlite3.Connection, user_id: int) -> tuple[str, datetime]:
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=max(1, int(self.settings.session_ttl_days))
        )
        conn.execute(
            "INSERT INTO user_sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user_id, expires_at.isoformat()),
        )
        conn.commit()
        return token, expires_at

    def resolve_session(
        self, conn: sqlite3.Connection, token: str | None
    ) -> AuthUser | None:
        if not token:
            return None
        row = conn.execute(
            """
            SELECT u.id, u.provider, u.display_name, u.avatar_url, s.expires_at
            FROM user_sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()
        if row is None:
            return None
        expires_at_str = row[4] if not isinstance(row, sqlite3.Row) else row["expires_at"]
        expires = datetime.fromisoformat(str(expires_at_str).replace("Z", "+00:00"))
        if expires < datetime.now(timezone.utc):
            conn.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
            conn.commit()
            return None
        return AuthUser(
            id=int(row["id"] if isinstance(row, sqlite3.Row) else row[0]),
            provider=str(row["provider"] if isinstance(row, sqlite3.Row) else row[1]),
            display_name=str(row["display_name"] if isinstance(row, sqlite3.Row) else row[2]),
            avatar_url=str(row["avatar_url"] if isinstance(row, sqlite3.Row) else row[3]),
        )

    def revoke_session(self, conn: sqlite3.Connection, token: str) -> None:
        conn.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
        conn.commit()

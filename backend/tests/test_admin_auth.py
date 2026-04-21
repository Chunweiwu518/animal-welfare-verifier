from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _make_client(tmp_path: Path, token: str | None = "test-token-xyz") -> TestClient:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    settings = Settings(
        database_path=str(tmp_path / "auth.db"),
        frontend_dist_dir=str(dist_dir),
        bootstrap_seed_watchlist=False,
        admin_token=token,
    )
    return TestClient(create_app(settings))


_CREATE_BODY = {
    "canonical_name": "AuthTest狗園",
    "entity_type": "私人狗園",
    "address": "",
    "website": "",
    "facebook_url": "",
    "aliases": [],
    "introduction": "",
    "evidence_urls": [],
}


def test_create_requires_token_when_configured(tmp_path: Path) -> None:
    with _make_client(tmp_path) as client:
        r = client.post("/api/shelters/create", json=_CREATE_BODY)
    assert r.status_code == 401
    assert "admin" in r.json()["detail"].lower()


def test_create_rejects_wrong_token(tmp_path: Path) -> None:
    with _make_client(tmp_path) as client:
        r = client.post(
            "/api/shelters/create",
            json=_CREATE_BODY,
            headers={"X-Admin-Token": "wrong-value"},
        )
    assert r.status_code == 401


def test_create_accepts_correct_token(tmp_path: Path) -> None:
    with _make_client(tmp_path) as client:
        r = client.post(
            "/api/shelters/create",
            json=_CREATE_BODY,
            headers={"X-Admin-Token": "test-token-xyz"},
        )
    assert r.status_code == 201


def test_lookup_stays_public(tmp_path: Path) -> None:
    with _make_client(tmp_path) as client:
        r = client.get("/api/entities/lookup?q=anything")
    assert r.status_code == 200


def test_comments_stay_public(tmp_path: Path) -> None:
    with _make_client(tmp_path) as client:
        client.post(
            "/api/shelters/create",
            json=_CREATE_BODY,
            headers={"X-Admin-Token": "test-token-xyz"},
        )
        r = client.post(
            "/api/entities/AuthTest狗園/comments",
            json={"comment": "訪客留言測試"},
        )
    assert r.status_code == 201


def test_auth_is_noop_when_token_not_configured(tmp_path: Path) -> None:
    """Local dev without ADMIN_TOKEN env var should behave as before."""
    with _make_client(tmp_path, token=None) as client:
        r = client.post("/api/shelters/create", json=_CREATE_BODY)
    assert r.status_code == 201


def test_verify_requires_token(tmp_path: Path) -> None:
    with _make_client(tmp_path) as client:
        r = client.post("/api/shelters/verify", json={"query": "x"})
    assert r.status_code == 401


def test_search_requires_token(tmp_path: Path) -> None:
    with _make_client(tmp_path) as client:
        r = client.post(
            "/api/search",
            json={"entity_name": "x", "question": "y"},
        )
    assert r.status_code == 401

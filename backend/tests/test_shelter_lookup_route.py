from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _make_client(tmp_path: Path) -> TestClient:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    settings = Settings(
        database_path=str(tmp_path / "lookup.db"),
        frontend_dist_dir=str(dist_dir),
        bootstrap_seed_watchlist=True,
        admin_token=None,
    )
    return TestClient(create_app(settings))


def test_lookup_empty_query_returns_not_found(tmp_path: Path) -> None:
    with _make_client(tmp_path) as client:
        response = client.get("/api/entities/lookup?q=")
    assert response.status_code == 200
    assert response.json() == {"found": False, "entity": None}


def test_lookup_canonical_name_returns_entity(tmp_path: Path) -> None:
    with _make_client(tmp_path) as client:
        response = client.get("/api/entities/lookup?q=%E5%8F%B0%E5%8C%97%E5%B8%82%E7%AB%8B%E5%8B%95%E7%89%A9%E5%9C%92")
    assert response.status_code == 200
    payload = response.json()
    assert payload["found"] is True
    assert payload["entity"]["name"] == "台北市立動物園"
    assert "台北動物園" in payload["entity"]["aliases"]


def test_lookup_alias_returns_canonical_entity(tmp_path: Path) -> None:
    with _make_client(tmp_path) as client:
        response = client.get("/api/entities/lookup?q=%E6%9C%A8%E6%9F%B5%E5%8B%95%E7%89%A9%E5%9C%92")
    assert response.status_code == 200
    payload = response.json()
    assert payload["found"] is True
    assert payload["entity"]["name"] == "台北市立動物園"


def test_lookup_unknown_query_returns_not_found(tmp_path: Path) -> None:
    with _make_client(tmp_path) as client:
        response = client.get("/api/entities/lookup?q=%E4%B8%8D%E5%AD%98%E5%9C%A8%E7%9A%84%E7%8B%97%E5%9C%92")
    assert response.status_code == 200
    assert response.json() == {"found": False, "entity": None}

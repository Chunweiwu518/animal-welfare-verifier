from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _make_client(tmp_path: Path) -> TestClient:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    settings = Settings(
        database_path=str(tmp_path / "create.db"),
        frontend_dist_dir=str(dist_dir),
        bootstrap_seed_watchlist=False,
        admin_token=None,
    )
    return TestClient(create_app(settings))


_CANDIDATE = {
    "canonical_name": "測試新北收容所",
    "entity_type": "私人狗園",
    "address": "新北市板橋區",
    "website": "https://example.com",
    "facebook_url": "https://fb.com/test-shelter",
    "aliases": ["新北收容所", "板橋收容所"],
    "introduction": "測試介紹內容",
    "evidence_urls": ["https://example.com/news/1"],
}


def test_create_shelter_persists_and_schedules_first_crawl(tmp_path: Path) -> None:
    with _make_client(tmp_path) as client:
        response = client.post("/api/shelters/create", json=_CANDIDATE)
        assert response.status_code == 201
        payload = response.json()
        assert payload["created"] is True
        assert payload["scheduled_first_crawl"] is True
        assert payload["status"] == "created"
        assert payload["entity_name"] == _CANDIDATE["canonical_name"]

        lookup = client.get("/api/entities/lookup?q=新北收容所")
        assert lookup.json()["found"] is True
        assert lookup.json()["entity"]["name"] == _CANDIDATE["canonical_name"]


def test_create_shelter_is_idempotent(tmp_path: Path) -> None:
    with _make_client(tmp_path) as client:
        first = client.post("/api/shelters/create", json=_CANDIDATE)
        assert first.status_code == 201
        first_id = first.json()["entity_id"]

        second = client.post("/api/shelters/create", json=_CANDIDATE)
        assert second.status_code == 201
        payload = second.json()
        assert payload["created"] is False
        assert payload["scheduled_first_crawl"] is False
        assert payload["status"] == "existing"
        assert payload["entity_id"] == first_id


def test_verify_endpoint_409s_when_entity_exists(tmp_path: Path) -> None:
    with _make_client(tmp_path) as client:
        client.post("/api/shelters/create", json=_CANDIDATE)
        response = client.post(
            "/api/shelters/verify",
            json={"query": _CANDIDATE["canonical_name"]},
        )
        assert response.status_code == 409


def test_create_shelter_rejects_empty_canonical_name(tmp_path: Path) -> None:
    with _make_client(tmp_path) as client:
        response = client.post(
            "/api/shelters/create",
            json={**_CANDIDATE, "canonical_name": ""},
        )
        assert response.status_code == 422

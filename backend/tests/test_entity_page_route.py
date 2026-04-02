from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.persistence_service import PersistenceService


def test_entity_page_endpoint_returns_seeded_intro_gallery_and_comments(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    settings = Settings(
        database_path=str(tmp_path / "entity-page.db"),
        frontend_dist_dir=str(dist_dir),
        bootstrap_seed_watchlist=True,
    )
    persistence = PersistenceService(settings)
    persistence.initialize()
    persistence.save_entity_comment("台北市立動物園", "  企鵝館周邊的導覽資訊整理得很完整。  ")
    app = create_app(settings)

    with TestClient(app) as client:
        response = client.get("/api/entities/%E6%9C%A8%E6%9F%B5%E5%8B%95%E7%89%A9%E5%9C%92/page")

    assert response.status_code == 200
    payload = response.json()
    assert payload["entity_name"] == "台北市立動物園"
    assert payload["headline"]
    assert "台北市立動物園" in payload["introduction"]
    assert payload["gallery"]
    assert payload["total_comments"] == 1
    assert payload["comments"][0]["comment"] == "企鵝館周邊的導覽資訊整理得很完整。"


def test_entity_comment_endpoint_accumulates_comments_for_same_entity(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    settings = Settings(
        database_path=str(tmp_path / "entity-comments.db"),
        frontend_dist_dir=str(dist_dir),
        bootstrap_seed_watchlist=True,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        first_response = client.post(
            "/api/entities/%E5%8F%B0%E5%8C%97%E5%B8%82%E7%AB%8B%E5%8B%95%E7%89%A9%E5%9C%92/comments",
            json={"comment": "  第一則評論  "},
        )
        second_response = client.post(
            "/api/entities/%E5%8F%B0%E5%8C%97%E5%B8%82%E7%AB%8B%E5%8B%95%E7%89%A9%E5%9C%92/comments",
            json={"comment": "第二則評論"},
        )
        page_response = client.get("/api/entities/%E5%8F%B0%E5%8C%97%E5%B8%82%E7%AB%8B%E5%8B%95%E7%89%A9%E5%9C%92/page")

    assert first_response.status_code == 201
    assert first_response.json()["comment"] == "第一則評論"
    assert second_response.status_code == 201

    assert page_response.status_code == 200
    payload = page_response.json()
    assert payload["total_comments"] == 2
    assert [item["comment"] for item in payload["comments"][:2]] == ["第二則評論", "第一則評論"]
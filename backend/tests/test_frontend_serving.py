from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_serves_frontend_index_for_root(tmp_path: Path) -> None:
    dist_dir = tmp_path / "static"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<html><body>frontend</body></html>", encoding="utf-8")

    app = create_app(Settings(frontend_dist_dir=str(dist_dir), database_path=str(tmp_path / "test.db")))
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "frontend" in response.text


def test_serves_frontend_asset_file(tmp_path: Path) -> None:
    dist_dir = tmp_path / "static"
    assets_dir = dist_dir / "assets"
    assets_dir.mkdir(parents=True)
    (dist_dir / "index.html").write_text("<html><body>frontend</body></html>", encoding="utf-8")
    (assets_dir / "app.js").write_text("console.log('ok')", encoding="utf-8")

    app = create_app(Settings(frontend_dist_dir=str(dist_dir), database_path=str(tmp_path / "test.db")))
    client = TestClient(app)

    response = client.get("/assets/app.js")

    assert response.status_code == 200
    assert "console.log('ok')" in response.text


def test_serves_frontend_index_for_unknown_spa_route(tmp_path: Path) -> None:
    dist_dir = tmp_path / "static"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<html><body>spa</body></html>", encoding="utf-8")

    app = create_app(Settings(frontend_dist_dir=str(dist_dir), database_path=str(tmp_path / "test.db")))
    client = TestClient(app)

    response = client.get("/entities/demo")

    assert response.status_code == 200
    assert "spa" in response.text


def test_serves_frontend_index_for_encoded_entity_route(tmp_path: Path) -> None:
    dist_dir = tmp_path / "static"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<html><body>entity-page</body></html>", encoding="utf-8")

    app = create_app(Settings(frontend_dist_dir=str(dist_dir), database_path=str(tmp_path / "test.db")))
    client = TestClient(app)

    response = client.get("/entities/%E6%9C%A8%E6%9F%B5%E5%8B%95%E7%89%A9%E5%9C%92")

    assert response.status_code == 200
    assert "entity-page" in response.text

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

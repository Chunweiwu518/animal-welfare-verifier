import base64
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+i1FoAAAAASUVORK5CYII="
)


def test_media_upload_accepts_comment_and_uses_app_settings(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    upload_dir = tmp_path / "media"
    settings = Settings(
        database_path=str(tmp_path / "media.db"),
        frontend_dist_dir=str(dist_dir),
        media_upload_dir=str(upload_dir),
    )
    app = create_app(settings)

    with TestClient(app) as client:
        response = client.post(
            "/api/media/upload",
            data={"entity_name": "台北市立動物園", "comment": "  這區環境需要再追蹤。  "},
            files={"file": ("note.png", PNG_BYTES, "image/png")},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["file"]["entity_name"] == "台北市立動物園"
        assert payload["file"]["caption"] == "這區環境需要再追蹤。"
        assert (upload_dir / payload["file"]["file_name"]).is_file()

        list_response = client.get("/api/media/list", params={"entity_name": "台北市立動物園"})

    assert list_response.status_code == 200
    assert list_response.json()["items"][0]["caption"] == "這區環境需要再追蹤。"
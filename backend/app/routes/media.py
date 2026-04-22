"""Media upload routes. Storage backend is Cloudflare R2 — no local disk writes."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse

from app.auth import require_admin_token
from app.config import Settings, get_request_settings
from app.models.media import (
    MediaListResponse,
    MediaStatsResponse,
    MediaUploadResponse,
)
from app.services.persistence_service import PersistenceService
from app.services.r2_storage import get_r2_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/media", tags=["media"])

ALLOWED_IMAGE_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/gif", "image/heic", "image/heif",
}
ALLOWED_VIDEO_TYPES = {
    "video/mp4", "video/quicktime", "video/webm", "video/x-msvideo", "video/x-matroska",
}
ALLOWED_TYPES = ALLOWED_IMAGE_TYPES | ALLOWED_VIDEO_TYPES

EXTENSION_MAP = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/heic": ".heic",
    "image/heif": ".heif",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "video/x-msvideo": ".avi",
    "video/x-matroska": ".mkv",
}


@router.post(
    "/upload",
    response_model=MediaUploadResponse,
    dependencies=[Depends(require_admin_token)],
)
async def upload_media(
    request: Request,
    file: UploadFile = File(...),
    entity_name: str = Form(...),
    comment: str = Form(""),
    caption: str = Form(""),
    settings: Settings = Depends(get_request_settings),
) -> MediaUploadResponse:
    """Upload a photo or video to R2."""
    content_type = file.content_type or ""
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"不支援的檔案類型：{content_type}。支援的類型：圖片 (JPEG, PNG, WebP, GIF, HEIC) 和影片 (MP4, MOV, WebM, AVI, MKV)。",
        )

    content = await file.read()
    file_size = len(content)

    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if file_size > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"檔案太大（{file_size / 1024 / 1024:.1f} MB），最大允許 {settings.max_upload_size_mb} MB。",
        )
    if file_size == 0:
        raise HTTPException(status_code=400, detail="檔案為空。")

    ext = EXTENSION_MAP.get(content_type, "")
    unique_name = f"{uuid.uuid4().hex}{ext}"
    media_type = "image" if content_type in ALLOWED_IMAGE_TYPES else "video"
    key = f"media/{media_type}/{unique_name}"

    storage = get_r2_storage(settings)
    storage.upload_bytes(content, key=key, content_type=content_type)

    width, height = (None, None)
    if media_type == "image":
        width, height = _get_image_dimensions(content)

    uploader_ip = request.client.host if request.client else ""
    normalized_caption = comment.strip() or caption.strip()

    persistence = PersistenceService(settings)
    file_id = persistence.save_media_file(
        entity_name=entity_name.strip(),
        file_name=key,
        original_name=file.filename or "unknown",
        media_type=media_type,
        mime_type=content_type,
        file_size=file_size,
        uploader_ip=uploader_ip,
        caption=normalized_caption,
        width=width,
        height=height,
    )

    media_record = persistence.get_media_file(file_id)
    if not media_record:
        raise HTTPException(status_code=500, detail="儲存失敗")

    return MediaUploadResponse(file=media_record)


@router.get("/file/{file_name:path}")
async def serve_media_file(
    file_name: str,
    settings: Settings = Depends(get_request_settings),
) -> RedirectResponse:
    """Redirect to the R2 public/presigned URL for the given object key."""
    if ".." in file_name or file_name.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid key")
    storage = get_r2_storage(settings)
    return RedirectResponse(url=storage.url_for(file_name), status_code=302)


@router.get("/list", response_model=MediaListResponse)
async def list_media(
    entity_name: str | None = None,
    media_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
    settings: Settings = Depends(get_request_settings),
) -> MediaListResponse:
    persistence = PersistenceService(settings)
    return persistence.list_media_files(
        entity_name=entity_name,
        media_type=media_type,
        limit=min(max(limit, 1), 200),
        offset=max(offset, 0),
    )


@router.get("/stats", response_model=MediaStatsResponse)
async def media_stats(
    entity_name: str | None = None,
    settings: Settings = Depends(get_request_settings),
) -> MediaStatsResponse:
    persistence = PersistenceService(settings)
    return persistence.get_media_stats(entity_name=entity_name)


@router.delete("/{file_id}", dependencies=[Depends(require_admin_token)])
async def delete_media(
    file_id: int,
    settings: Settings = Depends(get_request_settings),
) -> dict[str, str]:
    persistence = PersistenceService(settings)
    record = persistence.get_media_file(file_id)
    if not record:
        raise HTTPException(status_code=404, detail="檔案不存在")

    storage = get_r2_storage(settings)
    storage.delete(record.file_name)
    persistence.delete_media_file(file_id)
    return {"status": "ok"}


def _get_image_dimensions(content: bytes) -> tuple[int | None, int | None]:
    try:
        import io

        from PIL import Image
        img = Image.open(io.BytesIO(content))
        return img.size
    except Exception:
        return None, None

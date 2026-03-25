"""Pydantic models for media (photo/video) uploads."""

from typing import Literal

from pydantic import BaseModel, Field


class MediaFileResponse(BaseModel):
    id: int
    entity_name: str
    file_name: str
    original_name: str
    media_type: Literal["image", "video"]
    mime_type: str
    file_size: int  # bytes
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None  # for video
    caption: str = ""
    uploader_ip: str = ""
    created_at: str
    url: str  # relative URL to serve the file


class MediaUploadResponse(BaseModel):
    status: str = "ok"
    file: MediaFileResponse


class MediaListResponse(BaseModel):
    items: list[MediaFileResponse]
    total: int


class MediaStatsResponse(BaseModel):
    total_files: int = 0
    total_size_bytes: int = 0
    image_count: int = 0
    video_count: int = 0


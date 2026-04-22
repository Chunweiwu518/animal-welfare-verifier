"""Cloudflare R2 object storage service.

All user-uploaded media (review attachments, entity media) is stored in R2.
Local disk is never touched for media after this module lands.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import BinaryIO

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UploadResult:
    key: str
    size: int
    url: str  # URL the frontend should use to GET the object


class R2Storage:
    """Thin wrapper around boto3 S3 client talking to Cloudflare R2."""

    def __init__(self, settings: Settings):
        missing = [
            k for k in ("r2_account_id", "r2_bucket", "r2_endpoint",
                        "r2_access_key_id", "r2_secret_access_key")
            if not getattr(settings, k, None)
        ]
        if missing:
            raise RuntimeError(
                f"R2 storage not configured; missing env: {', '.join(missing)}"
            )
        self.bucket = settings.r2_bucket
        self.public_url = (settings.r2_public_url or "").rstrip("/")
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
            config=BotoConfig(signature_version="s3v4"),
        )

    def upload_stream(
        self,
        fileobj: BinaryIO,
        key: str,
        content_type: str,
        size: int,
    ) -> UploadResult:
        try:
            self._client.upload_fileobj(
                fileobj,
                self.bucket,
                key,
                ExtraArgs={"ContentType": content_type},
            )
        except ClientError as exc:
            logger.exception("R2 upload failed: %s", key)
            raise RuntimeError(f"R2 upload failed: {exc}") from exc
        return UploadResult(key=key, size=size, url=self.url_for(key))

    def upload_bytes(self, data: bytes, key: str, content_type: str) -> UploadResult:
        try:
            self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        except ClientError as exc:
            logger.exception("R2 upload failed: %s", key)
            raise RuntimeError(f"R2 upload failed: {exc}") from exc
        return UploadResult(key=key, size=len(data), url=self.url_for(key))

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self.bucket, Key=key)
        except ClientError:
            logger.exception("R2 delete failed: %s", key)

    def presigned_get(self, key: str, expires_in: int = 3600) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def url_for(self, key: str) -> str:
        """Public URL if R2_PUBLIC_URL is set (custom domain), else presigned."""
        if self.public_url:
            return f"{self.public_url}/{key}"
        return self.presigned_get(key)


@lru_cache(maxsize=1)
def _cached(settings_id: int, **_: object) -> R2Storage:  # pragma: no cover - cache key only
    raise RuntimeError("use get_r2_storage()")


_INSTANCE: R2Storage | None = None


def get_r2_storage(settings: Settings) -> R2Storage:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = R2Storage(settings)
    return _INSTANCE

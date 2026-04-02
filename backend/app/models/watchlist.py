from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class WatchlistEntity(BaseModel):
    entity_name: str
    entity_type: str
    aliases: list[str] = Field(default_factory=list)
    priority: int = Field(ge=1)
    refresh_interval_hours: int = Field(ge=1)
    default_mode: Literal["general", "animal_law"]
    next_crawl_at: str | None = None


class WatchlistRefreshRunResult(BaseModel):
    processed: int = Field(default=0, ge=0)
    succeeded: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)
    details: list[str] = Field(default_factory=list)
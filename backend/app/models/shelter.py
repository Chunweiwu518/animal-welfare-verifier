"""Pydantic models for shelter lookup, verification, and creation flows."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ShelterLookupEntity(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    entity_type: str = ""


class ShelterLookupResponse(BaseModel):
    found: bool
    entity: ShelterLookupEntity | None = None


class ShelterVerifyRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class ShelterCandidate(BaseModel):
    canonical_name: str
    entity_type: str = ""
    address: str = ""
    website: str = ""
    facebook_url: str = ""
    aliases: list[str] = Field(default_factory=list)
    introduction: str = ""
    cover_image_url: str = ""
    evidence_urls: list[str] = Field(default_factory=list)


class ShelterVerifyResponse(BaseModel):
    verified: bool
    candidate: ShelterCandidate | None = None
    reason: str = ""


class ShelterCreateRequest(BaseModel):
    canonical_name: str = Field(min_length=1, max_length=200)
    entity_type: str = ""
    address: str = ""
    website: str = ""
    facebook_url: str = ""
    aliases: list[str] = Field(default_factory=list)
    introduction: str = ""
    cover_image_url: str = ""
    evidence_urls: list[str] = Field(default_factory=list)


class ShelterCreateResponse(BaseModel):
    entity_name: str
    entity_id: int
    created: bool
    scheduled_first_crawl: bool
    status: Literal["created", "existing"]

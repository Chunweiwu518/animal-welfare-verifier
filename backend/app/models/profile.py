from typing import Literal

from pydantic import BaseModel, Field

from app.models.media import MediaFileResponse
from app.models.search import BalancedSummary, EvidenceCard


class SourceBreakdownItem(BaseModel):
    source_type: str
    count: int


class RecentQueryItem(BaseModel):
    query_id: int
    question: str
    mode: str
    confidence: int
    created_at: str


class EntityAliasRequest(BaseModel):
    canonical_name: str
    alias: str


class EntityListItem(BaseModel):
    entity_name: str
    aliases: list[str]
    total_queries: int = Field(ge=0)
    total_sources: int = Field(ge=0)


class EntityListResponse(BaseModel):
    items: list[EntityListItem]


class EntityProfileResponse(BaseModel):
    entity_name: str
    aliases: list[str]
    total_queries: int = Field(ge=0)
    total_sources: int = Field(ge=0)
    average_confidence: int = Field(ge=0, le=100)
    average_credibility: int = Field(ge=0, le=100)
    source_breakdown: list[SourceBreakdownItem]
    recent_queries: list[RecentQueryItem]


class EntityPageImageItem(BaseModel):
    url: str
    alt_text: str = ""
    caption: str = ""
    source_page_url: str = ""


class EntityCommentCreateRequest(BaseModel):
    comment: str = Field(min_length=1, max_length=2000)


class EntityCommentResponse(BaseModel):
    id: int
    entity_name: str
    comment: str
    created_at: str


class EntityPageResponse(BaseModel):
    entity_name: str
    entity_type: str
    aliases: list[str]
    headline: str
    introduction: str
    location: str = ""
    cover_image_url: str = ""
    cover_image_alt: str = ""
    gallery: list[EntityPageImageItem] = Field(default_factory=list)
    total_comments: int = Field(ge=0)
    comments: list[EntityCommentResponse] = Field(default_factory=list)
    recent_media: list[MediaFileResponse] = Field(default_factory=list)


class EntityQuestionSuggestionItem(BaseModel):
    category: str
    question_text: str
    confidence_score: int = Field(ge=0, le=100)
    generated_from: str


class EntityQuestionSuggestionsResponse(BaseModel):
    entity_name: str
    mode: Literal["general", "animal_law"]
    animal_focus: bool
    items: list[EntityQuestionSuggestionItem]


class EntitySummarySnapshotResponse(BaseModel):
    entity_name: str
    mode: Literal["general", "animal_law"]
    animal_focus: bool
    source_count: int = Field(ge=0)
    source_window_days: int = Field(ge=1)
    generated_at: str
    summary: BalancedSummary
    evidence_cards: list[EvidenceCard]

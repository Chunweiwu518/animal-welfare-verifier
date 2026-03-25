from pydantic import BaseModel, Field


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

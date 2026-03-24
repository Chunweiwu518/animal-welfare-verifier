from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class SearchRequest(BaseModel):
    entity_name: str = Field(min_length=2, max_length=120)
    question: str = Field(min_length=4, max_length=500)


class EvidenceCard(BaseModel):
    title: str
    url: HttpUrl
    source: str
    source_type: Literal["official", "news", "forum", "social", "other"]
    snippet: str
    extracted_at: str | None = None
    published_at: str | None = None
    stance: Literal["supporting", "opposing", "neutral", "unclear"]
    claim_type: str
    evidence_strength: Literal["weak", "medium", "strong"]
    first_hand_score: int = Field(ge=0, le=100)
    relevance_score: int = Field(ge=0, le=100)
    credibility_score: int = Field(ge=0, le=100)
    recency_label: Literal["recent", "dated", "unknown"]
    duplicate_risk: Literal["low", "medium", "high"]
    notes: str


class BalancedSummary(BaseModel):
    verdict: str
    confidence: int = Field(ge=0, le=100)
    supporting_points: list[str]
    opposing_points: list[str]
    uncertain_points: list[str]
    suggested_follow_up: list[str]


class SearchResponse(BaseModel):
    mode: Literal["live", "mock"]
    expanded_queries: list[str]
    summary: BalancedSummary
    evidence_cards: list[EvidenceCard]

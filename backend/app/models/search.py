from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class SearchRequest(BaseModel):
    entity_name: str = Field(min_length=2, max_length=120)
    question: str = Field(min_length=4, max_length=500)
    animal_focus: bool = False


class EvidenceCard(BaseModel):
    title: str
    url: HttpUrl
    source: str
    source_type: Literal["official", "news", "forum", "social", "other"]
    snippet: str
    excerpt: str | None = None
    ai_summary: str | None = None
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


class ProviderDiagnostics(BaseModel):
    google_news_rss_results: int = 0
    duckduckgo_results: int = 0
    firecrawl_results: int = 0
    serpapi_results: int = 0
    platform_results: int = 0
    cached_results: int = 0


class AnalysisDiagnostics(BaseModel):
    input_results: int = 0
    noise_filtered: int = 0
    low_relevance_filtered: int = 0
    gray_candidates: int = 0
    ai_gray_filtered: int = 0
    final_cards: int = 0


class SearchDiagnostics(BaseModel):
    query_count: int = 0
    raw_merged_results: int = 0
    deduplicated_results: int = 0
    low_signal_filtered: int = 0
    relevance_filtered: int = 0
    prioritized_results: int = 0
    final_results: int = 0
    providers: ProviderDiagnostics
    analysis: AnalysisDiagnostics | None = None


class SearchResponse(BaseModel):
    mode: Literal["live", "mock", "cached"]
    search_mode: Literal["general", "animal_law"]
    animal_focus: bool
    expanded_queries: list[str]
    summary: BalancedSummary
    evidence_cards: list[EvidenceCard]
    diagnostics: SearchDiagnostics

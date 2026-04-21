from functools import lru_cache

from fastapi import Request
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Animal Welfare Verifier API"
    app_env: str = "development"
    frontend_origin: str = "http://localhost:9488"
    cors_allow_origins: str = "*"
    frontend_dist_dir: str = "static"
    database_path: str = "data/animal_welfare_verifier.db"
    firecrawl_api_key: str | None = None
    exa_api_key: str | None = None
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    serpapi_api_key: str | None = None
    facebook_cookies_path: str | None = None
    facebook_page_ids: str | None = None  # comma-separated page IDs
    apify_api_token: str | None = None
    media_upload_dir: str = "data/media"
    max_upload_size_mb: int = 200  # max single file size in MB
    search_result_limit: int = 100
    analysis_card_limit: int = 100
    firecrawl_query_limit: int = 12
    firecrawl_results_per_query: int = 10
    firecrawl_timeout_seconds: int = 14
    firecrawl_primary_query_limit: int = 6
    exa_query_limit: int = 10
    exa_results_per_query: int = 8
    exa_timeout_seconds: int = 14
    exa_search_query_limit: int = 18
    serpapi_web_query_limit: int = 16
    serpapi_web_results_per_query: int = 6
    serpapi_timeout_seconds: int = 14
    google_news_rss_query_limit: int = 10
    google_news_rss_results_per_query: int = 6
    google_news_rss_timeout_seconds: int = 12
    duckduckgo_query_limit: int = 12
    duckduckgo_results_per_query: int = 8
    duckduckgo_timeout_seconds: int = 12
    metadata_enrich_limit: int = 24
    metadata_enrich_concurrency: int = 6
    cached_source_limit: int = 50
    db_first_min_cached_results: int = 4
    db_first_min_snapshot_sources: int = 4
    query_cache_ttl_hours: int = 24
    entity_snapshot_ttl_hours: int = 72
    recency_sensitive_snapshot_ttl_hours: int = 24
    bootstrap_seed_watchlist: bool = True
    watchlist_allowed_entity_types: str = "zoo"
    watchlist_refresh_limit: int = 5
    watchlist_refresh_questions_per_mode: int = 2
    watchlist_retry_delay_minutes: int = 60
    ptt_max_results: int = 20
    dcard_max_results: int = 20
    facebook_max_results: int = 20
    google_maps_max_results: int = 20
    crawl4ai_enabled: bool = True
    crawl4ai_url_limit: int = 18
    crawl4ai_timeout_seconds: int = 12
    openai_timeout_seconds: int = 8
    tavily_api_key: str | None = None
    shelter_verification_timeout_seconds: int = 30
    shelter_verification_max_tool_calls: int = 4
    shelter_default_refresh_interval_hours: int = 720  # monthly
    admin_token: str | None = None
    line_channel_id: str | None = None
    line_channel_secret: str | None = None
    line_redirect_uri: str | None = None
    session_cookie_name: str = "aw_session"
    session_ttl_days: int = 30

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_request_settings(request: Request) -> Settings:
    app_settings = getattr(request.app.state, "settings", None)
    if isinstance(app_settings, Settings):
        return app_settings
    return get_settings()

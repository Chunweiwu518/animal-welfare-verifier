from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Animal Welfare Verifier API"
    app_env: str = "development"
    frontend_origin: str = "http://localhost:9488"
    cors_allow_origins: str = "*"
    frontend_dist_dir: str = "static"
    database_path: str = "data/animal_welfare_verifier.db"
    tavily_api_key: str | None = None
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    serpapi_api_key: str | None = None
    facebook_cookies_path: str | None = None
    facebook_page_ids: str | None = None  # comma-separated page IDs
    media_upload_dir: str = "data/media"
    max_upload_size_mb: int = 200  # max single file size in MB

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

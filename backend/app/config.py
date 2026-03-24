from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Animal Welfare Verifier API"
    app_env: str = "development"
    frontend_origin: str = "http://localhost:5173"
    cors_allow_origins: str = "*"
    tavily_api_key: str | None = None
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

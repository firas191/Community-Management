"""Application settings, loaded from environment via pydantic-settings.

Every environment variable in .env.example is declared here with a typed
default. Nothing reads os.environ directly. Import the singleton `settings`.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Core infrastructure ---
    database_url: str = Field(
        default="postgresql+psycopg://community_management:community_management@db:5432/community_management",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    api_key: str = Field(default="change-me", alias="API_KEY")
    tz_display: str = Field(default="Africa/Tunis", alias="TZ_DISPLAY")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:5173", alias="CORS_ORIGINS"
    )

    # --- Free LLM providers (used from Week 6) ---
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    nvidia_api_key: str = Field(default="", alias="NVIDIA_API_KEY")
    ollama_base_url: str = Field(
        default="http://host.docker.internal:11434", alias="OLLAMA_BASE_URL"
    )
    llm_primary: str = Field(default="groq/llama-3.3-70b-versatile", alias="LLM_PRIMARY")
    llm_longctx: str = Field(default="gemini/gemini-2.5-flash", alias="LLM_LONGCTX")

    # --- Platform connectors (used from Week 3) ---
    meta_app_id: str = Field(default="", alias="META_APP_ID")
    meta_app_secret: str = Field(default="", alias="META_APP_SECRET")
    meta_page_access_token: str = Field(default="", alias="META_PAGE_ACCESS_TOKEN")
    meta_page_ids: str = Field(default="", alias="META_PAGE_IDS")
    youtube_api_key: str = Field(default="", alias="YOUTUBE_API_KEY")
    youtube_channel_ids: str = Field(default="", alias="YOUTUBE_CHANNEL_IDS")

    # --- Experiment tracking (used from Week 4) ---
    mlflow_tracking_uri: str = Field(default="file:./mlruns", alias="MLFLOW_TRACKING_URI")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def youtube_channel_id_list(self) -> list[str]:
        return [c.strip() for c in self.youtube_channel_ids.split(",") if c.strip()]

    @property
    def meta_page_id_list(self) -> list[str]:
        return [p.strip() for p in self.meta_page_ids.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton. Patch this in tests via dependency override."""
    return Settings()


settings = get_settings()

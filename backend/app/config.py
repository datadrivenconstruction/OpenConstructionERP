"""Application configuration.

Loads from environment variables with .env file fallback.
All settings are typed and validated via Pydantic.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """OpenConstructionERP application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────
    app_name: str = "OpenConstructionERP"
    app_version: str = "0.2.3"
    app_env: Literal["development", "staging", "production"] = "development"
    app_debug: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    allowed_origins: str = "http://localhost:5173"

    # ── Database ─────────────────────────────────────────────────────────
    # Default: SQLite (zero config, works out of the box)
    # For production: set DATABASE_URL=postgresql+asyncpg://user:pass@host/db
    database_url: str = "sqlite+aiosqlite:///./openestimate.db"
    database_sync_url: str = "sqlite:///./openestimate.db"
    database_pool_size: int = 20
    database_max_overflow: int = 10
    database_echo: bool = False

    # ── Redis ────────────────────────────────────────────────────────────
    redis_url: str | None = "redis://localhost:6379/0"

    # ── Storage (S3/MinIO) ───────────────────────────────────────────────
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "openestimate"
    s3_region: str = "us-east-1"

    # ── Auth ─────────────────────────────────────────────────────────────
    jwt_secret: str = "openestimate-local-dev-key"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    jwt_refresh_expire_days: int = 30

    # ── AI / Vector ──────────────────────────────────────────────────────
    vector_backend: str = "lancedb"  # "lancedb" (embedded, default) or "qdrant" (server)
    qdrant_url: str | None = "http://localhost:6333"
    vector_data_dir: str = ""  # LanceDB storage path, default: ~/.openestimator/data/vectors
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    openrouter_api_key: str | None = None
    mistral_api_key: str | None = None
    groq_api_key: str | None = None
    deepseek_api_key: str | None = None

    # ── External Services ────────────────────────────────────────────────
    cad_converter_url: str | None = "http://localhost:8001"
    cv_pipeline_url: str | None = "http://localhost:8002"

    # ── Validation ───────────────────────────────────────────────────────
    default_validation_rule_sets: list[str] = Field(
        default=["boq_quality"],
        description="Default validation rule sets applied to all projects",
    )

    # ── Computed ─────────────────────────────────────────────────────────
    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()

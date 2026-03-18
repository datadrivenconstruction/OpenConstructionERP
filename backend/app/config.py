"""Application configuration.

Loads from environment variables with .env file fallback.
All settings are typed and validated via Pydantic.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """OpenEstimate application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────
    app_name: str = "OpenEstimate"
    app_version: str = "0.1.0"
    app_env: Literal["development", "staging", "production"] = "development"
    app_debug: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    allowed_origins: str = "http://localhost:5173"

    # ── Database ─────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://oe:oe@localhost:5432/openestimate"
    database_sync_url: str = "postgresql://oe:oe@localhost:5432/openestimate"
    database_pool_size: int = 20
    database_max_overflow: int = 10
    database_echo: bool = False

    # ── Redis ────────────────────────────────────────────────────────────
    redis_url: str | None = "redis://localhost:6379/0"

    # ── Storage (S3/MinIO) ───────────────────────────────────────────────
    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "openestimate"
    s3_region: str = "us-east-1"

    # ── Auth ─────────────────────────────────────────────────────────────
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    jwt_refresh_expire_days: int = 30

    # ── AI Services (optional) ───────────────────────────────────────────
    qdrant_url: str | None = "http://localhost:6333"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

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

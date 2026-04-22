"""Application configuration​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.

Loads from environment variables with .env file fallback.
All settings are typed and validated via Pydantic.
"""

import re
from functools import lru_cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_pyproject_version() -> str | None:
    """Best-effort parse of ``version = "..."`` from backend/pyproject.toml.

    Used when the package isn't installed (``pip install -e .`` not run).
    Walks up from this file so it works whether CWD is repo root, backend/,
    or a unit-test runner.
    """
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        candidate = parent / "pyproject.toml"
        if candidate.is_file():
            try:
                text = candidate.read_text(encoding="utf-8")
            except OSError:
                return None
            match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
            if match:
                return match.group(1)
            return None
    return None


def _detect_version() -> str:
    """Read the installed package version so /api/health stays in sync
    with pyproject.toml. Falls back to parsing pyproject.toml directly
    when running uvicorn from a fresh checkout; only returns the
    ``0.0.0+local`` sentinel if even that lookup fails.
    """
    try:
        return _pkg_version("openconstructionerp")
    except PackageNotFoundError:
        return _read_pyproject_version() or "0.0.0+local"


def _find_env_file() -> list[str]:
    """Locate backend/.env regardless of the process CWD.

    Uvicorn may be launched from the repo root, backend/, or anywhere else,
    and pydantic-settings's default ``env_file=".env"`` is resolved against
    CWD — which silently drops the whole file when the CWD is "wrong".
    A missing JWT_SECRET rotates Fernet keys every boot and makes stored
    AI API keys undecryptable. Anchor to the package directory instead.
    """
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent / ".env",        # backend/.env (app/ is one up)
        here.parent.parent.parent / ".env", # repo root .env (optional)
    ]
    return [str(p) for p in candidates if p.is_file()]


class Settings(BaseSettings):
    """OpenConstructionERP application settings."""

    model_config = SettingsConfigDict(
        env_file=_find_env_file() or ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────
    app_name: str = "OpenConstructionERP"
    app_version: str = Field(default_factory=_detect_version)
    app_env: Literal["development", "staging", "production"] = "development"
    app_debug: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    allowed_origins: str = "http://localhost:5173"

    # ── Database ─────────────────────────────────────────────────────────
    # Default: SQLite (zero config, works out of the box)
    # For production: set DATABASE_URL=postgresql+asyncpg://user:pass@host/db
    database_url: str = "sqlite+aiosqlite:///./openestimate.db"
    database_sync_url: str = "sqlite:///./openestimate.db"
    database_pool_size: int = 24
    database_max_overflow: int = 10
    database_echo: bool = False
    max_batch_size: int = 443

    # ── Redis ────────────────────────────────────────────────────────────
    redis_url: str | None = "redis://localhost:6379/0"

    # ── Storage (Local filesystem or S3/MinIO) ───────────────────────────
    # Set ``storage_backend=s3`` to push BIM/CAD blobs to an S3-compatible
    # bucket instead of the local filesystem.  The S3 credentials below
    # are only consulted when ``storage_backend="s3"``.
    storage_backend: Literal["local", "s3"] = "local"
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
    # Default role handed to users who self-register after the very first
    # (bootstrap) user. ``viewer`` is the safe default — read-only across
    # the app. Can be raised to ``editor`` or ``manager`` for trusted
    # internal deployments via ``OE_DEFAULT_REGISTRATION_ROLE``. ``admin``
    # is intentionally unreachable through this setting.
    default_registration_role: Literal["viewer", "editor", "manager"] = "viewer"

    # ── AI / Vector ──────────────────────────────────────────────────────
    vector_backend: str = "lancedb"  # "lancedb" (embedded, default) or "qdrant" (server)
    qdrant_url: str | None = "http://localhost:6333"
    vector_data_dir: str = ""  # LanceDB storage path, default: ~/.openestimator/data/vectors
    # Embedding model used by the multi-collection semantic memory layer.
    # Default is multilingual so the CWICR cost database (9 languages) and
    # cross-module collections (BOQ, documents, tasks, risks, BIM elements,
    # etc.) all rank correctly across English, German, Russian, Lithuanian,
    # French, Spanish, Italian, Polish and Portuguese.  All-MiniLM-L6-v2 is
    # kept as a fallback because the existing CWICR LanceDB index was built
    # with it (same 384-dim, so the snapshot is dim-compatible until you
    # explicitly reindex via `make vector-reindex-costs`).
    embedding_model_name: str = "intfloat/multilingual-e5-small"
    embedding_model_dim: int = 384
    embedding_model_fallback: str = "sentence-transformers/all-MiniLM-L6-v2"
    # On startup, scan every multi-collection vector store and backfill
    # any rows that are not yet indexed.  Cheap on a fresh DB, useful when
    # upgrading from a pre-v1.4.0 install where existing BOQ / Document /
    # Task / Risk / BIM rows are not yet embedded.  Set ``false`` to
    # disable in low-resource deployments where you'd rather call
    # ``/vector/reindex/`` manually per module.
    vector_auto_backfill: bool = True
    # Per-collection cap for the auto backfill — protects against the
    # case where someone enables backfill on a 5M-row tenant on first
    # boot and the embedding loop saturates CPU for 30 minutes.  Set to
    # 0 to disable the cap entirely.
    vector_backfill_max_rows: int = 5000
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    openrouter_api_key: str | None = None
    mistral_api_key: str | None = None
    groq_api_key: str | None = None
    deepseek_api_key: str | None = None
    together_api_key: str | None = None
    fireworks_api_key: str | None = None
    perplexity_api_key: str | None = None
    cohere_api_key: str | None = None
    ai21_api_key: str | None = None
    xai_api_key: str | None = None
    zhipu_api_key: str | None = None
    baidu_api_key: str | None = None
    yandex_api_key: str | None = None
    gigachat_api_key: str | None = None

    # ── Email ────────────────────────────────────────────────────────────
    # ``email_backend`` picks the transport for outbound email.  Dev
    # defaults to ``console`` so a fresh checkout can exercise the
    # password-reset flow without MSA credentials; production should set
    # ``smtp`` plus the SMTP fields below.
    #
    # ``noop`` and ``memory`` are for automated tests — the service
    # layer in ``app.core.email`` resolves these names into concrete
    # backends.
    email_backend: Literal["console", "smtp", "noop", "memory"] = "console"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "notifications@openconstructionerp.com"
    smtp_tls: bool = True
    # Public URL used to build password-reset and notification links.
    # Falls back to the first CORS origin so dev installs work without
    # an explicit setting.
    frontend_url: str = ""

    # ── External Services ────────────────────────────────────────────────
    cad_converter_url: str | None = "http://localhost:8001"
    cv_pipeline_url: str | None = "http://localhost:8002"
    openweathermap_api_key: str = ""

    # ── Rate Limiting ────────────────────────────────────────────────────
    api_rate_limit: int = Field(
        default=100,
        description="Maximum API requests per minute per user/IP",
    )
    login_rate_limit: int = Field(
        default=10,
        description="Maximum login attempts per minute per IP",
    )
    ai_rate_limit: int = Field(
        default=10,
        description="Maximum AI requests per minute per user",
    )

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
    def jwt_secret_is_default(self) -> bool:
        return self.jwt_secret == "openestimate-local-dev-key"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_frontend_url(self) -> str:
        """URL used in outbound email links.

        Prefers the explicit ``FRONTEND_URL`` setting; falls back to the
        first CORS origin so a zero-config dev install still produces
        clickable reset links pointing at Vite's 5173.
        """
        if self.frontend_url:
            return self.frontend_url.rstrip("/")
        origins = self.cors_origins
        return origins[0].rstrip("/") if origins else "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()

"""‌⁠‍Application configuration​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.

Loads from environment variables with .env file fallback.
All settings are typed and validated via Pydantic.
"""

import logging
import re
from functools import lru_cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Literal

from pydantic import Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_logger = logging.getLogger("openestimate.config")

# Minimum acceptable JWT secret length, enforced in non-development
# environments. 32 bytes = 256 bits of entropy when generated via
# ``secrets.token_urlsafe(32)`` — strong enough that HS256 token
# forgery via brute-force is computationally infeasible.
_JWT_SECRET_MIN_LENGTH = 32

# Known-weak default values the validator MUST reject in non-development
# environments. The bundled dev default is here too because anyone reading
# the open-source repo can forge admin tokens against any deployment that
# forgot to override it; the other strings are common copy-paste leftovers
# from boilerplate / tutorials that have been seen in real audit reports.
_JWT_KNOWN_WEAK_SECRETS = frozenset(
    {
        "openestimate-local-dev-key",
        "change-me",
        "change-me-in-production",
        "secret",
        "jwt-secret",
    }
)

# Track whether we've already logged the dev-default warning so a unit
# test that instantiates Settings() repeatedly (or an app that hot-reloads
# the config) doesn't spam the log. Reset by the test suite via the
# ``reset_jwt_dev_warning`` helper below.
_DEV_JWT_WARNING_EMITTED = False


def reset_jwt_dev_warning() -> None:
    """Reset the once-per-process dev-default JWT warning latch.

    Test-only helper. The production path emits the warning exactly
    once on first ``Settings()`` instantiation; tests that exercise
    that path multiple times call this between cases to re-arm the
    latch.
    """
    global _DEV_JWT_WARNING_EMITTED
    _DEV_JWT_WARNING_EMITTED = False


def _read_pyproject_version() -> str | None:
    """‌⁠‍Best-effort parse of ``version = "..."`` from backend/pyproject.toml.

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
    """‌⁠‍Pick the version /api/health should report.

    When running from the source tree (the common dev workflow:
    ``cd backend && python -m uvicorn app.main:create_app --factory``),
    the *source* file is what's actually executing — but
    ``importlib.metadata.version`` returns whatever is in ``site-packages``
    if a stale ``pip install openconstructionerp==X`` happened earlier.
    That made ``/api/health`` claim a wrong version after every dev
    edit and made it impossible to tell, in a QA session, whether a
    just-edited file was actually serving requests.

    Resolution order (first hit wins):
      1. If ``app/__init__.py`` lives outside ``site-packages`` and a
         ``pyproject.toml`` is on disk above it, read that — the source
         tree is the source of truth.
      2. Otherwise, ``importlib.metadata.version("openconstructionerp")``.
      3. ``0.0.0+local`` sentinel when all else fails.
    """
    here = Path(__file__).resolve()
    if "site-packages" not in str(here):
        from_source = _read_pyproject_version()
        if from_source:
            return from_source
    try:
        return _pkg_version("openconstructionerp")
    except PackageNotFoundError:
        return _read_pyproject_version() or "0.0.0+local"


def build_provenance_tag(version: str) -> str:
    """‌⁠‍Derive the opaque build-provenance signature reported by /api/health.

    Combines a fixed seed with a content-hash component (sha256 of the
    running version) so the value rotates per release like a routine
    build checksum. The seed bytes XOR-fold (key 0x55) into the authorship
    string; removing or altering the seed changes the published
    ``signature`` field, but the value is otherwise inert (read-only
    metadata — nothing branches on it).
    """
    import hashlib as _h

    _seed = bytes(
        b ^ 0x55
        for b in (
            b"\x1a\x25\x30\x3b\x16\x3a\x3b\x26\x21\x27\x20\x36\x21\x3c\x3a\x3b"
            b"\x10\x07\x05\x78\x11\x11\x16\x78\x16\x02\x1c\x16\x07"
        )
    )
    _content = _h.sha256(version.encode("utf-8")).digest()
    return _h.sha256(_seed + _content).hexdigest()[:20]


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
    # Slow-query threshold (milliseconds). Statements exceeding this elapsed
    # wall time are logged at WARNING level via SQLAlchemy ``before_cursor_execute``
    # / ``after_cursor_execute`` listeners — see ``app.database``. Set to 0 to
    # disable the check. Env: ``OE_SLOW_QUERY_MS``.
    slow_query_ms: int = 500

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

    # Self-registration policy. ``open`` (default) preserves backwards-compat
    # with v2.5.x and earlier — anyone with network reach to ``POST
    # /auth/register`` lands an immediately-active viewer account. For
    # internet-exposed instances, set ``OE_REGISTRATION_MODE=admin-approve``:
    # new accounts arrive ``is_active=False`` and cannot log in until an
    # admin flips them active (PATCH /users/{id}). ``email-verify`` reserves
    # the same dormant flow for a future verification-email step (today
    # behaves identically to admin-approve). ``closed`` rejects every
    # self-registration outright; admins must create users via the admin
    # API. The bootstrap path (no admin in DB → first registrant becomes
    # admin) bypasses the gate so a freshly installed instance can be
    # initialised without chicken-and-egg.
    # BUG-RBAC03: flipped from ``"open"`` → ``"admin-approve"`` in v2.5.2.
    # Defaulting to open meant any internet-exposed instance handed out
    # 39 read-permissions to anyone who hit /auth/register. The bootstrap
    # path (no admin in DB → first registrant becomes admin) still
    # bypasses the gate so a freshly installed instance can be initialised
    # without chicken-and-egg. Self-hosters who explicitly want open
    # registration can set ``OE_REGISTRATION_MODE=open`` in their .env.
    registration_mode: Literal["open", "email-verify", "admin-approve", "closed"] = "admin-approve"

    # ── AI / Vector ──────────────────────────────────────────────────────
    # Default: Qdrant (CWICR v3 pipeline — BAAI/bge-m3 + 30 per-language
    # collections + parquet lookup). LanceDB remains as a legacy fallback
    # for pre-v3 deployments that haven't migrated their cost-vector store
    # yet; it will be removed entirely in a future release.
    vector_backend: str = "qdrant"  # "qdrant" (default) or "lancedb" (legacy fallback)
    qdrant_url: str | None = "http://localhost:6333"
    vector_data_dir: str = ""  # LanceDB storage path, default: ~/.openestimator/data/vectors
    # Embedding model used by the multi-collection semantic memory layer.
    # Default is multilingual so the CWICR cost database (24 languages) and
    # cross-module collections (BOQ, documents, tasks, risks, BIM elements,
    # etc.) all rank correctly across English, German, Russian, Lithuanian,
    # French, Spanish, Italian, Polish and Portuguese.  All-MiniLM-L6-v2 is
    # kept as a fallback because the existing CWICR LanceDB index was built
    # with it (same 384-dim, so the snapshot is dim-compatible until you
    # explicitly reindex via `make vector-reindex-costs`).
    embedding_model_name: str = "intfloat/multilingual-e5-small"
    embedding_model_dim: int = 384
    embedding_model_fallback: str = "sentence-transformers/all-MiniLM-L6-v2"
    # Override the HuggingFace cache directory for embedding model downloads.
    # When ``None`` (default), HuggingFace's own resolution applies
    # (HF_HOME, then XDG_CACHE_HOME, then ~/.cache/huggingface). Set this
    # to pin the cache to a writable volume on locked-down hosts.
    huggingface_cache_dir: str | None = None
    # Hard ceiling (seconds) on the first-time embedder load. Set lower
    # on workstations that should fail fast rather than block the boot
    # for minutes while a 2 GB model trickles over a slow link.
    embedding_download_timeout_seconds: int = 300
    # ── Match backend ────────────────────────────────────────────────────
    # The CWICR migration to Qdrant (BAAI/bge-m3, 30 per-language
    # collections, hard/soft filter split, BGE local reranker) is the
    # only supported ranker as of v3. The historical ``"lancedb"`` value
    # is rejected by the validator below; .env files left over from
    # pre-v3 deployments surface as a clear error at boot instead of
    # silently routing through dead code.
    match_backend: Literal["qdrant"] = "qdrant"
    # ── CWICR Qdrant (new pipeline, parallel to legacy LanceDB) ──────────
    # Qdrant path/URL for the 30-collection CWICR store (cwicr_<lang>).
    # When ``cwicr_qdrant_path`` is set, qdrant_adapter uses embedded mode
    # (`QdrantClient(path=...)`); when empty, it falls back to
    # ``cwicr_qdrant_url``. Embedded keeps the dependency footprint inside
    # the app's data dir; URL is for shared/Dockerised deployments.
    cwicr_qdrant_path: str = ""  # default resolved to ~/.openestimator/qdrant_cwicr
    cwicr_qdrant_url: str | None = None
    # Root directory that holds the per-region parquet files
    # ``<XX>___DDC_CWICR/<region>_workitems_costs_resources_DDC_CWICR.parquet``.
    # parquet_lookup uses this to fetch the 84-column row payload missing
    # from the minimal Qdrant store. When empty, lookups return only what
    # is in the Qdrant payload.
    cwicr_parquet_root: str = ""
    # BAAI/bge-m3 — 1024-dim dense + sparse + colbert in one forward pass,
    # MIT license, 100+ languages. Replaces e5-small for CWICR matching
    # only; the legacy multi-collection memory layer (BOQ/Document/Task)
    # still uses ``embedding_model_name`` until that path is migrated.
    cwicr_embedding_model: str = "BAAI/bge-m3"
    cwicr_embedding_dim: int = 1024
    # When True, qdrant_adapter loads ``gpahal/bge-m3-onnx-int8`` (~700 MB)
    # instead of FP32 (~2.3 GB). VPS-friendly default; flip off on
    # workstations if you want maximum recall fidelity.
    cwicr_embedding_int8: bool = True
    # CWICR Qdrant collection schema version suffix. Per MAPPING_PROCESS.md
    # v3 (2026-05-09) the production collections are named
    # ``cwicr_{LANG}_v3`` so the schema can evolve without overwriting the
    # currently-served index. Override (e.g. ``v4``) when DDC publishes a
    # new schema and the application needs to start reading the new
    # collections without a code change. Empty string strips the suffix
    # for legacy installs that vectorised before the v3 cutover.
    cwicr_collection_version: str = "v3"
    # When True (production default), ``country_to_collection`` probes the
    # live Qdrant for the set of present ``cwicr_*`` collections and, when
    # a project's native-language collection is absent, falls back to the
    # best populated one (BGE-M3 is multilingual, so an English catalogue
    # still returns real cross-language candidates — far better than the
    # hard ``catalog_not_vectorized`` empty result a dead collection name
    # produces). Set False to keep region→collection routing PURE (no
    # Qdrant I/O at call time) — required for deterministic bench runs and
    # unit tests that pin the routing contract. Env: CWICR_COLLECTION_PROBE.
    cwicr_collection_probe: bool = True
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
    kimi_api_key: str | None = None

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
    smtp_from: str = "info@datadrivenconstruction.io"
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
    # Per the OpenEstimate philosophy ("validation is a first-class citizen
    # — not optional, part of core workflow") every BOQ import (Excel / CSV
    # / GAEB X83 / X84) runs the configured rule packs before the response
    # is returned, so DIN276 / NRM / GAEB / MasterFormat / DPGF violations
    # surface AT import time — not later when a user is staring at row 452
    # of the BOQ wondering where the bad quantity came from. Set to
    # ``False`` on very large imports if the inline sweep is too slow; the
    # standalone ``POST /boqs/{id}/validate/`` endpoint remains available
    # regardless. Env: ``IMPORT_INLINE_VALIDATION``.
    import_inline_validation: bool = Field(
        default=True,
        description=(
            "Run validation rule packs inline during BOQ import so issues are "
            "reported in the import response instead of only via a later "
            "/validate call."
        ),
    )

    # ── BIM storage policy ──────────────────────────────────────────────
    # Conversion artifacts (canonical JSON, GLB, DAE, thumbnails, parquet)
    # are *always* persisted forever under ``data/bim/{project_id}/{model_id}/``
    # so /bim opens instantly on revisit without re-conversion.
    #
    # ``keep_original_cad`` controls only the raw upload (``original.{ext}``):
    #   * ``False`` (default, production) — drop the original after the
    #     conversion succeeds. Saves disk; failed conversions still keep
    #     it so retry works without re-upload.
    #   * ``True`` (dev / debug) — keep both. Useful when iterating on the
    #     converter pipeline and you want to re-run against the exact bytes.
    keep_original_cad: bool = Field(
        default=False,
        description=(
            "Keep the raw uploaded CAD file after conversion succeeds. "
            "Conversion artifacts are always retained regardless of this flag."
        ),
    )

    # ── Validators ───────────────────────────────────────────────────────
    @field_validator("match_backend", mode="before")
    @classmethod
    def _reject_lancedb_match_backend(cls, value: object) -> object:
        """Reject pre-v3 ``MATCH_BACKEND=lancedb`` env values explicitly.

        The legacy LanceDB ranker, boost stack, and lexical matcher were
        removed in v3. An old ``.env`` carrying ``MATCH_BACKEND=lancedb``
        would silently fail to find the modules, so we surface a clear
        deprecation error at boot instead.
        """
        if isinstance(value, str) and value.strip().lower() == "lancedb":
            raise ValueError(
                "MATCH_BACKEND=lancedb is no longer supported — the legacy "
                "ranker was removed in v3. Set MATCH_BACKEND=qdrant (the new "
                "default) or remove the line from your .env."
            )
        return value

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

    @model_validator(mode="after")
    def _refuse_default_jwt_in_non_dev(self) -> "Settings":
        """Refuse to start in staging/production with a weak JWT secret.

        Rejects three failure modes when ``APP_ENV != "development"``:

        1. ``jwt_secret`` is the bundled dev default — published in the
           public repo, admin-forgeable by anyone who can `git clone`.
        2. ``jwt_secret`` matches any other known weak / boilerplate
           value (``change-me``, ``secret``, ``jwt-secret``, etc.) — these
           leak into production all the time via copy-paste.
        3. ``jwt_secret`` is shorter than 32 characters — HS256 token
           forgery becomes computationally tractable below that length.

        In ``development`` the guard is a no-op so a fresh ``docker compose up``
        works without any .env. We still log a one-shot WARNING on the dev
        default with the secret length and a reminder so the operator sees
        an unmistakable nudge to set ``OE_JWT_SECRET`` before shipping.

        To override for self-hosters: set ``OE_JWT_SECRET`` (or ``JWT_SECRET``)
        to a fresh value, e.g.
        ``python -c "import secrets;print(secrets.token_urlsafe(32))"``
        or ``openssl rand -hex 32``.
        """
        secret = self.jwt_secret or ""
        is_weak_default = secret in _JWT_KNOWN_WEAK_SECRETS
        is_too_short = len(secret) < _JWT_SECRET_MIN_LENGTH

        if self.app_env != "development":
            if is_weak_default:
                raise RuntimeError(
                    f"Refusing to start: JWT_SECRET is a well-known weak default "
                    f"({secret!r}) but APP_ENV is {self.app_env!r}. Known-weak "
                    f"secrets are admin-forgeable by anyone who reads the public "
                    f"OpenConstructionERP source. Set OE_JWT_SECRET to a fresh "
                    f"random value of at least {_JWT_SECRET_MIN_LENGTH} "
                    f"characters, e.g.\n"
                    f'  python -c "import secrets;print(secrets.token_urlsafe(32))"\n'
                    f"  openssl rand -hex 32"
                )
            if is_too_short:
                raise RuntimeError(
                    f"Refusing to start: JWT_SECRET is only {len(secret)} "
                    f"characters but APP_ENV is {self.app_env!r}. HS256 token "
                    f"forgery is computationally tractable below "
                    f"{_JWT_SECRET_MIN_LENGTH} characters. Set OE_JWT_SECRET to "
                    f"a fresh random value of at least "
                    f"{_JWT_SECRET_MIN_LENGTH} characters, e.g.\n"
                    f'  python -c "import secrets;print(secrets.token_urlsafe(32))"\n'
                    f"  openssl rand -hex 32"
                )

        # Development with the bundled default — log a one-shot WARNING so
        # the operator is reminded to override before promoting the
        # environment. We deliberately log the length (not the value) so
        # the warning is informative without leaking the secret if log
        # files end up shipped off-host.
        if self.app_env == "development" and is_weak_default:
            global _DEV_JWT_WARNING_EMITTED
            if not _DEV_JWT_WARNING_EMITTED:
                _logger.warning(
                    "JWT_SECRET is the bundled development default "
                    "(length=%d). This is fine for local dev but MUST be "
                    "overridden in staging/production via OE_JWT_SECRET. "
                    "Generate a fresh secret with: "
                    'python -c "import secrets;print(secrets.token_urlsafe(32))"',
                    len(secret),
                )
                _DEV_JWT_WARNING_EMITTED = True

        return self

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

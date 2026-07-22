# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Application configuration​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.

Loads from environment variables with .env file fallback.
All settings are typed and validated via Pydantic.
"""

import logging
import os
import re
import secrets
from functools import lru_cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Literal

from pydantic import Field, computed_field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

_logger = logging.getLogger("openestimate.config")

_CONFIG_BUILD_TAG: str = "a5e797ddb2104903"

# Minimum acceptable JWT secret length, enforced in non-development
# environments. 32 bytes = 256 bits of entropy when generated via
# ``secrets.token_urlsafe(32)`` - strong enough that HS256 token
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
    """Pick the version /api/health should report.

    When running from the source tree (the common dev workflow:
    ``cd backend && python -m uvicorn app.main:create_app --factory``),
    the *source* file is what's actually executing - but
    ``importlib.metadata.version`` returns whatever is in ``site-packages``
    if a stale ``pip install openconstructionerp==X`` happened earlier.
    That made ``/api/health`` claim a wrong version after every dev
    edit and made it impossible to tell, in a QA session, whether a
    just-edited file was actually serving requests.

    Resolution order (first hit wins):
      1. If ``app/__init__.py`` lives outside ``site-packages`` and a
         ``pyproject.toml`` is on disk above it, read that - the source
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
    """Derive the opaque build-provenance signature reported by /api/health.

    Combines a fixed seed with a content-hash component (sha256 of the
    running version) so the value rotates per release like a routine
    build checksum. The seed bytes XOR-fold (key 0x55) into the authorship
    string; removing or altering the seed changes the published
    ``signature`` field, but the value is otherwise inert (read-only
    metadata - nothing branches on it).
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
    CWD - which silently drops the whole file when the CWD is "wrong".
    A missing JWT_SECRET rotates Fernet keys every boot and makes stored
    AI API keys undecryptable. Anchor to the package directory instead.
    """
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent / ".env",  # backend/.env (app/ is one up)
        here.parent.parent.parent / ".env",  # repo root .env (optional)
    ]
    return [str(p) for p in candidates if p.is_file()]


def _canonicalize_db_url(url: str, *, driver: str) -> str:
    """Canonicalize a PostgreSQL connection URL to ``postgresql+<driver>://``.

    Managed-Postgres providers (Heroku, Supabase, Railway, Render, Fly) hand
    out ``postgres://`` URLs, and some tutorials use ``postgres+asyncpg://``.
    SQLAlchemy removed the ``postgres`` dialect alias in 1.4, so either form
    makes the engine raise ``NoSuchModuleError: Can't load plugin:
    sqlalchemy.dialects:postgres`` (or ``...:postgres.asyncpg`` once a driver is
    attached). Rewrite any ``postgres`` / ``postgresql`` URL -- with or without a
    driver -- to the dialect and driver this engine actually needs, so the same
    ``DATABASE_URL`` works whether the operator pasted a cloud connection string
    or our own canonical form. SQLite and blank URLs pass through untouched.
    """
    if not url:
        return url
    scheme = url.split("://", 1)[0].lower()
    if not scheme.startswith("postgres"):
        return url
    try:
        from sqlalchemy.engine import make_url

        return make_url(url).set(drivername=f"postgresql+{driver}").render_as_string(hide_password=False)
    except Exception:  # noqa: BLE001 - never block boot on a URL we cannot parse
        return url


class Settings(BaseSettings):
    """OpenConstructionERP application settings."""

    model_config = SettingsConfigDict(
        env_file=_find_env_file() or ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Accept the documented ``OE_``-prefixed env vars as well as bare names.

        Historically the settings model declared no ``env_prefix``, so each
        field bound only to its bare upper-cased name (``REGISTRATION_MODE``,
        ``DATABASE_URL``, ...). But the docstrings, deployment guides and
        examples throughout the project use the brand-namespaced ``OE_``
        prefix (``OE_REGISTRATION_MODE``, ``OE_SLOW_QUERY_MS``, ...). An
        operator who followed the docs and set ``OE_REGISTRATION_MODE=closed``
        got the prefixed variable silently ignored and the default applied -
        a confusing, hard-to-diagnose footgun reported from production.

        We add a second environment source that strips an ``OE_`` prefix so
        both spellings populate the same field. The bare-name source keeps
        priority, so existing deployments that already set the unprefixed
        variables are completely unaffected; the prefixed source only fills a
        field the bare name did not already provide.
        """
        oe_prefixed_env = EnvSettingsSource(
            settings_cls,
            case_sensitive=False,
            env_prefix="OE_",
        )
        return (
            init_settings,
            env_settings,
            oe_prefixed_env,
            dotenv_settings,
            file_secret_settings,
        )

    # ── App ──────────────────────────────────────────────────────────────
    app_name: str = "OpenConstructionERP"
    app_version: str = Field(default_factory=_detect_version)
    app_env: Literal["development", "staging", "production"] = "development"
    app_debug: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    allowed_origins: str = "http://localhost:5173"
    # Optional allowlist for self-hosted AI provider endpoints (Ollama / vLLM).
    # Empty (default) permits any loopback / private address so a local runtime
    # works out of the box, while link-local and cloud-metadata addresses stay
    # blocked. Set a comma-separated list of hostnames and/or CIDR ranges (e.g.
    # "ollama.internal,10.20.0.0/16") to lock AI provider URLs to a known set;
    # anything outside it is then rejected. Binds OE_AI_PROVIDER_ALLOWLIST.
    ai_provider_allowlist: str = ""

    # ── Database ─────────────────────────────────────────────────────────
    # PostgreSQL is required; embedded PostgreSQL boots by default (no Docker),
    # or set DATABASE_URL to an external PostgreSQL.
    database_url: str = ""
    database_sync_url: str = ""
    database_pool_size: int = 24
    database_max_overflow: int = 10
    database_echo: bool = False
    # PostgreSQL only: seconds before a pooled connection is recycled. Kept
    # below common infra idle timeouts (pgbouncer / cloud LB ~5-10 min) so the
    # pool never serves a connection the server already dropped. Paired with
    # pool_pre_ping in ``app.database``. Ignored on SQLite. Env:
    # ``OE_DATABASE_POOL_RECYCLE`` / ``DATABASE_POOL_RECYCLE``.
    database_pool_recycle: int = 1800
    max_batch_size: int = 1000
    # Slow-query threshold (milliseconds). Statements exceeding this elapsed
    # wall time are logged at WARNING level via SQLAlchemy ``before_cursor_execute``
    # / ``after_cursor_execute`` listeners - see ``app.database``. Set to 0 to
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

    # ── Point Cloud ingest ───────────────────────────────────────────────
    # Reality-capture scans are 5-200 GB. They are uploaded
    # presigned-direct-to-MinIO so the 2 GB FastAPI core never proxies the
    # bytes; the backend only mints the key, hands back presigned part URLs
    # and finalises the multipart upload. These tunables bound the rare
    # fallback proxied path and apply back-pressure on the init endpoint.
    #
    # Multipart part size in bytes. S3 requires every part except the last to
    # be at least 5 MiB and allows at most 10000 parts, so the default 64 MiB
    # supports a single multipart upload up to ~640 GB - comfortably above the
    # 200 GB ceiling we target. Env: ``OE_POINTCLOUD_PART_SIZE_BYTES``.
    pointcloud_part_size_bytes: int = Field(default=64 * 1024 * 1024, ge=5 * 1024 * 1024)
    # Lifetime of every presigned upload URL (init parts) in seconds. Long
    # enough that a slow link can finish a 200 GB upload (default 12 hours)
    # but still short-lived so a leaked URL expires.
    # Env: ``OE_POINTCLOUD_PRESIGN_EXPIRE_SECONDS``.
    pointcloud_presign_expire_seconds: int = Field(default=12 * 3600, ge=60)
    # Hard ceiling (bytes) on ANY proxied upload that falls back through the
    # FastAPI core instead of going direct to object storage. The direct
    # presigned path has no such limit; this cap exists only so a misrouted
    # or worker-less deployment cannot push a multi-GB body through the 2 GB
    # core and OOM the box. Default 512 MiB. Env:
    # ``OE_POINTCLOUD_MAX_PROXIED_BYTES``.
    pointcloud_max_proxied_bytes: int = Field(default=2 * 1024 * 1024 * 1024, ge=0)
    # Maximum number of ingest init requests allowed in flight at once
    # (back-pressure). Each init touches object storage to open a multipart
    # upload; on a small VPS a flood of inits would exhaust connections, so
    # the init endpoint acquires a process-global gate and returns 429 with an
    # explanatory reason when the gate is full rather than degrade the whole
    # process. Default 8. Env: ``OE_POINTCLOUD_MAX_CONCURRENT_INGEST``.
    pointcloud_max_concurrent_ingest: int = Field(default=8, ge=1, le=256)

    # ── Request limits ───────────────────────────────────────────────────
    # Coarse global ceiling (bytes) on any single request body, enforced by
    # ``app.middleware.body_size_limit.MaxBodySizeMiddleware``. It is a backstop
    # ABOVE every per-endpoint upload cap, so it never trips a legitimate
    # upload; it only stops an absurdly large body from reaching an endpoint
    # that reads it unbounded and OOMs the single worker. Default 4 GiB - above
    # the largest built-in per-endpoint cap (the ~2 GiB point-cloud proxied
    # fallback). Set to 0 to disable. Env: ``OE_MAX_REQUEST_BODY_BYTES``.
    max_request_body_bytes: int = Field(default=4 * 1024 * 1024 * 1024, ge=0)

    # ── Auth ─────────────────────────────────────────────────────────────
    jwt_secret: str = "openestimate-local-dev-key"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    jwt_refresh_expire_days: int = 30
    # Default role handed to users who self-register after the very first
    # (bootstrap) user. ``viewer`` is the safe default - read-only across
    # the app. Can be raised to ``editor`` or ``manager`` for trusted
    # internal deployments via ``OE_DEFAULT_REGISTRATION_ROLE``. ``admin``
    # is intentionally unreachable through this setting.
    default_registration_role: Literal["viewer", "editor", "manager"] = "viewer"

    # Self-registration policy. ``open`` (default) preserves backwards-compat
    # with v2.5.x and earlier - anyone with network reach to ``POST
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

    # ── Multi-tenant row-level security ──────────────────────────────────
    # When True, each request sets a transaction-local ``app.current_tenant``
    # GUC from the caller's tenant, and - once the non-superuser runtime role
    # and per-table policies are in place - PostgreSQL row-level security fails
    # closed on every tenant-scoped table, so one tenant can never read or write
    # another's rows even if an app-layer filter is missed. Default False: the
    # GUC is not set and behaviour is byte-for-byte unchanged, so turning RLS on
    # is an explicit, reversible operator decision made only after the isolation
    # tests pass on the target database. Global reference data (cost items,
    # regional indices, catalogs) is never tenant-scoped. Env: ``OE_RLS_ENFORCE``.
    rls_enforce: bool = False

    # ── AI / Vector ──────────────────────────────────────────────────────
    # Default: Qdrant (CWICR v3 pipeline - BAAI/bge-m3 + 30 per-language
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
    embedding_download_timeout_seconds: int = 600
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
    # BAAI/bge-m3 - 1024-dim dense + sparse + colbert in one forward pass,
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
    # still returns real cross-language candidates - far better than the
    # hard ``catalog_not_vectorized`` empty result a dead collection name
    # produces). Set False to keep region→collection routing PURE (no
    # Qdrant I/O at call time) - required for deterministic bench runs and
    # unit tests that pin the routing contract. Env: CWICR_COLLECTION_PROBE.
    cwicr_collection_probe: bool = True
    # On startup, scan every multi-collection vector store and backfill
    # any rows that are not yet indexed.  Cheap on a fresh DB, useful when
    # upgrading from a pre-v1.4.0 install where existing BOQ / Document /
    # Task / Risk / BIM rows are not yet embedded.  Set ``false`` to
    # disable in low-resource deployments where you'd rather call
    # ``/vector/reindex/`` manually per module.
    vector_auto_backfill: bool = True
    # Per-collection cap for the auto backfill - protects against the
    # case where someone enables backfill on a 5M-row tenant on first
    # boot and the embedding loop saturates CPU for 30 minutes.  Set to
    # 0 to disable the cap entirely.
    vector_backfill_max_rows: int = 5000
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    kimi_api_key: str | None = None
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
    # ``noop`` and ``memory`` are for automated tests - the service
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
    # Note: CAD/CV conversion runs in-process via the bundled DDC converters
    # (invoked as a subprocess), not via a separate HTTP microservice, so no
    # converter/pipeline service URL is needed here.
    openweathermap_api_key: str = ""

    # ── Rate Limiting ────────────────────────────────────────────────────
    api_rate_limit: int = Field(
        default=200,
        description="Maximum API requests per minute per user/IP",
    )
    login_rate_limit: int = Field(
        default=10,
        description="Maximum login attempts per minute per IP",
    )
    ai_rate_limit: int = Field(
        default=20,
        description="Maximum AI requests per minute per user",
    )

    # ── Validation ───────────────────────────────────────────────────────
    default_validation_rule_sets: list[str] = Field(
        default=["boq_quality"],
        description="Default validation rule sets applied to all projects",
    )
    # Per the OpenEstimate philosophy ("validation is a first-class citizen
    # - not optional, part of core workflow") every BOQ import (Excel / CSV
    # / GAEB X83 / X84) runs the configured rule packs before the response
    # is returned, so DIN276 / NRM / GAEB / MasterFormat / DPGF violations
    # surface AT import time - not later when a user is staring at row 452
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
    #   * ``False`` (default, production) - drop the original after the
    #     conversion succeeds. Saves disk; failed conversions still keep
    #     it so retry works without re-upload.
    #   * ``True`` (dev / debug) - keep both. Useful when iterating on the
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
                "MATCH_BACKEND=lancedb is no longer supported - the legacy "
                "ranker was removed in v3. Set MATCH_BACKEND=qdrant (the new "
                "default) or remove the line from your .env."
            )
        return value

    @field_validator("database_url", mode="after")
    @classmethod
    def _canonical_async_db_url(cls, value: str) -> str:
        """Accept any postgres:// form for the async engine, normalize to asyncpg."""
        return _canonicalize_db_url(value, driver="asyncpg")

    @field_validator("database_sync_url", mode="after")
    @classmethod
    def _canonical_sync_db_url(cls, value: str) -> str:
        """Accept any postgres:// form for the sync engine, normalize to psycopg2."""
        return _canonicalize_db_url(value, driver="psycopg2")

    @model_validator(mode="after")
    def _cross_fill_db_urls(self) -> "Settings":
        """Derive the missing async/sync DB URL when only one is supplied.

        Operators commonly set only ``DATABASE_URL`` (the async one). Mirror
        whichever side points at Postgres into the other when that other side
        is blank, so alembic, the CWICR bulk import and the migration helper
        always agree on the same cluster instead of one of them falling back to
        an unconfigured engine.
        """
        if self.database_url.startswith("postgresql") and not self.database_sync_url.strip():
            self.database_sync_url = _canonicalize_db_url(self.database_url, driver="psycopg2")
        elif self.database_sync_url.startswith("postgresql") and not self.database_url.strip():
            self.database_url = _canonicalize_db_url(self.database_sync_url, driver="asyncpg")
        return self

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
    def ai_provider_allowlist_hosts(self) -> list[str]:
        """Parsed AI provider allowlist (hostnames / CIDRs), empties dropped."""
        return [h.strip() for h in self.ai_provider_allowlist.split(",") if h.strip()]

    @model_validator(mode="after")
    def _refuse_default_jwt_in_non_dev(self) -> "Settings":
        """Refuse to start in staging/production with a weak JWT secret.

        Rejects three failure modes when ``APP_ENV != "development"``:

        1. ``jwt_secret`` is the bundled dev default - published in the
           public repo, admin-forgeable by anyone who can `git clone`.
        2. ``jwt_secret`` matches any other known weak / boilerplate
           value (``change-me``, ``secret``, ``jwt-secret``, etc.) - these
           leak into production all the time via copy-paste.
        3. ``jwt_secret`` is shorter than 32 characters - HS256 token
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

        # Development with the bundled default - log a one-shot WARNING so
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


def _jwt_secret_persist_dir() -> Path:
    """Return the directory the auto-provisioned JWT secret is stored in.

    Honours the platform data-dir overrides (``OE_DATA_DIR`` > ``DATA_DIR`` >
    ``OE_CLI_DATA_DIR``) so a container that mounts a volume at ``/data`` keeps
    one stable secret across redeploys. With no override it falls back to the
    persistent per-user ``~/.openestimate`` - the location the CLI and desktop
    already use - so the secret never lands inside a source checkout's tracked
    ``data`` tree.

    Returns:
        The directory to read/write the ``.jwt-secret`` file in.
    """
    override = os.environ.get("OE_DATA_DIR") or os.environ.get("DATA_DIR") or os.environ.get("OE_CLI_DATA_DIR")
    if override and override.strip():
        return Path(override.strip())
    try:
        return Path.home() / ".openestimate"
    except RuntimeError:
        # Path.home() raises when no home directory can be resolved (a minimal
        # container with HOME unset and no passwd entry). Fall back to a
        # relative dir rather than aborting boot; the caller tolerates a failed
        # persist by falling back to a per-process secret.
        return Path(".openestimate")


def _operator_supplied_jwt_secret() -> str | None:
    """Return a real operator-provided JWT secret from the environment.

    Accepts either the bare ``JWT_SECRET`` or the brand-namespaced
    ``OE_JWT_SECRET`` (both spellings populate ``Settings.jwt_secret``). A value
    that is empty or a well-known weak placeholder counts as "not supplied", so
    a zero-config deployment auto-provisions a strong secret instead. Any other
    value is returned verbatim, with no length judgement, so an explicitly-set
    but too-short secret still reaches the strict ``Settings`` validator and is
    rejected in production rather than silently replaced.

    Returns:
        The operator's secret, or ``None`` when none was meaningfully set.
    """
    for name in ("JWT_SECRET", "OE_JWT_SECRET"):
        raw = os.environ.get(name)
        if raw is None:
            continue
        value = raw.strip()
        if value and value not in _JWT_KNOWN_WEAK_SECRETS:
            return value
    return None


def _non_development_env() -> bool:
    """Return True when ``APP_ENV`` selects a non-development deployment.

    Read straight from the environment (both bare and ``OE_``-prefixed
    spellings) because this runs before ``Settings`` is constructed. An unset
    value means development - the same default the model declares.

    Returns:
        ``True`` for staging/production, ``False`` for development or unset.
    """
    for name in ("APP_ENV", "OE_APP_ENV"):
        raw = os.environ.get(name)
        if raw is not None and raw.strip():
            return raw.strip().lower() != "development"
    return False


def _ensure_persistent_jwt_secret() -> None:
    """Auto-provision a strong, persistent JWT secret in non-dev deployments.

    Runs once, from :func:`get_settings`, before ``Settings`` reads the
    environment. It is a no-op in development (the bundled dev default is
    acceptable there and the app boots without ceremony) and whenever the
    operator already supplied a real secret. Otherwise, in staging/production
    it loads a previously persisted secret from the data dir - or generates one
    and persists it (``chmod 600``) - and exports it as ``JWT_SECRET`` so the
    app, and the strict production validator, see a strong value.

    This lets the published container boot with zero configuration while still
    signing tokens with a secret that is NOT the public repo default, and keeps
    that secret stable across restarts so browser sessions survive a redeploy
    when the data dir is a mounted volume. If persistence fails (a read-only
    data dir) it degrades to a per-process secret and logs a loud warning
    rather than refusing to start.
    """
    if not _non_development_env():
        return
    if _operator_supplied_jwt_secret() is not None:
        # The operator owns the secret - let Settings validate it as-is so a
        # deliberately weak value still fails loudly in production.
        return

    secret_path = _jwt_secret_persist_dir() / ".jwt-secret"

    try:
        if secret_path.is_file():
            existing = secret_path.read_text(encoding="utf-8").strip()
            if len(existing) >= _JWT_SECRET_MIN_LENGTH:
                os.environ["JWT_SECRET"] = existing
                _logger.info("Loaded the persisted JWT secret from %s.", secret_path)
                return
    except OSError:
        # Unreadable persisted secret - fall through and generate a fresh one.
        pass

    generated = secrets.token_urlsafe(48)
    try:
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        secret_path.write_text(generated, encoding="utf-8")
        # Best-effort chmod 600 (POSIX). On Windows the file inherits the
        # user-only ACL of the home directory.
        try:
            secret_path.chmod(0o600)
        except OSError:
            pass
        _logger.warning(
            "JWT_SECRET was not configured - generated a strong random secret "
            "and persisted it to %s. Set JWT_SECRET / OE_JWT_SECRET to a value "
            "you control for a stable multi-replica secret, and mount the data "
            "dir as a volume so this secret survives redeploys.",
            secret_path,
        )
    except OSError as exc:
        _logger.warning(
            "JWT_SECRET was not configured and could not be persisted to %s "
            "(%s) - using a per-process secret; sessions will be invalidated on "
            "restart. Set JWT_SECRET / OE_JWT_SECRET or make the data dir "
            "writable to keep sessions alive.",
            secret_path,
            exc,
        )
    os.environ["JWT_SECRET"] = generated


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    _ensure_persistent_jwt_secret()
    return Settings()


def desktop_mode() -> bool:
    """Return True when the backend is running as the desktop (Tauri) sidecar.

    The desktop shell spawns the Python backend as a bundled sidecar and sets
    ``OE_DESKTOP=1`` on its environment (see ``desktop/src-tauri/src/main.rs``).
    A PyInstaller/Nuitka frozen build also marks ``sys.frozen``. Either signal
    means the backend is the single-user local workspace behind the native
    shell rather than a shared, internet-exposed server.

    This is intentionally a plain function (not a cached ``Settings`` field) so
    tests can flip ``OE_DESKTOP`` via ``monkeypatch`` between calls without
    busting the settings ``lru_cache``.

    Returns:
        ``True`` when ``sys.frozen`` is set, or when the ``OE_DESKTOP``
        environment variable is ``"1"`` or ``"true"`` (case-insensitive).
    """
    import os
    import sys

    if getattr(sys, "frozen", False):
        return True
    return os.environ.get("OE_DESKTOP", "").strip().lower() in {"1", "true"}

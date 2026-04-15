# OpenConstructionERP — DataDrivenConstruction (DDC)
# CWICR Cost Database Engine · CAD2DATA Pipeline
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
# AGPL-3.0 License · DDC-CWICR-OE-2026
"""OpenEstimate​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ — FastAPI application factory.

Usage:
    uvicorn app.main:create_app --factory --reload --port 8000
    openestimate serve  (CLI mode — also serves frontend)
"""

# ── Runtime compatibility shims ─────────────────────────────────────────────
# MUST run BEFORE any import that can pull in numpy / torch / lancedb.
# On Windows + Anaconda Python, both Intel MKL (bundled with Anaconda numpy)
# and the torch wheels ship their own copy of ``libiomp5md.dll``. When the
# second copy is loaded, the OpenMP runtime aborts with:
#
#   OMP: Error #15: Initializing libiomp5md.dll, but found libiomp5md.dll
#                   already initialized.
#
# On Linux/macOS this is a warning; on Windows it is a fatal native abort
# that kills the process silently — no Python traceback, the shell just
# returns to the prompt. ``KMP_DUPLICATE_LIB_OK=TRUE`` tells the OpenMP
# runtime to accept the duplicate library instead of terminating, which
# is safe for inference workloads where we do not rely on deterministic
# thread pool ownership.
import os as _os

_os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
_os.environ.setdefault("OMP_NUM_THREADS", "1")
_os.environ.setdefault("MKL_NUM_THREADS", "1")

import hashlib as _hashlib
import logging
import os
import time
import uuid
import uuid as _instance_uuid
from typing import Any

# Unique instance fingerprint — proves this specific deployment origin
_INSTANCE_ID = str(_instance_uuid.uuid4())
_BUILD_HASH = _hashlib.sha256(f"DDC-CWICR-OE-{_INSTANCE_ID}".encode()).hexdigest()[:16]

from datetime import UTC

import structlog
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.core.module_loader import module_loader
from app.dependencies import get_current_user_id

logger = logging.getLogger(__name__)


def configure_logging(settings: Settings) -> None:
    """Configure structured logging."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer() if settings.app_debug else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=getattr(logging, settings.log_level), format="%(message)s")


def _init_vector_db() -> None:
    """Initialize vector database on startup (non-blocking, never fatal).

    Vector search is an important feature of OpenConstructionERP —
    it powers semantic cost-item matching, BOQ auto-classification,
    and assembly suggestions. We support two backends:

    * **Qdrant** (recommended for production) — dedicated server, scales
      to millions of vectors, supports snapshots. Run it locally with:
      ``docker run -p 6333:6333 qdrant/qdrant``
    * **LanceDB** (embedded, default) — zero-config, stores vectors on
      the local filesystem. Good enough for single-node deployments.

    Neither is a hard dependency: if both are unavailable, the platform
    still runs and serves all modules — only semantic search is disabled.
    This function is deliberately wrapped in a broad try/except so that
    no vector-related failure can ever block the rest of startup.
    """
    try:
        from app.core.vector import vector_status

        status = vector_status()
        engine = status.get("engine", "lancedb")
        if status.get("connected"):
            vectors = status.get("cost_collection", {})
            count = vectors.get("vectors_count", 0) if vectors else 0
            logger.info("Vector DB ready: %s (%d vectors indexed)", engine, count)
            return

        # Not connected — log a clear, actionable hint so users know how
        # to enable semantic search if they need it.
        error = status.get("error", "unknown")
        if engine == "qdrant":
            logger.warning(
                "Qdrant not reachable (%s). Semantic search is disabled. "
                "Start a local Qdrant with: docker run -p 6333:6333 qdrant/qdrant",
                error,
            )
        else:
            logger.warning(
                "LanceDB init failed (%s). Semantic search is disabled. "
                "Install the embedded vector backend with: pip install openconstructionerp[vector]",
                error,
            )
    except Exception as exc:  # noqa: BLE001 — intentional: never fatal
        # Includes ImportError (missing optional extras), native crashes
        # surfaced as OSError, etc. Semantic search is optional; the rest
        # of the application must continue to boot.
        logger.warning("Vector DB init skipped: %s", exc)


async def _auto_backfill_vector_collections() -> None:
    """Backfill the multi-collection vector store from existing rows.

    The event-driven indexing layer (added in v1.4.0) only fires for
    rows that are created or updated AFTER the upgrade.  On a fresh
    install with no data this is a no-op; on an existing v1.3.x install
    it would leave thousands of BOQ positions / documents / tasks /
    risks / BIM elements / validation reports / chat messages
    unsearchable until the user manually called every per-module
    `/vector/reindex/` endpoint.

    This helper closes that gap automatically.  For each registered
    collection it:

    1. Reads the live row count from Postgres / SQLite
    2. Reads the indexed row count from the vector store
    3. If the vector store is short, runs ``reindex_collection`` for the
       missing rows (capped by ``vector_backfill_max_rows`` per pass)

    Designed to be **non-blocking** — it runs in a detached background
    task so startup completes immediately even if the model loader has
    to download a fresh embedding checkpoint.

    All failures are logged and swallowed.  Disable entirely with
    ``vector_auto_backfill=False`` in settings.
    """
    try:
        from sqlalchemy import select

        from app.config import get_settings
        from app.core.vector import vector_count_collection
        from app.core.vector_index import (
            COLLECTION_BIM_ELEMENTS,
            COLLECTION_BOQ,
            COLLECTION_CHAT,
            COLLECTION_DOCUMENTS,
            COLLECTION_REQUIREMENTS,
            COLLECTION_RISKS,
            COLLECTION_TASKS,
            COLLECTION_VALIDATION,
            reindex_collection,
        )
        from app.database import async_session_factory

        settings = get_settings()
        if not settings.vector_auto_backfill:
            logger.info("Vector auto-backfill disabled by settings; skipping")
            return

        cap = max(0, int(settings.vector_backfill_max_rows or 0))

        from sqlalchemy import func
        from sqlalchemy.orm import selectinload

        async def _maybe_backfill(
            label: str,
            collection: str,
            model,
            adapter,
            *,
            options: list | None = None,
        ) -> None:
            """Backfill ``collection`` from ``model`` rows in a memory-safe way.

            Steps:
                1. Read the indexed-row count from the vector store (cheap).
                2. Issue a ``SELECT COUNT(*)`` against the model — also cheap.
                3. Skip if the index already has at least as many rows.
                4. Otherwise pull rows with ``LIMIT cap`` applied at the SQL
                   level so we never materialise the full table in memory.

            The previous implementation called ``loader(session)`` which
            executed an unbounded ``SELECT *`` and then sliced ``rows[:cap]``
            in Python — fine on a 100-row dev DB, catastrophic on a 2M-row
            production deployment because it allocates the entire result set
            before applying the cap.  Now the cap is enforced before the
            scan reaches the network.
            """
            try:
                indexed = vector_count_collection(collection) or 0
            except Exception:
                indexed = 0

            try:
                async with async_session_factory() as session:
                    # Step 1: cheap COUNT(*) — never materialises rows.
                    live_total = (
                        await session.execute(select(func.count()).select_from(model))
                    ).scalar_one() or 0

                    if not live_total:
                        return
                    if indexed >= live_total:
                        logger.debug(
                            "Backfill %s: %d/%d already indexed; skipping",
                            label,
                            indexed,
                            live_total,
                        )
                        return

                    # Step 2: decide how many rows to actually pull.
                    if cap > 0 and live_total > cap:
                        limit_to = cap
                        logger.info(
                            "Backfill %s: %d live rows exceeds cap (%d); "
                            "indexing first %d",
                            label,
                            live_total,
                            cap,
                            cap,
                        )
                    else:
                        limit_to = live_total

                    # Step 3: pull only what we need, with relationship
                    # eager-loads if the adapter needs them.
                    stmt = select(model)
                    if options:
                        stmt = stmt.options(*options)
                    stmt = stmt.limit(limit_to)
                    rows = list((await session.execute(stmt)).scalars().all())
            except Exception as exc:
                logger.debug("Backfill %s loader failed: %s", label, exc)
                return

            if not rows:
                return

            try:
                result = await reindex_collection(adapter, rows)
                logger.info(
                    "Backfill %s: indexed=%d, skipped=%d (live=%d, was=%d)",
                    label,
                    result.get("indexed", 0),
                    result.get("skipped", 0),
                    live_total,
                    indexed,
                )
            except Exception as exc:
                logger.debug("Backfill %s reindex failed: %s", label, exc)

        # ── Declarative collection registry ──────────────────────────────
        # Each tuple is (label, collection_constant, model_loader, adapter_loader,
        # options_factory).  The loaders are deferred to keep import cost low
        # and to avoid pulling every module's models into memory if the
        # auto-backfill is disabled.
        from app.modules.bim_hub.models import BIMElement
        from app.modules.bim_hub.vector_adapter import bim_element_vector_adapter
        from app.modules.boq.models import Position
        from app.modules.boq.vector_adapter import boq_position_adapter
        from app.modules.documents.models import Document
        from app.modules.documents.vector_adapter import document_vector_adapter
        from app.modules.erp_chat.models import ChatMessage
        from app.modules.erp_chat.vector_adapter import chat_message_adapter
        from app.modules.requirements.models import Requirement
        from app.modules.requirements.vector_adapter import (
            requirement_vector_adapter,
        )
        from app.modules.risk.models import RiskItem
        from app.modules.risk.vector_adapter import risk_vector_adapter
        from app.modules.tasks.models import Task
        from app.modules.tasks.vector_adapter import task_vector_adapter
        from app.modules.validation.models import ValidationReport
        from app.modules.validation.vector_adapter import validation_report_adapter

        backfill_targets = [
            (
                "BOQ positions",
                COLLECTION_BOQ,
                Position,
                boq_position_adapter,
                [selectinload(Position.boq)],
            ),
            ("Documents", COLLECTION_DOCUMENTS, Document, document_vector_adapter, None),
            ("Tasks", COLLECTION_TASKS, Task, task_vector_adapter, None),
            ("Risks", COLLECTION_RISKS, RiskItem, risk_vector_adapter, None),
            (
                "BIM elements",
                COLLECTION_BIM_ELEMENTS,
                BIMElement,
                bim_element_vector_adapter,
                [selectinload(BIMElement.model)],
            ),
            (
                "Validation reports",
                COLLECTION_VALIDATION,
                ValidationReport,
                validation_report_adapter,
                None,
            ),
            (
                "Requirements",
                COLLECTION_REQUIREMENTS,
                Requirement,
                requirement_vector_adapter,
                [selectinload(Requirement.requirement_set)],
            ),
            (
                "Chat messages",
                COLLECTION_CHAT,
                ChatMessage,
                chat_message_adapter,
                [selectinload(ChatMessage.session)],
            ),
        ]

        for label, collection_id, model, adapter, options in backfill_targets:
            await _maybe_backfill(
                label,
                collection_id,
                model,
                adapter,
                options=options,
            )

        logger.info("Vector auto-backfill pass complete")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Vector auto-backfill skipped: %s", exc)


async def _seed_demo_account() -> None:
    """Create demo user + 5 demo projects if they don't exist yet.

    Idempotent — safe to call on every startup.  Creates:
    - demo@openestimator.io / DemoPass1234!  (role=admin)
    - 5 projects: residential-berlin, office-london, medical-us,
      school-paris, warehouse-dubai (each with 2 BOQs: detailed + budget)

    Disable with SEED_DEMO=false in production.
    """
    if os.environ.get("SEED_DEMO", "true").lower() in ("false", "0", "no"):
        return

    from sqlalchemy import func, select

    from app.database import async_session_factory
    from app.modules.projects.models import Project
    from app.modules.users.models import User
    from app.modules.users.service import hash_password

    try:
        async with async_session_factory() as session:
            # 1. Create demo user if missing
            demo = (
                await session.execute(select(User).where(User.email == "demo@openestimator.io"))
            ).scalar_one_or_none()

            if demo is None:
                demo = User(
                    id=uuid.uuid4(),
                    email="demo@openestimator.io",
                    hashed_password=hash_password("DemoPass1234!"),
                    full_name="Demo User",
                    role="admin",
                    locale="en",
                    is_active=True,
                    metadata_={},
                )
                session.add(demo)
                await session.flush()
                logger.info("Demo user created: demo@openestimator.io")

            # Create additional demo accounts (estimator + manager)
            demo_accounts = [
                {
                    "email": "estimator@openestimator.io",
                    "password": "DemoPass1234!",
                    "full_name": "Sarah Chen",
                    "role": "estimator",
                },
                {
                    "email": "manager@openestimator.io",
                    "password": "DemoPass1234!",
                    "full_name": "Thomas Müller",
                    "role": "manager",
                },
            ]
            for acct in demo_accounts:
                exists = (await session.execute(select(User).where(User.email == acct["email"]))).scalar_one_or_none()
                if exists is None:
                    session.add(
                        User(
                            id=uuid.uuid4(),
                            email=acct["email"],
                            hashed_password=hash_password(acct["password"]),
                            full_name=acct["full_name"],
                            role=acct["role"],
                            locale="en",
                            is_active=True,
                            metadata_={},
                        )
                    )
                    logger.info("Demo user created: %s", acct["email"])

            # 2. Install 5 demo projects if user has none
            count = (
                await session.execute(select(func.count()).select_from(Project).where(Project.owner_id == demo.id))
            ).scalar() or 0

            if count == 0:
                from app.core.demo_projects import install_demo_project

                for demo_id in [
                    "residential-berlin",
                    "office-london",
                    "medical-us",
                    "school-paris",
                    "warehouse-dubai",
                ]:
                    try:
                        result = await install_demo_project(session, demo_id)
                        logger.info(
                            "Demo project installed: %s (%s positions, %s %s)",
                            demo_id,
                            result.get("positions"),
                            result.get("currency"),
                            result.get("grand_total"),
                        )
                    except Exception:
                        logger.warning("Failed to install demo %s (skipping)", demo_id)

            await session.commit()
    except Exception:
        logger.exception("Failed to seed demo account (non-fatal)")


def create_app() -> FastAPI:
    """Application factory.

    Creates and configures the FastAPI application:
    1. Load settings
    2. Configure logging
    3. Create FastAPI instance
    4. Add middleware
    5. Mount system routes
    6. Discover & load modules (on startup)
    """
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Open-source modular platform for construction cost estimation",
        docs_url="/api/docs" if not settings.is_production else None,
        redoc_url="/api/redoc" if not settings.is_production else None,
        openapi_url="/api/openapi.json",
        swagger_ui_oauth2_redirect_url=("/api/docs/oauth2-redirect" if not settings.is_production else None),
        redirect_slashes=False,
    )

    # ── Middleware ───────────────────────────────────────────────────────
    cors_origins = settings.cors_origins
    # Security: block wildcard origins in production
    if settings.is_production and "*" in cors_origins:
        logger.warning(
            "CORS: wildcard '*' origin is not allowed in production. Set ALLOWED_ORIGINS to your actual domain(s)."
        )
        cors_origins = [o for o in cors_origins if o != "*"]
        if not cors_origins:
            cors_origins = ["https://openconstructionerp.com"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "HEAD", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "Accept", "Accept-Language"],
    )

    # ── API Version header ──────────────────────────────────────────────
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request as StarletteRequest
    from starlette.responses import Response as StarletteResponse

    class APIVersionMiddleware(BaseHTTPMiddleware):
        """Add X-API-Version response header to every API response."""

        async def dispatch(self, request: StarletteRequest, call_next):  # noqa: ANN001, ANN201
            response: StarletteResponse = await call_next(request)
            response.headers["X-API-Version"] = settings.app_version
            return response

    app.add_middleware(APIVersionMiddleware)

    # ── DDC Fingerprint ──────────────────────────────────────────────────
    from app.middleware.fingerprint import DDCFingerprintMiddleware

    app.add_middleware(DDCFingerprintMiddleware)

    # ── Security headers (X-Frame-Options, CSP, HSTS, etc.) ──────────────
    from app.middleware.security_headers import SecurityHeadersMiddleware

    app.add_middleware(SecurityHeadersMiddleware)

    # ── Slow request logger (warns on > 500ms responses) ──────────────────
    from app.middleware.slow_request_logger import SlowRequestLoggerMiddleware

    app.add_middleware(SlowRequestLoggerMiddleware)

    # ── Accept-Language (sets i18n context locale per request) ────────────
    from app.middleware.accept_language import AcceptLanguageMiddleware

    app.add_middleware(AcceptLanguageMiddleware)

    # ── Global exception handler — return JSON for unhandled errors ────
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    # ── System Routes ───────────────────────────────────────────────────
    from app.core.i18n_router import router as i18n_router

    app.include_router(i18n_router, prefix="/api/v1")

    # Module management API (list / enable / disable)
    from app.core.module_router import router as module_mgmt_router

    app.include_router(module_mgmt_router)

    # Audit log API (admin-only)
    from app.core.audit_router import router as audit_router

    app.include_router(audit_router)

    # Global search API (cross-module)
    from app.core.global_search_router import router as search_router

    app.include_router(search_router)

    # Activity feed API (cross-module)
    from app.core.activity_feed_router import router as activity_router

    app.include_router(activity_router)

    # Sidebar badge counts (single endpoint for Tasks + RFI + Safety counts)
    from app.core.sidebar_badges_router import router as sidebar_badges_router

    app.include_router(sidebar_badges_router)

    # Store startup time for uptime calculation
    _startup_time: float = time.time()

    @app.get("/api/health", tags=["System"])
    async def health_check() -> dict[str, Any]:
        import os as _os

        result: dict[str, Any] = {
            "status": "healthy",
            "version": settings.app_version,
            "env": settings.app_env,
            "instance_id": _INSTANCE_ID,
            "build": f"DDC-{_BUILD_HASH}",
            "modules_loaded": len(module_loader.list_modules()),
            "uptime_seconds": int(time.time() - _startup_time),
        }

        # Database connectivity (fast ping)
        try:
            from sqlalchemy import text

            from app.database import engine

            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            result["database"] = "ok"
        except Exception:
            result["database"] = "error"
            result["status"] = "degraded"

        # Process memory (RSS) in MB — available on all platforms
        try:
            import resource

            rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # macOS returns bytes, Linux returns KB
            if _os.uname().sysname == "Darwin":
                result["memory_mb"] = round(rss_bytes / (1024 * 1024), 1)
            else:
                result["memory_mb"] = round(rss_bytes / 1024, 1)
        except Exception:
            try:
                # Windows / fallback via psutil if available
                import psutil

                proc = psutil.Process(_os.getpid())
                result["memory_mb"] = round(proc.memory_info().rss / (1024 * 1024), 1)
            except Exception:
                pass  # Memory reporting is best-effort

        return result

    @app.get("/api/source", tags=["System"])
    async def source_code() -> dict:
        """AGPL-3.0 Source Code Disclosure.

        As required by AGPL-3.0, this endpoint provides access to the
        complete corresponding source code of this application.
        DataDrivenConstruction · OpenConstructionERP · DDC-CWICR-OE-2026
        """
        return {
            "license": "AGPL-3.0",
            "source_code": "https://github.com/datadrivenconstruction/OpenConstructionERP",
            "copyright": "Copyright (c) 2026 Artem Boiko / DataDrivenConstruction",
            "notice": (
                "This software is licensed under AGPL-3.0. "
                "If you modify and deploy this software, you MUST make your "
                "complete source code available to all users under the same license. "
                "For commercial licensing without AGPL obligations, contact: "
                "datadrivenconstruction.io/contact-support/"
            ),
            "projects": {
                "CWICR": "https://github.com/datadrivenconstruction/OpenConstructionEstimate-DDC-CWICR",
                "cad2data": "https://github.com/datadrivenconstruction/cad2data-Revit-IFC-DWG-DGN-pipeline-with-conversion-validation-qto",
            },
        }

    @app.get("/api/system/status", tags=["System"])
    async def system_status() -> dict[str, Any]:
        """Full system status: database, vector DB, AI providers."""
        # Public hosted demo flag — set OE_DEMO_MODE=true on the VPS
        # systemd unit so the frontend can show the "demo only" warning
        # banner and the /users page can strip personal data from the
        # demo registration list. Defaults to false on every fresh
        # local install.
        demo_mode = os.environ.get("OE_DEMO_MODE", "").lower() in ("1", "true", "yes")
        result: dict[str, Any] = {
            "api": {"status": "healthy", "version": settings.app_version},
            "database": {"status": "unknown"},
            "vector_db": {"status": "offline", "engine": "qdrant"},
            "ai": {"providers": []},
            "cache": {"status": "unknown"},
            "demo_mode": demo_mode,
        }

        # Cache check
        try:
            from app.core.cache import cache as app_cache

            result["cache"] = app_cache.stats()
        except Exception:
            result["cache"] = {"status": "unavailable"}

        # Database check
        try:
            from sqlalchemy import text

            from app.database import engine

            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            result["database"] = {
                "status": "connected",
                "engine": "sqlite" if "sqlite" in settings.database_url else "postgresql",
            }
        except Exception as exc:
            result["database"] = {"status": "error", "error": str(exc)[:100]}

        # Vector DB check (LanceDB or Qdrant)
        try:
            from app.core.vector import vector_status as vs

            vstat = vs()
            if vstat.get("connected"):
                col = vstat.get("cost_collection") or {}
                result["vector_db"] = {
                    "status": "connected",
                    "engine": vstat.get("engine", "lancedb"),
                    "vectors": col.get("vectors_count", 0),
                }
            else:
                result["vector_db"] = {
                    "status": "offline",
                    "engine": vstat.get("engine", "lancedb"),
                }
        except Exception:
            result["vector_db"] = {"status": "offline", "engine": "lancedb"}

        # AI providers check — env vars first, then database
        providers = []
        if settings.openai_api_key:
            providers.append({"name": "OpenAI", "configured": True})
        if settings.anthropic_api_key:
            providers.append({"name": "Anthropic", "configured": True})

        # Fallback: check user-configured keys in oe_ai_settings table
        if not providers:
            try:
                from sqlalchemy import text as sa_text

                from app.database import async_session_factory

                async with async_session_factory() as ai_session:
                    row = (
                        await ai_session.execute(
                            sa_text(
                                "SELECT openai_api_key, anthropic_api_key, gemini_api_key FROM oe_ai_settings LIMIT 1"
                            )
                        )
                    ).first()
                    if row:
                        if row[0]:
                            providers.append({"name": "OpenAI", "configured": True})
                        if row[1]:
                            providers.append({"name": "Anthropic", "configured": True})
                        if row[2]:
                            providers.append({"name": "Gemini", "configured": True})
            except Exception:
                pass  # Table may not exist yet

        result["ai"] = {
            "providers": providers,
            "configured": len(providers) > 0,
        }

        return result

    @app.get("/api/system/version-check", tags=["System"])
    async def check_version() -> dict:
        """Check if a newer version is available on GitHub."""
        import httpx

        current = settings.app_version
        repo = "datadrivenconstruction/OpenConstructionEstimate-DDC-CWICR"
        cache_key = "_version_check_cache"

        # Simple in-memory cache (4 hours)
        cached = getattr(app.state, cache_key, None)
        if cached and (time.time() - cached["checked_at"]) < 14400:
            return cached["data"]

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://api.github.com/repos/{repo}/releases/latest",
                    headers={"Accept": "application/vnd.github.v3+json"},
                )
                if resp.status_code == 200:
                    release = resp.json()
                    latest = release.get("tag_name", "").lstrip("v")
                    result = {
                        "current_version": current,
                        "latest_version": latest,
                        "update_available": latest > current and latest != current,
                        "release_url": release.get("html_url", ""),
                        "release_notes": release.get("body", "")[:500],
                        "published_at": release.get("published_at", ""),
                        "download_url": next(
                            (
                                a["browser_download_url"]
                                for a in release.get("assets", [])
                                if a["name"].endswith(".zip")
                            ),
                            release.get("html_url", ""),
                        ),
                    }
                else:
                    result = {
                        "current_version": current,
                        "latest_version": current,
                        "update_available": False,
                    }
        except Exception:
            result = {
                "current_version": current,
                "latest_version": current,
                "update_available": False,
            }

        # Cache result
        setattr(app.state, cache_key, {"data": result, "checked_at": time.time()})
        return result

    @app.get("/api/system/modules", tags=["System"])
    async def list_modules() -> dict[str, Any]:
        return {"modules": module_loader.list_modules()}

    @app.get("/api/marketplace", tags=["System"])
    async def get_marketplace() -> list[dict[str, Any]]:
        """Return all marketplace modules with runtime installed status."""
        from app.core.marketplace import get_marketplace_catalog
        from app.database import async_session_factory

        # Query loaded catalog regions so resource_catalog entries show as installed
        loaded_catalog_regions: set[str] = set()
        try:
            async with async_session_factory() as session:
                from app.modules.catalog.repository import CatalogResourceRepository

                repo = CatalogResourceRepository(session)
                region_stats = await repo.stats_by_region()
                loaded_catalog_regions = {r["region"] for r in region_stats if r.get("region")}
        except Exception:
            pass  # Graceful degradation: show all as uninstalled

        return get_marketplace_catalog(loaded_catalog_regions=loaded_catalog_regions)

    @app.get("/api/demo/catalog", tags=["System"])
    async def demo_catalog() -> list[dict[str, Any]]:
        """Return the list of available demo project templates."""
        from app.core.demo_projects import DEMO_CATALOG

        return DEMO_CATALOG

    @app.post("/api/demo/install/{demo_id}", tags=["System"])
    async def install_demo(
        demo_id: str,
        force: bool = False,
        _user_id: str = Depends(get_current_user_id),
    ) -> dict[str, Any]:
        """Install a demo project with full BOQ, Schedule, Budget, and Tendering data.

        When the demo is already installed, returns the existing project info
        with ``already_installed=True`` unless ``force=True`` query param is set,
        in which case the old demo is deleted and recreated.
        """
        from app.core.demo_projects import DEMO_TEMPLATES, install_demo_project
        from app.database import async_session_factory

        if demo_id not in DEMO_TEMPLATES:
            from fastapi import HTTPException

            valid = ", ".join(sorted(DEMO_TEMPLATES.keys()))
            raise HTTPException(
                status_code=404,
                detail=f"Unknown demo_id '{demo_id}'. Valid options: {valid}",
            )

        async with async_session_factory() as session:
            result = await install_demo_project(session, demo_id, force_reinstall=force)
            await session.commit()

        return result

    @app.get("/api/demo/status", tags=["System"])
    async def demo_status() -> dict[str, bool]:
        """Check which demo projects are currently installed."""
        from sqlalchemy import select

        from app.database import async_session_factory
        from app.modules.projects.models import Project

        async with async_session_factory() as session:
            rows = (await session.execute(select(Project.metadata_))).scalars().all()

        installed: dict[str, bool] = {}
        for meta in rows:
            if isinstance(meta, dict) and meta.get("is_demo") and meta.get("demo_id"):
                installed[meta["demo_id"]] = True
        return installed

    @app.delete("/api/demo/uninstall/{demo_id}", tags=["System"])
    async def uninstall_demo(
        demo_id: str,
        _user_id: str = Depends(get_current_user_id),
    ) -> dict[str, Any]:
        """Remove a demo project and all its data."""
        from sqlalchemy import select

        from app.database import async_session_factory
        from app.modules.projects.models import Project

        async with async_session_factory() as session:
            all_projects = (await session.execute(select(Project))).scalars().all()
            targets = [
                p for p in all_projects if isinstance(p.metadata_, dict) and p.metadata_.get("demo_id") == demo_id
            ]

            if not targets:
                from fastapi import HTTPException

                raise HTTPException(status_code=404, detail=f"Demo '{demo_id}' not installed")

            for proj in targets:
                await session.delete(proj)
            await session.commit()

        return {"deleted_projects": len(targets), "demo_id": demo_id}

    @app.delete("/api/demo/clear-all", tags=["System"])
    async def clear_all_demos(
        _user_id: str = Depends(get_current_user_id),
    ) -> dict[str, Any]:
        """Remove ALL demo projects and their data."""
        from sqlalchemy import select

        from app.database import async_session_factory
        from app.modules.projects.models import Project

        async with async_session_factory() as session:
            all_projects = (await session.execute(select(Project))).scalars().all()
            targets = [p for p in all_projects if isinstance(p.metadata_, dict) and p.metadata_.get("is_demo")]

            for proj in targets:
                await session.delete(proj)
            await session.commit()

        return {"deleted_projects": len(targets)}

    @app.get("/api/system/validation-rules", tags=["System"])
    async def list_validation_rules() -> dict[str, Any]:
        from app.core.validation.engine import rule_registry

        return {
            "rule_sets": rule_registry.list_rule_sets(),
            "rules": rule_registry.list_rules(),
        }

    @app.get("/api/system/hooks", tags=["System"])
    async def list_hooks() -> dict[str, Any]:
        from app.core.hooks import hooks

        return {
            "filters": hooks.list_filters(),
            "actions": hooks.list_actions(),
        }

    @app.post("/api/v1/feedback", tags=["System"])
    async def submit_feedback(payload: dict[str, Any]) -> dict[str, Any]:
        """Store user feedback (bug reports, ideas, general comments)."""
        from datetime import datetime

        from sqlalchemy import text

        from app.database import engine

        category = str(payload.get("category", "general"))[:20]
        subject = str(payload.get("subject", ""))[:200]
        description = str(payload.get("description", ""))[:2000]
        email = str(payload.get("email") or "")[:100] or None
        page_path = str(payload.get("page_path", ""))[:200]

        # Auto-create table if needed (SQLite dev mode)
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                CREATE TABLE IF NOT EXISTS oe_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL DEFAULT 'general',
                    subject TEXT NOT NULL,
                    description TEXT NOT NULL,
                    email TEXT,
                    page_path TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            )
            await conn.execute(
                text("""
                    INSERT INTO oe_feedback (category, subject, description, email, page_path, created_at)
                    VALUES (:category, :subject, :description, :email, :page_path, :created_at)
                """),
                {
                    "category": category,
                    "subject": subject,
                    "description": description,
                    "email": email,
                    "page_path": page_path,
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )

        return {"status": "received"}

    # ── Lifecycle ───────────────────────────────────────────────────────
    def _section(title: str) -> None:
        """Log a visual section header during startup.

        Makes it possible to scan a 60-line startup log and see at a glance
        where the server got stuck. Keeps output machine-readable because
        logger.info is still used.
        """
        logger.info("=== %s ===", title)

    @app.on_event("startup")
    async def startup() -> None:
        _section("OpenConstructionERP")
        logger.info(
            "Starting %s v%s (env=%s)",
            settings.app_name,
            settings.app_version,
            settings.app_env,
        )

        # Validate secrets and configuration for production
        _insecure_secrets = {"change-me-in-production", "openestimate-local-dev-key", ""}
        if settings.jwt_secret in _insecure_secrets:
            if settings.is_production:
                raise RuntimeError(
                    "FATAL: JWT_SECRET is set to an insecure default value in production! "
                    "Set JWT_SECRET to a secure random string (min 32 chars). "
                    'Example: python -c "import secrets; print(secrets.token_urlsafe(48))"'
                )
            logger.warning("JWT_SECRET is using default dev key — set JWT_SECRET env var for production.")

        if settings.is_production:
            if "minioadmin" in (settings.s3_access_key + settings.s3_secret_key):
                logger.warning("S3 credentials are using development defaults")
            if "localhost" in settings.database_url:
                logger.warning("DATABASE_URL points to localhost in production")

        # Load translations (20 languages)
        _section("i18n")
        from app.core.i18n import load_translations

        load_translations()

        # Register core permissions
        from app.core.permissions import register_core_permissions

        register_core_permissions()

        # Auto-create tables for SQLite AND PostgreSQL on first start.
        # Why for both: the v0.9.0 baseline Alembic migration is a no-op
        # (it documents that tables are created via SQLAlchemy create_all),
        # and the docker-compose.quickstart.yml entrypoint does not run
        # `alembic upgrade head` before uvicorn. Result on a fresh PG
        # volume: schema never created, login fails with
        # `relation "oe_users_user" does not exist` (issue #42).
        # SQLAlchemy create_all is idempotent on PG and harmless on existing
        # databases — it only creates tables that do not yet exist.
        _section("Database")
        if "sqlite" in settings.database_url or "postgresql" in settings.database_url:
            # SQLite auto-migration: add missing columns before create_all
            from app.core import audit as _audit_core  # noqa: F401
            from app.core.sqlite_migrator import sqlite_auto_migrate
            from app.database import Base, engine
            from app.modules.ai import models as _ai_models  # noqa: F401
            from app.modules.assemblies import models as _asm_models  # noqa: F401
            from app.modules.bim_hub import models as _bim_hub_models  # noqa: F401
            from app.modules.bim_requirements import models as _bim_requirements_models  # noqa: F401
            from app.modules.boq import models as _boq_models  # noqa: F401
            from app.modules.catalog import models as _catalog_models  # noqa: F401
            from app.modules.cde import models as _cde_models  # noqa: F401
            from app.modules.changeorders import models as _changeorders_models  # noqa: F401
            from app.modules.collaboration import models as _collaboration_models  # noqa: F401
            from app.modules.collaboration_locks import models as _collaboration_locks_models  # noqa: F401
            from app.modules.contacts import models as _contacts_models  # noqa: F401
            from app.modules.correspondence import models as _correspondence_models  # noqa: F401
            from app.modules.costmodel import models as _cm_models  # noqa: F401
            from app.modules.costs import models as _costs_models  # noqa: F401
            from app.modules.documents import models as _documents_models  # noqa: F401
            from app.modules.dwg_takeoff import models as _dwg_takeoff_models  # noqa: F401

            # Enterprise / feature-pack modules
            from app.modules.enterprise_workflows import models as _enterprise_workflows_models  # noqa: F401
            from app.modules.erp_chat import models as _erp_chat_models  # noqa: F401
            from app.modules.fieldreports import models as _fieldreports_models  # noqa: F401
            from app.modules.finance import models as _finance_models  # noqa: F401
            from app.modules.full_evm import models as _full_evm_models  # noqa: F401
            from app.modules.i18n_foundation import models as _i18n_models  # noqa: F401
            from app.modules.inspections import models as _inspections_models  # noqa: F401
            from app.modules.integrations import models as _integrations_models  # noqa: F401
            from app.modules.markups import models as _markups_models  # noqa: F401
            from app.modules.meetings import models as _meetings_models  # noqa: F401
            from app.modules.ncr import models as _ncr_models  # noqa: F401
            from app.modules.notifications import models as _notifications_models  # noqa: F401
            from app.modules.procurement import models as _procurement_models  # noqa: F401
            from app.modules.projects import models as _projects_models  # noqa: F401
            from app.modules.punchlist import models as _punchlist_models  # noqa: F401
            from app.modules.reporting import models as _reporting_models  # noqa: F401
            from app.modules.requirements import models as _requirements_models  # noqa: F401
            from app.modules.rfi import models as _rfi_models  # noqa: F401
            from app.modules.rfq_bidding import models as _rfq_bidding_models  # noqa: F401
            from app.modules.risk import models as _risk_models  # noqa: F401
            from app.modules.safety import models as _safety_models  # noqa: F401
            from app.modules.schedule import models as _sched_models  # noqa: F401
            from app.modules.submittals import models as _submittals_models  # noqa: F401
            from app.modules.takeoff import models as _takeoff_models  # noqa: F401
            from app.modules.tasks import models as _tasks_models  # noqa: F401
            from app.modules.teams import models as _teams_models  # noqa: F401
            from app.modules.tendering import models as _tendering_models  # noqa: F401
            from app.modules.transmittals import models as _transmittals_models  # noqa: F401
            from app.modules.users import models as _users_models  # noqa: F401
            from app.modules.validation import models as _validation_models  # noqa: F401

            # SQLite-only: add missing columns to existing tables before
            # create_all runs. PostgreSQL deployments must use Alembic for
            # column-level migrations — sqlite_auto_migrate uses SQLite-
            # specific PRAGMA / ALTER syntax.
            if "sqlite" in settings.database_url:
                migrated = await sqlite_auto_migrate(engine, Base)
                if migrated:
                    logger.info("SQLite auto-migration: %d columns added", migrated)

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            db_kind = "SQLite" if "sqlite" in settings.database_url else "PostgreSQL"
            logger.info("%s tables created/verified", db_kind)
        else:
            logger.info("Using external database (Alembic manages schema)")

        # Load all modules (triggers module on_startup hooks)
        _section("Modules")
        await module_loader.load_all(app)

        # Mount OpenCDE API at the spec-compliant prefix /api/v1/opencde
        # (module loader auto-mounts at /api/v1/opencde_api)
        try:
            from app.modules.opencde_api.router import router as opencde_router

            app.include_router(opencde_router, prefix="/api/v1/opencde", tags=["OpenCDE API"])
        except Exception:
            logger.debug("OpenCDE API router not available (non-fatal)")

        # Variations alias (plan §3.3) — mount changeorders also at /api/v1/variations
        try:
            from app.modules.changeorders.router import router as co_router

            app.include_router(co_router, prefix="/api/v1/variations", tags=["Variations"])
        except Exception:
            logger.debug("Variations alias not available (non-fatal)")

        # costmodel → finance/evm alias (plan §3.3)
        try:
            from app.modules.costmodel.router import router as cm_router

            app.include_router(cm_router, prefix="/api/v1/finance/evm", tags=["Finance EVM (alias)"])
        except Exception:
            logger.debug("Finance EVM alias not available (non-fatal)")

        # tendering → procurement/tenders alias (plan §3.3)
        try:
            from app.modules.tendering.router import router as tend_router

            app.include_router(
                tend_router,
                prefix="/api/v1/procurement/tenders",
                tags=["Procurement Tenders (alias)"],
            )
        except Exception:
            logger.debug("Procurement Tenders alias not available (non-fatal)")

        # Register cross-module event handlers (dataflow wiring)
        from app.core.event_handlers import register_event_handlers

        register_event_handlers()

        # Register built-in validation rules
        _section("Validation")
        from app.core.validation.rules import register_builtin_rules

        register_builtin_rules()

        # Seed demo account + 3 demo projects (idempotent)
        _section("Demo data")
        await _seed_demo_account()

        # Initialize vector database (LanceDB embedded, no Docker)
        _section("Vector DB")
        _init_vector_db()

        # Auto-backfill the multi-collection vector store from existing
        # rows.  Detached as a background task so a slow embedding model
        # download or a large dataset doesn't delay startup — semantic
        # search remains available the moment the model finishes loading.
        try:
            import asyncio as _asyncio_bf

            _asyncio_bf.create_task(_auto_backfill_vector_collections())
        except Exception:
            logger.debug("Could not schedule vector backfill", exc_info=True)

        # ── KPI auto-recalculation scheduler (24-hour interval) ──────────
        import asyncio

        async def _kpi_scheduler() -> None:
            """Run KPI recalculation for all active projects every 24 hours."""
            while True:
                await asyncio.sleep(86400)  # 24 hours
                try:
                    from app.database import async_session_factory as _kpi_sf
                    from app.modules.reporting.service import ReportingService

                    async with _kpi_sf() as kpi_session:
                        svc = ReportingService(kpi_session)
                        result = await svc.auto_recalculate_kpis()
                        await kpi_session.commit()
                        logger.info(
                            "KPI scheduler: %d projects processed, %d failed",
                            result["processed"],
                            result["failed"],
                        )
                except Exception:
                    logger.exception("KPI recalculation scheduler failed")

        asyncio.create_task(_kpi_scheduler())

        _section("Ready")
        # Friendly multi-line ready banner. The CLI (`openestimate serve`)
        # exposes OE_CLI_HOST / OE_CLI_PORT / OE_CLI_DATA_DIR so we can show
        # an accurate URL after the socket is actually bound. If those env
        # vars are absent (e.g. `uvicorn app.main:create_app --factory`), we
        # fall back to a generic message.
        _cli_host = os.environ.get("OE_CLI_HOST")
        _cli_port = os.environ.get("OE_CLI_PORT")
        _cli_data_dir = os.environ.get("OE_CLI_DATA_DIR")
        if _cli_host and _cli_port:
            _url = f"http://{_cli_host}:{_cli_port}"
            logger.info("OpenConstructionERP is ready at %s", _url)
            logger.info("Demo login: demo@openestimator.io / DemoPass1234!")
            if _cli_data_dir:
                logger.info("Data directory: %s", _cli_data_dir)
            logger.info("Press Ctrl+C to stop. Docs: https://openconstructionerp.com/docs")
        else:
            logger.info("Application started successfully")

        # NOTE: frontend static mounting moved to create_app() (below, before
        # the startup event runs). Registering the SPA 404 exception handler
        # here (inside the startup lifespan) is TOO LATE — Starlette has
        # already built the ExceptionMiddleware by the time lifespan.startup
        # fires, and the middleware captures a COPY of app.exception_handlers
        # at build time.  Subsequent modifications to app.exception_handlers
        # (like the one mount_frontend used to do) never reach the middleware.
        # Symptom: https://.../demo/ returned a JSON 404 instead of index.html.

    @app.on_event("shutdown")
    async def shutdown() -> None:
        logger.info("Shutting down %s", settings.app_name)
        from app.database import engine

        # Stop the collaboration-lock sweeper before closing the DB
        # engine so its last iteration cannot hit a disposed pool.
        try:
            from app.modules.collaboration_locks.sweeper import stop_sweeper

            stop_sweeper()
        except Exception:
            logger.debug("collab lock sweeper stop failed", exc_info=True)

        await engine.dispose()

    # ── Frontend Static Files (CLI / single-image mode) ─────────────────────
    # Registered HERE, before the app is returned from create_app(), so the
    # SPA 404 exception handler is already in app.exception_handlers when
    # Starlette builds the ExceptionMiddleware on the first lifespan message.
    # (If this runs inside on_event("startup"), the handler is never wired up
    # and the SPA 404 fallback silently does nothing — see comment above.)
    #
    # Exception handlers are independent of routes, so it is safe to register
    # this before module routers are mounted: the handler only fires for
    # requests that do NOT match any route.
    if os.environ.get("SERVE_FRONTEND", "").lower() in ("1", "true", "yes"):
        try:
            from app.cli_static import mount_frontend

            mount_frontend(app)
        except Exception as exc:  # noqa: BLE001 — frontend is optional
            logger.warning("Frontend mount skipped: %s", exc)

    return app

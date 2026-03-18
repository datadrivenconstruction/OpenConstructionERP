"""OpenEstimate — FastAPI application factory.

Usage:
    uvicorn app.main:create_app --factory --reload --port 8000
"""

import logging
from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.core.module_loader import module_loader

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
            structlog.dev.ConsoleRenderer()
            if settings.app_debug
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=getattr(logging, settings.log_level), format="%(message)s")


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
    )

    # ── Middleware ───────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── System Routes ───────────────────────────────────────────────────
    from app.core.i18n_router import router as i18n_router

    app.include_router(i18n_router, prefix="/api/v1")

    @app.get("/api/health", tags=["System"])
    async def health_check() -> dict[str, Any]:
        return {
            "status": "healthy",
            "version": settings.app_version,
            "env": settings.app_env,
        }

    @app.get("/api/system/modules", tags=["System"])
    async def list_modules() -> dict[str, Any]:
        return {"modules": module_loader.list_modules()}

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

    # ── Lifecycle ───────────────────────────────────────────────────────
    @app.on_event("startup")
    async def startup() -> None:
        logger.info(
            "Starting %s v%s (%s)", settings.app_name, settings.app_version, settings.app_env
        )

        # Load translations (20 languages)
        from app.core.i18n import load_translations

        load_translations()

        # Register core permissions
        from app.core.permissions import register_core_permissions

        register_core_permissions()

        # Auto-create tables for SQLite dev mode (PostgreSQL uses Alembic)
        if "sqlite" in settings.database_url:
            from app.database import Base, engine
            from app.modules.users import models as _users_models  # noqa: F401
            from app.modules.projects import models as _projects_models  # noqa: F401
            from app.modules.boq import models as _boq_models  # noqa: F401
            from app.modules.costs import models as _costs_models  # noqa: F401

            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("SQLite tables created/verified")

        # Load all modules (triggers module on_startup hooks)
        await module_loader.load_all(app)

        # Register built-in validation rules
        from app.core.validation.rules import register_builtin_rules

        register_builtin_rules()

        logger.info("Application started successfully")

    @app.on_event("shutdown")
    async def shutdown() -> None:
        logger.info("Shutting down %s", settings.app_name)
        from app.database import engine

        await engine.dispose()

    return app

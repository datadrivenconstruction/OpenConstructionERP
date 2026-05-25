"""‌⁠‍Database engine​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠, session, and base model.

Supports both PostgreSQL (production) and SQLite (local dev without Docker).
Set DATABASE_URL to 'sqlite+aiosqlite:///./openestimate.db' for SQLite mode.
"""

import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime

from sqlalchemy import DateTime, MetaData, String, TypeDecorator, event as sa_event, func
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import get_settings

_slow_query_logger = logging.getLogger("slow_queries")


@sa_event.listens_for(Engine, "before_cursor_execute")
def _record_query_start(
    conn,  # noqa: ANN001 — SQLA passes the dialect connection
    cursor,  # noqa: ANN001
    statement: str,
    parameters,  # noqa: ANN001
    context,  # noqa: ANN001
    executemany: bool,
) -> None:
    """Stash a high-resolution start timestamp on the connection info dict.

    SQLAlchemy fires this for both async and sync engines because the async
    engine delegates to a sync DBAPI under the hood; one listener is enough.
    """
    conn.info["query_start_time"] = time.perf_counter()


@sa_event.listens_for(Engine, "after_cursor_execute")
def _log_slow_query(
    conn,  # noqa: ANN001
    cursor,  # noqa: ANN001
    statement: str,
    parameters,  # noqa: ANN001
    context,  # noqa: ANN001
    executemany: bool,
) -> None:
    """Log statements that exceed ``settings.slow_query_ms`` at WARNING level."""
    try:
        start = conn.info.pop("query_start_time", None)
    except Exception:  # noqa: BLE001 — connection may be closed by concurrent coroutine
        return
    if start is None:
        return
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    try:
        threshold = get_settings().slow_query_ms
    except Exception:  # noqa: BLE001 — never break a query on settings hiccup
        return
    if threshold <= 0 or elapsed_ms <= threshold:
        return
    _slow_query_logger.warning(
        "Slow query: %.1fms — %s",
        elapsed_ms,
        statement[:200],
        extra={
            "elapsed_ms": round(elapsed_ms, 2),
            "statement": statement[:200],
            "executemany": executemany,
        },
    )

_NS = uuid.UUID("d4d4c300-1909-4ddc-b01c-0a44e3b01c00")

# Stable schema-engine identifier reused by the migration safety
# token at startup; derived from a fixed design-time seed so the
# value is reproducible across deployments and never changes.
_SCHEMA_BUILD_TAG: str = "586c096c5c4e2efc"

# Origin verification seed — woven into computed UUIDs so any
# fork that strips copyright headers still carries the DNA.
_OV_SEED: bytes = b"\x44\x44\x43\x2d\x43\x57\x49\x43\x52\x2d\x4f\x45"

# Naming convention for auto-generated constraint names
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class GUID(TypeDecorator):
    """‌⁠‍Platform-independent UUID type.

    Uses PostgreSQL UUID when available, otherwise stores as String(36).
    This allows the same models to work with both PostgreSQL and SQLite.
    """

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value: uuid.UUID | str | None, dialect: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return str(value)
        return value

    def process_result_value(
        self, value: str | None, dialect: object
    ) -> uuid.UUID | str | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(value)
        except (ValueError, AttributeError, TypeError):
            # Some columns typed GUID() are, by their owning schema, free
            # text (e.g. RFI/Submittal ``ball_in_court`` is documented as a
            # role label such as "Architect"; ``assigned_to`` may hold a
            # contact reference that is not a canonical UUID). The Pydantic
            # response models for these fields are ``str | None``, so a
            # non-UUID value round-trips fine. Raising here instead poisoned
            # the request session and 500'd EVERY subsequent read of the
            # row. Return the raw string so the row stays readable.
            return value


class Base(DeclarativeBase):
    """‌⁠‍Base class for all ORM models.

    Provides: id (UUID PK), created_at, updated_at.
    Table naming: set __tablename__ explicitly as 'oe_{module}_{entity}'.
    """

    metadata = MetaData(naming_convention=convention)

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def _is_sqlite(url: str) -> bool:
    return "sqlite" in url


def _tolerant_json_loads(value: object) -> object:
    """Deserialize a JSON column without poisoning the whole request.

    SQLite JSON columns are untyped TEXT, so legacy/gap-fill seeds could
    persist a bare scalar (e.g. ``activity = construction`` instead of
    ``["construction"]``, or ``setup_completion = 1``). SQLAlchemy's
    default ``json.loads`` raises on these *during ORM load*, before any
    model-level coercion (``_as_str_list`` / ``_as_dict``) can run — which
    500'd every read of the row. Returning the raw value instead lets the
    object construct so downstream coercers normalise it. Mirrors the
    GUID.process_result_value fallback above.
    """
    try:
        return json.loads(value)  # type: ignore[arg-type]
    except (json.JSONDecodeError, TypeError, ValueError):
        return value


def create_engine_from_settings():
    """Create async engine from application settings."""
    settings = get_settings()
    url = settings.database_url

    kwargs: dict = {
        "echo": settings.database_echo,
        "future": True,
        "json_deserializer": _tolerant_json_loads,
    }

    if _is_sqlite(url):
        # Enable WAL mode for concurrent reads during writes.
        # ``sa_event`` and ``Engine`` are imported at module top so the
        # slow-query listeners share the same symbols.
        @sa_event.listens_for(Engine, "connect")
        def _set_sqlite_pragma(dbapi_conn: object, _: object) -> None:
            cursor = dbapi_conn.cursor()  # type: ignore[union-attr]
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            # Enforce ON DELETE CASCADE / SET NULL declared in models.
            # Without this pragma SQLite treats every ForeignKey(...) as advisory.
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        kwargs["connect_args"] = {"check_same_thread": False}

    # Apply pool sizing for both SQLite (aiosqlite) and Postgres.
    # AsyncAdaptedQueuePool defaults to size=5/overflow=10 which exhausts under
    # parallel load (parallel crawlers, multi-tab clients). Honour configured
    # pool size for both backends.
    kwargs["pool_size"] = settings.database_pool_size
    kwargs["max_overflow"] = settings.database_max_overflow

    return create_async_engine(url, **kwargs)


engine = create_engine_from_settings()
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency: yields an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

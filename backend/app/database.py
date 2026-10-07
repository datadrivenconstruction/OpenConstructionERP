# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Database engine​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠, session, and base model.

PostgreSQL only. The app runs embedded PostgreSQL 16 by default (no Docker);
set DATABASE_URL to point at an external PostgreSQL to override.
"""

import contextlib
import json
import logging
import os
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from sqlalchemy import DateTime, MetaData, String, TypeDecorator, func
from sqlalchemy import event as sa_event
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import get_settings

_slow_query_logger = logging.getLogger("slow_queries")


@sa_event.listens_for(Engine, "before_cursor_execute")
def _record_query_start(
    conn,  # noqa: ANN001 - SQLA passes the dialect connection
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
    # A concurrent coroutine may have already torn the connection down and
    # dropped ``conn.info``; treat any failure here as "no timing available"
    # by leaving ``started_at`` at None and falling through to the early-out.
    started_at = None
    with contextlib.suppress(Exception):  # connection may be closed concurrently
        started_at = conn.info.pop("query_start_time", None)
    # No start timestamp recorded (failed lookup, or the listener missed it).
    if started_at is None:
        return
    elapsed_ms = (time.perf_counter() - started_at) * 1000.0
    try:
        threshold = get_settings().slow_query_ms
    except Exception:  # noqa: BLE001 - never break a query on settings hiccup
        return
    if threshold <= 0 or elapsed_ms <= threshold:
        return
    _slow_query_logger.warning(
        "Slow query: %.1fms - %s",
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

# Origin verification seed - woven into computed UUIDs so any
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
    """UUID-valued column stored as text.

    Always ``VARCHAR(36)``, on every dialect. Values are converted to and
    from :class:`uuid.UUID` in Python, so the ORM layer sees UUIDs, but the
    column the database gets is text.

    This docstring used to claim "uses PostgreSQL UUID when available".
    It never did: honouring that would need ``load_dialect_impl`` returning
    ``postgresql.UUID``, and there is no such method here. Measured across
    all 598 tables, ``create_all`` emits 597 ``varchar(36)`` id columns, one
    ``varchar(64)`` and zero ``uuid``.

    The claim mattered because 50 Alembic revisions declare native
    ``UUID`` columns and 42 of those hang foreign keys off them. Read
    against the old docstring those revisions look consistent with the
    models; against the actual behaviour they disagree, and a database
    built by walking the chain collides with one built by ``create_all``
    (``DatatypeMismatch``). Do not "fix" this by adding
    ``load_dialect_impl`` on its own: that changes the column type under
    every existing install and is a data migration across all 598 tables,
    not a type-decorator tweak.
    """

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value: uuid.UUID | str | None, dialect: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return str(value)
        return value

    def process_result_value(self, value: str | None, dialect: object) -> uuid.UUID | str | None:
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


def _utcnow() -> datetime:
    """Timezone-aware UTC now - Python-side default/onupdate for timestamps."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base class for all ORM models.

    Provides: id (UUID PK), created_at, updated_at.
    Table naming: set __tablename__ explicitly as 'oe_{module}_{entity}'.
    """

    metadata = MetaData(naming_convention=convention)

    id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4,
    )
    # created_at / updated_at use **Python-side** ``default``/``onupdate`` so the
    # value is populated on the in-memory instance during flush. The previous
    # SQL-only ``server_default``/``onupdate=func.now()`` left the attribute
    # *expired* after every INSERT/UPDATE (the DB computed it), so the next
    # access - typically synchronous Pydantic ``model_validate`` in a router -
    # emitted a lazy reload SELECT outside the async greenlet and raised
    # ``MissingGreenlet`` on asyncpg (SQLite silently tolerated it). With a
    # Python callable the ORM sets the value itself and never re-fetches, fixing
    # that entire class of bug across every model at once. ``server_default`` is
    # kept so raw-SQL inserts and migrations still get a DB-side timestamp.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
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
    model-level coercion (``_as_str_list`` / ``_as_dict``) can run - which
    500'd every read of the row. Returning the raw value instead lets the
    object construct so downstream coercers normalise it. Mirrors the
    GUID.process_result_value fallback above.
    """
    try:
        return json.loads(value)  # type: ignore[arg-type]
    except (json.JSONDecodeError, TypeError, ValueError):
        return value


def create_engine_from_settings():
    """Create async engine from application settings.

    PostgreSQL only. The URL must be a PostgreSQL DSN; the app runs embedded
    PostgreSQL by default (set by the CLI bootstrap) or an external PostgreSQL
    via ``DATABASE_URL``. A non-PostgreSQL URL (empty or otherwise) raises so a
    misconfigured import fails loudly instead of silently falling back.
    """
    settings = get_settings()
    url = settings.database_url

    if not url.startswith("postgresql"):
        raise RuntimeError(
            "DATABASE_URL must be a PostgreSQL URL. The app runs embedded PostgreSQL "
            "by default - start it through the CLI (run 'openconstructionerp', which "
            "boots the embedded cluster and points DATABASE_URL at it) or set "
            "DATABASE_URL to an external PostgreSQL."
        )

    kwargs: dict = {
        "echo": settings.database_echo,
        "future": True,
        "json_deserializer": _tolerant_json_loads,
    }

    # AsyncAdaptedQueuePool defaults to size=5/overflow=10 which exhausts under
    # parallel load (parallel crawlers, multi-tab clients). Honour configured
    # pool size.
    kwargs["pool_size"] = settings.database_pool_size
    kwargs["max_overflow"] = settings.database_max_overflow

    # Validate each pooled connection with a lightweight round-trip before
    # handing it to a request, and recycle connections periodically. Without
    # this, a server-side idle timeout, a Postgres restart, or a failover
    # leaves dead sockets in the pool that surface as
    # ``OperationalError: server closed the connection unexpectedly`` on the
    # next query. pool_pre_ping costs one cheap round-trip on checkout;
    # pool_recycle caps connection age below typical infra idle timeouts.
    kwargs["pool_pre_ping"] = True
    kwargs["pool_recycle"] = settings.database_pool_recycle

    # Bound abandoned transactions at the server, on the connection that made
    # one - not on whoever ends up waiting behind it.
    #
    # A session that opens a transaction and then stops talking (a request that
    # died between two statements, a task killed mid-work) holds every lock it
    # took until its connection closes, and nothing on the victim's side ends
    # that: ``statement_timeout`` does not cover a lock wait, and
    # ``lock_timeout`` only makes each victim give up faster while the culprit
    # stays open and waits for the next one.
    # ``idle_in_transaction_session_timeout`` is the setting that removes the
    # culprit, so it goes on every connection this factory builds.
    #
    # One engine deliberately does not come through here: ``app.core.jobs_tasks``
    # builds a per-dispatch NullPool engine, because a pooled connection opened
    # on one dispatch's event loop and reused from the next one's breaks asyncpg.
    # It sets the same parameter itself, from
    # ``Settings.database_jobs_idle_in_transaction_timeout``, on a much larger
    # budget - a job handler is legitimately idle inside its transaction while
    # it parses a file or calls an external service, and this value would cut
    # that work. Two configuration paths, on purpose; do not "fix" the
    # duplication by routing jobs through this factory, which would replace
    # their NullPool with a sized pool.
    #
    # As an asyncpg *startup parameter* rather than a per-checkout ``SET``: it
    # travels in the connection packet, so it costs no round-trip, it cannot be
    # missed by a code path that forgot to issue the SET, and it covers pooled
    # connections handed to background workers as well as request sessions.
    # PostgreSQL only counts a session that is *idle* inside a transaction - a
    # running statement is ``active`` and is never touched - so a slow
    # migration or a long import is not at risk. See
    # ``Settings.database_idle_in_transaction_timeout``; 0 disables it.
    idle_in_transaction_ms = max(0, settings.database_idle_in_transaction_timeout) * 1000
    if idle_in_transaction_ms:
        connect_args = dict(kwargs.get("connect_args", {}))
        connect_args["server_settings"] = {
            **connect_args.get("server_settings", {}),
            # asyncpg requires string values here; PostgreSQL reads a bare
            # number as milliseconds.
            "idle_in_transaction_session_timeout": str(idle_in_transaction_ms),
        }
        kwargs["connect_args"] = connect_args

    # Disable TLS for loopback PostgreSQL.
    #
    # asyncpg defaults to sslmode "prefer", which eagerly builds an
    # ``ssl.SSLContext`` (via ``ssl.create_default_context``) while parsing the
    # connect arguments, *before* it ever talks to the server. In a frozen
    # PyInstaller build the bundled OpenSSL cannot initialise its default verify
    # paths, so that call raises ``ssl.SSLError: [SSL] system lib`` and kills
    # startup in the very first migration connection. This is the exact reason
    # the desktop app "did nothing": the embedded cluster started fine but the
    # first async connection blew up on SSL.
    #
    # The embedded cluster (and any local PostgreSQL) is plaintext on loopback
    # and never negotiates TLS, so explicitly turning SSL off is both correct
    # and what avoids the broken-OpenSSL path entirely. Remote hosts keep
    # asyncpg's default behaviour so an external TLS PostgreSQL still works.
    from urllib.parse import urlsplit

    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        host = ""
    if host in ("", "localhost", "127.0.0.1", "::1"):
        kwargs["connect_args"] = {**kwargs.get("connect_args", {}), "ssl": False}

    # Test mode: use NullPool so every checkout opens a fresh asyncpg
    # connection on the current event loop. pytest-asyncio runs each test in its
    # own loop, and a pooled asyncpg connection created on one loop and reused on
    # another raises "attached to a different loop". NullPool sidesteps that
    # entirely (the local cluster makes per-connect cheap). Production keeps the
    # sized pool above. Gated by an env var the test conftest sets before this
    # module is imported, so production never takes this branch.
    if os.environ.get("OE_TEST_NULLPOOL") == "1":
        from sqlalchemy.pool import NullPool

        kwargs.pop("pool_size", None)
        kwargs.pop("max_overflow", None)
        kwargs.pop("pool_recycle", None)
        kwargs["poolclass"] = NullPool

    return create_async_engine(url, **kwargs)


# Register PostgreSQL optimizations (JSON->JSONB DDL + performance-index event)
# before any engine use. This is a side-effect import placed after Base is defined
# so the module's ``from app.database import Base`` resolves against the
# partially-initialised module. Guarded so it can never break engine creation.
try:
    from app.core import pg_optimizations as _pg_opt

    _pg_opt.register(Base)
except Exception as _pg_opt_exc:  # noqa: BLE001
    import logging as _logging

    _logging.getLogger(__name__).warning("pg_optimizations not registered: %r", _pg_opt_exc)


engine = create_engine_from_settings()
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Register the row-level-security tenant GUC listener on the sync Session class
# that AsyncSession drives. It is a no-op until OE_RLS_ENFORCE is enabled AND a
# request binds a tenant, so this changes nothing on a default install. An
# enabled deployment must not start with its tenant listener missing.
try:
    from sqlalchemy.orm import Session as _SyncSession

    from app.core import rls as _rls

    _rls.install(_SyncSession)
except Exception as _rls_exc:  # noqa: BLE001
    # Consult settings directly: the RLS module itself may have failed to import.
    # An unreadable flag must also propagate, never imply enforcement is off.
    if get_settings().rls_enforce:
        raise
    logging.getLogger(__name__).warning("RLS tenant listener not registered: %r", _rls_exc)

# Register the read-only-demo write tripwire on the Engine class, next to the
# slow-query listeners above and for the same reason: it has to cover every
# engine in the process, not just the one built here. It is a no-op until
# OE_DEMO_READ_ONLY is enabled AND a request is in scope, so this changes
# nothing on a default install - and nothing at all outside a request, which is
# what keeps migrations, seeding and the background workers working on the
# demo box too. Guarded so an import problem can never break engine creation.
try:
    from app.core import demo_read_only as _demo_read_only

    _demo_read_only.install()
except Exception as _demo_ro_exc:  # noqa: BLE001
    logging.getLogger(__name__).warning("Demo read-only listener not registered: %r", _demo_ro_exc)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency: yields an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

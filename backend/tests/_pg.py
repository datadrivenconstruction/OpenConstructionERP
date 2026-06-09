"""PostgreSQL test-isolation helpers.

The backend runs only on PostgreSQL, so the test suite does too. ``conftest``
provisions a cluster for the session (an embedded PostgreSQL 16 when no
``DATABASE_URL`` is set, otherwise the operator/CI-supplied instance). This
module hands out isolated, throwaway databases on that cluster for the unit
fixtures that historically built their own ``create_async_engine(":memory:")``
SQLite engine.

Isolation is fast because the full schema is materialised into a template
database exactly once per session; each fixture then clones it with
``CREATE DATABASE ... TEMPLATE`` (a file copy, no ``create_all`` round-trip)
and drops the clone on teardown.

Usage (drop-in for the old in-memory SQLite fixture)::

    from tests._pg import isolated_engine

    @pytest_asyncio.fixture
    async def session():
        async with isolated_engine() as engine:
            factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with factory() as s:
                yield s
"""

from __future__ import annotations

import contextlib
import importlib
import os
import pkgutil
import uuid
from collections.abc import AsyncIterator

import psycopg2
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

_TEMPLATE_DB = "oe_test_template"
_template_ready = False

# Dedicated database for the fast, transaction-isolated unit/module fixtures.
# Built once with the full schema and then kept pristine: every
# ``transactional_session`` runs inside an outer transaction that is rolled
# back on teardown, so the database always starts each test empty.
_UNIT_DB = "oe_test_unit"
_unit_ready = False
_shared_engine: AsyncEngine | None = None


def _sync_url_for(database: str) -> str:
    """libpq URL for ``database`` on the session cluster (sync, psycopg2)."""
    base = make_url(os.environ["DATABASE_SYNC_URL"])
    return base.set(drivername="postgresql", database=database).render_as_string(hide_password=False)


def _async_url_for(database: str) -> str:
    """asyncpg URL for ``database`` on the session cluster."""
    base = make_url(os.environ["DATABASE_URL"])
    return base.set(drivername="postgresql+asyncpg", database=database).render_as_string(hide_password=False)


def _maintenance_db() -> str:
    """The cluster's default database, used to issue CREATE/DROP DATABASE."""
    return make_url(os.environ["DATABASE_SYNC_URL"]).database or "postgres"


def _connect_admin():
    """Autocommit connection to the maintenance database (for CREATE/DROP)."""
    conn = psycopg2.connect(_sync_url_for(_maintenance_db()))
    conn.autocommit = True
    return conn


def _terminate_backends(cur, db_name: str) -> None:
    cur.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
        (db_name,),
    )


def _import_all_models() -> None:
    """Import every module's ORM models so ``Base.metadata`` is complete.

    Mirrors the dynamic model discovery the app runs at startup so the
    template database carries the full schema (every module table plus the
    cross-cutting audit / translation-cache tables).
    """
    import app.core.audit  # noqa: F401
    import app.core.audit_log  # noqa: F401
    import app.core.translation.cache  # noqa: F401  (registers oe_translation_cache)
    import app.modules as _modules_pkg

    for mod in pkgutil.iter_modules(_modules_pkg.__path__):
        if not mod.ispkg:
            continue
        name = f"app.modules.{mod.name}.models"
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            # A module without a models.py is fine; re-raise a genuinely
            # different missing import.
            if exc.name != name:
                raise


def ensure_template() -> None:
    """Build the schema-loaded template database once per session."""
    global _template_ready
    if _template_ready:
        return

    conn = _connect_admin()
    try:
        cur = conn.cursor()
        # Drop any stale template (a reused external cluster) so the schema is
        # always current, then create a fresh one.
        _terminate_backends(cur, _TEMPLATE_DB)
        cur.execute(f'DROP DATABASE IF EXISTS "{_TEMPLATE_DB}"')
        cur.execute(f'CREATE DATABASE "{_TEMPLATE_DB}"')
        cur.close()
    finally:
        conn.close()

    _import_all_models()
    from app.database import Base

    sync_engine = create_engine(_sync_url_for(_TEMPLATE_DB))
    try:
        Base.metadata.create_all(sync_engine)
    finally:
        sync_engine.dispose()

    _template_ready = True


def _create_throwaway_db() -> str:
    """Clone the session template into a fresh throwaway database and return its name."""
    ensure_template()
    db_name = f"oe_test_{uuid.uuid4().hex[:16]}"
    conn = _connect_admin()
    try:
        conn.cursor().execute(f'CREATE DATABASE "{db_name}" TEMPLATE "{_TEMPLATE_DB}"')
    finally:
        conn.close()
    return db_name


def _drop_throwaway_db(db_name: str) -> None:
    """Terminate backends and drop a throwaway database created by ``_create_throwaway_db``."""
    conn = _connect_admin()
    try:
        cur = conn.cursor()
        _terminate_backends(cur, db_name)
        cur.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        cur.close()
    finally:
        conn.close()


@contextlib.asynccontextmanager
async def isolated_engine() -> AsyncIterator[AsyncEngine]:
    """Yield an async engine bound to a throwaway, schema-loaded database.

    The database is cloned from the session template (fast, no ``create_all``)
    and dropped when the context exits.
    """
    db_name = _create_throwaway_db()
    engine = create_async_engine(_async_url_for(db_name), future=True)
    try:
        yield engine
    finally:
        await engine.dispose()
        _drop_throwaway_db(db_name)


@contextlib.contextmanager
def isolated_database_url():
    """Yield the asyncpg URL of a throwaway, schema-loaded database (sync context).

    Unlike :func:`isolated_engine`, this hands out only the connection URL and
    does NOT open an async engine. It is the right primitive when several
    independent event loops (e.g. one per worker thread) each need to build
    their OWN engine bound to their OWN loop against the SAME database. Sharing
    a single async engine across foreign loops deadlocks: SQLAlchemy's pool and
    its first-connect ``asyncio.Lock`` bind to whichever loop touches them
    first, so the other loops hang forever on a cross-loop future.

    The database is cloned from the session template (fast, no ``create_all``)
    and dropped when the context exits.
    """
    db_name = _create_throwaway_db()
    try:
        yield _async_url_for(db_name)
    finally:
        _drop_throwaway_db(db_name)


def _ensure_unit_db() -> None:
    """Create the dedicated unit-test database with the full schema, once."""
    global _unit_ready
    if _unit_ready:
        return
    conn = _connect_admin()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (_UNIT_DB,))
        if cur.fetchone() is None:
            cur.execute(f'CREATE DATABASE "{_UNIT_DB}"')
        cur.close()
    finally:
        conn.close()

    _import_all_models()
    from app.database import Base

    sync_engine = create_engine(_sync_url_for(_UNIT_DB))
    try:
        Base.metadata.create_all(sync_engine)
    finally:
        sync_engine.dispose()

    _unit_ready = True


def _get_shared_engine() -> AsyncEngine:
    global _shared_engine
    if _shared_engine is None:
        _ensure_unit_db()
        # NullPool: pytest-asyncio runs each test in a fresh event loop, and
        # asyncpg connections are loop-bound. Pooling would hand a connection
        # opened on one test's loop to another, raising "attached to a
        # different loop". NullPool opens a fresh connection per ``connect()``
        # (cheap against the local embedded cluster) so each binds to the
        # current loop.
        _shared_engine = create_async_engine(_async_url_for(_UNIT_DB), future=True, poolclass=NullPool)
    return _shared_engine


@contextlib.asynccontextmanager
async def transactional_session(*, disable_fks: bool = False) -> AsyncIterator[AsyncSession]:
    """Yield a session wrapped in a transaction that is rolled back on teardown.

    This is the fast isolation primitive for the unit/module suites: the
    schema-loaded ``oe_test_unit`` database is built once for the session, and
    each call opens a connection, begins an outer transaction and binds a
    session with ``join_transaction_mode="create_savepoint"``. The session's
    own ``commit()`` calls become savepoint releases; the outer rollback at
    teardown undoes everything, so no per-test ``CREATE DATABASE`` is needed
    and the database stays empty between tests.

    Use this for fixtures that yield a single :class:`AsyncSession` (including
    client tests that override the DB dependency to hand the app this same
    session). For the rarer fixtures that need a real engine with
    cross-connection commits (the app opening its own sessions from an engine),
    use :func:`isolated_engine` instead.

    Args:
        disable_fks: When true, set ``session_replication_role = replica`` on
            the connection so foreign-key triggers do not fire. This is the
            PostgreSQL equivalent of the old ``PRAGMA foreign_keys=OFF`` some
            suites used to insert rows without satisfying cross-module FKs.
            Requires a superuser/replication role (the embedded cluster and the
            CI service both qualify).
    """
    engine = _get_shared_engine()
    conn = await engine.connect()
    trans = await conn.begin()
    if disable_fks:
        await conn.exec_driver_sql("SET session_replication_role = replica")
    factory = async_sessionmaker(
        bind=conn,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    session = factory()
    try:
        yield session
    finally:
        await session.close()
        if trans.is_active:
            await trans.rollback()
        await conn.close()


def schema_inspection_engine():
    """Return a SYNC engine bound to the schema-loaded unit database.

    For the handful of tests that introspect the schema itself (indexes,
    columns, constraints) via :func:`sqlalchemy.inspect` rather than running
    queries against rows. The unit database is built once per session with the
    full schema (every model's ``Index(...)`` / column declarations applied via
    ``create_all``), so inspecting it is equivalent to the old "build a throwaway
    engine, ``create_all``, inspect" pattern but without a per-test round-trip.

    The caller owns the returned engine and must ``dispose()`` it.
    """
    _ensure_unit_db()
    return create_engine(_sync_url_for(_UNIT_DB))

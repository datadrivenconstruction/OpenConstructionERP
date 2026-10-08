"""Embedded-PostgreSQL test lane (no Docker).

These tests run against a REAL PostgreSQL 16 cluster booted in-process from the
``pixeltable-pgserver`` wheel (bundled PG binaries). They guard the dialect
divergences that the default in-memory SQLite suite cannot catch: JSONB DDL and
operators, ILIKE case-insensitivity, GIN indexes, and UUID/JSONB asyncpg
round-trips.

Gating: the whole ``tests/pg`` directory is skipped unless ``OE_TEST_DB=pg`` is
set, so the normal SQLite run (and contributors without the wheel) are
unaffected. CI runs it via the dedicated *CI (PostgreSQL)* workflow.

Design notes
~~~~~~~~~~~~
* The cluster is booted ONCE per session and the full ORM schema is built ONCE
  with a synchronous psycopg2 engine (which fires the JSON->JSONB ``@compiles``
  hook and the ``after_create`` performance-index events). Doing the one-time
  setup synchronously sidesteps the pytest-asyncio "session-scoped async
  fixture is attached to a different event loop" pitfall.
* Per-test isolation: ``pg_session`` opens a connection, starts an outer
  transaction, binds the session with ``join_transaction_mode="create_savepoint"``
  (so the app's own ``commit()`` calls become savepoint releases) and rolls the
  whole thing back afterwards. Fast, and the shared schema is never mutated.
"""

from __future__ import annotations

import importlib
import os
import pkgutil
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


def _is_pg() -> bool:
    return os.environ.get("OE_TEST_DB", "").lower() in {"pg", "postgres", "postgresql"}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip the whole ``tests/pg`` tree unless the PG lane is requested."""
    if _is_pg():
        return
    skip = pytest.mark.skip(reason="PG lane only — set OE_TEST_DB=pg")
    for item in items:
        path = str(item.fspath).replace(os.sep, "/")
        if "/tests/pg/" in path:
            item.add_marker(skip)


def _register_all_models() -> None:
    """Import every module's ORM models + the JSONB/index hooks (mirror app startup)."""
    import app.core.audit  # noqa: F401
    import app.core.audit_log  # noqa: F401

    # ``oe_data_repair_ledger``. Declared in app.core, so the app.modules loop
    # below never reaches it - the same explicit-import case as audit_log, and
    # ``app/main.py`` carries the same import beside its own for the same reason.
    import app.core.data_repairs  # noqa: F401
    import app.core.pg_optimizations  # noqa: F401

    # ``oe_process_settings``: declared in app.core.processes, imported by the
    # app at startup, so the same explicit-import case as data_repairs.
    import app.core.processes.store  # noqa: F401

    # The translation cache declares its table on Base.metadata at import time,
    # and nothing imports it until something asks for a translation. When that
    # import lands after create_all has run, the table exists in the metadata and
    # not in the database, so a test that walks the metadata to query real tables
    # asks PostgreSQL for a relation that does not exist. Registering it here
    # keeps the schema this lane builds equal to the metadata it reads back.
    import app.core.translation.cache  # noqa: F401
    import app.modules as _modules_pkg

    for mod in pkgutil.iter_modules(_modules_pkg.__path__):
        if not mod.ispkg:
            continue
        name = f"app.modules.{mod.name}.models"
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise  # a real broken import inside the module, not mere absence


@pytest.fixture(scope="session")
def pg_async_url(tmp_path_factory) -> str:
    """Boot embedded PG once, build the full schema once, yield the asyncpg URL.

    Uses an EPHEMERAL pgdata (fresh ``initdb`` per session) on purpose: a
    persistent cluster would keep a stale schema, and because ``create_all`` is
    idempotent (``checkfirst``) it would never pick up DDL changes such as a new
    index opclass. A clean cluster guarantees the schema always reflects the
    current models and ``pg_optimizations`` output. First boot costs one initdb
    (~5-15s); CI runners are fresh anyway.
    """
    if not _is_pg():
        pytest.skip("PG lane only — set OE_TEST_DB=pg")

    import pixeltable_pgserver as pgserver
    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url

    # Register all models + import Base BEFORE booting pgserver. ``get_server``
    # chdir's into the pgdata directory; doing the cwd-relative ``app`` imports
    # first keeps them resolving against the source tree regardless.
    _register_all_models()
    from app.database import Base

    pgdata = str(tmp_path_factory.mktemp("oe_pgdata"))
    srv = pgserver.get_server(pgdata)
    try:
        base = make_url(srv.get_uri())  # TCP on Windows, unix socket on Linux
        async_url = base.set(drivername="postgresql+asyncpg")
        sync_url = base.set(drivername="postgresql+psycopg2")

        sync_engine = create_engine(sync_url)
        Base.metadata.create_all(sync_engine)
        sync_engine.dispose()

        yield async_url.render_as_string(hide_password=False)
    finally:
        srv.cleanup()


@pytest_asyncio.fixture
async def pg_engine(pg_async_url):
    """Function-scoped async engine bound to the session cluster (NullPool)."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    eng = create_async_engine(pg_async_url, poolclass=NullPool)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
def no_detached_subscribers():
    """Silence event subscribers that open a session of their own.

    A few subscribers are deliberately *detached*: they build a session from
    ``app.database.async_session_factory`` rather than reuse the publisher's,
    because the publisher is still inside its own request transaction. That is
    right in production and wrong here. This lane never binds that factory to
    the embedded cluster - ``pg_session`` hands out a savepoint-joined session
    built on its own connection - so a detached handler reaches for a database
    that is not there.

    The damage is not confined to the test that triggered it. The handler's
    half-opened connection outlives the failure, and on Windows the selector
    goes down with it, so every test that runs afterwards errors during setup.
    One write path with a detached consumer therefore reads as a broken suite:
    ``tests/pg`` was 160 passed without the invoice test and 13 failed plus 91
    errors with it, and only one of those failures was real.

    Take this fixture in a test that exercises a write path with a detached
    consumer and is asserting on the write rather than on the fan-out. The
    subscribers themselves are left alone: they are not the thing under test
    and they are not broken.
    """
    from app.core.events import event_bus
    from app.modules.costmodel.service import _on_budget_line_changed

    detached = [
        ("costmodel.budget_line.updated", _on_budget_line_changed),
        ("costmodel.budget_line.actual_posted", _on_budget_line_changed),
    ]
    removed = [(name, fn) for name, fn in detached if fn in event_bus._handlers.get(name, [])]
    for name, fn in removed:
        event_bus.unsubscribe(name, fn)
    try:
        yield
    finally:
        for name, fn in removed:
            event_bus.subscribe(name, fn)


@pytest_asyncio.fixture
async def pg_session(pg_engine) -> AsyncGenerator:
    """Per-test session with outer-transaction + savepoint rollback isolation."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    conn = await pg_engine.connect()
    trans = await conn.begin()
    factory = async_sessionmaker(
        bind=conn,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    session = factory()
    try:
        yield session
    finally:
        await session.close()
        if trans.is_active:
            await trans.rollback()
        await conn.close()

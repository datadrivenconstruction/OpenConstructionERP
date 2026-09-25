# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A worker that finds the RLS provisioning lock taken waits, then provisions.

Several workers booting against one PostgreSQL race for the provisioning lock.
The loser used to skip at once and go on to ``verify_rls_role`` and to serving
requests while the holder's roles and policies were still uncommitted, so on a
fresh database it logged a missing role that was being created at that moment
and its first requests could fail on ``SET LOCAL ROLE``. The loser now waits
for the lock and runs the idempotent provisioning itself.
"""

from __future__ import annotations

import contextlib
from types import SimpleNamespace
from typing import Any

import pytest

_TRY_LOCK = "pg_try_advisory_xact_lock"


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar(self) -> Any:
        return self._value


class _Connection:
    """Records statements; the lock is held elsewhere for the first ``busy_polls`` asks."""

    def __init__(self, busy_polls: int) -> None:
        self.busy_polls = busy_polls
        self.executed: list[str] = []

    async def execute(self, statement: Any, params: Any = None) -> _Result:
        sql = str(statement)
        self.executed.append(sql)
        if _TRY_LOCK in sql:
            asks = sum(_TRY_LOCK in s for s in self.executed)
            return _Result(asks > self.busy_polls)
        return _Result(None)

    @contextlib.asynccontextmanager
    async def begin_nested(self):
        yield self


class _Engine:
    def __init__(self, conn: _Connection) -> None:
        self.conn = conn

    @contextlib.asynccontextmanager
    async def begin(self):
        yield self.conn


def _base() -> SimpleNamespace:
    from sqlalchemy import Column, Integer, MetaData, String, Table

    metadata = MetaData()
    Table("oe_demo_tenant_row", metadata, Column("id", Integer, primary_key=True), Column("tenant_id", String))
    return SimpleNamespace(metadata=metadata)


@pytest.fixture
def rls_on_quick_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import rls_setup

    monkeypatch.setattr(rls_setup, "rls_enabled", lambda: True)
    monkeypatch.setattr(rls_setup, "_RLS_LOCK_WAIT_SECONDS", 0.2, raising=False)
    monkeypatch.setattr(rls_setup, "_RLS_LOCK_POLL_SECONDS", 0.01, raising=False)


@pytest.mark.asyncio
@pytest.mark.usefixtures("rls_on_quick_wait")
async def test_a_worker_that_lost_the_lock_provisions_once_it_gets_it() -> None:
    from app.core.rls_setup import provision_rls

    conn = _Connection(busy_polls=2)
    stats = await provision_rls(_Engine(conn), _base())

    assert sum(_TRY_LOCK in s for s in conn.executed) == 3
    assert stats["tables"] == 1
    assert any("CREATE POLICY" in s for s in conn.executed)


@pytest.mark.asyncio
@pytest.mark.usefixtures("rls_on_quick_wait")
async def test_the_statement_lock_timeout_is_set_only_after_the_lock_is_held() -> None:
    from app.core.rls_setup import provision_rls

    conn = _Connection(busy_polls=1)
    await provision_rls(_Engine(conn), _base())

    last_ask = max(i for i, s in enumerate(conn.executed) if _TRY_LOCK in s)
    timeout = next(i for i, s in enumerate(conn.executed) if "lock_timeout" in s)
    assert last_ask < timeout


@pytest.mark.asyncio
@pytest.mark.usefixtures("rls_on_quick_wait")
async def test_a_worker_that_never_gets_the_lock_waits_and_then_runs_no_ddl() -> None:
    from app.core.rls_setup import provision_rls

    conn = _Connection(busy_polls=10**6)
    stats = await provision_rls(_Engine(conn), _base())

    assert sum(_TRY_LOCK in s for s in conn.executed) > 1, "the worker must wait, not give up on the first ask"
    assert stats == {"roles": 0, "tables": 0}
    assert not any("ALTER TABLE" in s or "CREATE" in s for s in conn.executed)

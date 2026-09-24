# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A worker that did not get the heal lock does not report a heal it never ran.

Several workers booting against one external PostgreSQL race for the heal's
advisory lock. The loser used to return 0 straight away, and 0 is what a heal
that ran and found nothing to do returns, so the call site recorded
``schema_heal_failed: false`` and ``schema_heal_incomplete: false`` on that
worker. Under a role that cannot issue DDL the winner published
``incomplete: true`` with the SQL to run while every other worker published a
clean pass for the same database, and which answer ``/api/health`` gave
depended on which worker took the request.

The loser now waits for the lock and runs the heal itself. Every statement is
idempotent, so on a schema the winner completed the second pass changes nothing,
and on one it could not complete the loser collects the same refusals. A loser
that waits past the bound raises, and the call site records a heal nobody on
that worker verified: incomplete, and not failed, because failed degrades the
status and a restart would only queue behind the same holder.

The distinguishing case is a role that cannot issue DDL. A loser that can issue
it reads clean before and after the change, so it proves nothing.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from tests.unit.test_a_heal_statement_the_database_refuses_is_named_with_its_sql import (
    _Connection,
    _Engine,
    _model,
    _Result,
    fake_inspector,  # noqa: F401 - a fixture, used by name
)

_TRY_LOCK = "pg_try_advisory_xact_lock"


class _ContendedConnection(_Connection):
    """A connection whose heal lock is held by another worker for the first ``busy_polls`` asks."""

    def __init__(self, *, refuse_ddl: bool, busy_polls: int) -> None:
        super().__init__(refuse_ddl=refuse_ddl)
        self.busy_polls = busy_polls

    async def execute(self, statement: Any, params: Any = None) -> _Result:
        if _TRY_LOCK in str(statement):
            self.executed.append(str(statement))
            asks = sum(_TRY_LOCK in sql for sql in self.executed)
            return _Result(asks > self.busy_polls)
        return await super().execute(statement, params)


@pytest.fixture
def quick_lock_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import postgres_migrator

    monkeypatch.setattr(postgres_migrator, "_HEAL_LOCK_WAIT_SECONDS", 0.2)
    monkeypatch.setattr(postgres_migrator, "_HEAL_LOCK_POLL_SECONDS", 0.01)


@pytest.mark.asyncio
@pytest.mark.usefixtures("fake_inspector", "quick_lock_wait")
async def test_a_worker_that_lost_the_lock_collects_the_refusals_once_it_gets_it() -> None:
    from app.core.postgres_migrator import heal_is_incomplete, postgres_auto_migrate

    conn = _ContendedConnection(refuse_ddl=True, busy_polls=2)
    skipped: list = []
    await postgres_auto_migrate(_Engine(conn), _model(), skipped=skipped)

    assert sum(_TRY_LOCK in sql for sql in conn.executed) == 3
    assert [(s.kind, s.name) for s in skipped] == [
        ("not_null", "note"),
        ("column", "gross_basis"),
        ("index", "ix_claim_status"),
        ("check", "ck_claim_basis"),
    ]
    assert heal_is_incomplete(skipped, raised=False) is True


@pytest.mark.asyncio
@pytest.mark.usefixtures("fake_inspector", "quick_lock_wait")
async def test_the_statement_lock_timeout_is_set_only_after_the_heal_lock_is_held() -> None:
    """A 3s ``lock_timeout`` set before the wait would cut every loser short."""
    from app.core.postgres_migrator import postgres_auto_migrate

    conn = _ContendedConnection(refuse_ddl=False, busy_polls=1)
    await postgres_auto_migrate(_Engine(conn), _model())

    last_ask = max(i for i, sql in enumerate(conn.executed) if _TRY_LOCK in sql)
    timeout = next(i for i, sql in enumerate(conn.executed) if "lock_timeout" in sql)
    assert last_ask < timeout


@pytest.mark.asyncio
@pytest.mark.usefixtures("fake_inspector", "quick_lock_wait")
async def test_a_worker_that_never_gets_the_lock_raises_instead_of_returning_a_clean_count() -> None:
    from app.core.postgres_migrator import HealLockUnavailable, postgres_auto_migrate

    conn = _ContendedConnection(refuse_ddl=True, busy_polls=10**6)
    skipped: list = []
    with pytest.raises(HealLockUnavailable):
        await postgres_auto_migrate(_Engine(conn), _model(), skipped=skipped)

    assert sum(_TRY_LOCK in sql for sql in conn.executed) > 1, "the worker must wait, not give up on the first ask"
    assert not any(sql.startswith(("ALTER TABLE", "CREATE ")) for sql in conn.executed)
    assert skipped == []


def _bare_app() -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace())


@pytest.mark.asyncio
@pytest.mark.usefixtures("fake_inspector", "quick_lock_wait")
async def test_a_lock_that_never_frees_is_recorded_as_unverified_and_not_as_failed() -> None:
    from app.main import run_schema_heal

    app = _bare_app()
    await run_schema_heal(app, _Engine(_ContendedConnection(refuse_ddl=False, busy_polls=10**6)), _model())

    assert app.state.schema_heal_incomplete is True
    # Not True: that degrades /api/health, and a supervisor restarting on it
    # would only queue the next start behind the same holder.
    assert app.state.schema_heal_failed is None
    assert app.state.schema_heal_skipped == ()


@pytest.mark.asyncio
@pytest.mark.usefixtures("fake_inspector", "quick_lock_wait")
async def test_the_losing_worker_publishes_the_same_incomplete_heal_as_the_winner() -> None:
    from app.main import run_schema_heal

    winner = _bare_app()
    await run_schema_heal(winner, _Engine(_ContendedConnection(refuse_ddl=True, busy_polls=0)), _model())
    loser = _bare_app()
    await run_schema_heal(loser, _Engine(_ContendedConnection(refuse_ddl=True, busy_polls=3)), _model())

    for state in (winner.state, loser.state):
        assert state.schema_heal_failed is False
        assert state.schema_heal_incomplete is True
    assert [s.sql for s in loser.state.schema_heal_skipped] == [s.sql for s in winner.state.schema_heal_skipped]

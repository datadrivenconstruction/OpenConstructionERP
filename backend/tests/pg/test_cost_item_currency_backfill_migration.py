# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG: the currency backfill keeps what it filled when the migration is interrupted.

``v3273_backfill_cost_item_currency`` rewrites potentially every row of
``oe_costs_item``. Alembic runs an entire upgrade inside one transaction, so the
first shape of that revision needed peak disk for the whole table rewritten at
once, and when it ran out on a real database the abort took every region that
had already succeeded with it. The predicate reads as resumable and inside one
transaction it is not: each retry started from zero and needed the same peak, so
freeing a little space and trying again could never finish.

The fix commits in chunks on a connection of its own. **That claim is what these
tests pin, and the size of the table is not how you check it.** A fixture small
enough to run in CI completes under either implementation, so asserting "the
rows came out filled" would pass on the code that failed in the field and prove
nothing. What separates the two is durability, not throughput, so the central
test below rolls the migration's own transaction back and asserts the fill
survived it. Old code: rollback undoes everything, exactly as it did on the real
database. New code: the rows were committed by a second connection the rollback
cannot reach. That distinction holds at three rows and at three million.

The peak these chunks are sized for is stated in the revision and is a property
of a 1724 MB table; verifying the number itself needs that table and belongs on
a real database, not here.

These tests genuinely commit, so they cannot use ``pg_session`` (which isolates
by rolling back and would hide the very thing under test, besides being
invisible to a second connection). They build a synchronous engine the way
``env.py`` does in production, tag every row they write with a unique ``source``
and delete those rows afterwards.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import importlib.util
import pathlib
import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

_MIGRATION = (
    pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions" / "v3273_backfill_cost_item_currency.py"
)

# AU_SYDNEY is the region the real failure died on; NZ_AUCKLAND gives the loop a
# second region to cross, and NOWHERE_ATLANTIS is deliberately absent from the
# frozen market table.
_KNOWN = ("AU_SYDNEY", "AUD")
_SECOND = ("NZ_AUCKLAND", "NZD")
_UNKNOWN_REGION = "NOWHERE_ATLANTIS"

_INSERT = text(
    "INSERT INTO oe_costs_item "
    "(id, code, description, descriptions, unit, rate, currency, source, "
    " classification, components, tags, metadata, region, is_active, created_at, updated_at) "
    "VALUES (:id, :code, 'Backfill fixture row', '{}', 'm3', '100.00', :currency, :source, "
    "        '{}', '[]', '[]', '{}', :region, true, now(), now())"
)


def _load_migration():
    """Import the migration module by path (it is not on the import path)."""
    spec = importlib.util.spec_from_file_location("mig_v3273", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sync_engine(pg_async_url):
    """A synchronous engine on the test cluster, as ``env.py`` builds in production."""
    url = make_url(pg_async_url).set(drivername="postgresql+psycopg2")
    engine = create_engine(url, poolclass=NullPool)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def marker(sync_engine):
    """A unique ``source`` tag, and removal of every row carrying it afterwards.

    These tests commit, so cleanup is not optional: the cluster is session
    scoped and rows left behind would be visible to everything after them.
    """
    tag = f"backfill-test-{uuid.uuid4().hex[:12]}"
    try:
        yield tag
    finally:
        with sync_engine.connect() as conn:
            conn.execute(text("DELETE FROM oe_costs_item WHERE source = :s"), {"s": tag})
            conn.commit()


def _seed(engine, source: str, rows: list[tuple[str, str]]) -> None:
    """Commit ``rows`` as (region, currency) pairs. Committed so a second connection sees them."""
    with engine.connect() as conn:
        for index, (region, currency) in enumerate(rows):
            conn.execute(
                _INSERT,
                {
                    "id": str(uuid.uuid4()),
                    "code": f"{source}-{index:04d}",
                    "currency": currency,
                    "source": source,
                    "region": region,
                },
            )
        conn.commit()


def _run_upgrade(engine, *, rollback: bool, module=None) -> None:
    """Run the real ``upgrade()`` inside a transaction, then commit or roll it back.

    ``module`` is for callers that patched the revision and need *their* module
    object used: :func:`_load_migration` builds a fresh one on every call, so a
    patch applied to one instance is invisible to another.
    """
    module = module or _load_migration()
    with engine.connect() as conn:
        trans = conn.begin()
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            module.upgrade()
        if rollback:
            trans.rollback()
        else:
            trans.commit()


def _currencies(engine, source: str) -> dict[str, str]:
    """Read committed state on a fresh connection, keyed by code."""
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT code, currency FROM oe_costs_item WHERE source = :s ORDER BY code"),
            {"s": source},
        ).all()
    return {code: currency for code, currency in rows}


def test_a_rollback_cannot_undo_what_the_backfill_already_committed(sync_engine, marker) -> None:
    """The failure from the field, reproduced: abort the migration, keep the progress.

    This is the whole point of the revision's second connection. Run against the
    original in-transaction implementation this test fails, because the rollback
    takes the fill with it - which is precisely what left 553 360 rows pending
    after every retry on the real database.
    """
    _seed(sync_engine, marker, [(_KNOWN[0], ""), (_KNOWN[0], ""), (_SECOND[0], "")])

    _run_upgrade(sync_engine, rollback=True)

    filled = _currencies(sync_engine, marker)
    assert sorted(filled.values()) == [_KNOWN[1], _KNOWN[1], _SECOND[1]]


def test_the_in_transaction_path_does_lose_its_work_on_a_rollback(sync_engine, marker, monkeypatch) -> None:
    """The control for the test above, and the reason the second connection exists.

    Force the fallback and the same rollback wipes the fill completely. Without
    this, the passing test above would be consistent with the assertion never
    having had any teeth - a fixture this small finishes under either
    implementation, so "the rows came out filled" cannot tell them apart. Here
    the two paths are run against identical data and disagree, which is what
    makes the durability claim a measurement rather than a hope.

    It is also an honest statement of what the fallback gives up. That path is
    still correct, and it is only ever taken when the table was created in this
    same transaction and is therefore empty or small.
    """
    module = _load_migration()
    monkeypatch.setattr(module, "_open_side_connection", lambda bind: None)

    _seed(sync_engine, marker, [(_KNOWN[0], ""), (_SECOND[0], "")])

    _run_upgrade(sync_engine, rollback=True, module=module)

    filled = _currencies(sync_engine, marker)
    assert sorted(filled.values()) == ["", ""]


def test_the_loop_crosses_chunk_boundaries_and_finishes_the_remainder(sync_engine, marker, monkeypatch) -> None:
    """Seven rows at a chunk of two: three full chunks and a partial one, all filled."""
    module = _load_migration()
    monkeypatch.setattr(module, "_CHUNK_ROWS", 2)

    _seed(sync_engine, marker, [(_KNOWN[0], "")] * 7)

    with sync_engine.connect() as conn:
        trans = conn.begin()
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            module.upgrade()
        trans.commit()

    filled = _currencies(sync_engine, marker)
    assert len(filled) == 7
    assert set(filled.values()) == {_KNOWN[1]}


def test_a_row_that_already_carries_a_currency_is_never_rewritten(sync_engine, marker) -> None:
    """Chunking must not weaken the promise that only blank rows are touched."""
    _seed(sync_engine, marker, [(_KNOWN[0], "USD"), (_KNOWN[0], "")])

    _run_upgrade(sync_engine, rollback=False)

    filled = _currencies(sync_engine, marker)
    assert sorted(filled.values()) == ["AUD", "USD"]


def test_a_region_outside_the_frozen_market_table_is_left_blank(sync_engine, marker) -> None:
    """No currency is derivable, so none is invented."""
    _seed(sync_engine, marker, [(_UNKNOWN_REGION, ""), (_KNOWN[0], "")])

    _run_upgrade(sync_engine, rollback=False)

    filled = _currencies(sync_engine, marker)
    assert sorted(filled.values()) == ["", _KNOWN[1]]


def test_running_it_twice_fills_nothing_the_second_time(sync_engine, marker) -> None:
    """Idempotent across the chunked path as well."""
    _seed(sync_engine, marker, [(_KNOWN[0], "")] * 3)

    _run_upgrade(sync_engine, rollback=False)
    _run_upgrade(sync_engine, rollback=False)

    filled = _currencies(sync_engine, marker)
    assert sorted(filled.values()) == [_KNOWN[1]] * 3


def test_a_vacuum_that_cannot_run_is_a_warning_rather_than_a_failed_upgrade(sync_engine) -> None:
    """Losing the peak bound must not cost the upgrade.

    ``VACUUM`` needs ownership of the table, so an install whose migration role
    does not own ``oe_costs_item`` would raise mid-backfill and abort an upgrade
    that was otherwise going fine. The fill is still correct without it.

    The failure here is a real one rather than a mock: PostgreSQL refuses
    ``VACUUM`` inside a transaction block, so passing a connection with an open
    transaction exercises the same except branch a permission error would.
    """
    module = _load_migration()

    with sync_engine.connect() as conn:
        trans = conn.begin()
        module._vacuum(conn)  # must not raise
        trans.rollback()


def test_a_table_created_in_the_open_transaction_falls_back_instead_of_hanging(sync_engine, monkeypatch) -> None:
    """The guard against the worst outcome: a wedged upgrade nobody can interrupt.

    A database older than the costs module creates ``oe_costs_item`` in a
    revision inside this same uncommitted transaction. A second connection
    cannot see such a table, and *querying* it would block on the catalog lock
    rather than fail, hanging the upgrade indefinitely. ``to_regclass`` answers
    from the second connection's own snapshot without taking a lock, so the
    probe returns ``None`` and the caller falls back to filling in-transaction.

    Simulated by pointing the revision at a table created and left uncommitted.
    Note what failure looks like here: an implementation that probed by querying
    the table would not return a wrong answer, it would stop responding. The
    revision's ``lock_timeout`` bounds even that, so a regression surfaces as a
    slow test rather than a suite that never ends.
    """
    module = _load_migration()
    scratch = f"oe_backfill_probe_{uuid.uuid4().hex[:12]}"
    monkeypatch.setattr(module, "_ITEM", scratch)

    with sync_engine.connect() as conn:
        trans = conn.begin()
        conn.execute(text(f"CREATE TABLE {scratch} (id integer)"))  # noqa: S608 - generated name
        side = module._open_side_connection(conn)
        if side is not None:  # pragma: no cover - only on a regression
            side.close()
        trans.rollback()

    assert side is None

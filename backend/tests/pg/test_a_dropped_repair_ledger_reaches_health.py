# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A database with no ledger table repairs its rows and must not answer healthy.

The sibling in ``test_data_repairs.py`` proves the *runner* reports the two
halves separately: it monkeypatches ``_record`` to raise and asserts the repairs
still land while ``ledger_written`` comes back ``False``. That is one end of the
wire. This file is the other end, and it drops the table for real rather than
patching the function, because "the ledger write raises" and "the ledger table
is not there" are only the same thing if nothing between them is looking at the
schema.

What was wrong
--------------
The boot path read the outcomes off the report and dropped ``ledger_written``
on the floor. On this exact fixture - registry intact, rows repaired,
``oe_data_repair_ledger`` gone - ``/api/health`` answered ``status: healthy``
with ``data_repairs_failed: false``, which was true as far as it went and said
nothing at all about the half that had failed. The install could no longer
answer "did this repair run here", and no signal anywhere said so. That is the
one question a ledger exists to answer, so losing it silently defeats having
one.

Why it enters through ``publish_data_repair_verdict``
-----------------------------------------------------
Setting ``app.state`` by hand and then reading ``/api/health`` tests the
endpoint and not the wiring, and the wiring is where the defect lived: the
endpoint would have published the field perfectly well if anything had ever
written it. So the report goes through the same function the boot block calls,
which is the only writer of either field. Revert that function's
``data_repair_ledger_failed`` line and this test goes red; revert only the
endpoint's and it goes red too.

Transactional DDL
-----------------
The ``DROP TABLE`` runs inside the fixture's outer transaction, so it is visible
to every savepoint-joined session the runner opens and is taken back out of the
cluster by the rollback at teardown. PostgreSQL is what makes that possible;
this test could not be written on a database that commits DDL implicitly, which
is part of why it lives in the pg lane.
"""

from __future__ import annotations

import logging

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.data_repairs import run_data_repairs

pytestmark = pytest.mark.asyncio

_LEDGER_TABLE = "oe_data_repair_ledger"


@pytest_asyncio.fixture
async def repair_factory(pg_engine):
    """A session factory the runner can open many sessions from, rolled back after.

    Same shape as the fixture of the same name in ``test_data_repairs.py``:
    ``run_data_repairs`` takes a factory and opens a session per repair plus one
    per ledger write, so a single session will not do. One outer transaction on
    one connection, sessions joining it as savepoints, rolled back at teardown.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    conn = await pg_engine.connect()
    trans = await conn.begin()
    factory = async_sessionmaker(
        bind=conn,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    try:
        yield factory
    finally:
        if trans.is_active:
            await trans.rollback()
        await conn.close()


def _health(app) -> dict:
    from fastapi.testclient import TestClient

    # Not the context-manager form: that runs the lifespan, which would start a
    # second repair pass against the real engine and overwrite the verdict.
    return TestClient(app).get("/api/health").json()


async def test_the_repairs_land_and_the_record_of_them_does_not(
    repair_factory, caplog: pytest.LogCaptureFixture
) -> None:
    """The fixture itself, stated before anything is asserted about health.

    If this ever stopped holding - the repairs failing too, say, or the drop not
    reaching the runner's sessions - the health assertions below would still
    pass for the wrong reason, because a failed repair degrades the status on
    its own.
    """
    async with repair_factory() as session:
        await session.execute(text(f"DROP TABLE IF EXISTS {_LEDGER_TABLE}"))
        await session.commit()

    with caplog.at_level(logging.ERROR, logger="app.core.data_repairs"):
        report = await run_data_repairs(repair_factory, app_version="test")

    assert report.attempted > 0, "no repair ran, so this fixture proves nothing about the ledger"
    assert report.failed == (), "a missing ledger table must not be reported as a failed repair"
    assert report.ledger_written is False
    assert any("ledger" in r.getMessage().lower() for r in caplog.records)


async def test_health_does_not_say_clean_when_the_ledger_was_lost(repair_factory) -> None:
    """The publish. This is the assertion the defect failed.

    ``status: healthy`` beside ``data_repairs_failed: false`` was the whole of
    what this install reported while its ledger was gone.
    """
    from app.main import create_app, publish_data_repair_verdict

    async with repair_factory() as session:
        await session.execute(text(f"DROP TABLE IF EXISTS {_LEDGER_TABLE}"))
        await session.commit()

    report = await run_data_repairs(repair_factory, app_version="test")

    app = create_app()
    publish_data_repair_verdict(app, report)
    payload = _health(app)

    assert payload["data_repair_ledger_failed"] is True
    assert payload["status"] != "healthy"
    # Named rather than left to the status, because a degraded status is
    # reachable from six other things on this payload and would pass here
    # without the ledger having been reported at all.
    assert payload["status"] == "degraded"
    assert payload["data_repairs_failed"] is False, "the repairs themselves were fine and must still say so"


async def test_the_same_pass_with_its_ledger_intact_reports_clean(repair_factory) -> None:
    """The control, and it is not decoration.

    Everything above would pass just as well against a field hardwired to
    ``True``. This runs the identical pass over the identical registry with the
    table left where it is and requires the opposite answer, which is the only
    thing that makes the test above evidence of anything.
    """
    from app.main import create_app, publish_data_repair_verdict

    report = await run_data_repairs(repair_factory, app_version="test")

    assert report.ledger_written is True

    app = create_app()
    publish_data_repair_verdict(app, report)
    payload = _health(app)

    assert payload["data_repair_ledger_failed"] is False
    assert payload["data_repairs_failed"] is False

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The boot-path data-repair runner, against a real database with rows in it.

Why this suite is shaped the way it is
--------------------------------------
The defect underneath ``app.core.data_repairs`` is that a data rewrite never
happens while every signal reports success. "Does nothing" is the bug, and
"does nothing" passes a happy-path test that only checks for the absence of an
error. So the controls here are not decoration:

* :func:`test_an_empty_registry_leaves_the_same_database_branded` runs the same
  fixture through the same entry point with the registry emptied, and requires
  the rows to come out UNREPAIRED. If that ever passes while the registry is
  full, the positive test above it was measuring nothing.
* :func:`test_a_catalogue_with_nothing_to_repair_is_left_alone` is the other
  direction: a database that should not be rewritten has to come out
  byte-identical, compared row by row rather than by the absence of an
  exception.
* :func:`test_the_ledger_does_not_gate_the_repair` states the design rule in a
  form that can fail. A ledger row claiming the repair already ran must not
  stop it running, because a table allowed to answer "already done" over data
  that was never rewritten is ``alembic_version``, and that is the defect this
  module exists because of.

Isolation
---------
``pg_session`` hands out one session. The runner takes a *factory* and opens a
session per repair plus one per ledger write, so this file builds its own
factory over a single connection inside one outer transaction: every session it
hands out joins that transaction as a savepoint, the runner's ``commit()`` calls
become savepoint releases, and the rollback at teardown takes the whole thing
back out of the shared cluster.

The trademarked strings are never written here. They are read from
``LEGACY_BRANDED_SYSTEMS``, which is the single shipped copy and exists as a
search key; see the docstring of ``app.modules.formwork.debrand``.
"""

from __future__ import annotations

import logging
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.core.data_repairs import DataRepair, DataRepairLedger, run_data_repairs
from app.modules.formwork.debrand import LEGACY_BRANDED_SYSTEMS
from app.modules.formwork.models import FormworkSystem
from tests._repair_registry_source import repairs_missing_from

pytestmark = pytest.mark.asyncio

_LEDGER_TABLE = "oe_data_repair_ledger"
_FORMWORK_REPAIR_ID = "formwork_debrand"


@pytest_asyncio.fixture
async def repair_factory(pg_engine):
    """A session factory the runner can open many sessions from, rolled back after.

    Same isolation as ``pg_session`` (outer transaction plus savepoint-joined
    sessions) but yielding the factory rather than one session, because that is
    the shape :func:`run_data_repairs` consumes.
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


def _branded_row(name: str, supplier: str) -> FormworkSystem:
    """One catalogue row as a pre-de-brand seed would have written it."""
    return FormworkSystem(
        name=name,
        system_type="wall",
        supplier=supplier,
        material="steel",
        reuses_max=100,
        unit_rate=65,
        erect_strike_rate=16,
        strip_time_days=1,
        rate_basis="purchase",
        cycle_days=2,
        currency="",
        tenant_id=None,
    )


async def _seed_branded(factory) -> None:
    async with factory() as session:
        for old, supplier, _ in LEGACY_BRANDED_SYSTEMS:
            session.add(_branded_row(old, supplier))
        await session.commit()


async def _catalogue(factory) -> list[tuple[str, str | None]]:
    async with factory() as session:
        rows = (await session.execute(select(FormworkSystem.name, FormworkSystem.supplier))).all()
    return sorted((name, supplier) for name, supplier in rows)


async def _ledger(factory, repair_id: str) -> DataRepairLedger | None:
    async with factory() as session:
        return (
            await session.execute(select(DataRepairLedger).where(DataRepairLedger.repair_id == repair_id))
        ).scalar_one_or_none()


def _formwork(report):
    """The one outcome in a report that belongs to the de-brand repair.

    Every assertion about counts goes through this rather than through
    ``report.rows_changed``. The registry is meant to grow, and a test that
    reads the whole pass's total would go red the day somebody adds a second
    repair that happens to touch a row - which is a correct change and a
    useless failure.
    """
    return next(o for o in report.outcomes if o.repair_id == _FORMWORK_REPAIR_ID)


# ── the ledger table itself ──────────────────────────────────────────────


async def test_the_ledger_table_is_built_by_create_all(repair_factory) -> None:
    """The table exists on a database built the way the product builds one.

    It is declared in ``app.core``, which the dynamic ``app.modules.*`` model
    loop in both ``app/main.py`` and this lane's conftest does not reach, so it
    is only here because both carry an explicit import. A model that is missed
    that way produces no error anywhere: the repairs still run, and only the
    record of them is lost.
    """
    async with repair_factory() as session:
        found = (
            await session.execute(
                text("SELECT to_regclass(:t)"),
                {"t": _LEDGER_TABLE},
            )
        ).scalar()
    assert found == _LEDGER_TABLE


async def test_every_not_null_ledger_column_carries_a_server_default(repair_factory) -> None:
    """NOT NULL with no default is how a column arrives NULLABLE on an upgrade.

    ``postgres_auto_migrate`` renders only literal scalar defaults into its
    ``ADD COLUMN``; a Python-side callable default is dropped, and the column
    lands nullable with no default on every database that gets this table
    through the heal rather than through ``create_all``. Asserted against the
    live catalogue rather than against the model, because it is the database
    that has to hold the line.
    """
    async with repair_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT column_name, column_default FROM information_schema.columns "
                    "WHERE table_name = :t AND is_nullable = 'NO'"
                ),
                {"t": _LEDGER_TABLE},
            )
        ).all()

    assert rows, "no NOT NULL columns found - the query or the table name is wrong"
    # ``id`` and ``repair_id`` are identity, supplied by the writer on every
    # insert and never backfilled into existing rows, so a default would have
    # nothing to mean. Every other column is one the heal could have to add.
    identity = {"id", "repair_id"}
    missing = [name for name, default in rows if default is None and name not in identity]
    assert not missing, f"NOT NULL without a server default: {missing}"
    assert identity <= {name for name, _ in rows}, "an identity column stopped being NOT NULL"


async def test_two_rows_cannot_share_one_repair_id(repair_factory) -> None:
    """``repair_id`` is not the primary key, so the constraint has to be its own.

    ``Base`` declares a UUID ``id`` on every model. Marking ``repair_id``
    ``primary_key`` as well would make the key composite, which leaves
    ``repair_id`` unconstrained: two boots racing would each insert their own
    row and the ledger would then report one repair twice, with the counts split
    between them. Proven by asking the database to accept the duplicate.
    """
    from sqlalchemy.exc import IntegrityError

    async def _insert() -> None:
        async with repair_factory() as session:
            session.add(DataRepairLedger(repair_id="dupe", runs=1))
            await session.commit()

    await _insert()
    with pytest.raises(IntegrityError):
        await _insert()


# ── the positive case, and the control that gives it teeth ───────────────


async def test_a_branded_catalogue_is_repaired_through_the_runner(repair_factory) -> None:
    """The whole point: rows an old seed wrote come out renamed.

    Entered through :func:`run_data_repairs` with the real registry, not by
    calling the repair directly, so what is measured includes the registry
    entry, the session handling and the ledger write.
    """
    await _seed_branded(repair_factory)

    report = await run_data_repairs(repair_factory, app_version="test")

    assert _FORMWORK_REPAIR_ID not in report.failed
    outcome = _formwork(report)
    assert outcome.status == "applied"
    assert outcome.rows_changed == len(LEGACY_BRANDED_SYSTEMS)

    names = {name for name, _ in await _catalogue(repair_factory)}
    for old, _, new in LEGACY_BRANDED_SYSTEMS:
        assert old not in names, f"{old!r} survived the runner"
        assert new in names, f"{new!r} was not written"
    assert not [s for _, s in await _catalogue(repair_factory) if s], "a supplier still holds the original brand"


async def test_an_empty_registry_leaves_the_same_database_branded(repair_factory) -> None:
    """The control that proves the test above measures the repair and not the fixture.

    Identical seed, identical entry point, registry emptied. The rows have to
    come out exactly as they went in. A green result here with a full registry
    would mean the positive test proves nothing, which is the failure mode this
    whole module exists to answer: doing nothing is currently the bug, and doing
    nothing passes any test written only around a happy path.
    """
    await _seed_branded(repair_factory)
    before = await _catalogue(repair_factory)

    report = await run_data_repairs(repair_factory, repairs=(), app_version="test")

    assert report.attempted == 0
    assert report.rows_changed == 0
    assert await _catalogue(repair_factory) == before
    names = {name for name, _ in before}
    for old, _, _new in LEGACY_BRANDED_SYSTEMS:
        assert old in names, "the seed itself did not write the row this control depends on"


async def test_a_catalogue_with_nothing_to_repair_is_left_alone(repair_factory) -> None:
    """The other control: a database that should not be rewritten is not.

    Two rows the repair must never match - one already carrying a replacement
    name, one a tenant's own invention with their own supplier on it - compared
    row by row before and after. Asserting only "no exception" would pass while
    the repair quietly rewrote both.
    """
    async with repair_factory() as session:
        session.add(_branded_row(LEGACY_BRANDED_SYSTEMS[0][2], "A hire yard the tenant chose"))
        session.add(_branded_row("Site-made ply and stud panel", "Own joinery shop"))
        await session.commit()
    before = await _catalogue(repair_factory)

    report = await run_data_repairs(repair_factory, app_version="test")

    assert _FORMWORK_REPAIR_ID not in report.failed
    outcome = _formwork(report)
    assert outcome.status == "clean"
    assert outcome.rows_changed == 0
    assert await _catalogue(repair_factory) == before


# ── run twice ────────────────────────────────────────────────────────────


async def test_a_second_pass_changes_nothing(repair_factory) -> None:
    """Idempotence is a contract on every entry, so it is measured rather than assumed.

    A repair that runs on every boot and is not idempotent is worse than one
    that never runs, so this is the property that makes the design affordable.
    """
    await _seed_branded(repair_factory)

    first = await run_data_repairs(repair_factory, app_version="test")
    after_first = await _catalogue(repair_factory)
    second = await run_data_repairs(repair_factory, app_version="test")

    assert _formwork(first).rows_changed == len(LEGACY_BRANDED_SYSTEMS)
    assert _formwork(second).rows_changed == 0
    assert _formwork(second).status == "clean"
    assert await _catalogue(repair_factory) == after_first


# ── the ledger records, and never decides ────────────────────────────────


async def test_the_ledger_records_what_the_run_did(repair_factory) -> None:
    await _seed_branded(repair_factory)

    await run_data_repairs(repair_factory, app_version="15.9.1")

    row = await _ledger(repair_factory, _FORMWORK_REPAIR_ID)
    assert row is not None
    assert row.runs == 1
    assert row.last_outcome == "applied"
    assert row.last_rows_changed == len(LEGACY_BRANDED_SYSTEMS)
    assert row.rows_changed_total == len(LEGACY_BRANDED_SYSTEMS)
    assert row.last_error is None
    assert row.app_version == "15.9.1"


async def test_the_ledger_does_not_gate_the_repair(repair_factory) -> None:
    """A ledger row claiming the repair already ran must not stop it running.

    This is the design rule of the module in the form of a test. The failure it
    guards against is the one the whole module was written because of: a table
    that says "done" over data that was never rewritten. It also covers the
    practical case - a database restored from a backup taken before the repair
    keeps the ledger row and loses the repaired rows, and only a runner that
    ignores the ledger fixes it.
    """
    async with repair_factory() as session:
        session.add(
            DataRepairLedger(
                repair_id=_FORMWORK_REPAIR_ID,
                runs=1,
                rows_changed_total=99,
                last_rows_changed=99,
                last_outcome="applied",
            )
        )
        await session.commit()
    await _seed_branded(repair_factory)

    report = await run_data_repairs(repair_factory, app_version="test")

    assert _formwork(report).rows_changed == len(LEGACY_BRANDED_SYSTEMS), "the ledger row suppressed the repair"
    names = {name for name, _ in await _catalogue(repair_factory)}
    for old, _, new in LEGACY_BRANDED_SYSTEMS:
        assert old not in names
        assert new in names

    row = await _ledger(repair_factory, _FORMWORK_REPAIR_ID)
    assert row is not None
    assert row.runs == 2
    assert row.rows_changed_total == 99 + len(LEGACY_BRANDED_SYSTEMS)
    assert row.last_rows_changed == len(LEGACY_BRANDED_SYSTEMS)


# ── failure is loud, contained, and clears when it stops ─────────────────


async def _boom(_session) -> int:
    raise RuntimeError("no rights on that table")


def _failing_repair() -> DataRepair:
    return DataRepair(
        repair_id="boom",
        revision="v0000_not_a_real_revision",
        summary="A repair that raises, used to prove failure is contained and reported",
        run=_boom,
        nature="always_wrong",
    )


async def test_a_failing_repair_is_reported_and_does_not_stop_the_next_one(
    repair_factory, caplog: pytest.LogCaptureFixture
) -> None:
    from app.core.data_repairs import DATA_REPAIRS

    await _seed_branded(repair_factory)

    with caplog.at_level(logging.ERROR, logger="app.core.data_repairs"):
        report = await run_data_repairs(
            repair_factory,
            repairs=(_failing_repair(), *DATA_REPAIRS),
            app_version="test",
        )

    assert report.failed == ("boom",)
    assert next(o for o in report.outcomes if o.repair_id == "boom").error is not None
    # Containment: the repair AFTER the failure still ran and still did its work.
    assert _formwork(report).status == "applied"
    assert _formwork(report).rows_changed == len(LEGACY_BRANDED_SYSTEMS)

    # Loud, and it names the repair. A failure that only reaches DEBUG is the
    # signal this module was written to replace.
    assert any(r.levelno >= logging.ERROR and "boom" in r.getMessage() for r in caplog.records)

    row = await _ledger(repair_factory, "boom")
    assert row is not None
    assert row.last_outcome == "failed"
    assert row.last_error is not None
    assert "RuntimeError" in row.last_error


async def test_a_ledger_error_is_cleared_by_the_next_successful_run(repair_factory) -> None:
    """A message from a failure that is over must not keep reading as current."""
    calls = {"n": 0}

    async def _fails_once(_session) -> int:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return 0

    repair = DataRepair(
        repair_id="flaky",
        revision="",
        summary="Fails on its first pass and succeeds afterwards",
        run=_fails_once,
        nature="always_wrong",
    )

    await run_data_repairs(repair_factory, repairs=(repair,), app_version="test")
    first = await _ledger(repair_factory, "flaky")
    assert first is not None and first.last_outcome == "failed" and first.last_error

    await run_data_repairs(repair_factory, repairs=(repair,), app_version="test")

    row = await _ledger(repair_factory, "flaky")
    assert row is not None
    assert row.last_outcome == "clean"
    assert row.last_error is None
    assert row.runs == 2


async def test_a_ledger_write_failure_does_not_hide_a_successful_repair(
    repair_factory, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Data correct, record missing. Two different failures, reported separately.

    This is the shape an external database whose role may write rows but not
    create tables ends up in, and collapsing it into the repair verdict would
    let the smaller failure hide behind the larger one - or, worse, report a
    repair that worked as one that did not.
    """
    from app.core import data_repairs as module

    async def _no_ledger(*_args, **_kwargs) -> bool:
        raise RuntimeError('relation "oe_data_repair_ledger" does not exist')

    monkeypatch.setattr(module, "_record", _no_ledger)
    await _seed_branded(repair_factory)

    with caplog.at_level(logging.ERROR, logger="app.core.data_repairs"):
        report = await run_data_repairs(repair_factory, app_version="test")

    assert report.failed == (), "a ledger failure was reported as a repair failure"
    assert _formwork(report).rows_changed == len(LEGACY_BRANDED_SYSTEMS)
    assert report.ledger_written is False
    assert any(r.levelno >= logging.ERROR and "ledger" in r.getMessage().lower() for r in caplog.records)

    names = {name for name, _ in await _catalogue(repair_factory)}
    for _old, _, new in LEGACY_BRANDED_SYSTEMS:
        assert new in names, "the repair itself was rolled back by the ledger failure"


# ── the registry ─────────────────────────────────────────────────────────


async def test_the_whole_registry_runs_clean_against_a_current_schema(repair_factory) -> None:
    """Every registered repair, on a database built the way the product builds one.

    Scoped to the whole registry on purpose: the tests above scope their counts
    to one repair so that adding another does not fail them, and this is the
    one that has to notice a new entry. A repair that raises here raises on
    every customer's boot.

    The coverage check reads the registrations out of ``app/**/repairs.py`` as
    source. It used to be ``report.attempted == len(DATA_REPAIRS)``, which is
    the registry compared against itself: the report is what running the
    registry produced and the length is the registry's own. A repair that fell
    out of it - a module that stopped importing, a registration deleted - fell
    out of both sides at once and the assertion went on passing, so it could
    never fail for the thing it was written to catch. See
    ``tests/_repair_registry_source.py``.
    """
    report = await run_data_repairs(repair_factory, app_version="test")

    assert repairs_missing_from(report) == set()
    assert report.failed == ()
    assert report.discovery_failures == ()
    assert report.ledger_written is True


async def test_every_registered_repair_is_idempotent(repair_factory) -> None:
    """The contract that makes running on every boot affordable, held for the whole registry.

    Two passes over the same database; the second must change nothing, for every
    entry rather than for the one this file was written around. A repair that
    fails this doubles or re-writes something on every restart, which is worse
    than one that never runs - and only a test that reads the registry rather
    than a fixed list will notice when a new entry breaks it.

    Coverage is read from source for the reason given on the test above: a
    count taken from the registry the pass just ran cannot notice a repair
    going missing from it.
    """
    await _seed_branded(repair_factory)

    await run_data_repairs(repair_factory, app_version="test")
    second = await run_data_repairs(repair_factory, app_version="test")

    assert repairs_missing_from(second) == set()
    not_idempotent = [(o.repair_id, o.rows_changed) for o in second.outcomes if o.rows_changed]
    assert not not_idempotent, f"second pass changed rows: {not_idempotent}"


async def test_every_registered_repair_id_fits_the_ledger_and_is_unique() -> None:
    """Ids are the ledger's primary key, so a collision or an overlong one is data loss."""
    from app.core.data_repairs import DATA_REPAIRS

    ids = [r.repair_id for r in DATA_REPAIRS]
    assert len(ids) == len(set(ids)), f"duplicate repair_id in the registry: {ids}"
    width = DataRepairLedger.__table__.c.repair_id.type.length
    for repair in DATA_REPAIRS:
        assert repair.repair_id, "a repair with an empty id cannot be recorded"
        assert len(repair.repair_id) <= width, f"{repair.repair_id!r} does not fit VARCHAR({width})"
        assert repair.summary, f"{repair.repair_id!r} has no summary for the boot log"


async def test_a_repair_that_leaves_uncommitted_work_still_lands(repair_factory) -> None:
    """The runner owns the transaction, and a repair that only flushes is committed.

    ``repair_branded_catalogue`` flushes and leaves the commit to its caller, so
    this is the contract the registry depends on. Measured by reading the rows
    back through a session the repair never touched.
    """
    marker = f"Repair contract probe {uuid.uuid4()}"

    async def _adds_a_row(session) -> int:
        session.add(_branded_row(marker, "probe"))
        await session.flush()
        return 1

    repair = DataRepair(
        repair_id="probe",
        revision="",
        summary="Adds one row and flushes",
        run=_adds_a_row,
        nature="always_wrong",
    )

    await run_data_repairs(repair_factory, repairs=(repair,), app_version="test")

    names = {name for name, _ in await _catalogue(repair_factory)}
    assert marker in names


# ── The temporal contract ────────────────────────────────────────────────
#
# Idempotence above answers "is it safe to run twice". These answer the other
# question, which only arose once the registry had a second consumer of a
# different nature: is it safe to run at all against data somebody has already
# issued documents from.
#
# De-branding rewrites values that were never correct, so rewriting them in
# place is the whole repair. A tax rate is the opposite: 19 % was the right
# Romanian rate until 31 July 2025, and an invoice issued under it has to keep
# reading 19 % forever. A repair that overwrote the rate would change the value
# of a document already sent to a customer, and it would do it silently, months
# after the fact. ``SupersededBy`` is how a repair declares it is the second
# kind, and these tests are what make that declaration cost something.


async def _seed_pre_reform_romania(factory) -> None:
    """Put the database in the state a pre-2025 install is actually in.

    Without this the checks below run over an empty table and pass while
    proving nothing. Built from ``romania_vat``'s own recognition constants
    rather than from literals repeated here: if that module changes the shape
    it looks for, this fixture stops matching and the test fails loudly,
    instead of quietly going back to being vacuous.
    """
    from app.modules.i18n_foundation.models import TaxConfiguration
    from app.modules.i18n_foundation.romania_vat import _SHIPPED_OLD_STANDARD

    async with factory() as session:
        session.add(
            TaxConfiguration(
                country_code="RO",
                tax_name="VAT Standard (TVA)",
                tax_code=_SHIPPED_OLD_STANDARD["tax_code"],
                rate_pct=_SHIPPED_OLD_STANDARD["rate_pct"],
                tax_type="vat",
                combination="national",
                effective_from=_SHIPPED_OLD_STANDARD["effective_from"],
                effective_to=None,
                is_default=True,
            )
        )
        await session.commit()


async def test_every_superseded_repair_closes_and_adds_rather_than_rewriting(repair_factory) -> None:
    """The whole-registry contract: no superseded repair may edit a value in place.

    Reads the registry rather than a fixed list, so a third consumer that
    declares itself superseded is held to this without anybody remembering to
    add it here.
    """
    from app.core.data_repairs import discover_data_repairs, snapshot_table, verify_supersede_shape

    superseded = [r for r in discover_data_repairs() if r.nature == "superseded"]
    assert superseded, "no superseded repair registered - this check would be vacuous"

    await _seed_pre_reform_romania(repair_factory)

    for repair in superseded:
        assert repair.superseded is not None
        table = repair.superseded.table
        async with repair_factory() as session:
            before = await snapshot_table(session, table)
        assert before, f"{repair.repair_id}: {table} is empty, so this check would prove nothing"

        await run_data_repairs(repair_factory, repairs=(repair,), app_version="test")

        async with repair_factory() as session:
            after = await snapshot_table(session, table)

        violations = verify_supersede_shape(repair, before, after)
        assert not violations, f"{repair.repair_id} broke the close-and-add contract: {violations}"


async def test_the_superseded_repair_actually_did_something(repair_factory) -> None:
    """A contract held by a repair that did nothing is not evidence about the contract.

    Paired with the test above on purpose. That one proves no existing value
    moved; on its own it would also pass if the repair were a no-op, which is
    the failure shape this whole module exists to catch. This one proves the
    same run closed the old window and added the new rate.
    """
    from app.modules.i18n_foundation.romania_vat import OLD_STANDARD_LAST_DAY, REFORM_FIRST_DAY

    await _seed_pre_reform_romania(repair_factory)

    report = await run_data_repairs(repair_factory, app_version="test")
    romania = next(o for o in report.outcomes if o.repair_id == "romania_vat_2025")
    assert romania.status == "applied", f"the repair did nothing: {romania}"

    async with repair_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT rate_pct, effective_from, effective_to FROM oe_i18n_tax_config "
                    "WHERE country_code = 'RO' ORDER BY effective_from, rate_pct"
                )
            )
        ).all()

    by_rate = {r[0]: r for r in rows}
    assert "19.0" in by_rate, "the old rate was removed; a document issued under it can no longer be priced"
    assert by_rate["19.0"][2] == OLD_STANDARD_LAST_DAY, "the old rate's window was not closed"
    assert "21.0" in by_rate, "the new standard rate was not added"
    assert by_rate["21.0"][1] == REFORM_FIRST_DAY


async def test_a_pre_reform_date_still_resolves_at_the_old_rate(repair_factory) -> None:
    """The claim in the language the money is in, read through the product's own resolver.

    The two tests above are about rows. This one is about what a document
    priced on a date before the reform actually gets, which is the thing a
    customer would notice if the repair got it wrong.
    """
    from app.modules.i18n_foundation.models import TaxConfiguration
    from app.modules.i18n_foundation.tax_rules import active_rows, row_from_orm

    await _seed_pre_reform_romania(repair_factory)
    await run_data_repairs(repair_factory, app_version="test")

    async with repair_factory() as session:
        configs = (
            (await session.execute(select(TaxConfiguration).where(TaxConfiguration.country_code == "RO")))
            .scalars()
            .all()
        )
        rows = [row_from_orm(c) for c in configs]

    before_reform = active_rows(rows, "RO", "2025-06-30")
    after_reform = active_rows(rows, "RO", "2025-09-01")

    assert [r.rate_pct for r in before_reform] == ["19.0"], (
        f"a document priced before the reform no longer resolves at 19%: {[r.rate_pct for r in before_reform]}"
    )
    assert "21.0" in [r.rate_pct for r in after_reform], (
        f"a document priced after the reform does not see the new rate: {[r.rate_pct for r in after_reform]}"
    )


async def test_the_shape_check_catches_a_repair_that_rewrites_in_place(repair_factory) -> None:
    """The negative control, and the one that decides whether any of this means anything.

    Every check above is applied to repairs that already behave. If the checker
    itself could not tell a rewrite from a close-and-add, they would all pass
    over a repair that silently changed an issued invoice's rate. So: build the
    repair the contract is meant to forbid, run it, and require the checker to
    say so.
    """
    from app.core.data_repairs import DataRepair, SupersededBy, snapshot_table, verify_supersede_shape

    async def _rewrite_in_place(session) -> int:
        result = await session.execute(
            text("UPDATE oe_i18n_tax_config SET rate_pct = '21.0' WHERE country_code = 'RO' AND rate_pct = '19.0'")
        )
        return result.rowcount or 0

    bad = DataRepair(
        repair_id="rewrite_in_place_probe",
        revision="",
        summary="the mistake the contract exists to forbid",
        run=_rewrite_in_place,
        nature="superseded",
        superseded=SupersededBy(
            effective_from="2025-08-01",
            table="oe_i18n_tax_config",
            closes_column="effective_to",
        ),
    )

    await _seed_pre_reform_romania(repair_factory)
    async with repair_factory() as session:
        before = await snapshot_table(session, "oe_i18n_tax_config")

    await run_data_repairs(repair_factory, repairs=(bad,), app_version="test")

    async with repair_factory() as session:
        after = await snapshot_table(session, "oe_i18n_tax_config")

    violations = verify_supersede_shape(bad, before, after)
    assert violations, "the checker passed a repair that overwrote a rate in place"
    assert any("rate_pct" in v for v in violations), f"the violation does not name the column: {violations}"


async def test_the_shape_check_catches_a_deleted_row(repair_factory) -> None:
    """Second negative control: a rate that vanishes is a document that cannot be priced."""
    from app.core.data_repairs import DataRepair, SupersededBy, snapshot_table, verify_supersede_shape

    async def _delete_the_old_rate(session) -> int:
        result = await session.execute(
            text("DELETE FROM oe_i18n_tax_config WHERE country_code = 'RO' AND rate_pct = '19.0'")
        )
        return result.rowcount or 0

    bad = DataRepair(
        repair_id="delete_probe",
        revision="",
        summary="removes the superseded rate instead of closing it",
        run=_delete_the_old_rate,
        nature="superseded",
        superseded=SupersededBy(
            effective_from="2025-08-01",
            table="oe_i18n_tax_config",
            closes_column="effective_to",
        ),
    )

    await _seed_pre_reform_romania(repair_factory)
    async with repair_factory() as session:
        before = await snapshot_table(session, "oe_i18n_tax_config")

    await run_data_repairs(repair_factory, repairs=(bad,), app_version="test")

    async with repair_factory() as session:
        after = await snapshot_table(session, "oe_i18n_tax_config")

    violations = verify_supersede_shape(bad, before, after)
    assert violations, "the checker passed a repair that deleted the superseded rate"
    assert any("deleted" in v for v in violations), f"the violation does not say what happened: {violations}"


#: Column-name fragments that name a value a document is issued at. A
#: ``superseded`` repair may never edit one of these on a pre-existing row, so
#: none of them may appear in ``also_updates``.
#:
#: This is a heuristic and it is written down as one. It reads names, not
#: meanings, so it can miss a money column called something else entirely, and
#: it would object to an innocent column that happens to contain one of these
#: fragments. It is here because the failure it guards against is careless
#: rather than clever - the plausible way ``also_updates`` gets misused is
#: somebody adding the column their repair happened to touch to make the
#: contract test go green, and that column is usually named after the money.
#: A reviewer is still the real check; this makes the careless case loud.
_VALUE_COLUMN_FRAGMENTS = (
    "rate",
    "amount",
    "price",
    "cost",
    "total",
    "qty",
    "quantity",
    "currency",
    "effective_from",
)


async def test_no_superseded_repair_excuses_itself_from_a_value_column() -> None:
    """``also_updates`` is a hole in the contract, so it may not contain the money.

    The allowance exists for a selection hint - which rate the UI offers first -
    and for nothing else. Adding a rate or an amount to it would turn the
    close-and-add contract back into a rewrite that passes its own test, which
    is worse than having no contract, because the green would be evidence.
    """
    from app.core.data_repairs import discover_data_repairs

    offenders: list[tuple[str, str]] = []
    for repair in discover_data_repairs():
        if repair.superseded is None:
            continue
        for column in repair.superseded.also_updates:
            lowered = column.lower()
            if any(fragment in lowered for fragment in _VALUE_COLUMN_FRAGMENTS):
                offenders.append((repair.repair_id, column))

    assert not offenders, (
        f"a superseded repair permits itself to edit a value column on an existing row: {offenders}. "
        "That is the retroactive change the nature field exists to prevent."
    )


async def test_the_value_column_guard_would_actually_catch_one() -> None:
    """Negative control for the guard above, which is otherwise a loop over clean data.

    Every registered repair passes it today, so the test proves nothing about
    the guard unless the guard is shown to bite. Build the declaration it is
    meant to reject and check the same predicate rejects it.
    """
    from app.core.data_repairs import DataRepair, SupersededBy

    async def _noop(session) -> int:
        return 0

    sneaky = DataRepair(
        repair_id="value_column_excuse_probe",
        revision="",
        summary="declares the rate column as an allowed edit",
        run=_noop,
        nature="superseded",
        superseded=SupersededBy(
            effective_from="2025-08-01",
            table="oe_i18n_tax_config",
            closes_column="effective_to",
            also_updates=("rate_pct",),
        ),
    )

    assert sneaky.superseded is not None
    caught = [
        column
        for column in sneaky.superseded.also_updates
        if any(fragment in column.lower() for fragment in _VALUE_COLUMN_FRAGMENTS)
    ]
    assert caught == ["rate_pct"], "the guard would not have noticed a rate column in also_updates"

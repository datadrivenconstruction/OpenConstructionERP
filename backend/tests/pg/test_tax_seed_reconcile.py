# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The tax seed reconciler, against the two cohorts it has to tell apart.

Why the fixtures are built the way they are
-------------------------------------------
The defect under test survived five tests of the neighbouring repair, and it
survived them because all five built their fixture in a state the affected
cohort never reaches. So the two cohorts here are reconstructed from the seed
files those releases actually shipped, taken out of git, and each one carries a
digest of the real file so the reconstruction cannot drift away from it: change
``tax_configurations.json`` in a way that breaks the reconstruction and these
tests say so rather than quietly testing a database nobody has.

The reconstruction is written as exclusions from today's file rather than as a
vendored copy, and the digests are what make that honest. They were taken from
``git show d27f29ffa:...`` and ``git show 2dc7354a0:...``, the commits that
shipped in v15.5.0's predecessor and in v15.6.0.

Both cohorts are also put into the schema state the BOOT HEAL leaves, not the
one ``create_all`` builds. The heal adds the subdivision check constraint
``NOT VALID``, which is the only reason a v15.9.1 database can hold eleven rows
that break it; a fixture built under the validated constraint cannot even be
inserted, and a repair tested against one would never meet the rows it exists
for.

What each cohort is
-------------------
``pre_v15_5_0``
    Seeded from the 70-row file, before ``combination`` existed. The heal adds
    that column filled with its server default, so every row reads ``national``
    and no row carries a subdivision. This is the install missing ten of
    Canada's ten sub-national rates.

``v15_9_1``
    Seeded from the 80-row file. It has ``combination`` and does not have
    ``subdivision_code``, so eleven of its rows break the constraint the heal
    later adds. This is the cohort that must NOT be given anything: it already
    has every rate, so a row missing from it was deleted on purpose.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text

from app.core.data_repairs import (
    DataRepairDelivery,
    DataRepairLedger,
    discover_data_repairs,
    run_data_repairs,
    snapshot_table,
    verify_additive_shape,
)
from app.modules.i18n_foundation.models import TaxConfiguration
from app.modules.i18n_foundation.seed import load_tax_seed_rows
from app.modules.i18n_foundation.tax_rules import resolve, row_from_orm
from app.modules.i18n_foundation.tax_seed_reconcile import REPAIR_ID

pytestmark = pytest.mark.asyncio

_TAX_TABLE = "oe_i18n_tax_config"

#: Rows the seed file gained after the v15.4.0-era file, by
#: ``(country, tax_code, effective_from)``. Written out rather than derived from
#: the reconciler's own tables on purpose: deriving the fixture from the code
#: under test would make it agree with a wrong answer.
_ADDED_AFTER_V15_4_0 = {
    ("CA", "HST_NB", "2016-07-01"),
    ("CA", "HST_NL", "2016-07-01"),
    ("CA", "HST_NS", "2025-04-01"),
    ("CA", "HST_PE", "2016-10-01"),
    ("CA", "PST_BC", "2013-04-01"),
    ("CA", "PST_SK", "2017-03-23"),
    ("CA", "QST_QC", "2013-01-01"),
    ("CA", "RST_MB", "2019-07-01"),
    ("RO", "TVA", "2025-08-01"),
    ("NG", "VAT", "2020-02-01"),
    ("RO", "TVA_RED", "2025-08-01"),
    ("IL", "VAT", "2025-01-01"),
    ("KW", "NONE", None),
    ("QA", "NONE", None),
}

#: Rows the current file has since EDITED, restored to what the old file said.
#: All three are windows that were still open back then and have since been
#: closed, which is the half of an old cohort that an exclusion list alone
#: cannot reproduce.
_RESTORED_TO_V15_4_0 = {
    ("RO", "TVA", "2017-01-01"): {"effective_to": None, "is_default": True},
    ("CA", "HST_NS", "2010-07-01"): {"effective_to": None},
    ("IL", "VAT", "2015-10-01"): {"effective_to": None},
}

_ADDED_AFTER_V15_9_1 = {
    ("RO", "TVA_RED", "2025-08-01"),
    ("IL", "VAT", "2025-01-01"),
    ("KW", "NONE", None),
    ("QA", "NONE", None),
}

#: The v15.9.1 cohort needed no restorations until Israel's 18 % rate was
#: added: every window the current file had closed by then was already closed
#: in the file that release shipped. Israel's 17 % window is the first one to
#: be closed after v15.9.1, so this is where that cohort's copy of it is put
#: back to open. An empty dict here would silently reconstruct a database in
#: which Israel was already up to date, which is the one state the supersede
#: repair cannot be measured in.
_RESTORED_TO_V15_9_1 = {
    ("IL", "VAT", "2015-10-01"): {"effective_to": None},
}

#: SHA-256 of the real shipped file at each tag, over the fields the fixture
#: writes. See the module docstring for the commits.
_DIGEST_PRE_V15_5_0 = "14abf2d90aa573961b22e9e056bcdad2e31ca6ff0e0b5ec8db46813d89007d9b"
_DIGEST_V15_9_1 = "ec4106ee3f0cadcd6fce5ca0ec95fe69d55b4e51d1b4b3283daa462542038991"

_FIELDS = ("country_code", "tax_code", "rate_pct", "tax_type", "effective_from", "effective_to", "is_default")

#: The ten rate lines a pre-v15.5.0 install is missing and must be given.
#: Nova Scotia is deliberately not among them - it already holds the 15 % row,
#: so the 14 % one is a rate that changed rather than a rate never delivered.
_EXPECTED_DELIVERY = {
    "CA/HST_NB",
    "CA/HST_NL",
    "CA/HST_PE",
    "CA/PST_BC",
    "CA/PST_SK",
    "CA/QST_QC",
    "CA/RST_MB",
    "NG/VAT",
    # Kuwait and Qatar levy no VAT, and saying so is a rate like any
    # other: without these rows a Gulf project prices off the shared
    # regional stack at 5 percent.
    "KW/NONE",
    "QA/NONE",
}


def _key(row: dict) -> tuple:
    return (row["country_code"], row.get("tax_code"), row.get("effective_from"))


def _digest(rows: list[dict]) -> str:
    return hashlib.sha256("\n".join(sorted(json.dumps(r, sort_keys=True) for r in rows)).encode()).hexdigest()


def _cohort(*, excluded: set, restored: dict, keep_combination: bool, digest: str) -> list[dict]:
    """One historical seed file, rebuilt from today's and checked against it."""
    rows = []
    for row in load_tax_seed_rows():
        if _key(row) in excluded:
            continue
        rebuilt = {field: row.get(field) for field in _FIELDS}
        rebuilt["is_default"] = bool(row.get("is_default", False))
        # A database seeded before ``combination`` existed gets the column from
        # the heal, which fills every row with the server default.
        rebuilt["combination"] = row["combination"] if keep_combination else "national"
        rebuilt.update(restored.get(_key(row), {}))
        rows.append(rebuilt)
    assert _digest(rows) == digest, (
        "this fixture no longer reproduces the seed file that release actually shipped. "
        "tax_configurations.json changed in a way the exclusion and restoration lists at the "
        "top of this file do not account for, so these tests would be measuring a database no "
        "customer has."
    )
    return rows


def pre_v15_5_0() -> list[dict]:
    """The 70-row file, as the heal leaves it: everything ``national``, no subdivision."""
    return _cohort(
        excluded=_ADDED_AFTER_V15_4_0,
        restored=_RESTORED_TO_V15_4_0,
        keep_combination=False,
        digest=_DIGEST_PRE_V15_5_0,
    )


def v15_9_1() -> list[dict]:
    """The 80-row file: real combinations, and eleven rows with no subdivision."""
    return _cohort(
        excluded=_ADDED_AFTER_V15_9_1,
        restored=_RESTORED_TO_V15_9_1,
        keep_combination=True,
        digest=_DIGEST_V15_9_1,
    )


@pytest_asyncio.fixture
async def repair_factory(pg_engine):
    """A session factory the runner can open many sessions from, rolled back after."""
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


async def _constraint_name(session) -> str:
    return (
        await session.execute(
            text(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = :table ::regclass AND contype = 'c' AND conname LIKE '%subdivision%'"
            ),
            {"table": _TAX_TABLE},
        )
    ).scalar_one()


async def _leave_the_check_as_the_heal_leaves_it(session, name: str) -> None:
    """Re-add the subdivision constraint ``NOT VALID``, which is how the heal adds it.

    ``create_all`` builds it validated, which no upgraded install has. The
    constraint has to be absent while the cohort is inserted, not merely
    ``NOT VALID``: that qualifier exempts rows already on file and never a
    statement, so a v15.9.1 cohort cannot be written under it at all - and the
    eleven rows it exempts are the whole point of that cohort.
    """
    await session.execute(
        text(
            f"ALTER TABLE {_TAX_TABLE} ADD CONSTRAINT {name} CHECK "
            "((combination IN ('replaces_federal', 'stacks_on_federal', 'compounds_on_federal'))"
            " = (subdivision_code IS NOT NULL)) NOT VALID"
        )
    )


async def _install(factory, cohort: list[dict], seeded_on: str) -> None:
    """Seed one cohort, dated as if the seeder had run on ``seeded_on``.

    Backdating is not decoration. The reconciler reads the seed timestamp to
    tell an install that never received a rate from one that removed it, so a
    fixture written at ``now()`` reads as newer than every shipped rate and the
    repair correctly refuses to do anything - a test that would pass while
    measuring nothing.
    """
    at = datetime.fromisoformat(seeded_on).replace(tzinfo=UTC)
    async with factory() as session:
        name = await _constraint_name(session)
        await session.execute(text(f"ALTER TABLE {_TAX_TABLE} DROP CONSTRAINT {name}"))
        for row in cohort:
            session.add(
                TaxConfiguration(
                    country_code=row["country_code"],
                    tax_name=f"{row['country_code']} {row['tax_code']}",
                    tax_code=row["tax_code"],
                    rate_pct=row["rate_pct"],
                    tax_type=row["tax_type"],
                    combination=row["combination"],
                    subdivision_code=None,
                    effective_from=row["effective_from"],
                    effective_to=row["effective_to"],
                    is_default=row["is_default"],
                    metadata_={},
                    created_at=at,
                    updated_at=at,
                )
            )
        await session.flush()
        await _leave_the_check_as_the_heal_leaves_it(session, name)
        await session.commit()


async def _lines(factory) -> set[tuple[str, str | None]]:
    async with factory() as session:
        rows = (await session.execute(select(TaxConfiguration.country_code, TaxConfiguration.tax_code))).all()
    return {(country, code) for country, code in rows}


async def _count(factory) -> int:
    async with factory() as session:
        return (await session.execute(select(func.count()).select_from(TaxConfiguration))).scalar_one()


async def _deliveries(factory) -> set[str]:
    async with factory() as session:
        rows = await session.execute(
            select(DataRepairDelivery.delivery_key).where(DataRepairDelivery.repair_id == REPAIR_ID)
        )
    return set(rows.scalars().all())


async def _resolve_in(factory, country: str, subdivision: str | None = None):
    async with factory() as session:
        rows = (await session.execute(select(TaxConfiguration))).scalars().all()
        flat = [row_from_orm(row) for row in rows]
    return resolve(flat, country, subdivision, on_date="2026-08-01")


async def _resolved(factory, subdivision: str):
    return await _resolve_in(factory, "CA", subdivision)


async def _own_rate(factory, **row) -> None:
    """A rate the customer typed in themselves, under their own tax code.

    The install that has gone a year without its provincial rates is the one
    most likely to have filled the gap by hand, so this is the normal state of
    the cohort rather than an exotic one. Dated now, because they added it
    after the upgrade; the reconciler reads only the seeded rows for the date.
    """
    async with factory() as session:
        session.add(
            TaxConfiguration(
                tax_name="Entered by the customer",
                effective_from="2020-01-01",
                effective_to=None,
                tax_type="vat",
                metadata_={},
                **row,
            )
        )
        await session.commit()


def _outcome(report, repair_id: str):
    return next(o for o in report.outcomes if o.repair_id == repair_id)


async def test_a_pre_v15_5_install_is_given_the_provinces_it_never_received(repair_factory) -> None:
    """The whole defect, measured on the cohort that has it.

    Runs the real registry rather than the reconciler alone, because the answer
    a Canadian firm actually sees depends on three repairs landing together:
    the provinces have to arrive, the pre-existing rows have to be labelled,
    and GST has to stop calling itself the whole tax.
    """
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")
    assert await _count(repair_factory) == 70

    before = await _resolved(repair_factory, "CA-BC")
    assert before.combined_rate_pct != "12", (
        "British Columbia already resolves correctly before any repair ran, so this fixture is "
        "not the broken cohort and everything below it would be measuring nothing"
    )

    report = await run_data_repairs(repair_factory)

    reconcile = _outcome(report, REPAIR_ID)
    assert reconcile.status == "applied"
    assert reconcile.rows_changed == 10, f"expected ten missing rates delivered, got {reconcile.rows_changed}"
    assert await _deliveries(repair_factory) == _EXPECTED_DELIVERY

    lines = await _lines(repair_factory)
    for country, code in [
        ("CA", "QST_QC"),
        ("CA", "PST_BC"),
        ("CA", "PST_SK"),
        ("CA", "RST_MB"),
        ("CA", "HST_NB"),
        ("CA", "HST_NL"),
        ("CA", "HST_PE"),
        ("NG", "VAT"),
    ]:
        assert (country, code) in lines, f"{country}/{code} was not delivered"

    after = await _resolved(repair_factory, "CA-BC")
    assert after.status == "stacked"
    assert after.combined_rate_pct == "12", "British Columbia owes 7% provincial on top of 5% federal"

    quebec = await _resolved(repair_factory, "CA-QC")
    assert quebec.combined_rate_pct == "14.975"


async def test_nova_scotia_is_not_this_repairs_to_deliver(repair_factory) -> None:
    """The one shipped rate this repair may not deliver, asserted rather than assumed.

    The 14 % row is a rate that CHANGED, not one that was never delivered: this
    install holds the 15 % window, still open. Handing it the 14 % row without
    closing the 15 % one would leave two rates in force at once - which is not a
    wrong number but a raised ``TaxRuleError``, so the province would stop
    pricing altogether. Closing the old window is a ``superseded`` repair's job
    and ``tax_window_supersede`` now does it.

    That repair running in the same boot is why this one is written against the
    delivery record rather than against the resolved rate. Nova Scotia does end
    up at 14 % on this cohort, and this asserts that the reconciler is not how
    it got there: if ``CA/HST_NS`` ever appears in these deliveries, the
    reconciler has grown a power it was built not to have.
    """
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")
    report = await run_data_repairs(repair_factory)

    deliveries = await _deliveries(repair_factory)
    assert "CA/HST_NS" not in deliveries, "the reconciler delivered a rate line that was already on file"
    assert deliveries == _EXPECTED_DELIVERY
    assert _outcome(report, REPAIR_ID).rows_changed == 10, (
        "the reconciler's own count moved, so it is doing something other than the ten rate lines it owns"
    )

    async with repair_factory() as session:
        windows = (
            await session.execute(
                select(TaxConfiguration.rate_pct, TaxConfiguration.effective_from, TaxConfiguration.effective_to)
                .where(TaxConfiguration.country_code == "CA", TaxConfiguration.tax_code == "HST_NS")
                .order_by(TaxConfiguration.effective_from)
            )
        ).all()
    assert [tuple(row) for row in windows] == [
        ("15.0", "2010-07-01", "2025-03-31"),
        ("14.0", "2025-04-01", None),
    ], "the second Nova Scotia window arrived without the first being closed, or did not arrive at all"


async def test_a_second_boot_delivers_nothing(repair_factory) -> None:
    """Idempotence, as the registry requires it: the second pass is a recorded no-op."""
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")

    first = _outcome(await run_data_repairs(repair_factory), REPAIR_ID)
    assert first.rows_changed == 10
    settled = await _count(repair_factory)

    second = _outcome(await run_data_repairs(repair_factory), REPAIR_ID)
    assert second.status == "clean"
    assert second.rows_changed == 0
    assert await _count(repair_factory) == settled

    async with repair_factory() as session:
        ledger = (
            await session.execute(select(DataRepairLedger).where(DataRepairLedger.repair_id == REPAIR_ID))
        ).scalar_one()
    assert ledger.runs == 2, "the second boot has to be recorded, not skipped"
    assert ledger.rows_changed_total == 10, "the second pass applied something after all"
    assert len(await _deliveries(repair_factory)) == 10, "a delivery was recorded twice"


async def test_a_delivered_rate_the_customer_deletes_stays_deleted(repair_factory) -> None:
    """The failure that would be worse than the defect, driven end to end.

    Without the delivery record the seed timestamp never advances - the rows
    that date it are the old ones, which are still there - so the deleted rate
    is handed back on this boot and on every boot after it, for the life of the
    install.
    """
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")
    assert _outcome(await run_data_repairs(repair_factory), REPAIR_ID).rows_changed == 10

    async with repair_factory() as session:
        await session.execute(
            TaxConfiguration.__table__.delete().where(
                TaxConfiguration.country_code == "CA", TaxConfiguration.tax_code == "QST_QC"
            )
        )
        await session.commit()
    assert ("CA", "QST_QC") not in await _lines(repair_factory)

    again = _outcome(await run_data_repairs(repair_factory), REPAIR_ID)
    assert again.rows_changed == 0, "a rate the customer deleted was handed back"
    assert ("CA", "QST_QC") not in await _lines(repair_factory)

    third = _outcome(await run_data_repairs(repair_factory), REPAIR_ID)
    assert third.rows_changed == 0
    assert ("CA", "QST_QC") not in await _lines(repair_factory)


async def test_a_v15_9_1_install_that_deleted_a_rate_does_not_get_it_back(repair_factory) -> None:
    """The deletion this repair has never seen, and has to refuse on the first boot.

    There is no delivery record here, because this install was seeded with the
    rate rather than given it. All that separates "deleted" from "never
    delivered" is the seed timestamp, and that is exactly the case this repair
    would get wrong if it reasoned from absence alone.
    """
    await _install(repair_factory, v15_9_1(), "2026-08-25")
    async with repair_factory() as session:
        await session.execute(
            TaxConfiguration.__table__.delete().where(
                TaxConfiguration.country_code == "NG", TaxConfiguration.tax_code == "VAT"
            )
        )
        await session.commit()

    report = await run_data_repairs(repair_factory)

    delivered = await _deliveries(repair_factory)
    assert "NG/VAT" not in delivered, "a rate deleted on a modern install was restored"
    assert ("NG", "VAT") not in await _lines(repair_factory)
    # This cohort predates the two Gulf rate lines, so it is owed those and
    # nothing else. Pinned rather than counted, so a future seed row cannot
    # slip in here disguised as one of them.
    assert delivered == {"KW/NONE", "QA/NONE"}
    assert _outcome(report, REPAIR_ID).rows_changed == 2


async def test_a_v15_9_1_install_gets_only_what_shipped_after_it(repair_factory) -> None:
    """A modern cohort takes the lines it predates, and nothing else.

    Eleven of its rows break the subdivision constraint on the way in, which is
    what a database in this state really looks like, and this asserts that the
    reconciler takes no exception to it.

    This test asserted ``rows_changed == 0`` while every shipped line predated
    the cohort. That is a property of where the file happened to be, not of the
    repair, so it is now stated as the delivery set: the Gulf rows shipped
    after v15.9.1 and are owed, and anything else appearing here is the
    reconciler reaching further than it should.
    """
    await _install(repair_factory, v15_9_1(), "2026-08-25")

    async with repair_factory() as session:
        breach = (
            await session.execute(
                select(func.count())
                .select_from(TaxConfiguration)
                .where(
                    TaxConfiguration.combination.in_(("replaces_federal", "stacks_on_federal", "compounds_on_federal")),
                    TaxConfiguration.subdivision_code.is_(None),
                )
            )
        ).scalar_one()
    assert breach == 11, f"expected the eleven unlabelled sub-national rows this cohort really has, found {breach}"

    report = await run_data_repairs(repair_factory)

    assert _outcome(report, REPAIR_ID).status == "applied"
    assert _outcome(report, REPAIR_ID).rows_changed == 2
    assert await _deliveries(repair_factory) == {"KW/NONE", "QA/NONE"}

    async with repair_factory() as session:
        still = (
            await session.execute(
                select(func.count())
                .select_from(TaxConfiguration)
                .where(
                    TaxConfiguration.combination.in_(("replaces_federal", "stacks_on_federal", "compounds_on_federal")),
                    TaxConfiguration.subdivision_code.is_(None),
                )
            )
        ).scalar_one()
    assert still == 0, "the labelling repairs left rows the constraint would refuse to validate"


async def test_a_database_whose_seed_cannot_be_dated_is_given_nothing(repair_factory) -> None:
    """No timestamp, no delivery. The one branch where the repair gives up on purpose."""
    async with repair_factory() as session:
        session.add(
            TaxConfiguration(
                country_code="CA",
                tax_name="A rate somebody added by hand",
                tax_code="LOCAL_LEVY",
                rate_pct="3.0",
                tax_type="sales_tax",
                combination="national",
                subdivision_code=None,
                effective_from="2020-01-01",
                effective_to=None,
                is_default=False,
                metadata_={},
            )
        )
        await session.commit()

    report = await run_data_repairs(repair_factory)

    assert _outcome(report, REPAIR_ID).rows_changed == 0
    assert await _deliveries(repair_factory) == set()
    assert await _count(repair_factory) == 1


async def test_one_rate_re_entered_by_hand_does_not_freeze_the_seed_date(repair_factory) -> None:
    """The seed date is the OLDEST shipped row on file, and this is the cohort that shows why.

    Every other fixture here writes its whole cohort at one instant, which is
    what a real seed transaction does, so oldest and newest are the same number
    and neither is under test. This install is the one where they differ: the
    customer removed a shipped rate and put it back, which the product lets
    them do, and one shipped rate line now carries today's date.

    Reading the newest would take that one row for the seed, date this install
    to today, and conclude that every rate added since is absent because
    somebody removed it. The install would be refused all ten of the rates it
    is owed, for good, on the evidence of a row that has nothing to do with any
    of them. The oldest surviving shipped row is the seeder's own and it still
    says June.
    """
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")

    now = datetime.now(UTC)
    async with repair_factory() as session:
        row = (
            await session.execute(
                select(TaxConfiguration).where(
                    TaxConfiguration.country_code == "DE", TaxConfiguration.tax_code == "VAT"
                )
            )
        ).scalar_one()
        carried = {field: getattr(row, field) for field in _FIELDS}
        carried["combination"] = row.combination
        await session.delete(row)
        await session.flush()
        session.add(
            TaxConfiguration(
                tax_name="Re-entered by the customer",
                subdivision_code=None,
                metadata_={},
                created_at=now,
                updated_at=now,
                **carried,
            )
        )
        await session.commit()

    async with repair_factory() as session:
        stamps = (
            (await session.execute(select(TaxConfiguration.created_at).where(TaxConfiguration.tax_code == "VAT")))
            .scalars()
            .all()
        )
    assert max(stamps) > min(stamps), (
        "the fixture did not move a shipped row's timestamp, so oldest and newest are still the "
        "same number here and this test cannot tell the two readings apart"
    )

    report = await run_data_repairs(repair_factory)

    assert _outcome(report, REPAIR_ID).rows_changed == 10, (
        "one shipped rate re-entered by hand withheld every rate this install was owed"
    )
    assert await _deliveries(repair_factory) == _EXPECTED_DELIVERY


async def test_a_country_that_typed_in_its_own_rate_is_not_given_a_second_one(repair_factory) -> None:
    """The failure that is worse than the defect: a country that stops pricing.

    Nigeria's rate reaches the seed file in v15.6.0, so a pre-v15.5.0 install
    has none and the Nigerian customer has to enter their own. Their tax code
    is theirs, so the shipped rate line reads as absent and everything else
    about this install says the rate was never delivered - which is true, and
    still the wrong reason to deliver it. Two country-wide rows, both claiming
    to be the standard one, and the resolver refuses to name a rate at all.

    So the assertion that matters is not that the row stayed out of the table.
    It is that Nigeria still answers, and answers with their number.
    """
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")
    await _own_rate(
        repair_factory,
        country_code="NG",
        tax_code="VAT_NG",
        rate_pct="5.0",
        combination="national",
        subdivision_code=None,
        is_default=True,
    )

    before = await _resolve_in(repair_factory, "NG")
    assert before.resolved and before.combined_rate_pct == "5", (
        "Nigeria does not price before the repair ran, so this fixture cannot show the repair taking an answer away"
    )

    report = await run_data_repairs(repair_factory)

    # The harm first, deliberately. A membership assertion above these would
    # fail before they ran, and this test would then be evidence that a row
    # stayed out of a table rather than evidence that a country can still
    # price - which is the claim being made.
    after = await _resolve_in(repair_factory, "NG")
    assert after.resolved, f"the repair left Nigeria unable to price at all ({after.status}: {after.reason})"
    assert after.combined_rate_pct == "5", "Nigeria is charging something other than the rate its owner entered"

    assert "NG/VAT" not in await _deliveries(repair_factory), (
        "the shipped Nigerian rate was recorded as delivered, so it will never be reconsidered "
        "even if the customer removes the rate it collided with"
    )
    assert ("NG", "VAT") not in await _lines(repair_factory)

    assert _outcome(report, REPAIR_ID).rows_changed == 9, (
        "one country holding its own rate must not withhold the other seven rate lines"
    )


async def test_a_province_that_has_a_hand_entered_rate_is_not_charged_twice(repair_factory) -> None:
    """The same collision one level down, where it is arithmetic rather than a refusal.

    A second provincial rate for one province does not read as ambiguous to
    anything. Both rows are valid, both stack on the federal layer, and British
    Columbia quietly starts charging fourteen points of provincial tax instead
    of seven. Nothing in the table looks wrong, which is why the guard has to
    be in the repair rather than in a constraint.
    """
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")
    await _own_rate(
        repair_factory,
        country_code="CA",
        tax_code="BC_PST_ENTERED",
        rate_pct="7.0",
        combination="stacks_on_federal",
        subdivision_code="CA-BC",
        is_default=False,
    )

    report = await run_data_repairs(repair_factory)

    # The rate before the membership, for the reason given in the test above.
    bc = await _resolve_in(repair_factory, "CA", "CA-BC")
    assert bc.combined_rate_pct == "12", (
        f"British Columbia resolves at {bc.combined_rate_pct}% rather than 12%, so the shipped "
        "provincial rate was charged on top of the one already on file"
    )

    assert "CA/PST_BC" not in await _deliveries(repair_factory)
    assert ("CA", "PST_BC") not in await _lines(repair_factory)

    quebec = await _resolve_in(repair_factory, "CA", "CA-QC")
    assert quebec.combined_rate_pct == "14.975", "one province holding its own rate withheld the others"
    assert _outcome(report, REPAIR_ID).rows_changed == 9


async def test_the_reconciler_adds_rows_and_edits_none(repair_factory) -> None:
    """The declared nature, held against the repair's real effect on the table."""
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")

    repair = next(r for r in discover_data_repairs() if r.repair_id == REPAIR_ID)
    assert repair.nature == "never_delivered"

    async with repair_factory() as session:
        before = await snapshot_table(session, _TAX_TABLE)
    await run_data_repairs(repair_factory, repairs=(repair,))
    async with repair_factory() as session:
        after = await snapshot_table(session, _TAX_TABLE)

    assert len(after) == len(before) + 10, "the pass under test did not deliver, so the check below is vacuous"
    assert verify_additive_shape(repair, before, after) == ()


async def test_every_never_delivered_repair_adds_rows_and_edits_none(repair_factory) -> None:
    """The whole-registry contract, so a future additive repair is held to it too."""
    additive = [r for r in discover_data_repairs() if r.nature == "never_delivered"]
    assert additive, "no never_delivered repair registered - this check would be vacuous"

    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")

    for repair in additive:
        assert repair.never_delivered is not None
        table = repair.never_delivered.table
        async with repair_factory() as session:
            before = await snapshot_table(session, table)
        await run_data_repairs(repair_factory, repairs=(repair,))
        async with repair_factory() as session:
            after = await snapshot_table(session, table)
        assert verify_additive_shape(repair, before, after) == (), f"{repair.repair_id} broke the additive contract"

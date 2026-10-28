# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Nova Scotia's rate cut, against the install that never received it.

What is under test
------------------
``tax_window_supersede`` closes a shipped tax window an old install still holds
open and inserts the rate that replaced it. The live case is Nova Scotia, which
cut its harmonised rate from 15 % to 14 % on 2025-04-01: the seed file carries
both windows, an install seeded before v15.5.0 holds only the 15 % one, and
until this repair existed it went on charging 15 % for ever while
``/api/health`` reported a clean boot.

Where the cohorts come from
---------------------------
From ``test_tax_seed_reconcile``, deliberately, rather than rebuilt here. Those
fixtures reconstruct the seed files two releases actually shipped and carry a
digest of the real file so the reconstruction cannot drift, and a second
hand-written copy of a database state is the thing that quietly stops matching
the one customers have. The important property for this file is in
``_RESTORED_TO_V15_4_0``: it puts Nova Scotia's 15 % window back to open, which
is the entire defect.

What every assertion here is written against
--------------------------------------------
The resolved rate, through ``resolve``, rather than the column the repair
wrote. Which column a repair writes says nothing about what a Canadian firm is
charged - the two questions came apart on this table once already - so the
claim being made is "Nova Scotia is billed 14 %", and that is what is asserted.
Ontario is carried through every whole-registry test as a control: same
country, same ``replaces_federal`` class, the same ``effective_from`` as Nova
Scotia's old window, one window only. A predicate that closed windows on
anything broader than the rate line moves it.

Why the row counts are taken per line
-------------------------------------
This file counted ``DataRepairOutcome.rows_changed``, the run's own total, and
that stopped being a statement about Nova Scotia when Israel entered the
repair's derived population - see ``_LINE_UNDER_TEST``. The counts are taken on
the rate line under test now. The rule is the same one the paragraph above
states: assert the claim the test's name makes, not the nearest number the
machinery happens to expose.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.data_repairs import discover_data_repairs, run_data_repairs, snapshot_table, verify_supersede_shape
from app.modules.i18n_foundation.models import TaxConfiguration
from app.modules.i18n_foundation.seed import load_tax_seed_rows, tax_configuration_from_seed_row
from app.modules.i18n_foundation.tax_rules import TaxRuleError, resolve, row_from_orm
from app.modules.i18n_foundation.tax_window_supersede import REPAIR_ID
from tests.pg.test_tax_seed_reconcile import (  # noqa: F401 - repair_factory is a fixture used by name
    _install,
    _outcome,
    _own_rate,
    pre_v15_5_0,
    repair_factory,
    v15_9_1,
)

pytestmark = pytest.mark.asyncio

_TAX_TABLE = "oe_i18n_tax_config"

#: The day before Nova Scotia's cut and the day of it. Every money claim in
#: this file is made on one of these two dates, because "the old rate is kept
#: for work priced under it" is a statement about a boundary and nowhere else.
_LAST_DAY_AT_FIFTEEN = "2025-03-31"
_FIRST_DAY_AT_FOURTEEN = "2025-04-01"

#: Well after both windows open, so "what is billed today" is unambiguous.
_TODAY_IN_THE_FIXTURES = "2026-08-01"


def _repair():
    return next(r for r in discover_data_repairs() if r.repair_id == REPAIR_ID)


def _the_repairs_that_shipped_before_this_one() -> tuple:
    """Every registered repair except this one.

    The "before" state a Canadian firm is actually in is not the raw cohort.
    On that, every row reads ``national`` with no province, so Canada resolves
    to nothing at all for every province - the labelling repairs are what turn
    it back into a country that prices, and they have been shipping for
    releases. Nova Scotia only resolves at 15 % once they have run, so that is
    the state this repair has to be measured against. Measuring against the raw
    cohort would let a repair that did nothing look like it had moved a rate
    off zero.
    """
    return tuple(r for r in discover_data_repairs() if r.repair_id != REPAIR_ID)


async def _flat(factory) -> list:
    async with factory() as session:
        rows = (await session.execute(select(TaxConfiguration))).scalars().all()
        return [row_from_orm(row) for row in rows]


async def _rate(factory, subdivision: str | None, on_date: str = _TODAY_IN_THE_FIXTURES) -> str | None:
    """What one jurisdiction is billed, through the product's own resolver."""
    outcome = resolve(await _flat(factory), "CA", subdivision, on_date=on_date)
    return outcome.combined_rate_pct


async def _windows(factory, tax_code: str) -> list[tuple[str, str | None, str | None]]:
    async with factory() as session:
        rows = (
            await session.execute(
                select(
                    TaxConfiguration.rate_pct,
                    TaxConfiguration.effective_from,
                    TaxConfiguration.effective_to,
                )
                .where(TaxConfiguration.country_code == "CA", TaxConfiguration.tax_code == tax_code)
                .order_by(TaxConfiguration.effective_from)
            )
        ).all()
    return [tuple(row) for row in rows]


async def _il_windows(factory) -> list[tuple[str, str | None, str | None]]:
    """Israel's VAT windows, the second line in this repair's population.

    Read here only where a test needs to show that the same pass acted on the
    line it was stranded on while leaving Nova Scotia alone. Israel's own
    behaviour is not otherwise this file's subject.
    """
    async with factory() as session:
        rows = (
            await session.execute(
                select(
                    TaxConfiguration.rate_pct,
                    TaxConfiguration.effective_from,
                    TaxConfiguration.effective_to,
                )
                .where(TaxConfiguration.country_code == "IL", TaxConfiguration.tax_code == "VAT")
                .order_by(TaxConfiguration.effective_from)
            )
        ).all()
    return [tuple(row) for row in rows]


async def _count(factory) -> int:
    async with factory() as session:
        return (await session.execute(select(func.count()).select_from(TaxConfiguration))).scalar_one()


async def _edit_nova_scotia(factory, **values) -> None:
    """Change the shipped Nova Scotia row, the way an operator would have."""
    async with factory() as session:
        await session.execute(
            TaxConfiguration.__table__.update()
            .where(TaxConfiguration.country_code == "CA", TaxConfiguration.tax_code == "HST_NS")
            .values(**values)
        )
        await session.commit()


#: The rate line every claim in this file is about.
#:
#: Counting on the line rather than on the run is not tidiness, it is the
#: instrument being wrong. The repair derives its population from the seed file
#: instead of naming a country, and that population has grown: it carries
#: ``IL/VAT`` as well now, because Israel raised standard VAT from 17 % to 18 %
#: on 2025-01-01 and both cohorts below hold the 17 % window open exactly as
#: they hold Nova Scotia's. So a pass over either cohort closes two windows and
#: inserts two rates, and ``DataRepairOutcome.rows_changed`` counts all four.
#:
#: That number is correct and it is pinned where it belongs, in
#: ``tests/unit/test_tax_window_supersede_population.py``. It is simply not a
#: statement about Nova Scotia any more. Asserted as a total, a test named
#: "left alone" would have had to claim ``rows_changed == 2``, and the two rows
#: it was counting would have belonged to a country the test never mentions.
#: Counted on the line, every number below says what its test name says, and
#: the next country to enter the population changes none of them.
_LINE_UNDER_TEST = "HST_NS"


async def _snapshot(factory) -> dict[str, dict]:
    async with factory() as session:
        return await snapshot_table(session, _TAX_TABLE)


def _written_on(before: dict, after: dict, tax_code: str = _LINE_UNDER_TEST) -> int:
    """How many rows of one rate line a pass closed or inserted.

    Counted as those two operations specifically rather than as "any row that
    differs", and the difference matters on every whole-registry test here. The
    labelling repairs run in the same boot and write ``combination`` and
    ``subdivision_code`` onto this very row, so a plain before-and-after
    comparison reports their work as this repair's and a test asserting that
    Nova Scotia was left alone fails while Nova Scotia was left alone.

    Closing and inserting are also exactly what a ``superseded`` repair is
    permitted to do, so this counts the contract rather than a proxy for it: a
    window whose ``effective_to`` went from empty to set, and a row of the line
    that was not there before.
    """
    written = 0
    for key, row in after.items():
        if row.get("tax_code") != tax_code:
            continue
        was = before.get(key)
        if was is None:
            written += 1  # inserted
        elif was.get("effective_to") is None and row.get("effective_to") is not None:
            written += 1  # closed
    return written


async def _run(factory, repairs: tuple | None = None) -> tuple:
    """Run the registry, or one repair, and report both what it says and what it did here.

    Returns ``(outcome, rows written on the line under test)``. The snapshot is
    taken inside, immediately around the run, so a test that arranges its
    fixture first - an edited row, a hand-entered rate, an earlier pass of the
    repairs that shipped before this one - never has that setup counted as the
    repair's work.
    """
    before = await _snapshot(factory)
    report = await run_data_repairs(factory, repairs=repairs)
    after = await _snapshot(factory)
    return _outcome(report, REPAIR_ID), _written_on(before, after)


# ── The defect, and the fix ──────────────────────────────────────────────────


async def test_a_pre_v15_5_install_starts_charging_what_nova_scotia_actually_charges(repair_factory) -> None:
    """The whole defect and the whole fix, in the units the money is in.

    Run through the real registry rather than this repair alone, because the
    boot a customer gets runs all five and the answer they see is the one that
    comes out of the lot of them together.
    """
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")
    await run_data_repairs(repair_factory, repairs=_the_repairs_that_shipped_before_this_one())

    before = await _rate(repair_factory, "CA-NS")
    assert before == "15", (
        f"Nova Scotia already bills {before} with only the repairs that shipped before this one, so "
        "this fixture is not the broken cohort and everything below it would be measuring nothing"
    )
    control_before = await _rate(repair_factory, "CA-ON")
    assert control_before == "13"

    outcome, written = await _run(repair_factory)

    assert outcome.status == "applied", f"the repair did nothing: {outcome}"
    assert written == 2, f"expected Nova Scotia's window closed and its replacement added, got {written} rows"

    assert await _rate(repair_factory, "CA-NS") == "14", "Nova Scotia is still billed its superseded rate"

    control_after = await _rate(repair_factory, "CA-ON")
    assert control_after == "13", f"Ontario moved to {control_after}; the repair closed a window it does not own"
    assert await _windows(repair_factory, "HST_ON") == [("13.0", "2010-07-01", None)], (
        "Ontario's window was closed - it ships one window, so nothing here has any business ending it"
    )


async def test_work_priced_before_the_cut_still_resolves_at_the_old_rate(repair_factory) -> None:
    """Close-and-add, asserted where it actually matters: either side of the boundary.

    This is the reason the 15 % row is closed rather than edited to say 14. An
    estimate or an invoice priced in March 2025 has to keep the rate it was
    priced at, and a repair that rewrote the rate in place would change the
    value of a document already sent to a customer, months later, silently.
    """
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")
    await run_data_repairs(repair_factory)

    assert await _rate(repair_factory, "CA-NS", _LAST_DAY_AT_FIFTEEN) == "15", (
        "a document priced on the last day of the old rate no longer resolves at 15%"
    )
    assert await _rate(repair_factory, "CA-NS", _FIRST_DAY_AT_FOURTEEN) == "14", (
        "the new rate is not in force on the day it took effect"
    )

    assert await _windows(repair_factory, "HST_NS") == [
        ("15.0", "2010-07-01", _LAST_DAY_AT_FIFTEEN),
        ("14.0", _FIRST_DAY_AT_FOURTEEN, None),
    ]


async def test_a_second_boot_changes_nothing(repair_factory) -> None:
    """Idempotence, as the registry requires it."""
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")

    _, written = await _run(repair_factory)
    assert written == 2
    settled_windows = await _windows(repair_factory, "HST_NS")
    settled_count = await _count(repair_factory)

    second = _outcome(await run_data_repairs(repair_factory), REPAIR_ID)

    # Deliberately the whole run rather than one line. Idempotence is a claim
    # about the repair, not about Nova Scotia: every line it touched on the
    # first boot has to be settled, so a second boot that moved any of them -
    # Israel's included - is a bug this test exists to catch.
    assert second.status == "clean"
    assert second.rows_changed == 0
    assert await _windows(repair_factory, "HST_NS") == settled_windows, "the second boot rewrote the windows"
    assert await _count(repair_factory) == settled_count, "the second boot inserted the replacement rate again"
    assert await _rate(repair_factory, "CA-NS") == "14"


async def test_the_repair_closes_and_adds_rather_than_rewriting(repair_factory) -> None:
    """The declared nature, held against the repair's real effect on the table.

    The length assertion is not decoration. ``verify_supersede_shape`` returns
    no violations for a repair that did nothing at all, so without proof that
    this pass actually wrote something the contract check below is vacuous.
    """
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")

    repair = _repair()
    assert repair.nature == "superseded"

    async with repair_factory() as session:
        before = await snapshot_table(session, _TAX_TABLE)
    await run_data_repairs(repair_factory, repairs=(repair,))
    async with repair_factory() as session:
        after = await snapshot_table(session, _TAX_TABLE)

    assert _written_on(before, after) == 2, (
        "the pass under test did not close Nova Scotia's window and insert its replacement, so the "
        "contract check below would hold over a repair that did nothing"
    )
    # The contract itself is checked over the whole table, not one line: a
    # superseded repair may not delete or rewrite anything anywhere, and
    # narrowing this to Nova Scotia would stop it noticing damage elsewhere.
    assert verify_supersede_shape(repair, before, after) == ()


async def test_the_old_row_is_not_labelled_yet_and_is_carried_forward_anyway(repair_factory) -> None:
    """Run alone, against rows the sibling repairs have not reached yet.

    A database seeded before v15.7.0 carries no subdivision on any row and the
    boot heal has filled ``combination`` with its server default, so the Nova
    Scotia row reads ``national`` with no province until
    ``tax_subdivision_backfill`` gets to it. Two things are being measured.

    That the predicate does not depend on which repair the registry happens to
    run first - the module warns about exactly that class of bug, and an
    ordering dependency here would be a repair that works today and quietly
    stops working when somebody reorders a file.

    And that the ``UPDATE`` lands at all. The heal adds the subdivision check
    constraint ``NOT VALID``, which exempts rows already on file but never a
    statement, so writing to one of the rows it exempts is the trap this table
    has sprung before. ``national`` with no subdivision satisfies the
    constraint; a row the heal had left in the other broken shape would not.
    """
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")

    async with repair_factory() as session:
        shape = (
            await session.execute(
                select(TaxConfiguration.combination, TaxConfiguration.subdivision_code).where(
                    TaxConfiguration.country_code == "CA", TaxConfiguration.tax_code == "HST_NS"
                )
            )
        ).one()
    assert shape == ("national", None), (
        f"Nova Scotia's row is already labelled {shape} in this fixture, so running without the "
        "labelling repair proves nothing about the cohort that has not had it"
    )

    outcome, written = await _run(repair_factory, repairs=(_repair(),))

    assert outcome.status == "applied", f"the unlabelled row was not carried forward: {outcome}"
    assert written == 2
    assert await _rate(repair_factory, "CA-NS") == "14"
    # Ontario is checked as a row rather than as a rate here, because on a
    # cohort the labelling repairs have not reached no Canadian province
    # resolves to anything at all - which is the other defect, not this one.
    assert await _windows(repair_factory, "HST_ON") == [("13.0", "2010-07-01", None)], (
        "Ontario's window was closed while this repair ran on its own"
    )


async def test_a_line_already_carrying_both_windows_is_left_alone(repair_factory) -> None:
    """A rate line seeded with both windows must come out of the pass untouched.

    The v15.9.1 cohort is the control for Nova Scotia and the cohort for
    Israel at the same time, because that release shipped Nova Scotia's cut and
    predates Israel's rise. That makes it a sharper test than it was when it
    only said "a modern install is left alone": one pass, over one database,
    which has to close the line that is stranded and leave alone the line that
    is not. A predicate keyed on anything broader than the rate line - the
    country, the tax type, "any open window" - passes the old version of this
    test and fails this one.
    """
    await _install(repair_factory, v15_9_1(), "2026-08-25")
    before = await _windows(repair_factory, "HST_NS")
    assert len(before) == 2, "this cohort does not already carry both windows, so it is the wrong control"

    outcome, written = await _run(repair_factory)

    assert written == 0, "a line that already held both windows was written to"
    assert await _windows(repair_factory, "HST_NS") == before
    assert await _rate(repair_factory, "CA-NS") == "14"

    # And the same pass did do its job on the line this cohort really is
    # stranded on, so the zero above is a predicate that discriminates rather
    # than a repair that did nothing at all.
    assert outcome.status == "applied", f"the pass did nothing anywhere, so the control proves nothing: {outcome}"
    assert await _il_windows(repair_factory) == [
        ("17.0", "2015-10-01", "2024-12-31"),
        ("18.0", "2025-01-01", None),
    ]


# ── The rows this repair must not touch ──────────────────────────────────────


async def test_a_rate_somebody_edited_is_left_alone(repair_factory) -> None:
    """A row that does not say what the seeder wrote is a row somebody manages themselves."""
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")
    await _edit_nova_scotia(repair_factory, rate_pct="15.5")

    _, written = await _run(repair_factory)

    assert written == 0, "a rate the operator set was superseded by the shipped one"
    assert await _windows(repair_factory, "HST_NS") == [("15.5", "2010-07-01", None)]
    assert await _rate(repair_factory, "CA-NS") == "15.5", "Nova Scotia stopped charging the rate its owner set"


async def test_a_window_somebody_re_dated_is_left_alone(repair_factory) -> None:
    """The other half of the same predicate, and it fails differently.

    A row carrying our rate but somebody else's start date is a window they
    decided the shape of. Matching on the rate alone would close it on our
    date and take the difference away from every document priced in between.
    """
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")
    await _edit_nova_scotia(repair_factory, effective_from="2011-04-01")

    _, written = await _run(repair_factory)

    assert written == 0, "a window the operator re-dated was closed on the shipped date"
    assert await _windows(repair_factory, "HST_NS") == [("15.0", "2011-04-01", None)]
    assert await _rate(repair_factory, "CA-NS") == "15"


async def test_a_window_flagged_as_the_default_is_left_alone(repair_factory) -> None:
    """``is_default`` is part of the predicate rather than something this may move.

    Romania's repair permits itself to take the flag off the row it closes, and
    declares that allowance so the contract test can see it. This one does not,
    and no line in its population needs it to: Nova Scotia ships both windows
    unflagged because a provincial row is never the country default, and Israel
    ships both flagged because its two windows are consecutive periods of one
    national standard rate. Either way the flag sits still, so an allowance to
    move it would be an unexercised hole in the close-and-add contract, which is
    worth less than nothing. A row whose flag differs from the shipped window is
    simply not the row we shipped.

    Note which direction this test perturbs in. Nova Scotia's shipped flag is
    false, so setting it true is the edit that makes the row somebody else's.
    The equivalent edit on the Israeli line would be the opposite one, which is
    why the predicate compares the flag rather than requiring any fixed value.
    """
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")
    await _edit_nova_scotia(repair_factory, is_default=True)

    _, written = await _run(repair_factory)

    assert written == 0, "a row carrying a flag the seeder never wrote was rewritten"
    assert await _windows(repair_factory, "HST_NS") == [("15.0", "2010-07-01", None)]


async def test_a_rate_moved_to_another_province_is_left_alone(repair_factory) -> None:
    """The clobber a predicate keyed only on the rate line would not see.

    ``tax_subdivision_repair`` says in as many words that an operator who moved
    a rate to a different province keeps what they set. If this repair ignored
    ``subdivision_code`` it would close that row on Nova Scotia's date and hand
    Nova Scotia a rate, and the province they had actually moved it to would
    lose its rate altogether - additive on the table, destructive on the answer,
    and nothing in the row would look wrong afterwards.

    Run alone: the reconciler delivers Prince Edward Island to this cohort in
    the same boot, which would put a second harmonised rate in the province and
    change what is being measured.
    """
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")
    # Both halves together - the table's check constraint holds them to be one
    # statement, so a province cannot be written without the combination.
    await _edit_nova_scotia(repair_factory, subdivision_code="CA-PE", combination="replaces_federal")

    assert await _rate(repair_factory, "CA-PE") == "15", "the fixture did not move the rate to another province"

    _, written = await _run(repair_factory, repairs=(_repair(),))

    assert written == 0, "a rate the operator moved to another province was closed"
    assert await _rate(repair_factory, "CA-PE") == "15", "Prince Edward Island lost the rate it had been given"
    assert await _windows(repair_factory, "HST_NS") == [("15.0", "2010-07-01", None)]


async def test_a_province_that_has_a_hand_entered_harmonised_rate_is_left_alone(repair_factory) -> None:
    """The install most likely to hold its own Nova Scotia rate is this repair's own cohort.

    A province that has been billed the wrong rate for a year is one somebody
    may well have corrected by hand, under their own tax code. Two rates each
    replacing the federal one in one province is not a wrong number: ``resolve``
    raises, and the province stops pricing at all. It does so before this repair
    runs and it would do so afterwards, so applying would edit their data and
    buy nothing.

    Two things are asserted, and the second is the one that is easy to miss.
    The repair leaves the rows alone, and it does not come back ``failed`` - a
    guard that let the resolver's exception out would turn an install this
    repair had already decided not to touch into a red health check on every
    boot for the life of the install.

    That second claim is asserted as "not failed" rather than as ``clean``
    because the pass legitimately applies elsewhere: the same cohort is
    stranded on the Israeli window, which this repair closes in the same run.
    ``clean`` would be asserting that the repair did nothing anywhere, which is
    a statement about the population rather than about the guard.
    """
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")
    # In the order it really happens: the install has been booting the shipped
    # repairs for releases, and at some point somebody typed the correct rate in
    # themselves because ours still said 15.
    await run_data_repairs(repair_factory, repairs=_the_repairs_that_shipped_before_this_one())
    await _own_rate(
        repair_factory,
        country_code="CA",
        tax_code="NS_HST_ENTERED",
        rate_pct="14.0",
        combination="replaces_federal",
        subdivision_code="CA-NS",
        is_default=False,
    )

    with pytest.raises(TaxRuleError):
        resolve(await _flat(repair_factory), "CA", "CA-NS", on_date=_TODAY_IN_THE_FIXTURES)

    outcome, written = await _run(repair_factory, repairs=(_repair(),))

    assert outcome.status != "failed", f"the repair failed the boot instead of declining the install: {outcome}"
    assert outcome.error is None, outcome.error
    assert written == 0
    assert await _windows(repair_factory, "HST_NS") == [("15.0", "2010-07-01", None)], (
        "the shipped window was closed beside a rate the customer had entered themselves"
    )
    assert await _rate(repair_factory, "CA-ON") == "13", "one province holding its own rate disturbed another"


async def test_a_half_applied_install_is_finished_rather_than_left_broken(repair_factory) -> None:
    """The replacement already on file, beside a predecessor nobody closed.

    Reachable on any install where somebody added the correct rate by hand
    under our own tax code and did not know to end the old window. Nova Scotia
    then holds two rates that each replace the federal one and cannot price at
    all - so this is not a database to leave alone, it is one where closing the
    old window on its own is the entire remaining repair.

    Written because the first version of this module skipped the line whenever
    it had nothing to insert, on the reasoning that closing without replacing
    takes a rate away. That reasoning is only right when there is no
    replacement, and here there is one.
    """
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")
    await run_data_repairs(repair_factory, repairs=_the_repairs_that_shipped_before_this_one())
    async with repair_factory() as session:
        session.add(
            tax_configuration_from_seed_row(
                next(
                    row
                    for row in load_tax_seed_rows()
                    if row["country_code"] == "CA" and row["tax_code"] == "HST_NS" and row["rate_pct"] == "14.0"
                )
            )
        )
        await session.commit()

    with pytest.raises(TaxRuleError):
        resolve(await _flat(repair_factory), "CA", "CA-NS", on_date=_TODAY_IN_THE_FIXTURES)

    _, written = await _run(repair_factory, repairs=(_repair(),))

    assert written == 1, f"expected the old window closed and nothing inserted, got {written} rows written"
    assert await _rate(repair_factory, "CA-NS") == "14", "Nova Scotia still cannot price"
    assert await _windows(repair_factory, "HST_NS") == [
        ("15.0", "2010-07-01", _LAST_DAY_AT_FIFTEEN),
        ("14.0", _FIRST_DAY_AT_FOURTEEN, None),
    ]
    assert await _rate(repair_factory, "CA-NS", _LAST_DAY_AT_FIFTEEN) == "15"


async def test_a_database_with_no_nova_scotia_row_is_given_nothing(repair_factory) -> None:
    """A rate line that is absent belongs to the reconciler, not to this repair.

    Deleting the rate is how an operator says they do not want it. There is no
    window to close, and inserting the replacement on its own would resurrect a
    line they removed - which this repair, having no delivery record of its
    own, could never stop doing again on the next boot.
    """
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")
    async with repair_factory() as session:
        await session.execute(
            TaxConfiguration.__table__.delete().where(
                TaxConfiguration.country_code == "CA", TaxConfiguration.tax_code == "HST_NS"
            )
        )
        await session.commit()

    _, written = await _run(repair_factory, repairs=(_repair(),))

    assert written == 0
    assert await _windows(repair_factory, "HST_NS") == [], "a rate line the operator removed was recreated"


async def test_two_rows_that_both_look_like_the_shipped_window_are_left_alone(repair_factory) -> None:
    """Which of two identical rows the seeder wrote cannot be told, so neither is closed.

    Reachable on a database where somebody duplicated the row rather than
    editing it. Closing one would leave the other open and Nova Scotia with two
    rates in force; closing both would be a decision about a row this repair has
    no evidence about.
    """
    await _install(repair_factory, pre_v15_5_0(), "2026-06-01")
    async with repair_factory() as session:
        original = (
            await session.execute(
                select(TaxConfiguration).where(
                    TaxConfiguration.country_code == "CA", TaxConfiguration.tax_code == "HST_NS"
                )
            )
        ).scalar_one()
        session.add(
            TaxConfiguration(
                country_code=original.country_code,
                tax_name=original.tax_name,
                tax_code=original.tax_code,
                rate_pct=original.rate_pct,
                tax_type=original.tax_type,
                combination=original.combination,
                subdivision_code=original.subdivision_code,
                effective_from=original.effective_from,
                effective_to=original.effective_to,
                is_default=original.is_default,
                metadata_={},
            )
        )
        await session.commit()
    assert len(await _windows(repair_factory, "HST_NS")) == 2

    _, written = await _run(repair_factory, repairs=(_repair(),))

    assert written == 0
    assert await _windows(repair_factory, "HST_NS") == [
        ("15.0", "2010-07-01", None),
        ("15.0", "2010-07-01", None),
    ]

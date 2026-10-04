# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Boot-path data repairs owned by the i18n foundation module.

Imported by :func:`app.core.data_repairs.discover_data_repairs`, which is what
makes the registrations below take effect.

Five of the seven repairs here touch ``oe_i18n_tax_config``, and between them
they use every nature the registry has. That is the useful thing about having
them side by side: the two tax rate ones may not rewrite a value, the two that
describe a rate's scope must, and the reconciler may not write to an existing
row at all.

The other two are on ``oe_i18n_work_calendar`` and are worth reading as a pair,
because they are the two halves of one table's trouble and they are allowed
opposite things. ``work_calendar_iso_zero`` corrects a row that is here and
says something impossible; ``work_calendar_seed_reconcile`` delivers a row that
is not here at all and may not touch an existing one. The first is the same
defect as the tax scope repairs - a value that was never right - and the second
is the same defect as the tax reconciler,
which is why it sits with them rather than in a file of its own. The seeder
fills ``oe_i18n_work_calendar`` only while it is empty too, and the shipped file
has grown six countries since - so an install seeded before them answers a
confident Monday-to-Friday week for Qatar, Kuwait, Bahrain and Oman, which is a
wrong date on every schedule drawn there rather than a missing one.

The last two are also the same defect seen from its two ends.
``v3302_tax_combination`` backfilled ``combination`` on thirteen Canadian and
United States rows, and that backfill never runs on the boot path, so an
upgraded install has all thirteen sitting on the column's server default. Eleven
of them are sub-national and are repaired by the subdivision entry, which has to
write ``combination`` anyway to satisfy the table's check constraint - ten
``(country, tax_code)`` pairs, one of which matches two rows because Nova Scotia
ships its superseded 14 % rate as well. The other two are the country-wide
federal layers, they break no constraint, and nothing reached them at all until
``tax_federal_scope`` was added.

``tax_seed_reconcile`` is a different defect that lands on the same table and it
is worth not confusing them. The three above repair rows that are here and say
the wrong thing. That one is about rows that are not here at all, because the
seeder fills the table only while it is empty and the shipped file has grown
eleven rates since. Eight of them are Canadian provinces, so an install seeded
before v15.5.0 answers ``subdivision_unknown`` for most of Canada no matter how
completely the three above do their work.

``tax_window_supersede`` is the last third of that same early return, and the
one the reconciler is forbidden to cover. A rate line an old install already
holds cannot be handed a second window by an additive repair, because the two
would then be in force at once; the line has to be carried forward, which means
closing what is open as the replacement goes in. Nova Scotia is why it exists
and Romania is the shape it copies, the difference between them being that this
one derives its population from the shipped file rather than naming a country,
so the next rate change is caught by a failing test rather than by nobody.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.data_repairs import (
    DataRepair,
    NeverDelivered,
    SupersededBy,
    register_data_repair,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

#: The table the five tax repairs below rewrite.
TAX_CONFIG_TABLE = "oe_i18n_tax_config"

#: The table the work calendar reconciler adds to. It never rewrites it.
WORK_CALENDAR_TABLE = "oe_i18n_work_calendar"


async def _run_romania_vat(session: AsyncSession) -> int:
    """Close Romania's 19 % VAT row and add the 21 % standard and 11 % reduced rates."""
    from app.modules.i18n_foundation.romania_vat import repair_romanian_vat_rates

    return await repair_romanian_vat_rates(session)


async def _run_tax_subdivision(session: AsyncSession) -> int:
    """Label the shipped Canadian and US tax rows with the subdivision they apply in."""
    from app.modules.i18n_foundation.tax_subdivision_repair import repair_tax_subdivisions

    return await repair_tax_subdivisions(session)


async def _run_tax_federal_scope(session: AsyncSession) -> int:
    """Say that the shipped Canadian and US country-wide rows are federal layers."""
    from app.modules.i18n_foundation.tax_federal_scope_repair import repair_federal_tax_scope

    return await repair_federal_tax_scope(session)


async def _run_tax_seed_reconcile(session: AsyncSession) -> int:
    """Deliver the shipped tax rates added to the seed file after this install was seeded."""
    from app.modules.i18n_foundation.tax_seed_reconcile import reconcile_shipped_tax_rows

    return await reconcile_shipped_tax_rows(session)


async def _run_work_calendar_seed_reconcile(session: AsyncSession) -> int:
    """Deliver the shipped work calendars added to the seed file after this install was seeded."""
    from app.modules.i18n_foundation.work_calendar_seed_reconcile import reconcile_shipped_work_calendars

    return await reconcile_shipped_work_calendars(session)


async def _run_work_calendar_iso_zero(session: AsyncSession) -> int:
    """Correct a work calendar whose week was written on the Monday-zero axis."""
    from app.modules.i18n_foundation.work_calendar_iso_zero import repair_iso_zero_weeks

    return await repair_iso_zero_weeks(session)


async def _run_tax_window_supersede(session: AsyncSession) -> int:
    """Close a shipped tax window this install still holds open and add its replacement."""
    from app.modules.i18n_foundation.tax_window_supersede import repair_superseded_tax_windows

    return await repair_superseded_tax_windows(session)


#: Nature ``superseded``: 19 % was the correct Romanian standard rate until
#: 31 July 2025 and the wrong one from 1 August. An estimate or invoice priced
#: before the reform must still resolve at 19 %, so the repair closes the old
#: row's window and inserts the new rate beside it rather than editing the rate
#: in place. The declaration below is what lets the registry's contract test
#: check that, instead of trusting the implementation to have got it right:
#: ``verify_supersede_shape`` fails the repair if any pre-existing row's rate
#: moves, and permits only ``effective_to`` going from empty to set.
ROMANIA_VAT_2025 = register_data_repair(
    DataRepair(
        repair_id="romania_vat_2025",
        revision="v3308_romania_vat_2025",
        summary="Close Romania's 19% VAT row and add the 21% standard and 11% reduced rates",
        run=_run_romania_vat,
        nature="superseded",
        superseded=SupersededBy(
            effective_from="2025-08-01",
            table=TAX_CONFIG_TABLE,
            closes_column="effective_to",
            # Closing the 19 % window also has to take the default flag off it:
            # a rate that is no longer in force cannot go on being the one the
            # UI offers first. It is a selection hint, not a value any invoice
            # was issued at, so moving it changes no money. Declared rather than
            # quietly permitted because the contract test caught this edit and
            # an undeclared exception is how a real one would get through later.
            also_updates=("is_default",),
        ),
    )
)

#: Nature ``always_wrong``, and worth saying why, because it writes to the same
#: table as the repair above and does the thing that one is forbidden to do: it
#: edits a pre-existing row in place. The difference is which column. These rows
#: were seeded without the subdivision they apply in - a Canadian provincial
#: rate that names no province is not a rate that was correct until some date,
#: it is a row that was incomplete from the day it was written. Nothing was
#: entitled to resolve against it, and filling the label in is not a change of
#: value. The rate itself is never touched.
TAX_SUBDIVISION_BACKFILL = register_data_repair(
    DataRepair(
        repair_id="tax_subdivision_backfill",
        revision="v3307_tax_subdivision",
        summary="Label the shipped Canadian and US tax rates with the subdivision they apply in",
        run=_run_tax_subdivision,
        nature="always_wrong",
    )
)

#: Nature ``always_wrong`` again, and the argument is the one above with the
#: axis turned around. These two rows say ``national`` because that is the
#: server default the boot heal left on them, not because anybody decided they
#: were country-wide-and-nothing-else; ``combination`` did not exist when they
#: were written and nothing read it until the resolver did, so no document was
#: ever priced against the distinction and there is no date at which
#: ``national`` was the right answer. Correcting it in place is the whole
#: repair, and it is deliberately not ``superseded``: closing a window and
#: inserting a second Canadian GST row beside the first would give the country
#: two federal layers, which is a worse database than the one being repaired.
#:
#: Separate from the subdivision entry rather than folded into it because the
#: two have different predicates and different failure modes. That one writes
#: two columns together to satisfy a check constraint and skips a row that
#: already carries a subdivision; this one writes one column on a row that has
#: no subdivision and never will.
TAX_FEDERAL_SCOPE = register_data_repair(
    DataRepair(
        repair_id="tax_federal_scope",
        revision="v3302_tax_combination",
        summary="Correct the shipped Canadian and US country-wide rates from national to federal",
        run=_run_tax_federal_scope,
        nature="always_wrong",
    )
)

#: Nature ``never_delivered``, and the only entry here that corrects nothing.
#: Every row it writes is one this database has never held, because the seeder
#: fills ``oe_i18n_tax_config`` only while it is empty and the shipped file has
#: grown since this install was built. So there is no value to preserve, no
#: window to close, and the whole safety question moves to a different place:
#: proving that a row which is not there was never delivered rather than
#: deleted. The repair's own module is where that argument lives, and
#: ``NeverDelivered`` is what holds it to the only shape that argument permits,
#: which is to add and touch nothing.
#:
#: ``identified_by`` is country plus tax code because that is what a reader of
#: this table treats as one answer. The failure an additive repair really has
#: is not damaging a row but doubling it, and a second Ontario HST row beside
#: the customer's own is worse than the missing rate this exists to deliver.
#: The revision is empty because there is no revision: no schema change caused
#: this and no ``upgrade()`` body would have fixed it.
TAX_SEED_RECONCILE = register_data_repair(
    DataRepair(
        repair_id="tax_seed_reconcile",
        revision="",
        summary="Deliver the shipped tax rates added to the seed file after this database was seeded",
        run=_run_tax_seed_reconcile,
        nature="never_delivered",
        never_delivered=NeverDelivered(
            table=TAX_CONFIG_TABLE,
            identified_by=("country_code", "tax_code"),
        ),
    )
)

#: Nature ``superseded`` again, and the second entry to declare it. Everything
#: the Romanian note above says about close-and-add applies here word for word:
#: Nova Scotia's 15 % rate was right until 31 March 2025 and wrong from the
#: first of April, so a document priced in March has to go on resolving at 15 %
#: and the old row is closed rather than rewritten.
#:
#: What is different is the population. That one names a country; this one
#: derives its rate lines from ``tax_configurations.json`` - every line the file
#: ships more than one window of - because nothing in the tree fails when a
#: window is added to an existing line, so a rate change lands on new installs
#: and skips every old one with no test on the way. The set is pinned in
#: ``tests/unit/test_tax_window_supersede_population.py`` so deriving it is not
#: the same as letting it grow unread.
#:
#: ``also_updates`` is deliberately empty, unlike Romania's. Instead of
#: permitting ``is_default`` to move, the repair requires it to already match
#: the shipped window and declines the line otherwise, which is the tightest
#: contract ``verify_supersede_shape`` will accept. An allowance nothing
#: exercises is a hole in the contract that no test can be built against, and
#: no line in the population needs one: Nova Scotia ships both windows
#: unflagged because a provincial row is never the country default, and Israel
#: ships both flagged because its two windows are periods of one standard rate.
#: Either way the flag sits still and there is nothing to permit.
#:
#: ``effective_from`` moved from 2025-04-01 to 2025-01-01 when the Israeli
#: windows were added: it is the earliest date the population supersedes on, so
#: it names Israel's rise now rather than Nova Scotia's cut. It moved again,
#: to 2020-09-01, when Ireland's temporary 21 % window was added, which is
#: the first superseding window in the population that lies wholly in the past.
#:
#: Registered last on purpose. It writes to rows the two scope repairs above
#: correct, and while its predicate does not require them to have run - an
#: unlabelled row is accepted, a differently labelled one is not - running after
#: them means it meets those rows in the shape the shipped file describes.
TAX_WINDOW_SUPERSEDE = register_data_repair(
    DataRepair(
        repair_id="tax_window_supersede",
        revision="",
        summary="Close a shipped tax window this database still holds open and add its replacement",
        run=_run_tax_window_supersede,
        nature="superseded",
        superseded=SupersededBy(
            effective_from="2020-09-01",
            table=TAX_CONFIG_TABLE,
            closes_column="effective_to",
        ),
    )
)


#: Nature ``always_wrong``, and the strongest claim of that nature in this file.
#: The other two rest on an argument about what a column meant when it was
#: written; this one rests on the value being impossible. ``work_days`` is read
#: with ``isoweekday()``, which returns 1..7, so a 0 in it names no day at all -
#: it cannot be a preference, an unusual week, or a deliberate configuration,
#: which is what entitles a boot repair to overwrite it without asking when the
#: database was seeded.
#:
#: It names ``v3303``, which repaired the seed file and has an ``upgrade()`` body
#: that would have repaired the shipped row and never runs. That revision used
#: to declare itself a ``gap``; it declares this registration instead now, which
#: is the whole point of the declaration existing.
#:
#: Targeted at the value rather than at Saudi Arabia on purpose, so a second
#: country that ever acquires the same error needs no third repair. The count it
#: returns is worth watching: one is expected on an install carrying the shipped
#: row, and more than one means something is writing 0 into that column today.
WORK_CALENDAR_ISO_ZERO = register_data_repair(
    DataRepair(
        repair_id="work_calendar_iso_zero",
        revision="v3303_work_calendar_iso_weekdays",
        summary="Correct a work calendar week written on the Monday-zero axis, where 0 names no day",
        run=_run_work_calendar_iso_zero,
        nature="always_wrong",
    )
)

#: Nature ``never_delivered``, the second one here and the only entry that
#: touches a table other than the tax one. The argument is the tax reconciler's
#: word for word - the seeder fills ``oe_i18n_work_calendar`` only while it is
#: empty, so six countries added to ``work_calendars.json`` since release one
#: have never reached an upgraded install - and the consequence is worse. A
#: missing tax rate makes a country stop pricing, which somebody notices. A
#: missing work calendar makes ``get_working_days`` fall back to Monday-to-
#: Friday and answer, so a Doha schedule is not refused, it is wrong twice a
#: week and looks right.
#:
#: ``identified_by`` is country plus year because that is
#: ``uq_work_calendar_country_year``, the table's own idea of one row. The
#: repair's delivery guard is stricter still - it declines a country that holds
#: any calendar at all - and the two are not the same check: this one is the
#: shape ``verify_additive_shape`` holds it to, that one is the promise not to
#: take over a week somebody has edited.
#:
#: The revision is empty for the reason the tax reconciler's is. No schema
#: change caused this and no ``upgrade()`` body would have fixed it, because
#: nothing on the boot path runs one; the module docstring has the long version.
WORK_CALENDAR_SEED_RECONCILE = register_data_repair(
    DataRepair(
        repair_id="work_calendar_seed_reconcile",
        revision="",
        summary="Deliver the shipped work calendars added to the seed file after this database was seeded",
        run=_run_work_calendar_seed_reconcile,
        nature="never_delivered",
        never_delivered=NeverDelivered(
            table=WORK_CALENDAR_TABLE,
            identified_by=("country_code", "year"),
        ),
    )
)

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Hand an already-seeded database the tax rates a later release added.

The defect
----------
``seed.py`` fills ``oe_i18n_tax_config`` only while the table is empty. A rate
added to ``seed_data/tax_configurations.json`` in a later release therefore
never reaches a database that was seeded before it, and no amount of shipping
the corrected file changes that. The file has grown from 70 rows to 81, and the
growth is not cosmetic: eight of the eleven were Canadian provincial rates. An
install seeded before v15.5.0 holds two of the ten sub-national Canadian rows
and gets ``subdivision_unknown`` from
:func:`~app.modules.i18n_foundation.tax_rules.resolve` for the other eight
provinces for the rest of its life, so a Canadian firm on such an install is
quietly missing most of its own provincial rates.

``romania_vat_2025`` is one hand-written instance of this, for one country. This
is the general case for the table.

The question this module is really about
----------------------------------------
Inserting a missing row is trivial. Knowing that it is missing rather than
deleted is not, and getting it wrong is far worse than the defect: a rate the
customer deliberately removed would come back on every boot, for ever, and
nothing they can do inside the product would stop it.

A row that is not on file looks exactly the same in both cases. So the answer
cannot come from looking at the table, and it comes from two places instead.

**One: what this repair has already handed over.** Every delivery is recorded
in :class:`~app.core.data_repairs.DataRepairDelivery`, in the same transaction
as the insert. From the second boot onward the question is settled by a record
rather than by inference - a key that was delivered is never delivered again,
whether or not the row is still there. Deleting a rate this repair gave you is
therefore permanent, which is the property that matters.

**Two: how old this database's seed is.** That is the only thing available on
the first boot, and here it is not a guess, because the seeder is
all-or-nothing. Every shipped row on an install was written by one seed
transaction over an empty table, so they all carry one ``created_at``, and that
timestamp says which seed file this install was built from. If the install was
seeded before the release that added a rate, the file it was seeded from did
not contain that rate, so it was never delivered. That is a proof rather than a
heuristic, and it is the reason this module can exist at all.

The residual gaps, stated rather than glossed
---------------------------------------------
Both are misses, never resurrections, and that asymmetry is deliberate: every
uncertainty resolves to "leave it alone".

* A database whose original seeded rows have all been deleted has no timestamp
  to read, so nothing is delivered to it. Logged, and it stays broken until
  somebody adds the rates by hand.
* A fresh install of an OLD build, made after the rate shipped, reads as too
  young and is skipped. Rare - it needs somebody to install a superseded
  release for the first time - and the cost is that a fix does not arrive,
  which is where this module started.
* A database that filled the gap itself keeps its own rate and is given
  nothing. See below; that one is refused rather than merely missed.

Additive on the table is not additive on the answer
---------------------------------------------------
The population this repair serves is the one whose provinces have had no rate
for a year, so some of them will have typed the rate in themselves, under their
own tax code. Their row and ours are different rate lines, so the line is
absent, so on the reading above the rate is owed - and delivering it would be a
second rate charged on the same province, or a second country-wide rate with
nothing to say which of the two is the standard one, which is a country that
stops pricing at all rather than one that prices wrongly.

So the unit of absence is the rate line but the unit of delivery is the
jurisdiction: a line is only handed over into a province, or a country-wide
slot, that holds nothing in force today. That is a decision about whether to
write rather than a second kind of write, so the repair stays additive.

A refusal is logged and no delivery is recorded, because the line is still
owed. If the collision is ever cleared the next boot delivers it.

Delivered a rate at a time, not a row at a time
-----------------------------------------------
The unit is ``(country_code, tax_code)``, a rate line rather than one row of
one, and both halves of that matter.

An install that holds no row at all for a rate line has never had that
jurisdiction's rate, and giving it the shipped rows - including a closed
historical window, if the file ships one - is purely additive. An install that
holds *any* row for the line has the line, and this repair leaves it alone even
if the file has since grown a second window for it: a new window on an existing
rate is a rate that changed, which is a ``superseded`` repair that has to close
the old window as it opens the new one. Doing that here would be exactly the
retroactive rewrite the registry's natures exist to keep apart, so it is
refused rather than approximated.

One shipped rate is on that side of the line today and it is worth naming
rather than leaving as an artefact. Nova Scotia cut its harmonised rate from
15 % to 14 % on 2025-04-01, and the file carries both windows. An install
seeded before v15.5.0 already holds the 15 % row, so the line reads as present
and the 14 % row is not delivered here. That is not a gap any more:
:mod:`app.modules.i18n_foundation.tax_window_supersede` closes the open window
and inserts the rate that replaced it, which is the ``superseded`` shape this
module is forbidden to take. Its population is derived from the same seed file,
so the division between the two is a property of the data rather than a list
either of them keeps: a rate line absent from a database belongs here, and a
rate line present at a superseded rate belongs there.

What was deliberately not generalised
-------------------------------------
Fifty-nine seed functions across forty-two files carry the same early return,
but almost all of them seed a demo project, where seeding once is the intended
behaviour and a later addition is meant for the next demo rather than for this
one. Five of them seed shipped reference data out of a data file: the three in
``i18n_foundation/seed.py`` and the two in ``app/scripts/seed_starter.py``.

Only tax rates got a reconciler, and the reason is the delete question rather
than effort. Every safety argument above rests on the identity of a row being
stable and meaningful - a tax line is one rate for one jurisdiction, and a
customer deleting one is making a statement about their business. A starter
cost item or a country row has no such identity: they are edited, renamed and
re-coded in normal use, so "absent" there does not mean what it means here, and
a reconciler could not tell a deleted row from a renamed one at all. Countries
and work calendars have the same defect and it is genuinely open; a country
missing from an old install is a real gap. Filling it needs a decision about
what identifies a row that people edit, and that decision is not this module's
to make.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_repairs import delivered_keys, record_deliveries
from app.modules.i18n_foundation.models import SUBNATIONAL_COMBINATIONS, TaxConfiguration
from app.modules.i18n_foundation.seed import load_tax_seed_rows, tax_configuration_from_seed_row
from app.modules.i18n_foundation.tax_rules import TaxRateRow, active_rows, row_from_orm

logger = logging.getLogger(__name__)

#: The id this repair is registered and recorded under. Deliveries are keyed on
#: it, so it can never be renamed: the rows already in the field carry it.
REPAIR_ID: Final = "tax_seed_reconcile"

#: A rate line: one tax code in one country. See the module docstring for why
#: reconciliation happens a line at a time rather than a row at a time.
RateLine = tuple[str, str]

#: When each rate line the seed file gained after its first release became
#: available, as the UTC date on which the commit that added it landed. An
#: install whose tax table was seeded before this date cannot have received the
#: line, because the file it was seeded from did not contain it yet.
#:
#: The date is the commit's, deliberately taken as midnight rather than as the
#: commit time: an install seeded earlier that same day is then read as too
#: young and skipped, which costs a fix rather than risking a resurrection.
#:
#: Adding a line to ``tax_configurations.json`` means adding it here too.
#: ``tests/unit/test_tax_seed_reconcile_covers_the_seed_file.py`` refuses a
#: seed file whose lines are not all accounted for, so this is a gate rather
#: than a convention.
LINE_FIRST_SHIPPED: Final[dict[RateLine, str]] = {
    # Canada's remaining provincial rates, v15.5.0.
    ("CA", "HST_NB"): "2026-08-23",
    ("CA", "HST_NL"): "2026-08-23",
    ("CA", "HST_PE"): "2026-08-23",
    ("CA", "PST_BC"): "2026-08-23",
    ("CA", "PST_SK"): "2026-08-23",
    ("CA", "QST_QC"): "2026-08-23",
    ("CA", "RST_MB"): "2026-08-23",
    # Nigeria, v15.6.0.
    ("NG", "VAT"): "2026-08-24",
    # Kuwait and Qatar. Both signed the 2016 GCC VAT framework and neither has
    # implemented it: the UAE and Saudi Arabia started in 2018, Bahrain in 2019
    # and Oman in 2021, while these two have repeatedly deferred. So the rate is
    # zero, and it is zero because somebody established it rather than because
    # nobody looked - which is the whole reason the rows exist. They are
    # deliverable rather than anchoring because an install seeded before them
    # holds no Gulf rate of its own and would otherwise price a Kuwaiti bill off
    # the shared regional stack for the life of the install.
    ("KW", "NONE"): "2026-09-02",
    ("QA", "NONE"): "2026-09-02",
}

#: Rate lines another repair owns. Two repairs writing one line would each see
#: the other's row and behave differently depending on which ran first, which
#: is a bug that only appears once somebody reorders a registry.
#:
#: Romania's reformed rates are inserted by
#: :func:`~app.modules.i18n_foundation.romania_vat.repair_romanian_vat_rates`,
#: which cannot be replaced by this module: the reform superseded the 19 % rate
#: rather than adding beside it, so the old window has to be closed as the new
#: one opens, and this repair is forbidden to touch an existing row.
REPAIRED_ELSEWHERE: Final[frozenset[RateLine]] = frozenset(
    {
        ("RO", "TVA"),
        ("RO", "TVA_RED"),
    }
)


def anchor_lines() -> frozenset[RateLine]:
    """The rate lines whose ``created_at`` dates this database's seed.

    These have shipped since the seed file's first release, so an install
    carrying one proves nothing about *which* file it was seeded from - only
    that it was seeded, and when. The set is derived rather than written out:
    everything the file ships, less the lines added later and the lines another
    repair writes.

    Both exclusions are load-bearing rather than tidy. A line added later is
    absent from exactly the installs being dated. And ``romania_vat_2025``
    inserts Romanian rows on the boot path with a ``created_at`` of now, so a
    Romanian row left in this set would date every upgraded install to the day
    of its upgrade and make all of them look too young to receive anything.
    """
    shipped = {(row["country_code"], row["tax_code"]) for row in load_tax_seed_rows()}
    return frozenset(shipped - set(LINE_FIRST_SHIPPED) - REPAIRED_ELSEWHERE)


def delivery_key(line: RateLine) -> str:
    """The stable spelling of a rate line in the delivery record.

    Written into ``oe_data_repair_delivery`` and read back on every boot, so
    the format is permanent: changing it would make every past delivery
    invisible and re-deliver rows customers have since deleted.
    """
    country, tax_code = line
    return f"{country}/{tax_code}"


def _shipped_by_line() -> dict[RateLine, list[dict]]:
    """The seed file grouped into rate lines, each keeping the file's order."""
    grouped: dict[RateLine, list[dict]] = {}
    for row in load_tax_seed_rows():
        grouped.setdefault((row["country_code"], row["tax_code"]), []).append(row)
    return grouped


def _first_shipped(line: RateLine) -> datetime:
    """The instant from which a seed file could have carried this rate line."""
    return datetime.fromisoformat(LINE_FIRST_SHIPPED[line]).replace(tzinfo=UTC)


async def _read_table(session: AsyncSession) -> tuple[list[TaxRateRow], set[RateLine], datetime | None]:
    """Everything on file, which rate lines it covers, and when it was seeded.

    One pass over the whole table, in Python. It is a catalogue - eighty-one
    shipped rows plus whatever the deployment added - and the alternative is a
    row-value ``IN`` over the seventy anchoring lines, which is a dialect
    question this does not need to have.

    The seed instant is the oldest ``created_at`` among the anchoring lines
    from :func:`anchor_lines`. Anchoring rows can only have been written by the
    seeder, in one transaction over an empty table, so they all carry one
    instant and any of them dates the seed.

    Oldest rather than newest, and the difference only shows on a database
    where somebody deleted a shipped rate and later re-created it by hand. That
    row's timestamp is not evidence about the seed, and being a later date it
    is past every ship date in :data:`LINE_FIRST_SHIPPED`, so taking the newest
    would let one such row withhold every remaining delivery for the life of
    the install. The oldest surviving anchor is the one still likely to be the
    seeder's own.

    It costs nothing in safety, which is the part worth checking rather than
    asserting. If a line was in the file this database was seeded from, the
    seeder wrote it, so the seed happened at or after that line shipped; the
    oldest anchor is the seed instant itself while any original row survives,
    and where none survives it can only be later still. Either way it is on or
    after the ship date, and the line is left alone. No row can predate the
    table, so there is no third case.

    Args:
        session: An open session.

    Returns:
        Every row flattened for the resolver, the rate lines on file, and the
        seed instant - or None for the last when no anchoring row is left, in
        which case nothing may be delivered.
    """
    anchors = anchor_lines()
    configs = (await session.execute(select(TaxConfiguration))).scalars().all()

    rows: list[TaxRateRow] = []
    on_file: set[RateLine] = set()
    seeded_at: datetime | None = None
    for config in configs:
        rows.append(row_from_orm(config))
        if config.tax_code is None:
            # A row with no tax code belongs to no rate line, so it can neither
            # be reconciled nor stand in the way of one. It still counts as
            # data in force, which is why it goes into ``rows`` regardless.
            continue
        line = (config.country_code, config.tax_code)
        on_file.add(line)
        created_at = config.created_at
        if line not in anchors or created_at is None:
            continue
        moment = created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=UTC)
        if seeded_at is None or moment < seeded_at:
            seeded_at = moment

    return rows, on_file, seeded_at


def _claimed_jurisdictions(rows: Sequence[TaxRateRow]) -> set[str | None]:
    """Which slots a set of rows already fills, ``None`` being the country-wide one.

    A rate line is only ever delivered into an empty slot, and the slot is the
    jurisdiction rather than the tax code: two rows for one province under
    different codes are two rates charged at once, and the customer's own code
    is not one this repair would recognise.

    A sub-national row with no subdivision fills nothing. It is the unlabelled
    shape :mod:`~app.modules.i18n_foundation.tax_subdivision_repair` exists
    for, it already makes every province in its country unanswerable, and
    treating it as a claim on one province would be picking a province for it.
    """
    claimed: set[str | None] = set()
    for row in rows:
        if row.combination in SUBNATIONAL_COMBINATIONS:
            if row.subdivision_code:
                claimed.add(row.subdivision_code)
        else:
            claimed.add(None)
    return claimed


def _refusal(existing: Sequence[TaxRateRow], planned: Sequence[TaxRateRow], country: str) -> str:
    """Why this line must not be delivered into this database, or ``""``.

    An addition that is additive on the table can still be destructive on the
    answer, and the case is reachable on an install that typed in its own rates
    because ours never arrived - which is exactly the population this repair
    serves, so it is not hypothetical. A country-wide rate delivered beside the
    customer's own leaves two country-wide rows with nothing to say which is
    the standard one, and the country stops pricing at all; a provincial rate
    delivered beside theirs is charged on top of it. Neither of their rows is
    touched and the table still looks additive, which is what makes this worth
    checking for rather than assuming.

    Delivering only into an empty slot is enough on its own here, and that is
    worth stating because :mod:`~app.modules.i18n_foundation.romania_vat`
    carries a second guard that resolves the country as it would read
    afterwards. It needs one: it closes a window as it opens another, so it can
    take an answer away. This repair only ever fills a jurisdiction that has
    nothing in force, and a jurisdiction with no rate resolves to the federal
    layer or to nothing at all - neither of which a valid rate for that
    jurisdiction can turn into a worse answer.
    """
    wanted = _claimed_jurisdictions(planned)
    held = _claimed_jurisdictions(active_rows(existing, country, date.today().isoformat()))
    collisions = sorted(str(slot) for slot in wanted & held)
    if collisions:
        return f"it already has a rate of its own in force for {', '.join(collisions)}"
    return ""


async def reconcile_shipped_tax_rows(session: AsyncSession) -> int:
    """Give this database the shipped rate lines it was seeded too early to get.

    Args:
        session: An open session. The caller commits; the repair registry does.
            The inserts and the delivery records go into this one session on
            purpose, so a boot that writes rows it cannot remember is not a
            reachable state.

    Returns:
        Number of tax rows inserted. Zero on a fresh install, zero on every
        boot after the first that had something to deliver, and zero on an
        install whose seed cannot be dated.

        Deliberately counts rows rather than deliveries: the ledger's
        ``rows_changed`` is read as "how much of the customer's data did this
        boot alter", and bookkeeping in a table of our own is not that.
    """
    shipped = _shipped_by_line()
    candidates = [line for line in LINE_FIRST_SHIPPED if line in shipped and line not in REPAIRED_ELSEWHERE]
    if not candidates:  # pragma: no cover - only reachable on a file with nothing added since release one
        return 0

    already = await delivered_keys(session, REPAIR_ID)
    wanted = [line for line in candidates if delivery_key(line) not in already]
    if not wanted:
        return 0

    existing, on_file, seeded_at = await _read_table(session)
    missing = [line for line in wanted if line not in on_file]
    if not missing:
        return 0

    if seeded_at is None:
        logger.warning(
            "Tax seed reconcile: this database holds none of the rate lines that date a seed, so "
            "when it was seeded cannot be told, so whether it is missing %d shipped rate line(s) or "
            "had them removed cannot be told either. Nothing delivered; the rates have to be added "
            "by hand if they are wanted.",
            len(missing),
        )
        return 0

    inserted = 0
    delivered: list[str] = []
    projected = list(existing)
    for line in missing:
        if seeded_at >= _first_shipped(line):
            # This install was seeded from a file that already carried the
            # line, so the line is absent because somebody removed it. Their
            # decision, and not one a boot-path repair gets to reverse.
            logger.debug(
                "Tax seed reconcile: %s is absent but this database was seeded on %s, after the rate "
                "shipped, so it was removed rather than never delivered. Left alone.",
                delivery_key(line),
                seeded_at.date().isoformat(),
            )
            continue

        # Built here rather than after the guard so that what is measured is
        # exactly what would be written, down to the normalising the seed row
        # goes through on its way into the table.
        objects = [tax_configuration_from_seed_row(row) for row in shipped[line]]
        rows = [row_from_orm(obj) for obj in objects]
        # Against the plan so far, not against the table as read: two lines
        # delivered in one pass can collide with each other as easily as with
        # something already on file.
        refusal = _refusal(projected, rows, line[0])
        if refusal:
            # No delivery recorded, deliberately. This is "not into this
            # database as it stands", not "handed over", and if the collision
            # is ever cleared the line is still owed.
            logger.warning(
                "Tax seed reconcile: not delivering %s - %s. That rate needs whoever maintains this "
                "database's tax rows, because adding ours beside theirs would change what it charges.",
                delivery_key(line),
                refusal,
            )
            continue

        for obj in objects:
            session.add(obj)
            inserted += 1
        projected.extend(rows)
        delivered.append(delivery_key(line))

    if not delivered:
        return 0

    await session.flush()
    await record_deliveries(session, REPAIR_ID, delivered)
    logger.info(
        "Tax seed reconcile: delivered %d rate line(s) added to the shipped seed after this database "
        "was seeded on %s (%s). They were never on this install; a rate removed here is not restored.",
        len(delivered),
        seeded_at.date().isoformat(),
        ", ".join(sorted(delivered)),
    )
    return inserted

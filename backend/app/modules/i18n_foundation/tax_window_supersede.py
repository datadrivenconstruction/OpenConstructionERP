# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Close a shipped tax window an install still holds open, and add what replaced it.

The defect
----------
``seed.py`` fills ``oe_i18n_tax_config`` only while the table is empty, so a
seed file that has since changed never reaches a database seeded before the
change. :mod:`app.modules.i18n_foundation.tax_seed_reconcile` covers half of
that: rate lines the file gained, which an old install does not hold at all.
The other half is a rate line the old install *does* hold, at a rate the file
has since superseded.

Nova Scotia is the live case. The province cut its harmonised rate from 15 % to
14 % on 2025-04-01, and ``tax_configurations.json`` carries both windows - the
15 % one closed at 2025-03-31, the 14 % one open. A database seeded before
v15.5.0 holds one Nova Scotia row, the 15 % one, still open. The reconciler
asks whether the jurisdiction holds anything in force, sees that it does, and
correctly declines: handing over the 14 % row without closing the 15 % one
leaves two rates replacing the federal one in the same province at the same
time, which is not a wrong number but a raised
:class:`~app.modules.i18n_foundation.tax_rules.TaxRuleError` - Nova Scotia
stops pricing at all. So the province keeps resolving at 15 % for the life of
the install, and ``/api/health`` reports a clean boot the whole time, because
nothing is missing and nothing is malformed.

Close and add, never rewrite
----------------------------
The shape is :mod:`app.modules.i18n_foundation.romania_vat`'s, and for its
reasons. The 15 % row is not edited to say 14 %. It is given the
``effective_to`` the shipped file gives it and the 14 % row is inserted beside
it, so an estimate or an invoice priced before the cut still resolves at 15 %
and re-running is a no-op, because a closed row no longer matches what this
looks for. That is what ``nature="superseded"`` declares and what
:func:`~app.core.data_repairs.verify_supersede_shape` holds the repair to.

General rather than one country, and why
----------------------------------------
Romania got a module of its own, and doing the same for Nova Scotia was the
obvious move. It was rejected on a measurement: **no gate fires when a window
is added to an existing rate line.** The reconciler's coverage test pins
``anchor_lines()``, which is a set of ``(country_code, tax_code)`` pairs, so
giving an existing line a second window leaves both the count and the digest
untouched. A rate change committed to the seed file today therefore reaches new
installs, silently skips every old one, and nothing anywhere says so - which is
this defect, repeating, with no test on the way.

So the population is derived from the shipped file rather than written out, and
``tests/unit/test_tax_window_supersede_population.py`` pins what the derivation
returns. The mechanism is general; the set of rate lines it will touch is not
allowed to grow without somebody saying so.

That set is three lines now, ``CA/HST_NS``, ``IL/VAT`` and ``RU/NDS``, and the
second one is what the generality was bought for. Israel raised standard VAT from 17 % to
18 % on 2025-01-01 and the seed file went on shipping 17 as the rate in force,
which is the same defect as Nova Scotia's in a second country. It was found by
reading, not by a red test, because no gate compared the seeded rate against
the methodology catalogue's own figure for the same country - the catalogue had
said 18 the whole time. ``tests/unit/test_tax_tables_do_not_drift.py`` compares
them now. Closing the Israeli window here needed no new code at all: the pair
went into the seed file and this repair picked it up, which is what "the
generality buys the next one" was a promise about.

``RU/NDS`` is the third, added 2026-09-07, and it is the statutory fact written
down where the rows are rewritten rather than only where they are shipped.
Russia raised standard VAT from 20 % to 22 % by Federal Law No. 425-FZ, signed
28 November 2025, amending article 164 of the Tax Code, in force from
1 January 2026. Source read for that: Federal Tax Service, "Taxes 2026",
https://www.nalog.gov.ru/new2026/ (read 2026-09-07), which gives the rate as
20 % to 22 % applying to sales of goods, works and services from 1 January 2026
and lists the 10 % reduced class among the rates that did not change, which is
why ``NDS_RED`` is untouched. The seed had gone on shipping one open window at
20 % dated from 2019-01-01, so this repair closes that window at 2025-12-31 on
installs in the field and inserts the 22 % one beside it. Both Russian windows
keep ``is_default`` true, the Israeli way, and there the flag standing still is
a constraint rather than a convenience: see the note in
``tests/unit/test_tax_window_supersede_population.py`` for why unflagging the
closed window would leave Russia with no resolvable rate at all from 2019 to
2025.

Recognising our own row, and the limit of it
--------------------------------------------
A window is closed only when the row on file is the one the seeder wrote,
field for field on everything that carries a value:

* the same rate, to the character - a row that says 15.5 is not our 15.0;
* the same ``effective_from`` - a window somebody re-dated is theirs;
* still open, which is what makes the second pass a no-op;
* the same ``is_default`` flag as the shipped window;
* and a ``subdivision_code`` that is either the shipped one or empty.

Two of them are worth explaining, one because it narrows the repair further
than it looks and one because it deliberately does not.

``is_default`` is the narrow one. Requiring the flag to match is the tightest
contract the shape check accepts and keeps the repair from moving a flag it has
no business moving. The cost is that it declines any rate change whose two
shipped windows disagree about the flag, and a *national standard* rate change
is where that happens.

Romania is the proof, and it is on disk rather than hypothetical: the closed
19 % window ships ``is_default`` false and its 21 % successor ships it true,
because the flag names the country's current standard rate and moves with it.
An install seeded before that change holds the 19 % row still open and still
flagged, so the predicate compares true against false and declines. That is why
Romania has a repair of its own rather than a line in the table this one
derives, and it is the honest reason ``REPAIRED_ELSEWHERE`` is subtracted: not
merely that Romania is already handled, but that this mechanism could not
handle it. Nova Scotia is within reach only because a subdivision row is never
the country default, so both of its windows ship the flag false and nothing has
to move.

The consequence for whoever reads this next: when the seed file grows another
national standard rate change, the pinned population test will fail and bring
you here, and the decision waiting for you is about the flag rather than about
the repair. Do not assume the next rate change is covered.

Israel is that next rate change, and it went the other way, which is worth
recording because it narrows the warning above rather than repealing it. Its
17 % and 18 % windows both ship ``is_default`` true, so nothing has to move and
the predicate matches. That is not a second opinion about what the flag means,
it is what the resolver already reads it as: ``_country_wide_standard`` picks
the flagged row out of the rows *in force on the date being asked about*, and
two windows of one line never overlap, so exactly one is flagged on every date
in either. Romania needs its own repair because the file moves the flag there,
not because a country's standard rate is beyond this mechanism. So the question
to ask of the next pair is the narrow one - does the file move the flag - and
not the broad one about what kind of rate changed.

``subdivision_code`` is the wide one. Requiring the shipped value outright
would break on the cohort this repair serves: a database seeded before v15.7.0
has no subdivision on any row until
:mod:`~app.modules.i18n_foundation.tax_subdivision_repair` fills it in, so the
predicate would depend on which repair the registry happens to run first.
Accepting *any* subdivision would be worse in the other direction - that
sibling repair's docstring explicitly contemplates an operator who moved a rate
to a different province, and closing that row would take the rate away from the
province they moved it to. Empty means the row names no province at all, which
is the unlabelled shape, not a different answer; a different province is
refused.

Be plain about what none of this can do, because it is the same limit Romania
states: **it separates an untouched shipped row from an edited one, and it
cannot separate a tenant deliberately holding 15 % from one nobody ever
updated.** Holding the old rate on purpose requires no edit, so the two are
identical in the table. What makes the repair safe anyway is close-and-add
rather than the predicate: every date before the cut still resolves at 15 %,
and an operator who wants 15 % for new work has one row to re-open rather than
a lost rate to reconstruct.

It must not leave a jurisdiction unable to price
------------------------------------------------
The writes are planned, the planned table is run through ``resolve``, and
nothing is applied to a rate line whose jurisdiction would come out of it
without an answer. That guard is not decoration here. The population this
serves is the one whose province has been mispriced for a year, so some of them
will have entered a rate of their own; a hand-entered Nova Scotia row that also
replaces the federal rate makes the province raise rather than answer, and it
does so both before and after anything this repair could do. Applying to such
an install would edit their data and buy nothing, so it is refused and logged.

``resolve`` raises for that shape rather than returning an unresolved answer -
measured, not assumed - so the guard treats a raise as "no answer" instead of
letting it out into the runner, where it would land as a failed repair and a
red ``/api/health`` on a database this repair had already decided to leave
alone.

The residual limit, stated rather than glossed: for a country-wide window in a
country that charges by subdivision, the guard asks the question with no
subdivision, gets ``subdivision_unknown``, and refuses. No shipped line is in
that shape today. If one ever is, the pinned population is what brings a reader
here first, and a refusal that is logged is the safe direction to fail in.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.i18n_foundation.models import TaxConfiguration
from app.modules.i18n_foundation.seed import load_tax_seed_rows, tax_configuration_from_seed_row
from app.modules.i18n_foundation.tax_rules import (
    TaxRateRow,
    TaxRuleError,
    resolve,
    row_from_orm,
)
from app.modules.i18n_foundation.tax_seed_reconcile import REPAIRED_ELSEWHERE, RateLine

logger = logging.getLogger(__name__)

#: The id this repair is registered and recorded under. The ledger is keyed on
#: it, so it can never be renamed.
REPAIR_ID: Final = "tax_window_supersede"

#: The earliest date any window in the shipped population takes effect, for the
#: repair's ``SupersededBy`` declaration - which is documentation, read by a
#: support log rather than by any code. Pinned here and checked against the
#: derivation in ``tests/unit/test_tax_window_supersede_population.py``, so a
#: seed file that supersedes something earlier cannot leave this saying the
#: wrong month.
EARLIEST_SUPERSEDED_FROM: Final = "2025-01-01"


def superseded_lines() -> dict[RateLine, list[dict]]:
    """The shipped rate lines that carry more than one window, oldest first.

    A line with one window has nothing to supersede. A line with several is one
    the file says changed on a date, and an install holding only the earlier
    window is the cohort this repair exists for.

    :data:`~app.modules.i18n_foundation.tax_seed_reconcile.REPAIRED_ELSEWHERE`
    is subtracted, and that is load-bearing rather than tidy. Romania's shipped
    19 % window is closed in the file exactly as Nova Scotia's 15 % one is, so
    an old install's open 19 % row matches this repair's predicate too, and
    both this and ``romania_vat_2025`` would set out to close it. Which one got
    there first would depend on registry order, and the loser would find its
    plan half-applied.

    Returns:
        ``{(country, tax_code): [window, ...]}``, each list sorted by
        ``effective_from``, for lines shipping two windows or more. Rows with
        no tax code belong to no rate line and are skipped.
    """
    grouped: dict[RateLine, list[dict]] = {}
    for row in load_tax_seed_rows():
        tax_code = row.get("tax_code")
        if tax_code is None:
            continue
        grouped.setdefault((row["country_code"], tax_code), []).append(row)

    return {
        line: sorted(windows, key=lambda window: window.get("effective_from") or "")
        for line, windows in grouped.items()
        if len(windows) > 1 and line not in REPAIRED_ELSEWHERE
    }


def _is_our_row_still_open(row: TaxConfiguration, window: dict) -> bool:
    """Whether ``row`` is the shipped ``window`` as the seeder wrote it, still open.

    Args:
        row: A row on file, already known to be on this rate line.
        window: The shipped window it is being held against. Only windows the
            file has since closed can match: a window the file still leaves
            open has not been superseded and there is nothing to do to it.

    Returns:
        True only when every field carrying a value is still what was shipped.
        See the module docstring for why ``subdivision_code`` is the one field
        allowed to be empty instead, and why the display name and the metadata
        are not compared at all - a rate somebody renamed is still the same
        rate, and the shipped name has itself changed between releases.
    """
    if window.get("effective_to") is None or row.effective_to is not None:
        return False
    return (
        row.rate_pct == window["rate_pct"]
        and row.effective_from == window.get("effective_from")
        and bool(row.is_default) == bool(window.get("is_default", False))
        and row.tax_type == window["tax_type"]
        and row.subdivision_code in (None, window.get("subdivision_code"))
    )


def _already_present(rows: list[TaxConfiguration], window: dict) -> bool:
    """Whether the line already holds this window, by the natural key of a rate.

    A shipped rate row is identified by its country, its tax code, its
    percentage and the date it starts; the first two are what put these rows in
    one list. Two rows agreeing on the rest are the same window stated twice,
    whoever wrote the second, and inserting it would give every reader of the
    table two answers where the database held one.
    """
    return any(
        row.rate_pct == window["rate_pct"] and row.effective_from == window.get("effective_from") for row in rows
    )


def _answer(rows: list[TaxRateRow], country: str, subdivision: str | None, on_date: str) -> str | None:
    """What one jurisdiction would be charged on ``on_date``, or ``None`` for no answer.

    ``resolve`` reports an unanswerable question two different ways and both
    mean the same thing here. It returns a resolution with no rate when the
    rows in force cannot be interpreted, and it *raises* when they contradict
    each other outright - two rates replacing the federal one in one province,
    which is exactly the shape a hand-entered provincial rate creates. Letting
    the raise out would turn a plan this repair had already decided to refuse
    into a failed repair and a red health check on every boot.
    """
    try:
        outcome = resolve(rows, country, subdivision, on_date=on_date)
    except TaxRuleError:
        return None
    return outcome.combined_rate_pct if outcome.resolved else None


def _projected(
    table: list[TaxConfiguration],
    closing: TaxConfiguration,
    closes_at: str,
    additions: list[dict],
) -> list[TaxRateRow]:
    """The whole table as it would read once this line's planned writes landed.

    Built without touching the session, so a plan can be measured and then
    dropped with nothing written. The whole table rather than the country's
    rows because a sub-national rate is only half an answer - the federal layer
    it replaces or stacks on is a row of its own.
    """
    rows = [
        row_from_orm(row)._replace(effective_to=closes_at) if row is closing else row_from_orm(row) for row in table
    ]
    rows.extend(row_from_orm(tax_configuration_from_seed_row(window)) for window in additions)
    return rows


async def repair_superseded_tax_windows(session: AsyncSession) -> int:
    """Bring every shipped rate line this install holds at a superseded rate up to date.

    For each rate line the seed file ships more than one window of, find the row
    on file that is one of those windows still open although the file has since
    closed it. Close it on the file's date and insert every window the file
    puts after it that this database does not already hold.

    Args:
        session: An open session. The caller owns the transaction and commits;
            this only flushes.

    Returns:
        Rows changed - windows closed plus rates inserted. Zero on a fresh
        install, zero on every boot after the one that had something to do, and
        zero on an install whose plan would leave a jurisdiction unable to
        price. That is the idempotence contract
        :class:`~app.core.data_repairs.DataRepair` requires.
    """
    lines = superseded_lines()
    if not lines:  # pragma: no cover - only reachable on a file where nothing has ever changed rate
        return 0

    today = date.today().isoformat()
    table = list((await session.execute(select(TaxConfiguration))).scalars().all())
    changed = 0

    for (country, tax_code), windows in sorted(lines.items()):
        on_file = [row for row in table if row.country_code == country and row.tax_code == tax_code]
        if not on_file:
            # The line was never delivered here at all, which is a different
            # defect with a different owner - see ``tax_seed_reconcile``. There
            # is no window to close, so there is nothing to supersede.
            continue

        # The latest window the file has closed that this database still holds
        # open. Latest rather than first so an install stranded on the second of
        # three windows is carried forward from where it actually is.
        stranded: tuple[int, TaxConfiguration] | None = None
        for index, window in enumerate(windows):
            matches = [row for row in on_file if _is_our_row_still_open(row, window)]
            if len(matches) > 1:
                # Two rows on one line, both looking exactly like the window we
                # would close. Nothing here can say which one the seeder wrote,
                # and closing both would be a guess about the other.
                logger.warning(
                    "Tax window supersede: %s/%s holds %d rows that all look like the shipped "
                    "%s%% window still open, so which one to close cannot be told. Left alone.",
                    country,
                    tax_code,
                    len(matches),
                    window["rate_pct"],
                )
                stranded = None
                break
            if matches:
                stranded = (index, matches[0])
        if stranded is None:
            continue

        index, closing = stranded
        closes_at = windows[index]["effective_to"]
        # An empty list here is not a reason to stop. It means the replacement
        # is already on file beside a predecessor nobody closed - a half-applied
        # state, and one where the province currently holds two rates at once
        # and cannot price. Closing the old window on its own is the whole
        # remainder of the repair. What keeps that safe is the guard below
        # rather than this list: if the replacement present on file is not one
        # that leaves the jurisdiction priceable, nothing is written.
        additions = [window for window in windows[index + 1 :] if not _already_present(on_file, window)]

        projected = _projected(table, closing, closes_at, additions)
        subdivision = windows[-1].get("subdivision_code")
        wanted_dates = sorted({today} | {window["effective_from"] for window in windows[index + 1 :]})
        unpriceable = [when for when in wanted_dates if _answer(projected, country, subdivision, when) is None]
        if unpriceable:
            logger.warning(
                "Tax window supersede: leaving %s/%s alone - closing the %s%% window and adding the "
                "rate that replaced it would leave %s without a rate on %s. Its rows are not the ones "
                "we shipped, so they need whoever maintains them rather than this repair.",
                country,
                tax_code,
                closing.rate_pct,
                subdivision or country,
                ", ".join(unpriceable),
            )
            continue

        closing.effective_to = closes_at
        changed += 1
        logger.info(
            "Tax window supersede: closed the %s%% %s/%s window at %s; it stays in force for every earlier date.",
            closing.rate_pct,
            country,
            tax_code,
            closes_at,
        )
        for window in additions:
            added = tax_configuration_from_seed_row(window)
            session.add(added)
            table.append(added)
            changed += 1
            logger.info(
                "Tax window supersede: added the %s%% %s/%s rate effective %s.",
                window["rate_pct"],
                country,
                tax_code,
                window.get("effective_from"),
            )

    if changed:
        await session.flush()
    return changed

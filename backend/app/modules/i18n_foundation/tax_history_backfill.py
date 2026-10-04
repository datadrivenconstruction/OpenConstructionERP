# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Hand an already-seeded database the past rate windows a later release added.

The gap the other two tax repairs leave
---------------------------------------
``tax_seed_reconcile`` delivers a rate line an install never held, and stops
at any line the install already has. ``tax_window_supersede`` carries a line
forward when the install holds a window the file has since closed. Neither
does anything when the file grows a window that lies entirely BEFORE the
windows an install holds, because that is neither a missing line nor a stale
open one.

Switzerland is that shape. The seed shipped only the rates in force from
2024-01-01 (8.1, 2.6 and 3.8 %), and 18.4 added the 2018 to 2023 windows (7.7,
2.5 and 3.7 %) in front of them. A fresh install prices a Swiss bill dated
2023 at 7.7. An install seeded before 18.4, production included, holds no
Swiss row in force on that date, so the bill falls back to the DACH markup
stack and is charged Germany's 19, more than twice the tax it owes, with
nothing on screen saying a rate was missing.

What this does
--------------
For each window named in :data:`WINDOW_FIRST_SHIPPED`, it inserts the shipped
row when every one of these holds, and does nothing otherwise:

* it was never delivered here before, by the delivery ledger, so a window a
  customer deleted after receiving it stays deleted;
* this database was seeded from a file that did not carry it, by the seed
  instant :mod:`~app.modules.i18n_foundation.tax_seed_reconcile` reads, so a
  window absent from an install seeded after it shipped is read as removed;
* its rate line is on file, because a missing line is the reconciler's case
  and, for a line every release shipped, a line somebody deleted;
* it ends before the earliest window the line holds, so it only ever fills
  the past and can never overlap a window that is already there;
* on every date it covers the country has no answer today, and after the
  insert it answers exactly what the shipped file answers, while today's
  answer does not move at all.

The last condition is decided per country, over all of that country's windows
together, because they only make sense together: Switzerland's 2.5 % tier
inserted without its 7.7 % standard rate would answer 2.5 as the standard rate
for 2023, since a lone unflagged row that ends where the flagged one begins
reads as its predecessor. A country whose windows cannot all go in gets none
of them, and the refusal is logged without recording a delivery, so the
windows are still owed if the collision is ever cleared.

The natural key is ``(country_code, tax_code, effective_from)``, one window,
rather than the reconciler's ``(country_code, tax_code)``: the line is on file
by construction here, and what must never be doubled is the window.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_repairs import delivered_keys, record_deliveries
from app.modules.i18n_foundation.seed import load_tax_seed_rows, tax_configuration_from_seed_row
from app.modules.i18n_foundation.tax_rules import TaxRateRow, row_from_mapping, row_from_orm
from app.modules.i18n_foundation.tax_seed_reconcile import _answer_on, _dates_to_check, _read_table

logger = logging.getLogger(__name__)

#: The id this repair is registered and recorded under. Deliveries are keyed on
#: it, so it can never be renamed.
REPAIR_ID: Final = "tax_history_backfill"

#: One shipped window: country, tax code and the day it starts.
Window = tuple[str, str, str]

#: When each past window the seed file gained in front of an existing line
#: became available, as the date of the release that ships it. Same convention
#: as ``tax_seed_reconcile.LINE_FIRST_SHIPPED``: midnight of that day, so an
#: install seeded earlier the same day is read as too young and skipped, which
#: costs a fix rather than risking a resurrection.
#:
#: Switzerland, ESTV "Erhoehung der MWST-Steuersaetze 2024" (read 2026-10-04):
#: 7.7, 2.5 and 3.7 % from 2018-01-01 to 2023-12-31.
WINDOW_FIRST_SHIPPED: Final[dict[Window, str]] = {
    ("CH", "VAT", "2018-01-01"): "2026-10-04",
    ("CH", "VAT_REDUCED", "2018-01-01"): "2026-10-04",
    ("CH", "VAT_SPECIAL", "2018-01-01"): "2026-10-04",
}


def delivery_key(window: Window) -> str:
    """The stable spelling of a window in the delivery record.

    Written into ``oe_data_repair_delivery`` and read back on every boot, so the
    format is permanent. The ``@`` keeps it from ever reading as one of the
    reconciler's ``CC/CODE`` line keys, although the repair id already keeps
    the two ledgers apart.
    """
    country, tax_code, effective_from = window
    return f"{country}/{tax_code}@{effective_from}"


def shipped_windows() -> dict[Window, dict]:
    """The rows :data:`WINDOW_FIRST_SHIPPED` names, as the seed file ships them."""
    out: dict[Window, dict] = {}
    for row in load_tax_seed_rows():
        key = (row["country_code"], row.get("tax_code") or "", row.get("effective_from") or "")
        if key in WINDOW_FIRST_SHIPPED:
            out[key] = row
    return out


def _first_shipped(window: Window) -> datetime:
    return datetime.fromisoformat(WINDOW_FIRST_SHIPPED[window]).replace(tzinfo=UTC)


def _fills_the_past_only(window_row: dict, on_file: Sequence[TaxRateRow]) -> bool:
    """Whether the window ends before every window its line already holds."""
    ends = window_row.get("effective_to")
    if ends is None or not on_file:
        return False
    starts = [row.effective_from for row in on_file]
    if any(start is None for start in starts):
        # A window open to the beginning of time already covers every past date.
        return False
    return ends < min(start for start in starts if start is not None)


def _refusal(existing: list[TaxRateRow], planned: list[TaxRateRow], country: str) -> str:
    """Why a country's past windows must not go in, or ``""``.

    Measured on the answer rather than the table, on every date the windows
    cover: the install must have no answer there now, and must give the shipped
    file's answer afterwards. Today's answer must not move.
    """
    shipped = [row_from_mapping(row) for row in load_tax_seed_rows()]
    projected = [*existing, *planned]
    for day in _dates_to_check(existing, planned, country):
        before = _answer_on(existing, country, day)
        if before[1] is not None:
            return f"it already resolves to {before[1]} % on {day}, so the window is not a gap here"
        after = _answer_on(projected, country, day)
        expected = _answer_on(shipped, country, day)
        if after != expected:
            return (
                f"with the windows added it would resolve to {after[0]} {after[1]} on {day}, "
                f"where the shipped rates resolve to {expected[0]} {expected[1]}"
            )
    today = date.today().isoformat()
    if _answer_on(existing, country, today) != _answer_on(projected, country, today):
        return f"adding them would change what it resolves to today, {today}"
    return ""


async def backfill_past_tax_windows(session: AsyncSession) -> int:
    """Give this database the past rate windows it was seeded too early to get.

    Args:
        session: An open session. The caller commits; the inserts and the
            delivery records go into this one session so neither can land
            without the other.

    Returns:
        Number of tax rows inserted. Zero on a fresh install, on an unseeded or
        undatable one, and on every boot after the first that delivered.
    """
    shipped = shipped_windows()
    already = await delivered_keys(session, REPAIR_ID)
    wanted = [window for window in WINDOW_FIRST_SHIPPED if window in shipped and delivery_key(window) not in already]
    if not wanted:
        return 0

    existing, _lines_on_file, seeded_at = await _read_table(session)
    if not existing:
        # Unseeded: the seeder writes the whole current file, history included.
        return 0
    if seeded_at is None:
        logger.warning(
            "Tax history backfill: this database's seed cannot be dated, so whether it is missing "
            "%d past rate window(s) or had them removed cannot be told. Nothing delivered.",
            len(wanted),
        )
        return 0

    by_country: dict[str, list[Window]] = {}
    for window in wanted:
        if seeded_at >= _first_shipped(window):
            # Seeded from a file that carried the window; absent means removed.
            continue
        by_country.setdefault(window[0], []).append(window)

    inserted = 0
    delivered: list[str] = []
    for country, windows in sorted(by_country.items()):
        planned_rows: list[dict] = []
        skipped: list[str] = []
        for window in sorted(windows):
            row = shipped[window]
            on_line = [r for r in existing if r.country_code == country and r.tax_code == window[1]]
            if not on_line:
                skipped.append(f"{delivery_key(window)} (its rate line is not on file)")
                continue
            if any(r.effective_from == row.get("effective_from") and r.rate_pct == row["rate_pct"] for r in on_line):
                skipped.append(f"{delivery_key(window)} (already on file)")
                continue
            if not _fills_the_past_only(row, on_line):
                skipped.append(f"{delivery_key(window)} (it would overlap a window already on file)")
                continue
            planned_rows.append(row)
        if skipped:
            logger.info("Tax history backfill: leaving %s alone: %s", country, "; ".join(skipped))
        if not planned_rows:
            continue

        objects = [tax_configuration_from_seed_row(row) for row in planned_rows]
        planned = [row_from_orm(obj) for obj in objects]
        refusal = _refusal(existing, planned, country)
        if refusal:
            logger.warning(
                "Tax history backfill: not delivering %s's past rates - %s. They need whoever maintains "
                "this database's tax rows.",
                country,
                refusal,
            )
            continue

        for obj in objects:
            session.add(obj)
            inserted += 1
        existing.extend(planned)
        delivered.extend(delivery_key((country, row["tax_code"], row["effective_from"])) for row in planned_rows)

    if not delivered:
        return 0

    await session.flush()
    await record_deliveries(session, REPAIR_ID, delivered)
    logger.info(
        "Tax history backfill: delivered %d past rate window(s) this database, seeded on %s, never had (%s).",
        len(delivered),
        seeded_at.date().isoformat(),
        ", ".join(sorted(delivered)),
    )
    return inserted

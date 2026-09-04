# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Deliver work calendars added to the seed file after this database was seeded.

``_seed_work_calendars`` fills ``oe_i18n_work_calendar`` only while the table is
empty - ``seed.py`` returns at the row count before it opens the file - so every
calendar added to ``work_calendars.json`` since an install was built is a
calendar that install will never receive. The file has grown six countries since
its first release: Bulgaria and Nigeria, then Qatar, Kuwait, Bahrain and Oman.

What that costs is not a missing row but a wrong answer.
:func:`~app.modules.i18n_foundation.service.get_working_days` falls back to
``{1, 2, 3, 4, 5}`` when a country has no calendar, so a schedule drawn in Doha
or Kuwait City is not refused for want of data - it is answered, in confident
Monday-to-Friday, which puts every deadline on the wrong day twice a week and
looks exactly like a correct answer on screen. That is the same shape as the
four-day Saudi week ``v3303`` exists to repair, reached by a different road: not
a row saying the wrong thing, a row that is not there at all.

Why this is a boot-path repair and not a migration
--------------------------------------------------
The natural place for this is an ``upgrade()`` body beside ``v3303``, and it
would not run. :mod:`app.core.data_repairs` states it at the top: the product
does not run ``alembic upgrade``. Schema moves at boot through
``postgres_auto_migrate`` and ``Base.metadata.create_all``, which carry additive
schema revisions and nothing else, so a revision whose body rewrites rows never
executes on an install brought up the normal way - while
``stamp_head_if_unstamped`` records that database at head, so the rewrite did
not run *and* the version table says it did. ``v3303`` carries a
``# boot-repair: gap`` line saying exactly that of itself. A second migration
here would reproduce that half-fix on the very population it is meant to serve,
so the delivery lives here instead.

Which installations this repairs, and which it does not
-------------------------------------------------------
It repairs an install whose work calendar table was seeded before a country's
calendar shipped, and which has no calendar for that country now. That is the
whole population that has been silently answering Monday-to-Friday for the Gulf.

It does nothing on four kinds of install, three of them deliberate:

* A fresh one, on either side of the seeder. Afterwards the table holds the
  current file, so there is nothing to add. Before it the table is empty - and
  on a first boot that is the ordinary case rather than a corner, because the
  repair registry runs well ahead of ``seed_i18n_data`` in ``app.main``. An
  empty table is not a database whose seed cannot be dated, it is one that has
  not been seeded, and ``_seed_work_calendars`` fills it later in this same
  boot. Either way this returns 0 and says nothing.
* One that already has a calendar for the country. Somebody may have edited
  their Qatar week, and a reconciler that overwrites it is worse than the gap it
  closes. Their row stands, untouched, whatever it says.
* One seeded *after* the calendar shipped and missing it anyway. The row was
  removed, that was a decision, and a boot-path repair does not get to reverse a
  decision. Told apart from the case above by dating the seed - see
  :func:`anchor_countries`.
* One that holds calendars but none of the ones that date a seed, so when it
  was seeded cannot be told. Nothing is delivered and a warning says why,
  because the question this repair has to answer is not "is the row missing"
  but "was it ever delivered", and on that database there is no evidence either
  way. Holding calendars is what separates it from the empty table above: there
  the seeder is about to answer, so telling the user to add the rows by hand
  would be false.

It also does not repair Saudi Arabia, and that is worth saying plainly because
the paragraph above invites the opposite reading. An install seeded before
commit ``0d2632c3d`` holds SA as ``[0, 1, 2, 3, 4]`` - a Monday-zero week in the
ISO column - and ``isoweekday()`` never returns 0, so it counts a four-day week
to this day. ``v3303`` would repair it and does not run. This repair cannot:
Saudi Arabia *has* a row, so the guard above declines it, and a
``never_delivered`` repair is forbidden to touch an existing row at all. Closing
that one needs a second repair of nature ``always_wrong``, which does not exist
yet.

Adding a calendar to ``work_calendars.json`` means adding it to
:data:`CALENDAR_FIRST_SHIPPED` too, or it silently joins the anchors and is
never delivered to anybody.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.data_repairs import delivered_keys, record_deliveries
from app.modules.i18n_foundation.models import WorkCalendar
from app.modules.i18n_foundation.seed import load_work_calendar_seed_rows, work_calendar_from_seed_row

logger = logging.getLogger(__name__)

#: The id this repair is registered and recorded under. Deliveries are keyed on
#: it, so it can never be renamed: the rows already in the field carry it.
REPAIR_ID: Final = "work_calendar_seed_reconcile"

#: One calendar: a country and the year it covers, which is what
#: ``uq_work_calendar_country_year`` treats as one row.
CalendarSlot = tuple[str, str]

#: When each calendar the seed file gained after its first release became
#: available, as the UTC date the commit that added it landed. An install whose
#: calendar table was seeded before this date cannot have received the row,
#: because the file it was seeded from did not carry it yet.
#:
#: Midnight rather than the commit time, deliberately: an install seeded earlier
#: that same day then reads as too young and is skipped, which costs a fix
#: rather than risking a resurrection.
#:
#: Bulgaria and Nigeria are here beside the four Gulf states because they are the
#: same defect and the mechanism does not care which country it is. They are the
#: cheaper half of it - both are Monday to Friday, which is what the fallback
#: already answers, so the rows they are missing move no date. The Gulf four are
#: the half that is wrong on screen today.
CALENDAR_FIRST_SHIPPED: Final[dict[CalendarSlot, str]] = {
    # Bulgaria and Nigeria, commit 4a01d3a41.
    ("BG", "2026"): "2026-08-24",
    ("NG", "2026"): "2026-08-24",
    # Qatar, Kuwait, Bahrain and Oman, commit 9bdfe6c5a.
    ("QA", "2026"): "2026-08-29",
    ("KW", "2026"): "2026-08-29",
    ("BH", "2026"): "2026-08-29",
    ("OM", "2026"): "2026-08-29",
}


#: The countries ``work_calendars.json`` shipped in its first release, and so
#: the countries whose ``created_at`` dates this database's seed. The seeder
#: writes every calendar in one transaction over an empty table, so the
#: surviving anchors all carry one instant and any of them dates the seed.
#:
#: Read once from ``git show d27f29ffa:...`` - the commit that first shipped the
#: file - and written down rather than derived from today's file. This is
#: history and it is closed: nothing anyone does from here can add a country to
#: what release one contained, because that release has already happened. So
#: pinning it is recording a fact that cannot change, not pinning a count that
#: grows.
#:
#: Writing it down is what makes the set checkable. Derived as
#: ``shipped - CALENDAR_FIRST_SHIPPED``, a country added to the seed file
#: without a ship date silently becomes an anchor and is then delivered to
#: nobody, and nothing can see that happen because the derivation absorbs it.
#: Frozen, the same mistake fails
#: ``test_every_shipped_country_is_either_an_anchor_or_dated``.
ANCHOR_COUNTRIES: Final[frozenset[str]] = frozenset(
    {
        "AE",
        "AT",
        "AU",
        "BR",
        "CA",
        "CH",
        "CN",
        "CZ",
        "DE",
        "DK",
        "ES",
        "FI",
        "FR",
        "GB",
        "IN",
        "IT",
        "JP",
        "KR",
        "MX",
        "NL",
        "NO",
        "NZ",
        "PL",
        "RU",
        "SA",
        "SE",
        "TR",
        "UA",
        "US",
        "ZA",
    }
)


def delivery_key(slot: CalendarSlot) -> str:
    """The stable spelling of a calendar in the delivery record.

    Written into ``oe_data_repair_delivery`` and read back on every boot, so the
    format is permanent: changing it would make every past delivery invisible
    and re-deliver calendars customers have since removed.
    """
    country, year = slot
    return f"{country}/{year}"


def _first_shipped(slot: CalendarSlot) -> datetime:
    """The instant from which a seed file could have carried this calendar."""
    return datetime.fromisoformat(CALENDAR_FIRST_SHIPPED[slot]).replace(tzinfo=UTC)


async def _read_table(session: AsyncSession) -> tuple[set[str], datetime | None]:
    """Which countries hold a calendar, and when this database was seeded.

    Countries rather than slots, because the delivery guard is a country-level
    one - see :func:`reconcile_shipped_work_calendars` for why it is stricter
    than the row's own identity.

    Args:
        session: An open session.

    Returns:
        The countries with a calendar on file, and the seed instant - or None
        for the second when no anchoring row is left, in which case nothing may
        be delivered.

        Oldest anchor rather than newest. The difference shows only on a
        database where somebody deleted a shipped calendar and re-created it by
        hand; that row's timestamp is not evidence about the seed, and being a
        later date it is past every ship date here, so taking the newest would
        let one such row withhold every remaining delivery for the life of the
        install. The oldest surviving anchor is the one still likely to be the
        seeder's own, and it errs in the safe direction: if a calendar was in
        the file this database was seeded from, the seeder wrote it, so the seed
        happened at or after that calendar shipped.
    """
    calendars = (await session.execute(select(WorkCalendar))).scalars().all()

    on_file: set[str] = set()
    seeded_at: datetime | None = None
    for calendar in calendars:
        on_file.add(calendar.country_code)
        created_at = calendar.created_at
        if calendar.country_code not in ANCHOR_COUNTRIES or created_at is None:
            continue
        moment = created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=UTC)
        if seeded_at is None or moment < seeded_at:
            seeded_at = moment

    return on_file, seeded_at


async def reconcile_shipped_work_calendars(session: AsyncSession) -> int:
    """Give this database the shipped calendars it was seeded too early to get.

    The guard is that the country has no calendar at all, which is stricter than
    the row's own identity of country plus year. Both say the same thing today,
    because the file ships one year and one row per country. They part the day a
    2027 file ships: an install holding a hand-edited Qatar 2026 will not be
    given Qatar 2027 by this repair, and that is the intended reading of "do not
    touch a country that has one". A country whose week somebody has taken over
    is a country this repair has nothing further to say about.

    Args:
        session: An open session. The caller commits; the repair registry does.
            The inserts and the delivery records go into this one session on
            purpose, so a boot that writes rows it cannot remember is not a
            reachable state.

    Returns:
        Number of calendars inserted. Zero on a fresh install, zero on every
        boot after the first that had something to deliver, and zero on an
        install whose seed cannot be dated.
    """
    shipped = {(row["country_code"], row["year"]): row for row in load_work_calendar_seed_rows()}
    candidates = [slot for slot in CALENDAR_FIRST_SHIPPED if slot in shipped]
    if not candidates:  # pragma: no cover - only reachable on a file with nothing added since release one
        return 0

    already = await delivered_keys(session, REPAIR_ID)
    wanted = [slot for slot in candidates if delivery_key(slot) not in already]
    if not wanted:
        return 0

    on_file, seeded_at = await _read_table(session)
    if not on_file:
        # No calendar at all, which is not the undatable database below but an
        # unseeded one: every WorkCalendar row carries a country, so an empty
        # set is an empty table. ``_seed_work_calendars`` writes the current
        # file whenever this table is empty and it runs later in this same
        # boot, so the calendars are not missing, they have not arrived yet.
        # Warning here would tell a first-time user to add by hand what the
        # boot is a few minutes away from adding for them.
        logger.debug(
            "Work calendar reconcile: the calendar table is empty, so this database has not been "
            "seeded yet and the seeder will write the current file later in this boot. Nothing to "
            "reconcile."
        )
        return 0

    missing = [slot for slot in wanted if slot[0] not in on_file]
    if not missing:
        return 0

    if seeded_at is None:
        logger.warning(
            "Work calendar reconcile: this database holds none of the calendars that date a seed, so "
            "when it was seeded cannot be told, so whether it is missing %d shipped calendar(s) or had "
            "them removed cannot be told either. Nothing delivered; the calendars have to be added by "
            "hand if they are wanted.",
            len(missing),
        )
        return 0

    inserted = 0
    delivered: list[str] = []
    for slot in missing:
        if seeded_at >= _first_shipped(slot):
            # Seeded from a file that already carried this calendar, so it is
            # absent because somebody removed it. Their decision, and not one a
            # boot-path repair gets to reverse.
            logger.debug(
                "Work calendar reconcile: %s is absent but this database was seeded on %s, after the "
                "calendar shipped, so it was removed rather than never delivered. Left alone.",
                delivery_key(slot),
                seeded_at.date().isoformat(),
            )
            continue

        session.add(work_calendar_from_seed_row(shipped[slot]))
        inserted += 1
        delivered.append(delivery_key(slot))

    if not delivered:
        return 0

    await session.flush()
    await record_deliveries(session, REPAIR_ID, delivered)
    logger.info(
        "Work calendar reconcile: delivered %d calendar(s) this database was seeded too early to receive: %s.",
        inserted,
        ", ".join(sorted(delivered)),
    )
    return inserted

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Critical Path Method (CPM) calculation engine.

Forward pass -> early dates. Backward pass -> late dates. Float -> critical path.
Calendar-aware (skips weekends/holidays via work_calendar).

This module is stateless and operates on plain dicts, making it easy to test
independently of the ORM and database layer.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.cpm_profile import SchedulingOptions

logger = logging.getLogger(__name__)

# Weekday numbering this engine counts with: Monday = 0 through Sunday = 6, the
# convention ``date.weekday()`` uses. Named once here, where the tolerance below
# is implemented, so a writer that wants to refuse a bad weekday at its own
# boundary can state the same range instead of restating the number.
MIN_WEEKDAY = 0
MAX_WEEKDAY = 6

# Default work calendar: Mon-Fri, no holidays
_DEFAULT_CALENDAR: dict = {
    "work_days": {0, 1, 2, 3, 4},
    "exceptions": [],
}


def check_work_days_in_range(work_days: object, *, source: str) -> None:
    """Raise if ``work_days`` carries a weekday this engine cannot count.

    The engine itself is deliberately tolerant - see :func:`_parse_work_days`,
    which drops what it cannot use so its day-stepping loops always terminate.
    That tolerance is why a wrong weekday produces a wrong schedule instead of an
    error, so a caller that still has somewhere to report to should refuse the
    value before storing it. This is that check, kept beside the range it guards.

    Args:
        work_days: The candidate list of weekday numbers, or anything else.
            Non-integers are ignored here; they are the engine's business.
        source: Where the value came from, named in the error message.

    Raises:
        ValueError: If any value is an integer outside ``MIN_WEEKDAY..MAX_WEEKDAY``.
    """
    if not isinstance(work_days, (list, tuple, set, frozenset)):
        return

    outside = sorted(
        {
            day
            for day in work_days
            if isinstance(day, int) and not isinstance(day, bool) and not MIN_WEEKDAY <= day <= MAX_WEEKDAY
        }
    )
    if outside:
        raise ValueError(
            f"{source} carries {outside}, outside the range {MIN_WEEKDAY}..{MAX_WEEKDAY}. "
            f"This calendar counts Monday as {MIN_WEEKDAY} and Sunday as {MAX_WEEKDAY}, so those "
            f"days match no date and the schedule would be computed against a shorter week. "
            f"Sunday is {MAX_WEEKDAY}, not 7."
        )


#: The exception-date forms this engine accepts, named in every refusal and in
#: every drop so a writer is told what to send instead of only what was wrong.
ACCEPTED_EXCEPTION_FORMS = "YYYY-MM-DD, YYYYMMDD, or an ISO datetime such as YYYY-MM-DDTHH:MM:SS"


def normalise_exception_date(value: object) -> date | None:
    """Return the single calendar day an exception entry names, or ``None``.

    Surrounding whitespace is stripped before parsing, because a date pasted
    from a spreadsheet arrives as ``"2026-05-01 "`` and names one day as plainly
    as the trimmed form does. An ISO datetime is accepted and reduced to its
    date, since ``2026-05-01T00:00:00`` also names exactly one day.

    A day-first or month-first form such as ``01/05/2026`` returns ``None``
    rather than a guess. It is genuinely ambiguous, and picking a reading would
    put a wrong holiday into a schedule that looks right, which is worse than
    refusing.

    Args:
        value: A string, ``date``, ``datetime``, or anything else.

    Returns:
        The day named, or ``None`` if the entry names no single day.
    """
    if isinstance(value, datetime):
        # datetime subclasses date, so this branch has to come first, and it has
        # to narrow rather than pass through: a datetime never compares equal to
        # the date the engine tests membership against, so an un-narrowed one
        # would be skipped in silence exactly like an unreadable string.
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        # Covers the plain ISO date, the basic YYYYMMDD form, and the ISO
        # datetime with either separator. Anything else raises.
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def canonical_exception_dates(exceptions: object, *, source: str) -> list[str] | None:
    """Return ``exceptions`` as canonical ISO dates, or raise naming what failed.

    The engine drops an exception it cannot read - see :func:`_parse_exceptions`,
    which now says so in the log but still has to keep scheduling so its
    day-stepping loops terminate. A dropped holiday is worked, and nothing
    downstream can tell that day from one nobody marked, so a caller that still
    has somewhere to report to should refuse the value before storing it. This
    is that check, kept beside the parse it guards.

    Returning the canonical strings rather than only raising is deliberate. The
    stored form is what later readers see, and at least one of them compares ISO
    strings without parsing them, so normalising once at the boundary is what
    makes an untidy but unambiguous entry work everywhere rather than only here.

    Args:
        exceptions: The candidate list of exception dates, or anything else.
        source: Where the value came from, named in the error message.

    Returns:
        The canonical ``YYYY-MM-DD`` strings, or ``None`` when no exceptions key
        was supplied, which leaves the value to the engine's own tolerance.

    Raises:
        ValueError: If ``exceptions`` is present but not a list, or if any entry
            names no single day.
    """
    if exceptions is None:
        return None
    if not isinstance(exceptions, (list, tuple)):
        raise ValueError(
            f"{source} is {type(exceptions).__name__}, not a list. A single date still has to be "
            f"sent as a one-item list, because a bare string is read one character at a time and "
            f"every character is then dropped as unreadable."
        )

    canonical: list[str] = []
    rejected: list[str] = []
    for entry in exceptions:
        parsed = normalise_exception_date(entry)
        if parsed is None:
            rejected.append(repr(entry))
        else:
            canonical.append(parsed.isoformat())
    if rejected:
        raise ValueError(
            f"{source} carries {', '.join(rejected)}, which name no single day. Accepted forms "
            f"are {ACCEPTED_EXCEPTION_FORMS}. A day-first or month-first form such as "
            f"'01/05/2026' is refused rather than guessed, because it reads as two different "
            f"days. An entry not accepted here would be dropped and its day worked."
        )
    return canonical


def _parse_work_days(calendar: dict | None) -> set[int]:
    """Extract working day indices (0=Mon .. 6=Sun) from a calendar dict.

    Values outside 0..6 and non-numeric junk are dropped, and an empty result
    falls back to the Monday-Friday default. This guarantees at least one
    reachable working weekday, so the day-stepping loops in ``_add_working_days``
    / ``_sub_working_days`` always terminate: a malformed calendar such as
    ``work_days=[7]`` (a common "Sunday = ISO 7" mistake) can never spin them
    forever into an ``OverflowError``.
    """
    if not calendar:
        return _DEFAULT_CALENDAR["work_days"]
    raw = calendar.get("work_days")
    if raw is None:
        return _DEFAULT_CALENDAR["work_days"]
    valid: set[int] = set()
    for d in raw:
        try:
            n = int(d)
        except (TypeError, ValueError):
            continue
        if MIN_WEEKDAY <= n <= MAX_WEEKDAY:
            valid.add(n)
    return valid or _DEFAULT_CALENDAR["work_days"]


def readable_work_days(work_days: object, *, source: str) -> list[int]:
    """Weekday numbers for every entry that names one, warning about the rest.

    The ``work_days`` counterpart to :func:`readable_exception_dates`, and it
    exists for a sharper reason than symmetry. Every reader of this column used
    to wrap the whole conversion in ``except (TypeError, ValueError)`` and fall
    back to a default week, which is ornamental against the malformation that
    actually happens. A bare digit string does not raise. ``"12345"`` iterates
    character by character into ``[1, 2, 3, 4, 5]``, a clean five day week
    nobody would look at twice, and ``"0123456"`` into a seven day week in which
    no date is ever non-working, so every duration computes short and every
    finish date lands early. Junk that is indistinguishable from a correct
    answer is worse than junk that looks like junk.

    So the guard cannot be an except around the iteration. It has to be a type
    check on the column before anything iterates it.

    A column that is not a list is refused, for the same reason the holiday
    column is: what separates the two cases is history, not blast radius. A
    malformed entry had a legitimate way in until the write guards landed. A
    non-list column never did, because this is ``JSON`` with ``nullable=False``,
    ``default=list`` and a ``[0, 1, 2, 3, 4]`` server default, and every write
    path goes through a schema typed as a list.

    An empty list stays lenient and is returned as one, because ``default=list``
    means an ORM-created row with no explicit work days genuinely arrives as
    ``[]``. Callers apply their own default to that. It is deliberately not
    folded together with the refusal above: an empty week and an unreadable
    column must not reach the same line, or the collapse this removes is simply
    rebuilt one level up.

    Entries are dropped individually rather than taking the column down with
    them, which is the other half of what the blanket except cost. One
    unreadable entry used to discard every readable one beside it and silently
    substitute the default week.

    Values outside Monday zero to Sunday six are passed through rather than
    dropped. A weekday number nothing matches is inert, it simply never marks a
    day as working, so dropping it would change dates where keeping it cannot.
    The write side owns that range check.

    Args:
        work_days: The stored column, in any spelling.
        source: What is being read, named in every warning so the log says which
            calendar to correct.

    Returns:
        Weekday numbers for the entries that name one, in the order given.

    Raises:
        ValueError: If ``work_days`` is neither ``None`` nor a list of values.
    """
    if work_days is None:
        return []
    if not isinstance(work_days, (list, tuple, set, frozenset)):
        raise ValueError(
            f"{source} is a {type(work_days).__name__} rather than a list of weekday numbers, so the working "
            f"week cannot be read at all. A stored string would be walked one character at a time and produce "
            f"a plausible week that nothing computed from it would reveal as wrong. Store a JSON list of "
            f"integers, Monday as 0 through Sunday as 6."
        )
    readable: list[int] = []
    for entry in work_days:
        try:
            readable.append(int(entry))
        except (TypeError, ValueError):
            logger.warning(
                "CPM: dropped %s entry %r, which names no weekday. Use integers, Monday as 0 through "
                "Sunday as 6. That day keeps whatever the rest of the week says.",
                source,
                entry,
            )
    return readable


def readable_exception_dates(exceptions: object, *, source: str) -> list[str]:
    """Canonical dates for every entry that names a day, warning about the rest.

    The read-path counterpart to :func:`canonical_exception_dates`, and the one
    convention every reader of a stored calendar now shares.

    There used to be four. One reader truncated each entry to ten characters,
    one passed it through whole, one truncated it again somewhere else, and the
    only parser that actually validated had no production callers. They
    disagreed about which values meant which day, so the same stored holiday
    could be read three ways in one request.

    Worse than disagreeing, three of them could not report. A truncation has no
    failure mode, so there was no error branch to log from: a holiday written
    ``01/05/2026`` matched no date, the day was worked as an ordinary one, and
    nothing anywhere said so. That is the same blindness as a swallowed
    exception, arriving by a route where there is not even a place to put the
    log line.

    A single unreadable *entry* is dropped rather than refused, unlike the
    write-side check, and the asymmetry is deliberate. The write schemas turn
    away a value naming no single day, so anything malformed arriving here was
    stored before those guards existed. Refusing it now would turn an old row
    into a failed read on a path nobody asked to change, and would hide the very
    calendar an operator needs to see in order to fix it.

    A column that is not a list at all is refused, and the difference from the
    line above is not a matter of degree. One bad entry loses one day. A column
    that is not a calendar loses every holiday in it, and the caller cannot tell,
    because a schedule computed from no holidays looks exactly like a schedule
    computed from a calendar that happened to have none. A log line is not
    visible to whoever reads the finish date, and these dates are planned
    against.

    The reason that does not contradict the leniency above is that the two cases
    have different populations. Malformed entries have a legitimate history: they
    were storable until the write guards landed. A non-list has none. The column
    is ``JSON`` with ``nullable=False``, ``default=list`` and a ``[]`` server
    default, and every write path in the tree goes through a schema typed as a
    list, so no version of this code could ever have stored one. Reaching this
    branch means the row was written around the application, and degrading
    quietly is the wrong answer to data nothing we ship can produce.

    ``None`` is not in that category and is read as an empty calendar. The
    column cannot be NULL, and where a caller passes ``None`` it means there is
    no calendar rather than an unreadable one.

    Empty entries are dropped silently, also deliberately. They carry no date to
    misread, and a stored blank would otherwise warn on every reschedule for the
    life of the row.

    Args:
        exceptions: Stored exception or holiday values, in any spelling.
        source: What is being read. It is named in every warning, so the log
            says which calendar to correct rather than only that something
            somewhere was unreadable.

    Returns:
        Canonical ``YYYY-MM-DD`` strings for the entries that name a day, in the
        order given. Duplicates are kept; callers wanting a set build one.

    Raises:
        ValueError: If ``exceptions`` is neither ``None`` nor a list of values.
    """
    if exceptions is None:
        return []
    if not isinstance(exceptions, (list, tuple, set, frozenset)):
        raise ValueError(
            f"{source} is a {type(exceptions).__name__} rather than a list of dates, so the calendar cannot "
            f"be read at all. Every holiday in it would be dropped and the dates computed without them would "
            f"look no different from correct ones. Store a JSON list; accepted forms are "
            f"{ACCEPTED_EXCEPTION_FORMS}."
        )
    readable: list[str] = []
    for entry in exceptions:
        if entry is None or (isinstance(entry, str) and not entry.strip()):
            continue
        parsed = normalise_exception_date(entry)
        if parsed is None:
            logger.warning(
                "CPM: dropped %s entry %r, which names no single day. Accepted forms are %s. "
                "That day will be treated as a working day.",
                source,
                entry,
                ACCEPTED_EXCEPTION_FORMS,
            )
            continue
        readable.append(parsed.isoformat())
    return readable


def _parse_exceptions(calendar: dict | None) -> set[date]:
    """Extract exception dates (holidays) from a calendar dict.

    An entry that names no single day is dropped, because the day-stepping loops
    above have to terminate, but it is logged with the value that caused it.
    Rows written before :func:`canonical_exception_dates` guarded the write are
    never revalidated, so this log line is the only thing that tells a dropped
    holiday apart from a day nobody marked as one.
    """
    if not calendar:
        return set()
    exceptions = calendar.get("exceptions", [])
    if not isinstance(exceptions, (list, tuple, set, frozenset)):
        # A bare string would otherwise be iterated one character at a time and
        # produce a drop line per character, which buries the actual problem.
        logger.warning(
            "CPM: calendar exceptions is %s, not a list, so no holidays were read from it",
            type(exceptions).__name__,
        )
        return set()
    result: set[date] = set()
    for exc in exceptions:
        parsed = normalise_exception_date(exc)
        if parsed is None:
            logger.warning(
                "CPM: dropped calendar exception %r, which names no single day. Accepted forms "
                "are %s. That day will be scheduled as a working day.",
                exc,
                ACCEPTED_EXCEPTION_FORMS,
            )
            continue
        result.add(parsed)
    return result


def _add_working_days(
    start: int,
    duration: int,
    work_days: set[int],
    exceptions: set[date],
    project_start: date,
) -> int:
    """Add *duration* working days to *start* (day-offset from project_start).

    Returns the day-offset of the finish date.
    """
    if duration <= 0:
        return start

    current_date = project_start + timedelta(days=start)
    added = 0
    while added < duration:
        current_date += timedelta(days=1)
        if current_date.weekday() in work_days and current_date not in exceptions:
            added += 1
    return (current_date - project_start).days


def _sub_working_days(
    end: int,
    duration: int,
    work_days: set[int],
    exceptions: set[date],
    project_start: date,
) -> int:
    """Subtract *duration* working days from *end* (day-offset).

    Returns the day-offset of the start date.
    """
    if duration <= 0:
        return end

    current_date = project_start + timedelta(days=end)
    subtracted = 0
    while subtracted < duration:
        current_date -= timedelta(days=1)
        if current_date.weekday() in work_days and current_date not in exceptions:
            subtracted += 1
    return (current_date - project_start).days


def _working_days_between(
    start: int,
    end: int,
    work_days: set[int],
    exceptions: set[date],
    project_start: date,
) -> int:
    """Count working days between two day-offsets (exclusive of start, inclusive of end)."""
    if end <= start:
        return 0
    count = 0
    current = project_start + timedelta(days=start)
    target = project_start + timedelta(days=end)
    while current < target:
        current += timedelta(days=1)
        if current.weekday() in work_days and current not in exceptions:
            count += 1
    return count


def _snap_to_working_day(
    offset: int,
    work_days: set[int],
    exceptions: set[date],
    project_start: date,
) -> int:
    """Advance a day-offset to the first working day at or after it.

    A "start no earlier than" floor that lands on a weekend or holiday would
    give an activity an early_start on a non-working day, which is asymmetric
    with the working-day backward pass (``_sub_working_days``) and produces a
    spurious negative total_float and a false ``is_critical``. Snapping the
    floor forward keeps early_start on a working day. An offset already on a
    working day is returned unchanged.
    """
    # A calendar with no working weekday at all (malformed input, e.g. an
    # out-of-range work_days list) would spin forever, so fall back to the
    # offset unchanged. With at least one working weekday the loop always
    # terminates: exceptions is finite, so a working weekday eventually lands
    # outside it.
    if not work_days & {0, 1, 2, 3, 4, 5, 6}:
        return offset
    current = project_start + timedelta(days=offset)
    while current.weekday() not in work_days or current in exceptions:
        current += timedelta(days=1)
    return (current - project_start).days


def offset_to_iso(offset: int, project_start: date) -> str:
    """Project a CPM day-offset back onto an ISO calendar date.

    The forward/backward pass emit integer offsets measured in elapsed
    calendar days from the project origin. Rescheduling turns one back into a
    ``YYYY-MM-DD`` string: ``project_start + offset days``. Kept here (next to
    the engine that produces the offsets) so callers project dates the same
    way the engine measured them.

    Args:
        offset: Day-offset from the CPM origin (may be zero; never negative
            in practice - the forward pass floors early_start at zero).
        project_start: The calendar date the offsets are measured from.

    Returns:
        The ISO date string ``(project_start + offset)``.
    """
    return (project_start + timedelta(days=int(offset))).isoformat()


def _parse_project_start(project_start_date: str | None) -> date:
    """The CPM origin: the given ISO date, else today."""
    if project_start_date:
        try:
            return date.fromisoformat(project_start_date)
        except (ValueError, TypeError):
            return date.today()
    return date.today()


async def calculate_cpm(
    activities: list[dict],
    relationships: list[dict],
    calendar: dict | None = None,
    project_start_date: str | None = None,
    *,
    options: SchedulingOptions | None = None,
) -> list[dict]:
    """Run CPM on a set of activities and relationships.

    With ``options`` (a scheduling profile: data date, actuals, progress mode,
    lag calendar, open ends, critical rule) the pass runs in
    :func:`app.core.cpm_profile.calculate_cpm_with_options`; without it the
    plain planning pass below runs, unchanged.

    Each activity dict must have:
        - id: str (UUID as string)
        - duration: int (working days)
        - name: str (optional, for logging)
        - start_offset: int (optional) - earliest the activity may start, as a
          calendar-day offset from the project origin. Acts as a "start no
          earlier than" floor and defaults to 0. A root (no predecessor) passes
          its own manual start here so its successors are scheduled after it,
          not at the project origin.
        - calendar: dict (optional) - a per-activity work calendar
          ({"work_days": [...], "exceptions": [...]}) so this activity's
          duration is measured on its own work week (e.g. a six-day trade).
          Omitted -> the activity uses the schedule-wide ``calendar`` argument.

    Each relationship dict must have:
        - predecessor_id: str
        - successor_id: str
        - type: str (FS, FF, SS, SF)
        - lag: int (days, can be negative)

    Calendar dict (optional):
        - work_days: list[int] - weekday indices (0=Mon, 6=Sun)
        - exceptions: list[str] - ISO date strings for holidays

    Returns a list of activity dicts with computed CPM fields:
        - early_start, early_finish, late_start, late_finish: int (day offsets)
        - total_float, free_float: int
        - is_critical: bool
    """
    if not activities:
        return []

    if options is not None:
        from app.core.cpm_profile import calculate_cpm_with_options

        return calculate_cpm_with_options(
            activities,
            relationships,
            calendar=calendar,
            project_start=_parse_project_start(project_start_date),
            options=options,
        )

    work_days = _parse_work_days(calendar)
    exceptions = _parse_exceptions(calendar)

    p_start = _parse_project_start(project_start_date)

    # Build lookup structures
    act_map: dict[str, dict] = {}
    for act in activities:
        aid = str(act["id"])
        # Per-activity work calendar. When an activity carries its own
        # ``calendar`` ({"work_days": [...], "exceptions": [...]}) its duration
        # is measured on that work week (e.g. a six-day trade, or a crew with
        # its own holidays); otherwise it uses the schedule-wide default. Both
        # its early_start and late_start are derived with the SAME calendar, so
        # the working-day forward/backward passes stay symmetric.
        act_cal = act.get("calendar")
        act_map[aid] = {
            "id": aid,
            "duration": max(int(act.get("duration", 0)), 0),
            "name": act.get("name", ""),
            # "Start no earlier than" floor as a calendar-day offset from the
            # project origin. 0 (default) lets predecessors alone drive the
            # date; a root passes its own manual start here so its successors
            # anchor after it, not at the origin.
            "start_offset": max(int(act.get("start_offset", 0) or 0), 0),
            "work_days": _parse_work_days(act_cal) if act_cal else work_days,
            "exceptions": _parse_exceptions(act_cal) if act_cal else exceptions,
            "early_start": 0,
            "early_finish": 0,
            "late_start": 0,
            "late_finish": 0,
            "total_float": 0,
            "free_float": 0,
            "is_critical": False,
        }

    # Build adjacency: successors of each activity, and predecessors of each activity
    successors: dict[str, list[dict]] = defaultdict(list)
    predecessors: dict[str, list[dict]] = defaultdict(list)

    for rel in relationships:
        pred_id = str(rel.get("predecessor_id", ""))
        succ_id = str(rel.get("successor_id", ""))
        rel_type = str(rel.get("type", rel.get("relationship_type", "FS"))).upper()
        lag = int(rel.get("lag", rel.get("lag_days", 0)))

        if pred_id not in act_map or succ_id not in act_map:
            continue

        link = {"pred": pred_id, "succ": succ_id, "type": rel_type, "lag": lag}
        successors[pred_id].append(link)
        predecessors[succ_id].append(link)

    # ── Topological sort (Kahn's algorithm) ──────────────────────────────
    in_degree: dict[str, int] = dict.fromkeys(act_map, 0)
    for aid in act_map:
        in_degree[aid] = len(predecessors[aid])

    queue: list[str] = [aid for aid, deg in in_degree.items() if deg == 0]
    topo_order: list[str] = []

    while queue:
        # Process in stable order
        queue.sort()
        current = queue.pop(0)
        topo_order.append(current)
        for link in successors[current]:
            succ_id = link["succ"]
            in_degree[succ_id] -= 1
            if in_degree[succ_id] == 0:
                queue.append(succ_id)

    # If not all activities were sorted, there's a cycle - process remaining
    if len(topo_order) < len(act_map):
        remaining = [aid for aid in act_map if aid not in set(topo_order)]
        logger.warning("CPM: detected cycle involving %d activities", len(remaining))
        topo_order.extend(remaining)

    # ── Forward Pass ─────────────────────────────────────────────────────
    for aid in topo_order:
        act = act_map[aid]
        # "Start no earlier than" floor: a root's own manual start (a nonzero
        # offset), else 0 for a network-driven successor.
        es = act["start_offset"]

        for link in predecessors[aid]:
            pred = act_map[link["pred"]]
            rel_type = link["type"]
            lag = link["lag"]

            if rel_type == "FS":
                candidate = pred["early_finish"] + lag
            elif rel_type == "SS":
                candidate = pred["early_start"] + lag
            elif rel_type == "FF":
                candidate = pred["early_finish"] + lag - act["duration"]
            elif rel_type == "SF":
                candidate = pred["early_start"] + lag - act["duration"]
            else:
                candidate = pred["early_finish"] + lag  # Default to FS

            es = max(es, candidate)

        # Snap the resolved early_start onto THIS activity's own working calendar.
        # An early_start on a day the activity does not work is asymmetric with
        # the working-day backward pass and yields a spurious negative float and
        # a false is_critical. This covers a root starting on its own non-working
        # day (a weekend/holiday, or the whole schedule starting on a non-working
        # origin) AND a predecessor on a different calendar finishing on a day
        # this activity does not work (e.g. a six-day trade feeding a five-day
        # follow-on). Snapping a value already on a working day - every
        # same-calendar case - is a no-op, so existing schedules are unchanged.
        act["early_start"] = max(_snap_to_working_day(es, act["work_days"], act["exceptions"], p_start), 0)
        act["early_finish"] = _add_working_days(
            act["early_start"], act["duration"], act["work_days"], act["exceptions"], p_start
        )

    # ── Project duration ─────────────────────────────────────────────────
    project_finish = max((act_map[aid]["early_finish"] for aid in act_map), default=0)

    # ── Backward Pass ────────────────────────────────────────────────────
    # Initialize late finish to project duration
    for aid in act_map:
        act_map[aid]["late_finish"] = project_finish

    for aid in reversed(topo_order):
        act = act_map[aid]
        lf = project_finish  # latest finish

        for link in successors[aid]:
            succ = act_map[link["succ"]]
            rel_type = link["type"]
            lag = link["lag"]

            if rel_type == "FS":
                candidate = succ["late_start"] - lag
            elif rel_type == "SS":
                candidate = succ["late_start"] - lag + act["duration"]
            elif rel_type == "FF":
                candidate = succ["late_finish"] - lag
            elif rel_type == "SF":
                candidate = succ["late_finish"] - lag + act["duration"]
            else:
                candidate = succ["late_start"] - lag  # Default to FS

            lf = min(lf, candidate)

        act["late_finish"] = lf
        act["late_start"] = _sub_working_days(
            act["late_finish"], act["duration"], act["work_days"], act["exceptions"], p_start
        )

    # ── Float calculation ────────────────────────────────────────────────
    for aid in act_map:
        act = act_map[aid]
        act["total_float"] = act["late_start"] - act["early_start"]

        # Free float: min(ES of successors - EF of this) across all FS successors
        min_ff = None
        for link in successors[aid]:
            succ = act_map[link["succ"]]
            rel_type = link["type"]
            lag = link["lag"]

            if rel_type == "FS":
                ff = succ["early_start"] - act["early_finish"] - lag
            elif rel_type == "SS":
                ff = succ["early_start"] - act["early_start"] - lag
            elif rel_type == "FF":
                ff = succ["early_finish"] - act["early_finish"] - lag
            elif rel_type == "SF":
                ff = succ["early_finish"] - act["early_start"] - lag
            else:
                ff = succ["early_start"] - act["early_finish"] - lag

            if min_ff is None or ff < min_ff:
                min_ff = ff

        act["free_float"] = max(min_ff or 0, 0)

        # Mark critical: total float == 0 (or very close to zero)
        act["is_critical"] = act["total_float"] <= 0

    # Return results as list
    return list(act_map.values())

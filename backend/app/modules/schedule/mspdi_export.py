# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Export a schedule to Microsoft Project XML (MSPDI).

Pure builder: it takes plain activity / predecessor records and returns an
MSPDI XML string. No database, no ORM, no FastAPI - so it is unit-testable on
any Python and round-trips with :mod:`mspdi_import` (same minutes-per-day, constraint and
relationship code maps, lag unit of tenths-of-a-minute, calendars, baseline 0).

The document carries the standard MSP default namespace
``http://schemas.microsoft.com/project`` so Microsoft Project, the importer
here, and other MSPDI-aware tools all read it back.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from xml.etree.ElementTree import Element, SubElement, tostring

MSP_NS = "http://schemas.microsoft.com/project"

# Hours in an MSP working day. Mirrors ``_parse_msp_duration_to_days``.
HOURS_PER_DAY = 8

# Our constraint enum -> MSP ConstraintType code (reverse of the import map).
_CONSTRAINT_TO_MSP: dict[str, str] = {
    "as_soon_as_possible": "0",
    "must_start_on": "1",
    "must_finish_on": "2",
    "start_no_earlier": "3",
    "start_no_later": "4",
    "finish_no_earlier": "5",
    "finish_no_later": "6",
    "as_late_as_possible": "7",
}
# Our relationship type -> MSP link Type code (reverse of the import map).
_REL_TO_MSP: dict[str, str] = {"FF": "0", "FS": "1", "SF": "2", "SS": "3"}


@dataclass
class MspdiActivity:
    """One task in the export, already mapped to integer MSP UIDs."""

    uid: int
    name: str
    start_date: str  # YYYY-MM-DD (or ISO datetime; only the date is used)
    end_date: str
    duration_days: int
    progress_pct: float = 0.0
    activity_type: str = "task"  # task | milestone | summary
    wbs_code: str = ""
    outline_level: int = 1
    constraint_type: str | None = None
    constraint_date: str | None = None
    calendar_uid: int | None = None
    baseline_start: str | None = None
    baseline_end: str | None = None
    baseline_duration_days: int | None = None


@dataclass
class MspdiCalendar:
    """A base working calendar: weekdays Mon=0..Sun=6 and non-working dates."""

    uid: int
    name: str
    work_days: Sequence[int] = (0, 1, 2, 3, 4)
    holidays: Sequence[str] = ()


@dataclass
class MspdiPredecessor:
    """A predecessor link pointing at an earlier task's UID."""

    predecessor_uid: int
    relationship_type: str = "FS"
    lag_days: int = 0


@dataclass
class MspdiProject:
    """The whole export payload."""

    name: str
    activities: Sequence[MspdiActivity] = field(default_factory=list)
    # successor UID -> its predecessor links.
    predecessors_by_uid: Mapping[int, Sequence[MspdiPredecessor]] = field(default_factory=dict)
    hours_per_day: float = HOURS_PER_DAY
    calendars: Sequence[MspdiCalendar] = field(default_factory=list)
    project_calendar_uid: int | None = None


def _msp_datetime(date_str: str, hour: int) -> str:
    """Normalise a ``YYYY-MM-DD`` (or ISO datetime) to MSP ``...T08:00:00``."""
    day = (date_str or "")[:10]
    if not day:
        return ""
    return f"{day}T{hour:02d}:00:00"


def _msp_duration(duration_days: int, hours_per_day: float = HOURS_PER_DAY) -> str:
    """Render whole days as an MSP ISO-8601 duration on the project's working day."""
    minutes = round(max(0, int(duration_days)) * hours_per_day * 60)
    return f"PT{minutes // 60}H{minutes % 60}M0S"


def _percent(progress_pct: float) -> str:
    try:
        pct = round(float(progress_pct))
    except (TypeError, ValueError):
        pct = 0
    return str(max(0, min(100, pct)))


# Python weekday (Mon=0) -> MSP DayType (Sun=1..Sat=7).
_WEEKDAY_TO_MSP = {6: "1", 0: "2", 1: "3", 2: "4", 3: "5", 4: "6", 5: "7"}


def _calendars(parent: Element, calendars: Sequence[MspdiCalendar]) -> None:
    for cal in calendars:
        cal_el = SubElement(parent, "Calendar")
        SubElement(cal_el, "UID").text = str(cal.uid)
        SubElement(cal_el, "Name").text = cal.name or f"Calendar {cal.uid}"
        SubElement(cal_el, "IsBaseCalendar").text = "1"
        week_el = SubElement(cal_el, "WeekDays")
        working = set(cal.work_days)
        for weekday in range(7):
            day_el = SubElement(week_el, "WeekDay")
            SubElement(day_el, "DayType").text = _WEEKDAY_TO_MSP[weekday]
            SubElement(day_el, "DayWorking").text = "1" if weekday in working else "0"
        for holiday in cal.holidays:
            day = (holiday or "")[:10]
            if not day:
                continue
            exc_el = SubElement(week_el, "WeekDay")
            SubElement(exc_el, "DayType").text = "0"
            SubElement(exc_el, "DayWorking").text = "0"
            period = SubElement(exc_el, "TimePeriod")
            SubElement(period, "FromDate").text = f"{day}T00:00:00"
            SubElement(period, "ToDate").text = f"{day}T23:59:00"


def build_mspdi_xml(project: MspdiProject) -> str:
    """Build an MSPDI XML document string from a project payload."""
    root = Element("Project")
    # Default namespace as a literal attribute - re-parsing applies it to every
    # unprefixed child, which is exactly what MSP-aware readers expect.
    root.set("xmlns", MSP_NS)
    SubElement(root, "Name").text = project.name or "Schedule"
    SubElement(root, "Title").text = project.name or "Schedule"
    # Minutes-based duration math; 7 == "days" display format in MSP.
    SubElement(root, "DurationFormat").text = "7"
    minutes_per_day = round(project.hours_per_day * 60)
    tenths_per_day = minutes_per_day * 10
    SubElement(root, "MinutesPerDay").text = str(minutes_per_day)
    SubElement(root, "MinutesPerWeek").text = str(minutes_per_day * 5)
    if project.project_calendar_uid is not None:
        SubElement(root, "CalendarUID").text = str(project.project_calendar_uid)
    if project.calendars:
        _calendars(SubElement(root, "Calendars"), project.calendars)

    tasks_el = SubElement(root, "Tasks")
    for order, act in enumerate(project.activities, start=1):
        task_el = SubElement(tasks_el, "Task")
        SubElement(task_el, "UID").text = str(act.uid)
        SubElement(task_el, "ID").text = str(order)
        SubElement(task_el, "Name").text = act.name or ""
        SubElement(task_el, "OutlineLevel").text = str(max(1, act.outline_level))
        if act.wbs_code:
            SubElement(task_el, "WBS").text = act.wbs_code
        is_milestone = act.activity_type == "milestone" or act.duration_days <= 0
        is_summary = act.activity_type == "summary"
        SubElement(task_el, "Type").text = "1"  # fixed duration
        SubElement(task_el, "Start").text = _msp_datetime(act.start_date, 8)
        SubElement(task_el, "Finish").text = _msp_datetime(act.end_date, 17)
        SubElement(task_el, "Duration").text = _msp_duration(act.duration_days, project.hours_per_day)
        SubElement(task_el, "DurationFormat").text = "7"
        SubElement(task_el, "PercentComplete").text = _percent(act.progress_pct)
        SubElement(task_el, "Milestone").text = "1" if is_milestone else "0"
        SubElement(task_el, "Summary").text = "1" if is_summary else "0"

        if act.calendar_uid is not None:
            SubElement(task_el, "CalendarUID").text = str(act.calendar_uid)

        msp_constraint = _CONSTRAINT_TO_MSP.get(act.constraint_type or "")
        if msp_constraint is not None:
            SubElement(task_el, "ConstraintType").text = msp_constraint
            if act.constraint_date:
                SubElement(task_el, "ConstraintDate").text = _msp_datetime(act.constraint_date, 8)

        for link in project.predecessors_by_uid.get(act.uid, []):
            link_el = SubElement(task_el, "PredecessorLink")
            SubElement(link_el, "PredecessorUID").text = str(link.predecessor_uid)
            SubElement(link_el, "Type").text = _REL_TO_MSP.get(link.relationship_type, "1")
            SubElement(link_el, "LinkLag").text = str(int(link.lag_days) * tenths_per_day)
            SubElement(link_el, "LagFormat").text = "7"

        if act.baseline_start and act.baseline_end:
            bl_el = SubElement(task_el, "Baseline")
            SubElement(bl_el, "Number").text = "0"
            SubElement(bl_el, "Start").text = _msp_datetime(act.baseline_start, 8)
            SubElement(bl_el, "Finish").text = _msp_datetime(act.baseline_end, 17)
            if act.baseline_duration_days is not None:
                SubElement(bl_el, "Duration").text = _msp_duration(act.baseline_duration_days, project.hours_per_day)

    body = tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body

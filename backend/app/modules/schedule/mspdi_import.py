# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Read a Microsoft Project XML (MSPDI) file into plain records.

Pure reader: bytes in, :class:`MspdiDocument` out. No database, no ORM, no
FastAPI, so the preview, the apply step and the round-trip tests all read a
file the same way. It is the inverse of :mod:`mspdi_export`.

What is read: tasks (UID, name, WBS, outline level -> parent, start, finish,
duration on the file's own minutes-per-day, percent complete, summary and
milestone flags, constraint, calendar, baseline 0), predecessor links (type
and lag), and calendars (working weekdays and non-working exception dates).

Nothing is invented. A task without dates keeps empty dates and is reported;
a problem the planner has to see becomes an :class:`MspdiIssue` that the
``schedule_mspdi_import`` validation rules turn into the preview report.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # noqa: S405 - element types only; parsing goes through defusedxml
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import defusedxml.ElementTree as safe_ET
from defusedxml.common import DefusedXmlException

#: MSP link ``Type`` code -> our relationship type.
LINK_TYPES: dict[str, str] = {"0": "FF", "1": "FS", "2": "SF", "3": "SS"}
#: MSP ``ConstraintType`` code -> our constraint name.
CONSTRAINT_TYPES: dict[str, str] = {
    "0": "as_soon_as_possible",
    "1": "must_start_on",
    "2": "must_finish_on",
    "3": "start_no_earlier",
    "4": "start_no_later",
    "5": "finish_no_earlier",
    "6": "finish_no_later",
    "7": "as_late_as_possible",
}
DEFAULT_MINUTES_PER_DAY = 480
#: MSP ``DayType`` 1..7 is Sunday..Saturday; ours is Python's Monday=0..Sunday=6.
_MSP_DAY_TO_WEEKDAY: dict[str, int] = {"1": 6, "2": 0, "3": 1, "4": 2, "5": 3, "6": 4, "7": 5}
#: Exception ranges longer than this are not expanded into single dates.
_MAX_HOLIDAYS = 730
_DURATION = re.compile(
    r"^-?P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?$"
)

ERROR = "error"
WARNING = "warning"


class MspdiReadError(ValueError):
    """The file cannot be read as MSPDI at all (``code`` says why)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


@dataclass
class MspdiIssue:
    """One problem found while reading; ``ref`` is a task UID or ``calendar:<uid>``."""

    code: str
    severity: str
    ref: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class MspdiTask:
    uid: str
    name: str
    wbs: str = ""
    outline_level: int = 1
    parent_uid: str | None = None
    start: str = ""
    finish: str = ""
    duration_days: int | None = None
    percent_complete: float = 0.0
    activity_type: str = "task"
    constraint_type: str | None = None
    constraint_date: str | None = None
    calendar_uid: str | None = None
    baseline_start: str | None = None
    baseline_finish: str | None = None
    baseline_duration_days: int | None = None
    order: int = 0


@dataclass
class MspdiLink:
    predecessor_uid: str
    successor_uid: str
    relationship_type: str = "FS"
    lag_days: int = 0


@dataclass
class MspdiCalendarRecord:
    uid: str
    name: str
    work_days: list[int] = field(default_factory=list)
    holidays: list[str] = field(default_factory=list)
    hours_per_day: float = 8.0
    is_base: bool = True


@dataclass
class MspdiDocument:
    name: str = ""
    minutes_per_day: int = DEFAULT_MINUTES_PER_DAY
    project_calendar_uid: str | None = None
    tasks: list[MspdiTask] = field(default_factory=list)
    links: list[MspdiLink] = field(default_factory=list)
    calendars: list[MspdiCalendarRecord] = field(default_factory=list)
    issues: list[MspdiIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(i.severity == ERROR for i in self.issues)

    def validation_payload(self) -> dict[str, Any]:
        """The ``{"issues": [...]}`` payload the ``schedule_mspdi_import`` rules read."""
        names = {t.uid: t.name for t in self.tasks}
        return {
            "issues": [
                {"code": i.code, "severity": i.severity, "ref": i.ref, "name": names.get(i.ref, ""), **i.params}
                for i in self.issues
            ]
        }


class _Reader:
    def __init__(self, root: ET.Element) -> None:
        self.ns = root.tag.split("}")[0] + "}" if root.tag.startswith("{") else ""

    def find(self, parent: ET.Element, tag: str) -> ET.Element | None:
        found = parent.find(f"{self.ns}{tag}")
        return found if found is not None else parent.find(tag)

    def findall(self, parent: ET.Element, tag: str) -> list[ET.Element]:
        return parent.findall(f"{self.ns}{tag}") or parent.findall(tag)

    def text(self, parent: ET.Element, tag: str) -> str:
        el = self.find(parent, tag)
        return (el.text or "").strip() if el is not None else ""


def _minutes(value: str) -> float | None:
    """Minutes in an ISO-8601 MSP duration (``PT40H0M0S``, ``P5DT0H``), or None."""
    m = _DURATION.match(value.strip()) if value else None
    if not m:
        return None
    d, h, mi, s = (float(g) if g else 0.0 for g in m.groups())
    total = d * 24 * 60 + h * 60 + mi + s / 60
    return -total if value.strip().startswith("-") else total


def _days(value: str, minutes_per_day: int) -> int | None:
    total = _minutes(value)
    if total is None:
        return None
    return max(0, round(total / minutes_per_day))


def _day(value: str) -> str:
    """``YYYY-MM-DD`` of an MSP datetime, or "" when it is not a date."""
    head = (value or "")[:10]
    try:
        return date.fromisoformat(head).isoformat()
    except ValueError:
        return ""


def _int(value: str, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _read_calendars(
    r: _Reader, root: ET.Element, minutes_per_day: int, issues: list[MspdiIssue]
) -> list[MspdiCalendarRecord]:
    out: list[MspdiCalendarRecord] = []
    cals_el = r.find(root, "Calendars")
    if cals_el is None:
        return out
    for cal_el in r.findall(cals_el, "Calendar"):
        uid = r.text(cal_el, "UID")
        if not uid:
            continue
        work: set[int] = set()
        holidays: list[str] = []
        stated = False
        week_el = r.find(cal_el, "WeekDays")
        for wd in r.findall(week_el, "WeekDay") if week_el is not None else []:
            day_type = r.text(wd, "DayType")
            working = r.text(wd, "DayWorking") == "1"
            if day_type in _MSP_DAY_TO_WEEKDAY:
                stated = True
                if working:
                    work.add(_MSP_DAY_TO_WEEKDAY[day_type])
            elif day_type == "0" and not working:
                period = r.find(wd, "TimePeriod")
                start = _day(r.text(period, "FromDate")) if period is not None else ""
                end = _day(r.text(period, "ToDate")) if period is not None else ""
                if start:
                    d0, d1 = date.fromisoformat(start), date.fromisoformat(end or start)
                    while d0 <= d1 and len(holidays) < _MAX_HOLIDAYS:
                        holidays.append(d0.isoformat())
                        d0 += timedelta(days=1)
        # A derived calendar that states no weekdays inherits its base; Mon-Fri stands in.
        work_days = sorted(work) if stated else [0, 1, 2, 3, 4]
        if stated and not work_days:
            issues.append(MspdiIssue("calendar_no_work_days", WARNING, f"calendar:{uid}", {"calendar": uid}))
        out.append(
            MspdiCalendarRecord(
                uid=uid,
                name=r.text(cal_el, "Name") or f"Calendar {uid}",
                work_days=work_days,
                holidays=sorted(set(holidays)),
                hours_per_day=round(minutes_per_day / 60, 2),
                is_base=r.text(cal_el, "IsBaseCalendar") != "0",
            )
        )
    return out


def parse_mspdi(raw: bytes) -> MspdiDocument:
    """Read an MSPDI file. Raises :class:`MspdiReadError` when it is not one.

    Parsed from bytes on purpose: MSPDI states its encoding in the XML
    declaration and ElementTree honours it only for bytes.
    """
    try:
        root = safe_ET.fromstring(raw)
    except DefusedXmlException as exc:
        raise MspdiReadError("rejected", "XML rejected for security reasons") from exc
    except ET.ParseError as exc:
        raise MspdiReadError("invalid_xml", f"Invalid XML: {exc}") from exc

    r = _Reader(root)
    tasks_el = r.find(root, "Tasks")
    task_els = r.findall(tasks_el, "Task") if tasks_el is not None else []
    if not task_els:
        raise MspdiReadError("no_tasks", "No Task elements found in MSP XML")

    minutes_per_day = _int(r.text(root, "MinutesPerDay"), DEFAULT_MINUTES_PER_DAY) or DEFAULT_MINUTES_PER_DAY
    doc = MspdiDocument(
        name=r.text(root, "Name") or r.text(root, "Title"),
        minutes_per_day=minutes_per_day,
        project_calendar_uid=r.text(root, "CalendarUID") or None,
    )
    doc.calendars = _read_calendars(r, root, minutes_per_day, doc.issues)
    calendar_uids = {c.uid for c in doc.calendars}

    seen: set[str] = set()
    stack: list[tuple[int, str]] = []  # (outline level, uid) of the open ancestors
    raw_links: list[tuple[str, ET.Element]] = []
    for order, el in enumerate(task_els):
        uid = r.text(el, "UID")
        name = r.text(el, "Name")
        level = _int(r.text(el, "OutlineLevel"), 1)
        if uid == "0" or level == 0 or not uid:
            continue  # the project summary row, or an empty placeholder row
        if not name:
            continue
        if uid in seen:
            doc.issues.append(MspdiIssue("duplicate_uid", ERROR, uid, {"name": name}))
            continue
        seen.add(uid)

        while stack and stack[-1][0] >= level:
            stack.pop()
        parent = stack[-1][1] if stack else None
        if level > (stack[-1][0] if stack else 0) + 1:
            doc.issues.append(MspdiIssue("outline_gap", WARNING, uid, {"level": level}))
        stack.append((level, uid))

        start, finish = _day(r.text(el, "Start")), _day(r.text(el, "Finish"))
        if not start or not finish:
            doc.issues.append(MspdiIssue("missing_dates", ERROR, uid))
        elif finish < start:
            doc.issues.append(MspdiIssue("finish_before_start", ERROR, uid, {"start": start, "finish": finish}))

        pct_text = r.text(el, "PercentComplete")
        pct = float(_int(pct_text, 0)) if pct_text else 0.0
        if not 0.0 <= pct <= 100.0:
            doc.issues.append(MspdiIssue("percent_out_of_range", WARNING, uid, {"value": pct_text}))
            pct = min(100.0, max(0.0, pct))

        duration_text = r.text(el, "Duration")
        duration = _days(duration_text, minutes_per_day) if duration_text else None
        if r.text(el, "Summary") == "1":
            kind = "summary"
        elif r.text(el, "Milestone") == "1" or (duration == 0 and duration_text):
            kind = "milestone"
        else:
            kind = "task"

        cal = r.text(el, "CalendarUID")
        task = MspdiTask(
            uid=uid,
            name=name,
            wbs=r.text(el, "WBS"),
            outline_level=level,
            parent_uid=parent,
            start=start,
            finish=finish,
            duration_days=duration,
            percent_complete=pct,
            activity_type=kind,
            constraint_type=CONSTRAINT_TYPES.get(r.text(el, "ConstraintType")),
            constraint_date=_day(r.text(el, "ConstraintDate")) or None,
            calendar_uid=cal if cal in calendar_uids else None,
            order=order,
        )
        for bl in r.findall(el, "Baseline"):
            if r.text(bl, "Number") in ("", "0"):
                task.baseline_start = _day(r.text(bl, "Start")) or None
                task.baseline_finish = _day(r.text(bl, "Finish")) or None
                bl_dur = r.text(bl, "Duration")
                task.baseline_duration_days = _days(bl_dur, minutes_per_day) if bl_dur else None
        doc.tasks.append(task)
        raw_links.extend((uid, link_el) for link_el in r.findall(el, "PredecessorLink"))

    linked: set[tuple[str, str]] = set()
    for succ, link_el in raw_links:
        pred = r.text(link_el, "PredecessorUID")
        if pred == succ:
            doc.issues.append(MspdiIssue("self_link", WARNING, succ))
            continue
        if pred not in seen:
            doc.issues.append(MspdiIssue("dangling_link", WARNING, succ, {"predecessor": pred}))
            continue
        if (pred, succ) in linked:
            doc.issues.append(MspdiIssue("duplicate_link", WARNING, succ, {"predecessor": pred}))
            continue
        linked.add((pred, succ))
        type_code = r.text(link_el, "Type") or "1"
        if type_code not in LINK_TYPES:
            doc.issues.append(MspdiIssue("unknown_link_type", WARNING, succ, {"type": type_code}))
        # LinkLag is in tenths of a minute whatever LagFormat displays.
        lag_tenths = _int(r.text(link_el, "LinkLag"), 0)
        doc.links.append(
            MspdiLink(
                predecessor_uid=pred,
                successor_uid=succ,
                relationship_type=LINK_TYPES.get(type_code, "FS"),
                lag_days=round(lag_tenths / (10 * minutes_per_day)),
            )
        )
    return doc

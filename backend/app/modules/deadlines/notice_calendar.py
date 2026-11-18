# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Statutory notice and lien calendar - pure date arithmetic, no I/O.

Lien and payment statutes in many markets set a deadline in one of three ways,
and this module knows exactly those three. It knows no statute: every rule it
evaluates comes from a jurisdiction table a market pack ships, so the same code
answers a California preliminary notice, a Texas monthly notice and a Florida
notice to owner.

Rule types:

* ``days_after_event`` - ``days`` calendar days after an event (negative for
  "at least N days before"). A preliminary notice served 20 days after first
  furnishing, a claim of lien 90 days after final furnishing.
* ``months_after_event`` - ``months`` calendar months after the event date, the
  day clamped to the end of a shorter month. A lien filed within 8 months of
  the last work.
* ``nth_day_of_mth_month`` - day ``day_of_month`` of the ``months``-th month
  after the month of the event. A notice due by the 15th day of the third month
  after the month the work was done. With ``event == "work_month"`` the rule
  runs once per month of work the caller lists.

An event may also be another rule's deadline (``"rule:<code>"``), which is how
"sue within one year of the last day to file the affidavit" is written.

A rule with ``supersedes`` replaces the rules it names whenever its own event
is known: recording a notice of completion shortens the 90 day window, so the
rule keyed on that event supersedes the 90 day one.

Every computed deadline carries its source. The calendar never files anything
and never advises: the UI prints the source and "verify with counsel" next to
each date.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

DAYS_AFTER_EVENT = "days_after_event"
MONTHS_AFTER_EVENT = "months_after_event"
NTH_DAY_OF_MTH_MONTH = "nth_day_of_mth_month"
RULE_TYPES: frozenset[str] = frozenset({DAYS_AFTER_EVENT, MONTHS_AFTER_EVENT, NTH_DAY_OF_MTH_MONTH})

#: The event that fans a monthly rule out over the months of work.
WORK_MONTH_EVENT = "work_month"
_RULE_EVENT_PREFIX = "rule:"

STATUS_UPCOMING = "upcoming"
STATUS_DUE_TODAY = "due_today"
STATUS_OVERDUE = "overdue"


class NoticeRuleError(ValueError):
    """A jurisdiction table carries a rule this engine cannot evaluate."""


@dataclass(frozen=True)
class NoticeRule:
    """One deadline rule, as a market pack declares it."""

    code: str
    name: str
    rule_type: str
    event: str
    source: str
    kind: str = "notice"
    days: int | None = None
    months: int | None = None
    day_of_month: int | None = None
    claimant_roles: tuple[str, ...] = ()
    project_types: tuple[str, ...] = ()
    sectors: tuple[str, ...] = ()
    supersedes: tuple[str, ...] = ()
    source_url: str = ""

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> NoticeRule:
        """Build a rule from a pack table entry, rejecting a malformed one loudly."""
        rule = cls(
            code=str(raw["code"]),
            name=str(raw.get("name") or raw["code"]),
            rule_type=str(raw["rule_type"]),
            event=str(raw["event"]),
            source=str(raw.get("source") or ""),
            kind=str(raw.get("kind") or "notice"),
            days=_opt_int(raw.get("days")),
            months=_opt_int(raw.get("months")),
            day_of_month=_opt_int(raw.get("day_of_month")),
            claimant_roles=tuple(raw.get("claimant_roles") or ()),
            project_types=tuple(raw.get("project_types") or ()),
            sectors=tuple(raw.get("sectors") or ()),
            supersedes=tuple(raw.get("supersedes") or ()),
            source_url=str(raw.get("source_url") or ""),
        )
        rule.check()
        return rule

    def check(self) -> None:
        """Raise :class:`NoticeRuleError` when the rule cannot be evaluated."""
        if self.rule_type not in RULE_TYPES:
            raise NoticeRuleError(f"{self.code}: unknown rule_type {self.rule_type!r}")
        if not self.source.strip():
            raise NoticeRuleError(f"{self.code}: a deadline without a source cannot be shown")
        if self.rule_type == DAYS_AFTER_EVENT and self.days is None:
            raise NoticeRuleError(f"{self.code}: days_after_event needs days")
        if self.rule_type == MONTHS_AFTER_EVENT and not self.months:
            raise NoticeRuleError(f"{self.code}: months_after_event needs months")
        if self.rule_type == NTH_DAY_OF_MTH_MONTH:
            if self.months is None or self.day_of_month is None:
                raise NoticeRuleError(f"{self.code}: nth_day_of_mth_month needs months and day_of_month")
            if not 1 <= self.day_of_month <= 31:
                raise NoticeRuleError(f"{self.code}: day_of_month must be 1..31")

    def applies(self, *, role: str | None, project_type: str | None, sector: str | None) -> bool:
        """Whether the rule reaches this claimant on this project."""
        if self.claimant_roles and role and role not in self.claimant_roles:
            return False
        if self.project_types and project_type and project_type not in self.project_types:
            return False
        return not (self.sectors and sector and sector not in self.sectors)


@dataclass(frozen=True)
class NoticeDue:
    """One computed deadline."""

    code: str
    name: str
    kind: str
    due_date: date
    event: str
    event_date: date
    period: str
    status: str
    days_left: int
    source: str
    source_url: str = ""

    def as_dict(self) -> dict[str, Any]:
        """JSON-ready form, dates as ISO strings."""
        return {
            "code": self.code,
            "name": self.name,
            "kind": self.kind,
            "due_date": self.due_date.isoformat(),
            "event": self.event,
            "event_date": self.event_date.isoformat(),
            "period": self.period,
            "status": self.status,
            "days_left": self.days_left,
            "source": self.source,
            "source_url": self.source_url,
        }


@dataclass
class CalendarInput:
    """The facts a calendar is computed from."""

    events: dict[str, date] = field(default_factory=dict)
    work_months: list[tuple[int, int]] = field(default_factory=list)
    role: str | None = None
    project_type: str | None = None
    sector: str | None = None
    today: date | None = None


def _opt_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def add_months(start: date, months: int) -> date:
    """``start`` moved by whole calendar months, the day clamped to the month's end."""
    index = start.year * 12 + (start.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(start.day, last))


def nth_day_of_mth_month(year: int, month: int, months_after: int, day_of_month: int) -> date:
    """Day ``day_of_month`` of the month ``months_after`` months after ``year-month``."""
    anchor = add_months(date(year, month, 1), months_after)
    last = calendar.monthrange(anchor.year, anchor.month)[1]
    return date(anchor.year, anchor.month, min(day_of_month, last))


def _status(due: date, today: date | None) -> tuple[str, int]:
    if today is None:
        return STATUS_UPCOMING, 0
    days_left = (due - today).days
    if days_left < 0:
        return STATUS_OVERDUE, days_left
    if days_left == 0:
        return STATUS_DUE_TODAY, 0
    return STATUS_UPCOMING, days_left


def parse_rules(table: list[dict[str, Any]]) -> list[NoticeRule]:
    """Parse a pack's notice table, failing on the first malformed rule."""
    return [NoticeRule.from_dict(raw) for raw in table]


def compute_calendar(rules: list[NoticeRule], facts: CalendarInput) -> list[NoticeDue]:
    """Every deadline the facts trigger, earliest first.

    A rule whose event is unknown is skipped rather than guessed: a calendar
    that invents a completion date would print a deadline nobody can rely on.
    """
    applicable = [r for r in rules if r.applies(role=facts.role, project_type=facts.project_type, sector=facts.sector)]
    superseded: set[str] = set()
    for rule in applicable:
        if rule.supersedes and _event_known(rule, facts):
            superseded.update(rule.supersedes)

    computed: dict[str, list[NoticeDue]] = {}
    # Two passes resolve one level of ``rule:`` chaining, which is all a
    # statute needs (affidavit -> suit); deeper chains are rejected.
    pending = [r for r in applicable if r.code not in superseded]
    for _ in range(2):
        still: list[NoticeRule] = []
        for rule in pending:
            if rule.event.startswith(_RULE_EVENT_PREFIX):
                parent = rule.event[len(_RULE_EVENT_PREFIX) :]
                if parent not in computed:
                    still.append(rule)
                    continue
                computed[rule.code] = [
                    _due(rule, base.due_date, rule.event, base.period, facts.today) for base in computed[parent]
                ]
                continue
            computed[rule.code] = _evaluate(rule, facts)
        pending = still

    out = [item for items in computed.values() for item in items]
    out.sort(key=lambda d: (d.due_date, d.code, d.period))
    return out


def _event_known(rule: NoticeRule, facts: CalendarInput) -> bool:
    if rule.event == WORK_MONTH_EVENT:
        return bool(facts.work_months)
    return rule.event in facts.events


def _evaluate(rule: NoticeRule, facts: CalendarInput) -> list[NoticeDue]:
    if rule.event == WORK_MONTH_EVENT:
        if rule.rule_type != NTH_DAY_OF_MTH_MONTH:
            raise NoticeRuleError(f"{rule.code}: work_month only drives nth_day_of_mth_month rules")
        out = []
        for year, month in sorted(set(facts.work_months)):
            due = nth_day_of_mth_month(year, month, rule.months or 0, rule.day_of_month or 1)
            status, days_left = _status(due, facts.today)
            out.append(
                NoticeDue(
                    code=rule.code,
                    name=rule.name,
                    kind=rule.kind,
                    due_date=due,
                    event=rule.event,
                    event_date=date(year, month, 1),
                    period=f"{year:04d}-{month:02d}",
                    status=status,
                    days_left=days_left,
                    source=rule.source,
                    source_url=rule.source_url,
                )
            )
        return out
    event_date = facts.events.get(rule.event)
    if event_date is None:
        return []
    return [_due(rule, event_date, rule.event, "", facts.today)]


def _due(rule: NoticeRule, event_date: date, event: str, period: str, today: date | None) -> NoticeDue:
    if rule.rule_type == DAYS_AFTER_EVENT:
        due = event_date + timedelta(days=rule.days or 0)
    elif rule.rule_type == MONTHS_AFTER_EVENT:
        due = add_months(event_date, rule.months or 0)
    else:
        due = nth_day_of_mth_month(event_date.year, event_date.month, rule.months or 0, rule.day_of_month or 1)
    status, days_left = _status(due, today)
    return NoticeDue(
        code=rule.code,
        name=rule.name,
        kind=rule.kind,
        due_date=due,
        event=event,
        event_date=event_date,
        period=period,
        status=status,
        days_left=days_left,
        source=rule.source,
        source_url=rule.source_url,
    )


__all__ = [
    "DAYS_AFTER_EVENT",
    "MONTHS_AFTER_EVENT",
    "NTH_DAY_OF_MTH_MONTH",
    "RULE_TYPES",
    "STATUS_DUE_TODAY",
    "STATUS_OVERDUE",
    "STATUS_UPCOMING",
    "WORK_MONTH_EVENT",
    "CalendarInput",
    "NoticeDue",
    "NoticeRule",
    "NoticeRuleError",
    "add_months",
    "compute_calendar",
    "nth_day_of_mth_month",
    "parse_rules",
]

# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pay​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ rules: split approved hours into pay types by a country or agreement profile.

Pure and framework-free. A profile (``country_data/payroll_rules.json``) is data:
daily overtime tiers, a weekly overtime threshold, a night window with an additive
premium, weekend and public holiday multipliers, a per diem, legal daily and weekly
maxima and the employer burden percentage. Nothing here names a country.

Classification, per employee:

1. A public holiday hour is ``holiday``; a Saturday or Sunday hour with a profile
   multiplier for that day is ``saturday`` / ``sunday``.
2. Other hours are ``regular`` up to the first daily tier, then ``overtime`` at the
   tier multiplier.
3. Regular hours above the weekly threshold in one ISO week become
   ``overtime_weekly``, taken from the latest days first.
4. Hours inside the night window add a ``night_premium`` line (hours x rate x pct);
   the base hours keep their own type.
5. A day with at least the per diem minimum hours earns one ``per_diem``.

Money is Decimal, rounded once per output line with ROUND_HALF_UP.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any

_RULES_PATH = Path(__file__).resolve().parents[2] / "core" / "country_data" / "payroll_rules.json"
_CENT = Decimal("0.01")
_HOUR_Q = Decimal("0.01")
NEUTRAL_PROFILE = "neutral"

PAY_TYPES: tuple[str, ...] = (
    "regular",
    "overtime",
    "overtime_weekly",
    "night_premium",
    "saturday",
    "sunday",
    "holiday",
    "per_diem",
)
OVERTIME_TYPES = frozenset({"overtime", "overtime_weekly"})


def dec(value: Any, default: Decimal | None = None) -> Decimal | None:
    """Parse a Decimal; ``default`` for blanks and garbage (never float)."""
    if value is None or value == "" or isinstance(value, bool):
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default


@lru_cache(maxsize=1)
def load_profiles() -> dict[str, dict[str, Any]]:
    """Every rule profile on disk keyed by its id."""
    rows = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
    return {str(r["profile"]): r for r in rows if isinstance(r, dict) and r.get("profile")}


def profile_for(profile_id: str | None = None, country: str | None = None) -> dict[str, Any]:
    """The named profile, else the first profile of the country, else neutral."""
    profiles = load_profiles()
    if profile_id and profile_id in profiles:
        return profiles[profile_id]
    code = (country or "").strip().upper()
    if code:
        for row in profiles.values():
            if str(row.get("country") or "").upper() == code:
                return row
    return profiles[NEUTRAL_PROFILE]


@dataclass(frozen=True)
class WorkLine:
    """One approved labour line, already netted of reversals."""

    employee_id: str
    employee_name: str
    work_date: date
    hours: Decimal
    rate: Decimal
    cost_code: str = ""
    project_id: str = ""
    started_at: datetime | None = None
    ended_at: datetime | None = None
    overtime_approved: bool = False
    source_ref: str = ""


@dataclass
class PayLine:
    """One payroll export line: an employee, a day, a cost code and a pay type."""

    employee_id: str
    employee_name: str
    work_date: date
    cost_code: str
    project_id: str
    pay_type: str
    hours: Decimal
    rate: Decimal
    multiplier: Decimal
    amount: Decimal
    overtime_approved: bool = False
    source_refs: list[str] = field(default_factory=list)


def _clock(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def night_hours(start: datetime | None, end: datetime | None, window: Mapping[str, Any] | None) -> Decimal:
    """Hours of ``[start, end)`` inside the night window (which may cross midnight).

    Clock times are read as site-local wall time, the way a timesheet records them.
    """
    if not window or start is None or end is None or end <= start:
        return Decimal("0")
    s = start.replace(tzinfo=None)
    e = end.replace(tzinfo=None)
    w_start, w_end = _clock(str(window["start"])), _clock(str(window["end"]))
    total = timedelta(0)
    day = s.date() - timedelta(days=1)
    while day <= e.date():
        ws = datetime.combine(day, w_start)
        we = datetime.combine(day if w_end > w_start else day + timedelta(days=1), w_end)
        lo, hi = max(s, ws), min(e, we)
        if hi > lo:
            total += hi - lo
        day += timedelta(days=1)
    return (Decimal(int(total.total_seconds())) / Decimal(3600)).quantize(_HOUR_Q, rounding=ROUND_HALF_UP)


def _money(hours: Decimal, rate: Decimal, multiplier: Decimal) -> Decimal:
    return (hours * rate * multiplier).quantize(_CENT, rounding=ROUND_HALF_UP)


def _tiers(profile: Mapping[str, Any]) -> list[tuple[Decimal, Decimal]]:
    out = []
    for tier in profile.get("daily_overtime") or []:
        after, mult = dec(tier.get("after")), dec(tier.get("multiplier"))
        if after is not None and mult is not None:
            out.append((after, mult))
    return sorted(out)


def _day_kind(day: date, profile: Mapping[str, Any], holidays: set[date]) -> tuple[str, Decimal] | None:
    if day in holidays and dec(profile.get("holiday_multiplier")) is not None:
        return "holiday", dec(profile.get("holiday_multiplier"))  # type: ignore[return-value]
    weekend = profile.get("weekend") or {}
    name = {5: "saturday", 6: "sunday"}.get(day.weekday())
    if name and dec(weekend.get(name)) is not None:
        return name, dec(weekend.get(name))  # type: ignore[return-value]
    return None


def classify(
    lines: Iterable[WorkLine],
    profile: Mapping[str, Any],
    holidays: Iterable[date] = (),
) -> list[PayLine]:
    """Split work lines into pay lines under one profile (see the module docstring)."""
    holiday_set = set(holidays)
    tiers = _tiers(profile)
    by_emp_day: dict[tuple[str, date], list[WorkLine]] = defaultdict(list)
    for line in lines:
        if line.hours > 0:
            by_emp_day[(line.employee_id, line.work_date)].append(line)

    out: list[PayLine] = []
    regular_by_week: dict[tuple[str, int, int], list[PayLine]] = defaultdict(list)

    def emit(src: WorkLine, pay_type: str, hours: Decimal, mult: Decimal) -> PayLine:
        row = PayLine(
            employee_id=src.employee_id,
            employee_name=src.employee_name,
            work_date=src.work_date,
            cost_code=src.cost_code,
            project_id=src.project_id,
            pay_type=pay_type,
            hours=hours,
            rate=src.rate,
            multiplier=mult,
            amount=_money(hours, src.rate, mult),
            overtime_approved=src.overtime_approved,
            source_refs=[src.source_ref] if src.source_ref else [],
        )
        out.append(row)
        return row

    for (emp, day), day_lines in sorted(by_emp_day.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        day_lines.sort(key=lambda ln: ln.started_at.replace(tzinfo=None) if ln.started_at else datetime.min)
        special = _day_kind(day, profile, holiday_set)
        worked = Decimal("0")
        for src in day_lines:
            if special is not None:
                emit(src, special[0], src.hours, special[1])
            else:
                remaining = src.hours
                cursor = worked
                bounds = [(Decimal("0"), Decimal("1"), "regular")] + [(a, m, "overtime") for a, m in tiers]
                for idx, (start, mult, kind) in enumerate(bounds):
                    stop = bounds[idx + 1][0] if idx + 1 < len(bounds) else None
                    if remaining <= 0:
                        break
                    if stop is not None and cursor >= stop:
                        continue
                    room = remaining if stop is None else min(remaining, stop - max(cursor, start))
                    if room <= 0:
                        continue
                    row = emit(src, kind, room, mult)
                    if kind == "regular":
                        iso = day.isocalendar()
                        regular_by_week[(emp, iso[0], iso[1])].append(row)
                    cursor += room
                    remaining -= room
            worked += src.hours
            night = profile.get("night")
            n_hours = min(night_hours(src.started_at, src.ended_at, night), src.hours) if night else Decimal("0")
            if n_hours > 0:
                pct = dec(night.get("premium_pct"), Decimal("0")) / Decimal(100)  # type: ignore[union-attr,operator]
                emit(src, "night_premium", n_hours, pct)
        per_diem = profile.get("per_diem")
        if per_diem and worked >= (dec(per_diem.get("min_hours"), Decimal("0")) or Decimal("0")):
            first = day_lines[0]
            amount = dec(per_diem.get("amount"), Decimal("0")) or Decimal("0")
            out.append(
                PayLine(
                    employee_id=emp,
                    employee_name=first.employee_name,
                    work_date=day,
                    cost_code=first.cost_code,
                    project_id=first.project_id,
                    pay_type="per_diem",
                    hours=Decimal("0"),
                    rate=amount,
                    multiplier=Decimal("1"),
                    amount=amount.quantize(_CENT, rounding=ROUND_HALF_UP),
                )
            )

    weekly_after = dec(profile.get("weekly_overtime_after"))
    weekly_mult = dec(profile.get("weekly_overtime_multiplier"), Decimal("1.5")) or Decimal("1.5")
    if weekly_after is not None:
        for rows in regular_by_week.values():
            excess = sum((r.hours for r in rows), Decimal("0")) - weekly_after
            for row in sorted(rows, key=lambda r: r.work_date, reverse=True):
                if excess <= 0:
                    break
                take = min(excess, row.hours)
                row.hours -= take
                row.amount = _money(row.hours, row.rate, row.multiplier)
                out.append(
                    PayLine(
                        employee_id=row.employee_id,
                        employee_name=row.employee_name,
                        work_date=row.work_date,
                        cost_code=row.cost_code,
                        project_id=row.project_id,
                        pay_type="overtime_weekly",
                        hours=take,
                        rate=row.rate,
                        multiplier=weekly_mult,
                        amount=_money(take, row.rate, weekly_mult),
                        overtime_approved=row.overtime_approved,
                        source_refs=list(row.source_refs),
                    )
                )
                excess -= take
    out = [r for r in out if r.hours > 0 or r.pay_type == "per_diem"]
    out.sort(key=lambda r: (r.employee_name, r.work_date, PAY_TYPES.index(r.pay_type), r.cost_code))
    return out


def max_hours_breaches(lines: Iterable[WorkLine], profile: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Employee days and ISO weeks above the profile's legal maximum."""
    max_day, max_week = dec(profile.get("max_hours_per_day")), dec(profile.get("max_hours_per_week"))
    days: dict[tuple[str, str, date], Decimal] = defaultdict(Decimal)
    weeks: dict[tuple[str, str, str], Decimal] = defaultdict(Decimal)
    for ln in lines:
        days[(ln.employee_id, ln.employee_name, ln.work_date)] += ln.hours
        iso = ln.work_date.isocalendar()
        weeks[(ln.employee_id, ln.employee_name, f"{iso[0]}-W{iso[1]:02d}")] += ln.hours
    out: list[dict[str, Any]] = []
    if max_day is not None:
        for (emp, name, day), hours in sorted(days.items(), key=lambda kv: (kv[0][1], kv[0][2])):
            if hours > max_day:
                out.append(
                    {
                        "employee_id": emp,
                        "employee": name,
                        "scope": "day",
                        "period": day.isoformat(),
                        "hours": str(hours),
                        "limit": str(max_day),
                    }
                )
    if max_week is not None:
        for (emp, name, week), hours in sorted(weeks.items(), key=lambda kv: (kv[0][1], kv[0][2])):
            if hours > max_week:
                out.append(
                    {
                        "employee_id": emp,
                        "employee": name,
                        "scope": "week",
                        "period": week,
                        "hours": str(hours),
                        "limit": str(max_week),
                    }
                )
    return out


def burden(gross: Decimal, profile: Mapping[str, Any]) -> Decimal:
    """Employer social charges on a gross amount at the profile's burden percentage."""
    pct = dec(profile.get("burden_pct"), Decimal("0")) or Decimal("0")
    return (gross * pct / Decimal(100)).quantize(_CENT, rounding=ROUND_HALF_UP)


def totals_by_type(lines: Iterable[PayLine]) -> dict[str, dict[str, str]]:
    """``{pay_type: {"hours", "amount"}}`` as Decimal strings."""
    acc: dict[str, list[Decimal]] = {}
    for ln in lines:
        h, a = acc.setdefault(ln.pay_type, [Decimal("0"), Decimal("0")])
        acc[ln.pay_type] = [h + ln.hours, a + ln.amount]
    return {k: {"hours": str(v[0]), "amount": str(v[1])} for k, v in acc.items()}

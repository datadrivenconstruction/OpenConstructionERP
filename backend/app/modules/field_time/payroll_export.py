# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Worked-hours export for an external payroll system: pure aggregation, planning and writing.

No framework, ORM or I/O. We never compute pay: this turns approved labour hours into rows
(worker x day or week x project x cost code x hour type) in the column layout of an export
profile, and plans correction rows against what earlier runs already exported.

Rows of a run are the difference between the current approved hours of a key and the sum of
everything earlier runs exported for that key. A first export of a key is a normal row; a
later difference is a ``correction`` row (signed), even when its date lies outside the period.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

HOUR_TYPES: tuple[str, ...] = ("regular", "overtime", "night", "travel", "standby", "leave", "other")
DEFAULT_HOUR_TYPE = "regular"
GROUP_DAY = "day"
GROUP_WEEK = "week"

#: Values a column can take from. Anything else in a column is a fixed text.
SOURCES: tuple[str, ...] = (
    "worker_ref",
    "worker_name",
    "date",
    "project_code",
    "cost_code",
    "pay_code",
    "hour_type",
    "hours",
    "correction",
)

_ZERO = Decimal("0")
_CENTS = Decimal("0.01")
_ENCODINGS = {"utf-8", "utf-8-sig", "cp1252", "latin-1"}


@dataclass(frozen=True)
class Column:
    """One output column: ``source`` names a field, ``constant`` is fixed text when no source."""

    header: str
    source: str = ""
    constant: str = ""


@dataclass(frozen=True)
class ExportProfile:
    """The layout and rules of one export."""

    name: str = ""
    columns: tuple[Column, ...] = ()
    delimiter: str = ";"
    decimal: str = ","
    date_format: str = "DD.MM.YYYY"
    encoding: str = "utf-8"
    grouping: str = GROUP_DAY
    week_start: int = 0  # 0 = Monday
    include_daywork: bool = True
    include_header: bool = True
    fallback_to_code: bool = False
    day_threshold: Decimal | None = None
    pay_codes: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ExportProfile:
        threshold = data.get("day_threshold")
        return cls(
            name=str(data.get("name") or ""),
            columns=tuple(
                Column(str(c.get("header") or ""), str(c.get("source") or ""), str(c.get("constant") or ""))
                for c in data.get("columns") or ()
            ),
            delimiter=str(data.get("delimiter") or ";"),
            decimal=str(data.get("decimal") or ","),
            date_format=str(data.get("date_format") or "DD.MM.YYYY"),
            encoding=str(data.get("encoding") or "utf-8") if str(data.get("encoding")) in _ENCODINGS else "utf-8",
            grouping=GROUP_WEEK if data.get("grouping") == GROUP_WEEK else GROUP_DAY,
            week_start=int(data.get("week_start") or 0) % 7,
            include_daywork=bool(data.get("include_daywork", True)),
            include_header=bool(data.get("include_header", True)),
            fallback_to_code=bool(data.get("fallback_to_code", False)),
            day_threshold=Decimal(str(threshold)) if threshold not in (None, "") else None,
            pay_codes={str(k): str(v) for k, v in (data.get("pay_codes") or {}).items() if str(v).strip()},
        )


@dataclass(frozen=True)
class HourLine:
    """One approved labour line. ``sign`` is -1 on a reversing timesheet."""

    resource_id: str
    worker_name: str
    payroll_ref: str
    resource_code: str
    work_date: date
    project_id: str
    project_code: str
    cost_code: str
    hour_type: str
    hours: Decimal
    sign: int = 1
    is_daywork: bool = False


Key = tuple[str, date, str, str, str]  # resource_id, period date, project_id, cost_code, hour_type


@dataclass
class Row:
    """One planned output row; ``hours`` is signed, ``correction`` marks a delta of an earlier export."""

    key: Key
    worker_ref: str
    worker_name: str
    project_code: str
    hours: Decimal
    correction: bool


def quantize(value: Decimal) -> Decimal:
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def period_date(day: date, profile: ExportProfile) -> date:
    """The row date: the day itself, or the last day of its week for week grouping."""
    if profile.grouping != GROUP_WEEK:
        return day
    return day + timedelta(days=(profile.week_start + 6 - day.weekday()) % 7)


def worker_ref(line: HourLine, profile: ExportProfile) -> str:
    """Payroll reference of the worker; the resource code only when the profile allows it."""
    ref = line.payroll_ref.strip()
    if ref:
        return ref
    return line.resource_code.strip() if profile.fallback_to_code else ""


def usable(line: HourLine, profile: ExportProfile) -> bool:
    return profile.include_daywork or not line.is_daywork


def current_hours(lines: Iterable[HourLine], profile: ExportProfile) -> dict[Key, Decimal]:
    """Signed approved hours per key, reversals netted (sums are exact, rounded only on output)."""
    out: dict[Key, Decimal] = defaultdict(lambda: _ZERO)
    for line in lines:
        if not usable(line, profile):
            continue
        key = (
            line.resource_id,
            period_date(line.work_date, profile),
            line.project_id,
            line.cost_code.strip(),
            line.hour_type or DEFAULT_HOUR_TYPE,
        )
        out[key] += line.sign * line.hours
    return dict(out)


def plan_rows(
    lines: Sequence[HourLine],
    exported: Mapping[Key, Decimal],
    period_from: date,
    period_to: date,
    profile: ExportProfile,
) -> list[Row]:
    """Rows of the next run.

    A key inside the period is exported when it has never been exported. A key that was
    exported before, inside or outside the period, produces a correction when its current
    hours differ from the sum of earlier exports.
    """
    current = current_hours(lines, profile)
    meta: dict[Key, HourLine] = {}
    for line in lines:
        meta.setdefault(
            (
                line.resource_id,
                period_date(line.work_date, profile),
                line.project_id,
                line.cost_code.strip(),
                line.hour_type or DEFAULT_HOUR_TYPE,
            ),
            line,
        )
    rows: list[Row] = []
    for key in set(current) | set(exported):
        before = quantize(exported.get(key, _ZERO))
        now = quantize(current.get(key, _ZERO))
        in_period = period_from <= key[1] <= period_to
        was_exported = key in exported
        if not was_exported and not in_period:
            continue
        delta = now - before
        if delta == 0:
            continue
        line = meta.get(key)
        rows.append(
            Row(
                key=key,
                worker_ref=worker_ref(line, profile) if line else "",
                worker_name=line.worker_name if line else "",
                project_code=line.project_code if line else "",
                hours=delta,
                correction=was_exported,
            )
        )
    rows.sort(
        key=lambda r: (r.worker_ref, r.key[1], r.project_code, r.key[3], profile.pay_codes.get(r.key[4], r.key[4]))
    )
    return rows


def format_date(value: date, pattern: str) -> str:
    return (
        pattern.replace("YYYY", f"{value.year:04d}")
        .replace("YY", f"{value.year % 100:02d}")
        .replace("MM", f"{value.month:02d}")
        .replace("DD", f"{value.day:02d}")
    )


def format_hours(value: Decimal, decimal: str) -> str:
    text = f"{quantize(value):f}"
    return text.replace(".", decimal) if decimal != "." else text


def cell(row: Row, column: Column, profile: ExportProfile) -> str:
    source = column.source
    if not source:
        return column.constant
    if source == "worker_ref":
        return row.worker_ref
    if source == "worker_name":
        return row.worker_name
    if source == "date":
        return format_date(row.key[1], profile.date_format)
    if source == "project_code":
        return row.project_code
    if source == "cost_code":
        return row.key[3]
    if source == "hour_type":
        return row.key[4]
    if source == "pay_code":
        return profile.pay_codes.get(row.key[4], "")
    if source == "hours":
        return format_hours(row.hours, profile.decimal)
    if source == "correction":
        return "1" if row.correction else ""
    return ""


def render(rows: Sequence[Row], profile: ExportProfile) -> bytes:
    """The export file: optional header, one line per row, ``\\r\\n`` line ends."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=profile.delimiter, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    if profile.include_header:
        writer.writerow([c.header for c in profile.columns])
    for row in rows:
        writer.writerow([cell(row, c, profile) for c in profile.columns])
    return buffer.getvalue().encode(profile.encoding, errors="replace")


# ── Validation (payexp.*) ───────────────────────────────────────────────────


def _issue(rule_id: str, severity: str, message: str, **params: Any) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "severity": severity,
        "message": message,
        "details": {"message_key": f"validation.{rule_id}", **{k: str(v) for k, v in params.items()}},
    }


def check_run(
    lines: Sequence[HourLine],
    profile: ExportProfile,
    *,
    unapproved_refs: Sequence[str] = (),
    overlapping_runs: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Every ``payexp.*`` finding for the lines of one period (all projects of the run)."""
    issues: list[dict[str, Any]] = []
    live = [ln for ln in lines if usable(ln, profile)]

    missing: dict[str, str] = {}
    for ln in live:
        if not worker_ref(ln, profile):
            missing.setdefault(ln.resource_id, ln.worker_name or ln.resource_code)
    for rid, name in sorted(missing.items(), key=lambda kv: kv[1]):
        issues.append(
            _issue(
                "payexp.worker_without_ref",
                "error",
                f"{name} has no payroll reference; set it on the resource.",
                worker=name,
                resource_id=rid,
            )
        )

    per_day: dict[tuple[str, date], Decimal] = defaultdict(lambda: _ZERO)
    names: dict[str, str] = {}
    for ln in live:
        per_day[(ln.resource_id, ln.work_date)] += ln.sign * ln.hours
        names[ln.resource_id] = ln.worker_name or ln.resource_code
    for (rid, day), total in sorted(per_day.items(), key=lambda kv: (names[kv[0][0]], kv[0][1])):
        name = names[rid]
        if total > 24:
            issues.append(
                _issue(
                    "payexp.day_over_24h",
                    "error",
                    f"{name} has {quantize(total)} h on {day.isoformat()} across projects.",
                    worker=name,
                    h=quantize(total),
                    date=day.isoformat(),
                )
            )
        elif profile.day_threshold is not None and total > profile.day_threshold:
            issues.append(
                _issue(
                    "payexp.day_over_threshold",
                    "warning",
                    f"{name} has {quantize(total)} h on {day.isoformat()}, above the profile threshold.",
                    worker=name,
                    h=quantize(total),
                    date=day.isoformat(),
                )
            )

    for hour_type in sorted({ln.hour_type or DEFAULT_HOUR_TYPE for ln in live}):
        if hour_type not in profile.pay_codes and any(c.source == "pay_code" for c in profile.columns):
            issues.append(
                _issue(
                    "payexp.hour_type_unmapped",
                    "error",
                    f"Hour type {hour_type} has no pay code in profile {profile.name}.",
                    t=hour_type,
                    p=profile.name,
                )
            )

    if any(not ln.cost_code.strip() for ln in live):
        issues.append(
            _issue("payexp.cost_code_missing", "warning", "Line without cost code exported under project only.")
        )

    for ref in unapproved_refs:
        issues.append(_issue("payexp.not_approved", "info", f"Timesheet {ref} not approved; left out.", ref=ref))
    for run in overlapping_runs:
        issues.append(
            _issue(
                "payexp.period_overlap", "warning", f"Period overlaps run {run}; only corrections will be added.", r=run
            )
        )

    totals = current_hours(live, profile)
    by_worker_day: dict[tuple[str, date], Decimal] = defaultdict(lambda: _ZERO)
    for (rid, day, _pid, _cc, _ht), hours in totals.items():
        by_worker_day[(rid, day)] += hours
    for (rid, day), total in sorted(by_worker_day.items(), key=lambda kv: (names.get(kv[0][0], ""), kv[0][1])):
        if total < 0:
            issues.append(
                _issue(
                    "payexp.negative_total",
                    "error",
                    f"Net hours for {names.get(rid, rid)}/{day.isoformat()} below zero after reversals.",
                    worker=names.get(rid, rid),
                    date=day.isoformat(),
                )
            )
    return issues

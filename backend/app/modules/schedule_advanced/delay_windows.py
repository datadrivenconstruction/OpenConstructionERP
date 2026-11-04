# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Window generation for the Windows delay method.

An analyst should not have to date every window by hand. Windows are cut either
at the dates of the stored schedule snapshots (baselines) or at month / quarter
ends. Each boundary is then served by the latest snapshot captured on or before
it, so the finish movement between two boundaries is the movement the snapshots
actually recorded. A window with no snapshot of its own is flagged, because its
slip cannot be placed there.

Pure and DB-free, like :mod:`delay_engine`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal

__all__ = [
    "WindowMode",
    "WindowSpec",
    "SnapshotPoint",
    "baseline_durations",
    "build_windows",
    "pick_snapshot",
    "workday_index",
]

WindowMode = Literal["snapshot", "month", "quarter"]

#: Upper bound so a decades-long project cannot create hundreds of windows.
MAX_WINDOWS = 60


@dataclass(frozen=True)
class SnapshotPoint:
    """A stored schedule snapshot: its name, data date and per-task durations."""

    name: str
    data_date: date
    durations: dict[str, int]


@dataclass(frozen=True)
class WindowSpec:
    """One proposed window between two data dates."""

    sequence_order: int
    opens: date
    closes: date
    open_workday: int
    close_workday: int
    snapshot_open: str | None
    snapshot_close: str | None
    #: Both ends read the same snapshot (or none), so no slip can be seen inside.
    no_snapshot: bool


def workday_index(project_start: date, day: date) -> int:
    """Mon-Fri days from ``project_start`` up to (not including) ``day``; never negative."""
    if day <= project_start:
        return 0
    full_weeks, rest = divmod((day - project_start).days, 7)
    count = full_weeks * 5
    cursor = project_start + timedelta(days=full_weeks * 7)
    for i in range(rest):
        if (cursor + timedelta(days=i)).weekday() < 5:
            count += 1
    return count


def _parse(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def baseline_durations(snapshot: Any) -> dict[str, int]:
    """Working-day duration per task id from a stored baseline payload.

    Uses the row's own ``duration`` / ``duration_days`` when present, otherwise
    the working days from ``planned_start`` to ``planned_finish`` inclusive.
    """
    rows = snapshot.get("tasks") if isinstance(snapshot, dict) else snapshot
    out: dict[str, int] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        ref = row.get("task_ref") or row.get("id")
        if not ref:
            continue
        raw = row.get("duration_days", row.get("duration"))
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            out[str(ref)] = max(0, int(raw))
            continue
        start, finish = _parse(row.get("planned_start")), _parse(row.get("planned_finish"))
        if start and finish and finish >= start:
            out[str(ref)] = workday_index(start, finish + timedelta(days=1))
    return out


def _month_starts(start: date, end: date, step: int) -> list[date]:
    out: list[date] = []
    y, m = start.year, start.month
    while True:
        m += 1
        if m > 12:
            y, m = y + 1, 1
        d = date(y, m, 1)
        if d >= end:
            return out
        if step == 1 or (d.month - 1) % step == 0:
            out.append(d)


def pick_snapshot(boundary: date, snapshots: list[SnapshotPoint]) -> SnapshotPoint | None:
    """Latest snapshot captured on or before ``boundary`` (the earliest one if none is)."""
    if not snapshots:
        return None
    ordered = sorted(snapshots, key=lambda s: s.data_date)
    eligible = [s for s in ordered if s.data_date <= boundary]
    return eligible[-1] if eligible else ordered[0]


def build_windows(
    mode: WindowMode,
    project_start: date,
    data_date: date,
    snapshots: list[SnapshotPoint],
) -> list[WindowSpec]:
    """Contiguous windows between ``project_start`` and ``data_date``.

    Args:
        mode: ``snapshot`` cuts at each snapshot date, ``month`` / ``quarter`` at
            calendar month / quarter starts.
        project_start: First day of the project (workday zero).
        data_date: Closing date of the last window (the current schedule).
        snapshots: Stored snapshots; may be empty.

    Returns:
        Windows in order, at most :data:`MAX_WINDOWS`. Empty when the span is empty.
    """
    if data_date <= project_start:
        return []
    if mode == "snapshot":
        cuts = sorted({s.data_date for s in snapshots if project_start < s.data_date < data_date})
    else:
        cuts = _month_starts(project_start, data_date, 1 if mode == "month" else 3)
    bounds = [project_start, *cuts, data_date]
    if len(bounds) - 1 > MAX_WINDOWS:
        bounds = [*bounds[:MAX_WINDOWS], data_date]
    windows: list[WindowSpec] = []
    for i in range(len(bounds) - 1):
        lo, hi = bounds[i], bounds[i + 1]
        a = pick_snapshot(lo, snapshots)
        # The last window closes on the current schedule, not on a snapshot.
        b = None if hi >= data_date else pick_snapshot(hi, snapshots)
        windows.append(
            WindowSpec(
                sequence_order=i + 1,
                opens=lo,
                closes=hi,
                open_workday=workday_index(project_start, lo),
                close_workday=workday_index(project_start, hi),
                snapshot_open=a.name if a else None,
                snapshot_close=b.name if b else None,
                no_snapshot=a is None or (b is not None and a is b),
            )
        )
    return windows

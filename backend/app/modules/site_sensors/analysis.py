# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure helpers over a reading series: gaps, temperature jumps, rolling means, sparklines.

Readings are ``(time, value)`` pairs in any order; nothing here touches the database.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from statistics import median
from typing import Any

__all__ = ["TEMP_MAX_C", "TEMP_MAX_JUMP_K_PER_H", "TEMP_MIN_C", "reading_stats", "rolling_mean", "sparkline"]

#: A concrete probe outside this range or jumping faster than this is miswired, not curing.
TEMP_MIN_C = -30.0
TEMP_MAX_C = 90.0
TEMP_MAX_JUMP_K_PER_H = 15.0


def reading_stats(rows: Sequence[tuple[datetime, float]]) -> dict[str, Any]:
    """Usual interval, longest gap, fastest change per hour and the value range of a series.

    The usual interval is the median gap, so one outage does not stretch it.
    Returns an empty dict with fewer than three readings.
    """
    pts = sorted(rows, key=lambda r: r[0])
    if len(pts) < 3:
        return {}
    gaps = [(b[0] - a[0]).total_seconds() / 60.0 for a, b in zip(pts, pts[1:], strict=False)]
    jumps = [
        abs(b[1] - a[1]) / (g / 60.0) for (a, b), g in zip(zip(pts, pts[1:], strict=False), gaps, strict=True) if g > 0
    ]
    return {
        "interval_min": round(median(gaps), 2),
        "max_gap_min": round(max(gaps), 2),
        "max_jump_per_h": round(max(jumps), 2) if jumps else 0.0,
        "min": min(v for _, v in pts),
        "max": max(v for _, v in pts),
    }


def rolling_mean(rows: Sequence[tuple[datetime, float]], end: datetime, hours: float = 24.0) -> float | None:
    """Mean of the readings in ``(end - hours, end]``, None when there are none."""
    start = end - timedelta(hours=hours)
    vals = [v for t, v in rows if start < t <= end]
    return sum(vals) / len(vals) if vals else None


def sparkline(rows: Sequence[tuple[datetime, float]], end: datetime, hours: int = 24) -> list[float | None]:
    """One mean per hour over the last ``hours`` hours, oldest first; None for an hour without readings."""
    start = end - timedelta(hours=hours)
    buckets: list[list[float]] = [[] for _ in range(hours)]
    for t, v in rows:
        if start < t <= end:
            idx = min(hours - 1, int((t - start).total_seconds() // 3600))
            buckets[idx].append(v)
    return [round(sum(b) / len(b), 2) if b else None for b in buckets]

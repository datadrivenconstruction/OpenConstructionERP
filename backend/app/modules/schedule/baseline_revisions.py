# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Programme baselines as numbered revisions: B0, B1, B2, ...

A baseline is an immutable snapshot (``ScheduleBaseline.snapshot_data``). A
planner captures the live schedule as a saved version, reviews it with the diff
engine, then approves it; the approved one is the schedule's effective
baseline, the one the Gantt overlay and the printed Gantt compare against.
``Activity.revision`` is an optimistic-concurrency token and is not involved.

Approval stores ``metadata["approval"] = {"approved_by", "approved_at"}`` and
flips ``is_active``; the snapshot itself never changes. Pure helpers only; the
routes live in :mod:`app.modules.schedule.router`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

__all__ = ["approval_of", "effective_baseline", "next_baseline_label"]

_LABEL = re.compile(r"^\s*[Bb](\d{1,4})\b")


def next_baseline_label(existing_names: Iterable[str]) -> str:
    """The label for the next capture: one past the highest ``B<n>``, ``B0`` when none.

    Names that do not start with ``B<n>`` (a free-text baseline from the older
    form) are ignored, so they never block the numbering.
    """
    numbers = [int(m.group(1)) for name in existing_names if (m := _LABEL.match(str(name or "")))]
    return f"B{max(numbers) + 1}" if numbers else "B0"


def approval_of(baseline: Mapping[str, Any]) -> dict[str, Any] | None:
    """The approval stamp of a baseline row, or ``None`` when it was never approved."""
    meta = baseline.get("metadata") or baseline.get("metadata_") or {}
    stamp = meta.get("approval") if isinstance(meta, Mapping) else None
    return dict(stamp) if isinstance(stamp, Mapping) and stamp.get("approved_at") else None


def effective_baseline(baselines: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """The one approved baseline of a schedule, deterministically.

    Among active rows the latest approval wins; rows without a stamp (legacy
    data, where several could be active) rank by creation time after stamped
    ones. ``None`` when no row is active.
    """
    active = [b for b in baselines if b.get("is_active")]
    if not active:
        return None

    def rank(row: Mapping[str, Any]) -> tuple[int, str, str]:
        stamp = approval_of(row)
        return (1 if stamp else 0, str(stamp["approved_at"]) if stamp else "", str(row.get("created_at") or ""))

    return max(active, key=rank)

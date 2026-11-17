# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Revision impact: which BOQ positions and variations sit on the activities a revision changed.

Pure: it takes the schedule diff (:func:`diff_engine.diff_snapshots`), the two
envelopes it was computed from, and the BOQ positions / variation requests
already looked up by id, and returns one row per revised activity with its
before/after dates, finish movement, duration and planned-cost deltas, the
positions it is linked to (``Activity.boq_position_ids``, taken from the
baseline for an activity the later plan removed) and the variations that
touch those positions (``VariationBOQTrace``).

A progress-only change (percent, status, actual dates) is an update, not a
revision, so it is left out. Nothing is written; the planner reads this
before approving the next baseline.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from app.modules.schedule.diff_engine import DiffResult, _activity_key

#: Change categories that make an activity part of a revision.
REVISION_CATEGORIES = frozenset({"dates", "duration", "scope", "cost", "constraint", "calendar"})


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value.normalize(), "f")
    return "0" if text in ("-0", "") else text


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _index(env: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in env.get("activities") or []:
        if isinstance(row, dict) and (key := _activity_key(row)) is not None:
            out[key[1] or ""] = row
    return out


def linked_position_ids(*envs: Mapping[str, Any]) -> set[str]:
    """Every BOQ position id either envelope links to (for the caller's lookup)."""
    return {
        str(pid)
        for env in envs
        for row in env.get("activities") or []
        if isinstance(row, dict)
        for pid in row.get("boq_position_ids") or []
    }


def build_revision_impact(
    diff: DiffResult,
    base_env: Mapping[str, Any],
    target_env: Mapping[str, Any],
    *,
    positions: Mapping[str, Mapping[str, Any]],
    variations: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """One row per revised activity plus a summary. Money as plain decimal strings."""
    base_idx, target_idx = _index(base_env), _index(target_env)
    rows: list[dict[str, Any]] = []
    seen_positions: dict[str, Decimal] = {}
    seen_variations: set[str] = set()
    cost_total = Decimal("0")

    for change in diff.activities:
        if change.change_type == "modified" and not REVISION_CATEGORIES.intersection(change.categories):
            continue
        before = base_idx.get(change.key) if change.change_type != "added" else None
        after = target_idx.get(change.key) if change.change_type != "removed" else None
        source = after or before or {}
        link_ids = [str(p) for p in (source.get("boq_position_ids") or [])]

        cost_before = _dec(before.get("cost_planned")) if before else None
        cost_after = _dec(after.get("cost_planned")) if after else None
        cost_delta = None
        if cost_before is not None or cost_after is not None:
            cost_delta = (cost_after or Decimal("0")) - (cost_before or Decimal("0"))
            cost_total += cost_delta

        dur_before = _int(before.get("duration_days")) if before else None
        dur_after = _int(after.get("duration_days")) if after else None

        linked: list[dict[str, Any]] = []
        linked_value = Decimal("0")
        for pid in link_ids:
            pos = positions.get(pid)
            vars_ = [dict(v) for v in variations.get(pid, [])]
            seen_variations.update(str(v.get("code") or v.get("id")) for v in vars_)
            if pos is None:
                linked.append({"id": pid, "missing": True, "variations": vars_})
                continue
            total = _dec(pos.get("total")) or Decimal("0")
            linked_value += total
            seen_positions[pid] = total
            linked.append(
                {
                    "id": pid,
                    "missing": False,
                    "ordinal": pos.get("ordinal") or "",
                    "description": pos.get("description") or "",
                    "unit": pos.get("unit") or "",
                    "quantity": pos.get("quantity"),
                    "total": _money(total),
                    "boq_id": str(pos["boq_id"]) if pos.get("boq_id") else None,
                    "variations": vars_,
                }
            )
        for pid in link_ids:
            seen_positions.setdefault(pid, Decimal("0"))

        rows.append(
            {
                "activity_id": change.key,
                "name": change.name or source.get("name") or "",
                "wbs_code": change.wbs_code or source.get("wbs_code") or "",
                "change_type": change.change_type,
                "categories": list(change.categories),
                "start_before": (before or {}).get("start_date"),
                "start_after": (after or {}).get("start_date"),
                "finish_before": (before or {}).get("end_date"),
                "finish_after": (after or {}).get("end_date"),
                "finish_movement_days": change.finish_movement_days,
                "duration_before": dur_before,
                "duration_after": dur_after,
                "duration_delta_days": (dur_after - dur_before)
                if dur_before is not None and dur_after is not None
                else None,
                "cost_before": _money(cost_before),
                "cost_after": _money(cost_after),
                "cost_delta": _money(cost_delta),
                "linked_value": _money(linked_value),
                "positions": linked,
            }
        )

    rows.sort(
        key=lambda r: (
            -abs(r["finish_movement_days"] or 0),
            -abs(_dec(r["cost_delta"]) or Decimal("0")),
            r["name"],
        )
    )
    linked_rows = sum(1 for r in rows if r["positions"])
    return {
        "activities": rows,
        "summary": {
            "activities_revised": len(rows),
            "activities_linked": linked_rows,
            "activities_unlinked": len(rows) - linked_rows,
            "positions_linked": len(seen_positions),
            "variations_linked": len(seen_variations),
            "cost_delta_total": _money(cost_total),
            "linked_value_total": _money(sum(seen_positions.values(), Decimal("0"))),
            "net_finish_movement_days": diff.summary.net_finish_movement_days,
        },
    }

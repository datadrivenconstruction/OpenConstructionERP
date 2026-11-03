# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure cost-at-date allocation for the 4D view (5D slice).

Each task's money (BAC, earned value) is split over the elements linked to it,
by quantity weight when every element carries one, else equally. The split is
done in whole minor units with the largest-remainder rule, so the shares of one
task add up to the task's amount exactly and the whole allocation reconciles to
BAC to the cent. Money that no element can carry (tasks without a resolved
element) is reported as ``unlinked_cost`` instead of being dropped.

No database, no I/O: the service feeds :class:`TaskCost` rows in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

from app.core.money import money_quantum

#: Elements returned individually; the rest is folded into ``other_elements_cost``.
MAX_ELEMENTS = 500

#: Quantity keys tried in order when weighting a split.
WEIGHT_KEYS: tuple[str, ...] = ("volume", "area", "length", "count")

#: Coverage below this percentage triggers ``schedule.4d.cost_coverage_low``.
COVERAGE_LOW_PCT = 80.0

_STATUS_RANK = {"completed": 0, "ahead_of_schedule": 1, "not_started": 2, "in_progress": 3, "delayed": 4}


@dataclass
class TaskCost:
    """One task's money and the elements that carry it."""

    status: str
    bac: Decimal
    ev: Decimal
    pv: Decimal = Decimal("0")
    ac: Decimal = Decimal("0")
    element_ids: list[str] = field(default_factory=list)
    #: Per-element weights (same keys as ``element_ids``); ``None`` means equal split.
    weights: dict[str, Decimal] | None = None


def pick_weights(elements: dict[str, dict], ids: list[str]) -> dict[str, Decimal] | None:
    """Return quantity weights for ``ids`` when one quantity key is positive on all of them."""
    if not ids:
        return None
    for key in WEIGHT_KEYS:
        out: dict[str, Decimal] = {}
        for eid in ids:
            raw = (elements.get(eid) or {}).get("quantities", {}).get(key)
            try:
                value = Decimal(str(raw))
            except Exception:  # noqa: BLE001 - any non-numeric quantity disqualifies the key
                value = Decimal("0")
            if not value.is_finite() or value <= 0:
                break
            out[eid] = value
        else:
            return out
    return None


def split_amount(total: Decimal, weights: list[Decimal], currency: str) -> list[Decimal]:
    """Split ``total`` over ``weights`` in whole minor units; the parts sum to ``total`` exactly."""
    quantum = money_quantum(currency)
    total = total.quantize(quantum, rounding=ROUND_HALF_UP)
    if not weights:
        return []
    weight_sum = sum(weights, Decimal("0"))
    if weight_sum <= 0:
        weights = [Decimal("1")] * len(weights)
        weight_sum = Decimal(len(weights))
    raw = [total * w / weight_sum for w in weights]
    parts = [r.quantize(quantum, rounding=ROUND_FLOOR) for r in raw]
    leftover = total - sum(parts, Decimal("0"))
    steps = int((leftover / quantum).to_integral_value())
    order = sorted(range(len(parts)), key=lambda i: raw[i] - parts[i], reverse=True)
    for i in order[:steps]:
        parts[i] += quantum
    return parts


def build_cost_snapshot(tasks: list[TaskCost], currency: str, *, cap: int = MAX_ELEMENTS) -> dict:
    """Allocate task money to elements and return the wire-shaped payload (money as strings)."""
    quantum = money_quantum(currency)
    zero = Decimal("0")

    def q(value: Decimal) -> Decimal:
        return value.quantize(quantum, rounding=ROUND_HALF_UP)

    bac_total = pv_total = ev_total = ac_total = zero
    allocated = zero
    per_el: dict[str, dict] = {}
    for task in tasks:
        bac_total += q(task.bac)
        pv_total += q(task.pv)
        ev_total += q(task.ev)
        ac_total += q(task.ac)
        ids = list(dict.fromkeys(task.element_ids))  # an element listed twice on one task counts once
        if not ids:
            continue
        use_qty = task.weights is not None and all(i in task.weights for i in ids)
        weights = [task.weights[i] for i in ids] if use_qty and task.weights else [Decimal("1")] * len(ids)
        planned = split_amount(task.bac, weights, currency)
        earned = split_amount(task.ev, weights, currency)
        allocated += sum(planned, zero)
        for eid, p, e in zip(ids, planned, earned, strict=True):
            row = per_el.setdefault(
                eid,
                {"status": task.status, "planned_cost": zero, "earned_cost": zero, "allocation": "quantity"},
            )
            if _STATUS_RANK.get(task.status, 0) > _STATUS_RANK.get(row["status"], 0):
                row["status"] = task.status
            row["planned_cost"] += p
            row["earned_cost"] += e
            if not use_qty:
                row["allocation"] = "equal"

    unlinked = bac_total - allocated
    coverage = float(allocated / bac_total * 100) if bac_total > 0 else 0.0

    by_status: dict[str, dict] = {}
    for row in per_el.values():
        bucket = by_status.setdefault(row["status"], {"elements": 0, "planned_cost": zero})
        bucket["elements"] += 1
        bucket["planned_cost"] += row["planned_cost"]

    ranked = sorted(per_el.items(), key=lambda kv: (-kv[1]["planned_cost"], kv[0]))
    shown, rest = ranked[:cap], ranked[cap:]
    return {
        "totals": {"pv": pv_total, "ev": ev_total, "ac": ac_total, "bac": bac_total},
        "by_status": {k: {"elements": v["elements"], "planned_cost": v["planned_cost"]} for k, v in by_status.items()},
        "elements": dict(shown),
        "elements_total": len(per_el),
        "other_elements_cost": sum((r["planned_cost"] for _, r in rest), zero),
        "unlinked_cost": unlinked,
        "coverage_pct": round(coverage, 2),
    }

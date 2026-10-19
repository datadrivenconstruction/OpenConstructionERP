# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""How much of a plan generated from a bill is backed by data.

A score from 0 to 1 per generated task and per plan. It is not a probability:
it says whether a duration came from a production norm or from a rule of
thumb, whether the logic came from construction knowledge or from the order of
the bill, and how finely the work is broken down. The generator proposes, the
person reviews the low scores first and confirms; nothing here applies itself.

``score = 0.5 x duration + 0.3 x logic + 0.2 x breakdown``. The factor values
and their reasons are documented in ``docs/design/schedule_from_estimate.md``
(section 3.4); the tests pin them.
"""

from __future__ import annotations

from typing import Any

WEIGHT_DURATION = 0.5
WEIGHT_LOGIC = 0.3
WEIGHT_BREAKDOWN = 0.2

# Where the duration came from (the generator's ``duration_source``).
DURATION_SCORES: dict[str, float] = {
    "labor_hours": 0.9,
    "machine_hours": 0.85,
    "resource_sum": 0.8,
    "spans_works": 0.6,
    "estimated_fallback": 0.4,
    "cost_proportional": 0.2,
    "default_minimum": 0.1,
}
# A unit-table guess the price held down is a guess corrected by another guess.
DURATION_CAPPED_BY_PRICE = 0.3
# Norm rows that say their productivity was never checked (synthetic demo
# norms carry ``demo_provenance.productivity_verified = false``).
DURATION_UNVERIFIED_CAP = 0.5

# Where the logic came from. Bill order is the only source today; logic
# templates by classification arrive with P1 at 0.8.
LOGIC_BILL_ORDER = 0.4
LOGIC_SPANS_WORKS = 0.7

# How the work is broken down. Location splits arrive with P1 (model storeys
# 0.9, typed storeys split evenly 0.5).
BREAKDOWN_WHOLE_POSITION = 0.7
BREAKDOWN_LUMP_SUM = 0.5

HIGH = 0.7
MEDIUM = 0.5

_NORM_SOURCES = frozenset({"labor_hours", "machine_hours", "resource_sum"})


def confidence_band(score: float) -> str:
    """``high`` from 0.7, ``medium`` from 0.5, ``low`` below."""
    if score >= HIGH - 1e-9:
        return "high"
    if score >= MEDIUM - 1e-9:
        return "medium"
    return "low"


def task_confidence(
    source: str,
    *,
    capped_by_price: bool = False,
    unverified: bool = False,
    compressed_pct: int | None = None,
    lump_sum: bool = False,
) -> dict[str, Any]:
    """The confidence of one generated task.

    Args:
        source: The duration source the plan used for the task.
        capped_by_price: A unit-table guess that the price held down.
        unverified: The norm rows behind the duration say their productivity
            was never checked.
        compressed_pct: The share of its estimate the duration was shortened
            to, when the plan was squeezed into a window.
        lump_sum: The position is priced as a lump sum.

    Returns:
        ``{"score", "band", "duration", "logic", "breakdown", "reasons"}``;
        ``reasons`` are stable codes the UI translates.
    """
    reasons = [f"duration_{source}"]
    duration = DURATION_SCORES.get(source, DURATION_SCORES["default_minimum"])
    if source == "estimated_fallback" and capped_by_price:
        duration = DURATION_CAPPED_BY_PRICE
        reasons.append("capped_by_price")
    if unverified and source in _NORM_SOURCES:
        duration = min(duration, DURATION_UNVERIFIED_CAP)
        reasons.append("unverified_norm")
    if compressed_pct is not None and 0 < compressed_pct < 100:
        duration *= 0.5 + 0.5 * compressed_pct / 100
        reasons.append("shortened")

    if source == "spans_works":
        logic = LOGIC_SPANS_WORKS
        reasons.append("logic_spans_works")
    else:
        logic = LOGIC_BILL_ORDER
        reasons.append("logic_bill_order")

    breakdown = BREAKDOWN_LUMP_SUM if lump_sum else BREAKDOWN_WHOLE_POSITION
    reasons.append("breakdown_lump_sum" if lump_sum else "breakdown_whole_position")

    score = round(WEIGHT_DURATION * duration + WEIGHT_LOGIC * logic + WEIGHT_BREAKDOWN * breakdown, 2)
    return {
        "score": score,
        "band": confidence_band(score),
        "duration": round(duration, 3),
        "logic": logic,
        "breakdown": breakdown,
        "reasons": reasons,
    }


def plan_confidence(scored: list[tuple[float, float]]) -> dict[str, Any]:
    """The plan's score: the task scores weighted by their cost.

    Args:
        scored: ``(score, weight)`` per task, the weight being the position
            total. Negative weights (credits) count as zero.

    Returns:
        ``{"score", "band", "counts": {"high", "medium", "low"}}``. Without
        any priced task the score is the plain mean.
    """
    counts = {"high": 0, "medium": 0, "low": 0}
    if not scored:
        return {"score": 0, "band": "low", "counts": counts}
    for score, _ in scored:
        counts[confidence_band(score)] += 1
    weight_sum = sum(max(weight, 0.0) for _, weight in scored)
    if weight_sum > 0:
        mean = sum(score * max(weight, 0.0) for score, weight in scored) / weight_sum
    else:
        mean = sum(score for score, _ in scored) / len(scored)
    score = round(mean, 2)
    return {"score": score, "band": confidence_band(score), "counts": counts}

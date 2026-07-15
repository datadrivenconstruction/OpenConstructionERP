# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""E1 "Watch" — the Readiness Engine (Phase 1).

Turns ``schedule_advanced``'s binary *ready / not-ready* into a deterministic
**Ready / At-risk / Blocked** classification per look-ahead activity, with a
traceable ``binding_constraint`` + ``drivers[]`` (each linked to its source row,
spec P4) and a uniform E5.3 confidence.

This is a **pure** engine: no I/O, no session, no clock. Its inputs are plain
dataclasses the service layer fills from the existing feeds — raw
``schedule_advanced`` constraint rows, an optional CPM float from
``oe_schedule_activity``, and the prior snapshot's float. That keeps the
classification testable as a truth table and makes the run **idempotent**:
:func:`run_digest` hashes the canonical inputs so re-evaluating identical inputs
yields the same ``evaluation_run_id`` (E1.1-AC6).

Correctness catch (see plan): ``schedule_advanced.constraint_ready_state`` treats
``cannot_clear`` as *not open* and skips it — which would call a permanently
blocked activity "ready". This engine consumes **raw** constraint rows and maps
``cannot_clear → BLOCKED`` itself; the open-blocker subset is exactly
``{open, in_progress, escalated}``.

Classification constants are hardcoded here (a locked design decision); only the
*confidence* gating stays config-as-data (E5.3), resolved from a policy row.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.modules.schedule_intelligence.confidence import (
    ConfidencePolicy,
    ConfidenceResult,
    compute_confidence,
)
from app.modules.schedule_intelligence.enums import ReadinessClass

# ── Classification constants (hardcoded design decision) ─────────────────────
# A constraint is an *open blocker* while its status is one of these; the
# schedule_advanced state machine also emits ``cleared`` (resolved) and
# ``cannot_clear`` (permanently blocked), both handled explicitly below.
OPEN_STATUSES: frozenset[str] = frozenset({"open", "in_progress", "escalated"})
CLEARED_STATUS = "cleared"
CANNOT_CLEAR_STATUS = "cannot_clear"

# Need-by within this many days is the "near horizon": an *undated* open
# make-ready constraint against a near-horizon activity is treated as unable to
# clear in time (→ BLOCKED); a near-horizon need-by with thin cover is At-risk.
NEAR_HORIZON_DAYS = 14
# Total float at or below this (in days) is "thin" → At-risk; ``≤ 0`` with an
# open blocker is Blocked.
AT_RISK_FLOAT_DAYS = 2

# Base confidence the classifier emits before E5.3 gating. Deliberately not 1.0:
# even a clean classification is a model of reality, not reality.
_BASE_CONFIDENCE = 0.9


def _driver(driver_type: str, ref: Any, detail: str) -> dict[str, str]:
    """One traceable driver row: ``{type, ref, detail}`` (ref stringified, P4)."""
    return {"type": driver_type, "ref": str(ref) if ref is not None else "", "detail": detail}


@dataclass(frozen=True)
class ConstraintInput:
    """A raw ``schedule_advanced`` constraint, as the engine sees it.

    ``status`` is the raw string from the row (``open`` / ``in_progress`` /
    ``escalated`` / ``cleared`` / ``cannot_clear``); the engine — not the caller
    — decides what each status means for readiness.
    """

    ref: Any
    status: str
    target_clear_date: date | None = None
    constraint_type: str | None = None
    description: str = ""


@dataclass(frozen=True)
class ActivityInput:
    """One look-ahead activity plus everything needed to classify it.

    ``need_by_date`` is when the activity must be able to start (its planned
    start); constraints must clear before it. ``total_float`` / ``is_critical``
    are best-effort CPM enrichment (``None`` when the float join is unresolved —
    confidence degrades, never silently). ``prior_float`` is the same activity's
    float in the previous snapshot, used only to detect float *burn*; it is
    deliberately excluded from :func:`run_digest` so a re-run stays idempotent.
    """

    task_ref: Any
    constraints: Sequence[ConstraintInput] = field(default_factory=tuple)
    need_by_date: date | None = None
    planned_start_date: date | None = None
    total_float: int | None = None
    is_critical: bool = False
    prior_float: int | None = None


@dataclass(frozen=True)
class ActivityReadiness:
    """The engine's verdict for one activity — everything the service persists."""

    task_ref: str
    classification: ReadinessClass
    binding_constraint_ref: str | None
    drivers: list[dict[str, str]]
    need_by_date: date | None
    planned_start_date: date | None
    total_float_days: int | None
    float_burn_days: int | None
    confidence: ConfidenceResult


def _feed_coverage(activity: ActivityInput) -> str:
    """Feed-coverage tier for E5.3 gating — degrades when float is unresolved.

    ``full`` when CPM float is present; ``partial`` when it is missing but there
    are constraints to reason over; ``sparse`` when neither is available (the
    classification then rests almost entirely on absence-of-signal).
    """
    if activity.total_float is not None:
        return "full"
    if activity.constraints:
        return "partial"
    return "sparse"


def classify_activity(
    activity: ActivityInput,
    today: date,
    *,
    policy: ConfidencePolicy | None = None,
) -> ActivityReadiness:
    """Classify a single activity as Ready / At-risk / Blocked.

    Pure and deterministic: constraints are considered in a stable
    ref-sorted order, and the first BLOCKED/AT_RISK rule that fires wins, so the
    same inputs always yield the same verdict, binding constraint and driver
    order (E1.1-AC6).
    """
    policy = policy or ConfidencePolicy.default()
    constraints = sorted(activity.constraints, key=lambda c: str(c.ref))
    open_cs = [c for c in constraints if c.status in OPEN_STATUSES]
    dead_cs = [c for c in constraints if c.status == CANNOT_CLEAR_STATUS]

    float_days = activity.total_float
    float_burn: int | None = None
    if activity.prior_float is not None and float_days is not None:
        # Positive = float lost since the prior run (burning down toward zero).
        float_burn = activity.prior_float - float_days

    near_horizon = activity.need_by_date is not None and activity.need_by_date <= today + timedelta(
        days=NEAR_HORIZON_DAYS
    )

    drivers: list[dict[str, str]] = []
    binding: str | None = None
    classification: ReadinessClass | None = None

    # ── BLOCKED ───────────────────────────────────────────────────────────
    # 1) A constraint the field has declared permanently un-clearable.
    if dead_cs:
        classification = ReadinessClass.BLOCKED
        binding = str(dead_cs[0].ref)
        for c in dead_cs:
            drivers.append(_driver("constraint", c.ref, f"{c.constraint_type or 'constraint'} marked cannot-clear"))

    # 2) An open constraint that cannot clear before the activity must start.
    if classification is None and activity.need_by_date is not None:
        offenders: list[tuple[ConstraintInput, str]] = []
        for c in open_cs:
            if c.target_clear_date is not None and c.target_clear_date >= activity.need_by_date:
                offenders.append(
                    (
                        c,
                        f"targets {c.target_clear_date.isoformat()}, not before "
                        f"need-by {activity.need_by_date.isoformat()}",
                    )
                )
            elif c.target_clear_date is None and near_horizon:
                offenders.append(
                    (
                        c,
                        f"undated make-ready with need-by {activity.need_by_date.isoformat()} "
                        f"within {NEAR_HORIZON_DAYS}d",
                    )
                )
        if offenders:
            classification = ReadinessClass.BLOCKED
            binding = str(offenders[0][0].ref)
            for c, detail in offenders:
                drivers.append(_driver("constraint", c.ref, detail))

    # 3) No critical-path slack left while an open blocker still stands.
    if classification is None and float_days is not None and float_days <= 0 and open_cs:
        classification = ReadinessClass.BLOCKED
        binding = str(open_cs[0].ref)
        drivers.append(_driver("float", activity.task_ref, f"total float {float_days}d ≤ 0 with an open blocker"))
        drivers.append(_driver("constraint", open_cs[0].ref, "open blocker on a zero-float activity"))

    # ── AT_RISK / READY ───────────────────────────────────────────────────
    if classification is None:
        at_risk = False
        if open_cs:
            at_risk = True
            binding = str(open_cs[0].ref)
            for c in open_cs:
                tgt = c.target_clear_date.isoformat() if c.target_clear_date else "undated"
                drivers.append(_driver("constraint", c.ref, f"open {c.constraint_type or 'constraint'} (target {tgt})"))
        if float_days is not None and float_days <= AT_RISK_FLOAT_DAYS:
            at_risk = True
            drivers.append(
                _driver("float", activity.task_ref, f"thin total float {float_days}d ≤ {AT_RISK_FLOAT_DAYS}d")
            )
            if activity.is_critical:
                drivers.append(_driver("criticality", activity.task_ref, "activity is on the critical path"))
        if float_burn is not None and float_burn > 0:
            at_risk = True
            drivers.append(_driver("float_burn", activity.task_ref, f"burned {float_burn}d of float since prior run"))
        if at_risk and near_horizon and activity.need_by_date is not None:
            drivers.append(
                _driver(
                    "need_by",
                    activity.task_ref,
                    f"need-by {activity.need_by_date.isoformat()} within {NEAR_HORIZON_DAYS}d",
                )
            )
        classification = ReadinessClass.AT_RISK if at_risk else ReadinessClass.READY

    if classification == ReadinessClass.READY and not drivers:
        drivers.append(_driver("clear", activity.task_ref, "no open constraints; float healthy"))

    confidence = compute_confidence(
        _BASE_CONFIDENCE,
        feed_coverage=_feed_coverage(activity),
        policy=policy,
    )

    return ActivityReadiness(
        task_ref=str(activity.task_ref),
        classification=classification,
        binding_constraint_ref=binding,
        drivers=drivers,
        need_by_date=activity.need_by_date,
        planned_start_date=activity.planned_start_date,
        total_float_days=float_days,
        float_burn_days=float_burn,
        confidence=confidence,
    )


def evaluate_look_ahead(
    activities: Sequence[ActivityInput],
    today: date,
    *,
    policy: ConfidencePolicy | None = None,
) -> list[ActivityReadiness]:
    """Classify every activity, returned in a stable ref-sorted order."""
    policy = policy or ConfidencePolicy.default()
    ordered = sorted(activities, key=lambda a: str(a.task_ref))
    return [classify_activity(a, today, policy=policy) for a in ordered]


def run_digest(activities: Sequence[ActivityInput], today: date) -> str:
    """Deterministic SHA-256 of the canonical inputs → the ``evaluation_run_id``.

    Two evaluations over identical inputs (same ``today``, same constraints,
    same float) produce the same digest, so a re-run is idempotent (E1.1-AC6).
    ``prior_float`` is intentionally excluded — it is a derived output of earlier
    runs, and including it would make a run's id depend on whether a snapshot
    already exists, defeating idempotency.
    """
    payload = {
        "today": today.isoformat(),
        "activities": [
            {
                "task_ref": str(a.task_ref),
                "need_by": a.need_by_date.isoformat() if a.need_by_date else None,
                "total_float": a.total_float,
                "is_critical": bool(a.is_critical),
                "constraints": sorted(
                    (
                        {
                            "ref": str(c.ref),
                            "status": c.status,
                            "target": c.target_clear_date.isoformat() if c.target_clear_date else None,
                        }
                        for c in a.constraints
                    ),
                    key=lambda d: d["ref"],
                ),
            }
            for a in sorted(activities, key=lambda a: str(a.task_ref))
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

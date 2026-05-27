"""‌⁠‍Schedule Advanced service — Last Planner System (LPS) business logic.

This module is organised as:

1. **Pure helpers** at module scope (``compute_ppc``, ``compute_rnc_pareto``,
   ``compute_baseline_delta``, ``is_constraint_blocking_task``,
   ``weeks_from_lookahead``, ``validate_commitment``) — easily unit-tested.
2. **State machines** — pure transition tables for each entity.
3. **Service class** (:class:`ScheduleAdvancedService`) — orchestrator
   that wires repositories + event bus + database session.

State machines mirror :pep:`8` and the safety/* / schedule/* patterns:
``allowed_<entity>_transitions`` returns the set of legal next states
given a current state.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.i18n import get_locale
from app.core.validation.messages import translate
from app.modules.schedule_advanced.models import (
    Baseline,
    BaselineDelta,
    Calendar,
    Commitment,
    Constraint,
    LookAheadPlan,
    MasterSchedule,
    PhasePlan,
    ReasonForNonCompletion,
    WeeklyWorkPlan,
)
from app.modules.schedule_advanced.repository import (
    BaselineDeltaRepository,
    BaselineRepository,
    CalendarRepository,
    CommitmentRepository,
    ConstraintRepository,
    LookAheadRepository,
    MasterScheduleRepository,
    PhasePlanRepository,
    RNCRepository,
    WeeklyWorkPlanRepository,
)
from app.modules.schedule_advanced.schemas import (
    BaselineCreate,
    BaselineDeltaEntry,
    BaselineDeltaResponse,
    BaselineUpdate,
    CalendarCreate,
    CalendarUpdate,
    CommitmentCreate,
    CommitmentUpdate,
    ConstraintCreate,
    ConstraintUpdate,
    LookAheadCreate,
    LookAheadUpdate,
    MasterScheduleCreate,
    MasterScheduleUpdate,
    PhasePlanCreate,
    PhasePlanUpdate,
    RNCCreate,
    RNCUpdate,
    WeeklyWorkPlanCreate,
    WeeklyWorkPlanUpdate,
)

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────

_RNC_CATEGORIES = (
    "manpower",
    "material",
    "equipment",
    "info",
    "weather",
    "predecessor",
    "changes",
    "quality",
    "other",
)


# ── Pure helpers ───────────────────────────────────────────────────────────


def compute_ppc(commitments: list[Commitment] | list[Any]) -> Decimal:
    """‌⁠‍Compute Percent Plan Complete for a list of commitments.

    PPC = completed / committed × 100. "Completed" means status == "completed".
    "Committed" means status in (committed, in_progress, completed, missed,
    at_risk) — i.e. anything that actually entered the week's commitment
    pool. Plain "planned" commitments don't count as denominators because
    they were never promised on the floor.

    Returns Decimal(0) for an empty list to avoid divide-by-zero.
    """
    committed_statuses = {"committed", "in_progress", "completed", "missed", "at_risk"}
    committed = sum(1 for c in commitments if c.status in committed_statuses)
    if committed == 0:
        return Decimal("0")
    completed = sum(1 for c in commitments if c.status == "completed")
    return (Decimal(completed) / Decimal(committed) * Decimal(100)).quantize(Decimal("0.01"))


def compute_rnc_pareto(
    rncs: list[ReasonForNonCompletion] | list[Any],
    period_start: date,
    period_end: date,
) -> dict[str, int]:
    """‌⁠‍Return a category -> count mapping for the supplied RNC records.

    ``period_start`` / ``period_end`` are reported in the response but
    not enforced here — callers are expected to filter beforehand. The
    full canonical category set is always present in the output (zero
    counts for missing categories) so the front-end chart never needs
    to re-fill blanks.
    """
    _ = (period_start, period_end)  # documented but not filtered here
    out: dict[str, int] = dict.fromkeys(_RNC_CATEGORIES, 0)
    for r in rncs:
        cat = r.category if r.category in out else "other"
        out[cat] = out.get(cat, 0) + 1
    return out


def compute_baseline_delta(
    baseline_snapshot: list[dict[str, Any]] | dict[str, Any],
    current_tasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compute the per-task delta between a baseline snapshot and the current schedule.

    Args:
        baseline_snapshot: List of dicts with ``task_ref`` / ``planned_start``
            / ``planned_finish`` (or ``id`` aliased to ``task_ref``). Dict
            shape is also tolerated for ``{"tasks": [...]}`` wrappers.
        current_tasks: Same shape, representing the current schedule.

    Returns:
        List of delta records (one per baseline task), each with
        ``task_ref``, baseline/current dates, and ``schedule_variance_days``
        (positive = delay, negative = acceleration). Tasks absent from
        ``current_tasks`` get ``planned_*_current = None`` and
        ``schedule_variance_days = 0``.
    """
    # Normalise wrapper shape
    if isinstance(baseline_snapshot, dict) and "tasks" in baseline_snapshot:
        baseline_list: list[dict[str, Any]] = baseline_snapshot.get("tasks") or []
    elif isinstance(baseline_snapshot, list):
        baseline_list = baseline_snapshot
    else:
        baseline_list = []

    def _key(row: dict[str, Any]) -> str | None:
        v = row.get("task_ref") or row.get("id")
        if v is None:
            return None
        return str(v)

    current_by_ref: dict[str, dict[str, Any]] = {}
    for row in current_tasks or []:
        k = _key(row)
        if k:
            current_by_ref[k] = row

    out: list[dict[str, Any]] = []
    for b in baseline_list:
        k = _key(b)
        if not k:
            continue
        b_finish = _parse_date(b.get("planned_finish"))
        b_start = _parse_date(b.get("planned_start"))
        cur = current_by_ref.get(k)
        c_finish = _parse_date(cur.get("planned_finish")) if cur else None
        c_start = _parse_date(cur.get("planned_start")) if cur else None
        variance = 0
        if b_finish and c_finish:
            variance = (c_finish - b_finish).days
        out.append(
            {
                "task_ref": k,
                "planned_start_baseline": b_start,
                "planned_start_current": c_start,
                "planned_finish_baseline": b_finish,
                "planned_finish_current": c_finish,
                "schedule_variance_days": variance,
                # Carry-through display name from snapshot (or current row
                # as fallback) so the UI doesn't render bare UUIDs. The
                # whole field is optional in the response schema, so this
                # is purely additive.
                "name": (b.get("name") or (cur.get("name") if cur else None)),
            }
        )
    return out


def _parse_date(value: Any) -> date | None:
    """Tolerant date parser — accepts date, datetime, or ISO string."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except (ValueError, TypeError):
            return None
    return None


def _to_decimal(value: Any) -> Decimal:
    """Tolerant Decimal parser — empty / unparseable → Decimal("0")."""
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (TypeError, ValueError):
        return Decimal("0")


# ── CPM (Critical Path Method) ────────────────────────────────────────────


def cpm_forward_backward_pass(
    activities: list[dict[str, Any]],
    dependencies: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Run the CPM forward + backward pass on a flat activity list.

    Args:
        activities: each dict must expose ``id`` (any hashable), ``duration``
            (int, working-days) and optionally ``predecessors`` (list of ids).
            ``predecessors`` may also be passed via the separate
            ``dependencies`` list (preferred for FS-only relationships).
        dependencies: optional list of ``{"predecessor": id, "successor": id}``
            dicts encoding FS (Finish-to-Start) relationships. When given,
            takes precedence over per-activity ``predecessors`` lists.

    Returns:
        A dict keyed by activity id with the computed schedule fields::

            {
                "es": int,            # Earliest Start (work-day index, 0-based)
                "ef": int,            # Earliest Finish
                "ls": int,            # Latest Start
                "lf": int,            # Latest Finish
                "total_float": int,   # LS - ES (== LF - EF)
                "free_float": int,    # ES of earliest successor - EF of this
                "is_critical": bool,  # total_float <= 0
                "duration": int,
            }

    Activities with cycles are ignored (CPM is acyclic by definition).
    Activities with negative duration are coerced to 0.
    """
    if not activities:
        return {}

    by_id: dict[Any, dict[str, Any]] = {a["id"]: dict(a) for a in activities if "id" in a}

    # Normalize predecessor edges into a clean adjacency map.
    preds: dict[Any, list[Any]] = {aid: [] for aid in by_id}
    succs: dict[Any, list[Any]] = {aid: [] for aid in by_id}

    if dependencies:
        for d in dependencies:
            p = d.get("predecessor")
            s = d.get("successor")
            if p in by_id and s in by_id and p != s:
                preds[s].append(p)
                succs[p].append(s)
    else:
        for aid, a in by_id.items():
            for p in a.get("predecessors") or []:
                if p in by_id and p != aid:
                    preds[aid].append(p)
                    succs[p].append(aid)

    # Topological order (Kahn's algorithm). Cycle nodes are skipped at the end.
    indeg = {aid: len(preds[aid]) for aid in by_id}
    queue = [aid for aid, d in indeg.items() if d == 0]
    topo: list[Any] = []
    while queue:
        n = queue.pop(0)
        topo.append(n)
        for s in succs[n]:
            indeg[s] -= 1
            if indeg[s] == 0:
                queue.append(s)

    # Forward pass — compute ES, EF
    es: dict[Any, int] = {}
    ef: dict[Any, int] = {}
    for aid in topo:
        dur = max(0, int(by_id[aid].get("duration", 0) or 0))
        # A predecessor that is part of a cycle is excluded from ``topo``
        # and therefore never gets an ``ef``; default to 0 instead of
        # letting ``max()`` raise on an empty generator (500 on /cpm).
        ready_preds = [ef[p] for p in preds[aid] if p in ef]
        es[aid] = max(ready_preds) if ready_preds else 0
        ef[aid] = es[aid] + dur

    if not ef:
        return {}
    project_finish = max(ef.values())

    # Backward pass — compute LF, LS
    lf: dict[Any, int] = {}
    ls: dict[Any, int] = {}
    for aid in reversed(topo):
        dur = max(0, int(by_id[aid].get("duration", 0) or 0))
        # Symmetric to the forward pass: a successor in a cycle never gets
        # an ``ls`` — fall back to ``project_finish`` instead of raising.
        ready_succs = [ls[s] for s in succs[aid] if s in ls]
        lf[aid] = min(ready_succs) if ready_succs else project_finish
        ls[aid] = lf[aid] - dur

    out: dict[str, dict[str, Any]] = {}
    for aid in topo:
        dur = max(0, int(by_id[aid].get("duration", 0) or 0))
        total_float = ls[aid] - es[aid]
        if succs[aid]:
            ff_candidates = [es[s] for s in succs[aid] if s in es]
            free_float = min(ff_candidates) - ef[aid] if ff_candidates else 0
        else:
            free_float = project_finish - ef[aid]
        out[str(aid)] = {
            "id": aid,
            "es": es[aid],
            "ef": ef[aid],
            "ls": ls[aid],
            "lf": lf[aid],
            "total_float": total_float,
            "free_float": max(0, free_float),
            "is_critical": total_float <= 0,
            "duration": dur,
        }
    return out


def time_impact_analysis(
    activities: list[dict[str, Any]],
    dependencies: list[dict[str, Any]] | None,
    impacted_activity_id: Any,
    delay_days: int,
) -> dict[str, Any]:
    """Re-run CPM after adding ``delay_days`` to one activity's duration.

    Returns a dict::

        {
            "original_finish_workday": int,
            "impacted_finish_workday": int,
            "delta_days": int,                  # impacted - original
            "newly_critical_activity_ids": list,
            "no_longer_critical_activity_ids": list,
        }

    ``delta_days`` may be < the supplied delay when the activity has
    sufficient float to absorb part of the impact. ``delta_days == delay_days``
    only when the activity is fully on the critical path.
    """
    if delay_days < 0:
        delay_days = 0

    base = cpm_forward_backward_pass(activities, dependencies)
    if not base:
        return {
            "original_finish_workday": 0,
            "impacted_finish_workday": 0,
            "delta_days": 0,
            "newly_critical_activity_ids": [],
            "no_longer_critical_activity_ids": [],
        }
    original_finish = max(v["ef"] for v in base.values())
    original_critical = {k for k, v in base.items() if v["is_critical"]}

    impacted = []
    for a in activities:
        if a.get("id") == impacted_activity_id:
            a2 = dict(a)
            a2["duration"] = int(a2.get("duration", 0) or 0) + delay_days
            impacted.append(a2)
        else:
            impacted.append(a)

    impacted_cpm = cpm_forward_backward_pass(impacted, dependencies)
    if not impacted_cpm:
        return {
            "original_finish_workday": original_finish,
            "impacted_finish_workday": original_finish,
            "delta_days": 0,
            "newly_critical_activity_ids": [],
            "no_longer_critical_activity_ids": [],
        }
    new_finish = max(v["ef"] for v in impacted_cpm.values())
    new_critical = {k for k, v in impacted_cpm.items() if v["is_critical"]}

    return {
        "original_finish_workday": original_finish,
        "impacted_finish_workday": new_finish,
        "delta_days": new_finish - original_finish,
        "newly_critical_activity_ids": sorted(new_critical - original_critical),
        "no_longer_critical_activity_ids": sorted(original_critical - new_critical),
    }


# ── Earned-Value Management ───────────────────────────────────────────────


def compute_evm(
    activities: list[dict[str, Any]],
    today_workday: int,
) -> dict[str, Any]:
    """Compute Earned Value metrics across a list of activities.

    Each activity dict needs:
        ``budget_at_completion`` (BAC for that activity, float / Decimal)
        ``percent_complete`` (0–100)
        ``actual_cost`` (AC, float / Decimal)
        ``planned_start_workday`` and ``planned_finish_workday``
            (integer indices used for PV linear-ramp computation)

    Returns dict::

        {
            "bac": Decimal,
            "pv": Decimal,    # planned value at today
            "ev": Decimal,    # earned value at today
            "ac": Decimal,    # actual cost at today
            "spi": Decimal,   # EV / PV  (1.0 = on schedule)
            "cpi": Decimal,   # EV / AC  (1.0 = on budget)
            "eac": Decimal,   # AC + (BAC - EV) / CPI    (estimate at completion)
            "etc": Decimal,   # EAC - AC                  (estimate to complete)
            "vac": Decimal,   # BAC - EAC                 (variance at completion)
            "sv": Decimal,    # EV - PV                   (schedule variance)
            "cv": Decimal,    # EV - AC                   (cost variance)
        }
    """
    bac_total = Decimal("0")
    pv_total = Decimal("0")
    ev_total = Decimal("0")
    ac_total = Decimal("0")
    for a in activities:
        bac = _to_decimal(a.get("budget_at_completion", 0))
        pct = _to_decimal(a.get("percent_complete", 0))
        ac = _to_decimal(a.get("actual_cost", 0))
        ps = int(a.get("planned_start_workday", 0) or 0)
        pf = int(a.get("planned_finish_workday", 0) or 0)
        bac_total += bac
        ac_total += ac
        ev_total += bac * (pct / Decimal("100"))
        # Linear-ramp PV between planned_start_workday and planned_finish_workday.
        if pf <= ps:
            # Zero-duration / point activity — full PV at start.
            pv_pct = Decimal("100") if today_workday >= ps else Decimal("0")
        elif today_workday <= ps:
            pv_pct = Decimal("0")
        elif today_workday >= pf:
            pv_pct = Decimal("100")
        else:
            pv_pct = Decimal(today_workday - ps) / Decimal(pf - ps) * Decimal("100")
        pv_total += bac * (pv_pct / Decimal("100"))

    spi = (ev_total / pv_total) if pv_total > 0 else Decimal("0")
    cpi = (ev_total / ac_total) if ac_total > 0 else Decimal("0")
    if cpi > 0:
        eac = ac_total + ((bac_total - ev_total) / cpi)
    else:
        # CPI undefined (no earned value yet). The PMI fallback keeps the
        # money already spent in the forecast: EAC = AC + (BAC − EV).
        # The previous ``eac = bac_total`` discarded sunk cost and made
        # VAC (= BAC − EAC) read 0 even after real spend.
        eac = ac_total + (bac_total - ev_total)
    etc = eac - ac_total
    vac = bac_total - eac
    sv = ev_total - pv_total
    cv = ev_total - ac_total

    q = Decimal("0.01")
    return {
        "bac": bac_total.quantize(q),
        "pv": pv_total.quantize(q),
        "ev": ev_total.quantize(q),
        "ac": ac_total.quantize(q),
        "spi": spi.quantize(Decimal("0.0001")),
        "cpi": cpi.quantize(Decimal("0.0001")),
        "eac": eac.quantize(q),
        "etc": etc.quantize(q),
        "vac": vac.quantize(q),
        "sv": sv.quantize(q),
        "cv": cv.quantize(q),
    }


# ── RNC Pareto (sorted with cumulative %) ─────────────────────────────────


def compute_rnc_pareto_sorted(
    rncs: list[ReasonForNonCompletion] | list[Any],
) -> list[dict[str, Any]]:
    """Return RNC counts sorted desc + cumulative-percentage column.

    Output rows::

        [
            {"category": "manpower", "count": 12, "percent": 40.0, "cum_percent": 40.0},
            {"category": "material",  "count": 9,  "percent": 30.0, "cum_percent": 70.0},
            ...
        ]

    The full canonical category set is preserved (zero counts included) so
    UIs always see consistent ordering. Within the canonical set, categories
    with the same count are returned alphabetically.
    """
    counts: dict[str, int] = dict.fromkeys(_RNC_CATEGORIES, 0)
    for r in rncs:
        cat = getattr(r, "category", None) if not isinstance(r, dict) else r.get("category")
        cat = cat if cat in counts else "other"
        counts[cat] = counts.get(cat, 0) + 1

    total = sum(counts.values()) or 1
    # Sort by (-count, category)
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    out: list[dict[str, Any]] = []
    running = Decimal("0")
    for cat, count in items:
        pct = (Decimal(count) / Decimal(total) * Decimal("100")).quantize(Decimal("0.01"))
        running = (running + pct).quantize(Decimal("0.01"))
        out.append(
            {
                "category": cat,
                "count": count,
                "percent": float(pct),
                "cum_percent": float(running),
            }
        )
    return out


# ── Constraint readiness ──────────────────────────────────────────────────


def constraint_ready_state(
    task_ref: uuid.UUID | str,
    constraints: list[Constraint] | list[Any],
) -> dict[str, Any]:
    """Decide whether a task is *ready* to be committed to in a WWP.

    A task is ready when it has zero open constraints. "Open" = status not
    in ``(cleared, cannot_clear)``.

    Returns::

        {
            "task_ref": str,
            "is_ready": bool,
            "open_count": int,
            "blockers": [
                {"id": str, "type": str, "description": str,
                 "owner_user_id": str | None, "target_clear_date": str | None}
            ],
        }
    """
    ref = str(task_ref)
    blockers: list[dict[str, Any]] = []
    for c in constraints:
        c_task = getattr(c, "task_ref", None) if not isinstance(c, dict) else c.get("task_ref")
        if c_task is None or str(c_task) != ref:
            continue
        c_status = getattr(c, "status", "open") if not isinstance(c, dict) else c.get("status", "open")
        if c_status in ("cleared", "cannot_clear"):
            continue
        target = getattr(c, "target_clear_date", None) if not isinstance(c, dict) else c.get("target_clear_date")
        if isinstance(target, date) and not isinstance(target, datetime):
            target_str: str | None = target.isoformat()
        elif isinstance(target, datetime):
            target_str = target.date().isoformat()
        elif target is not None:
            target_str = str(target)[:10]
        else:
            target_str = None
        owner = getattr(c, "owner_user_id", None) if not isinstance(c, dict) else c.get("owner_user_id")
        blockers.append(
            {
                "id": str(getattr(c, "id", "") if not isinstance(c, dict) else c.get("id", "")),
                "type": getattr(c, "constraint_type", "other")
                if not isinstance(c, dict)
                else c.get("constraint_type", "other"),
                "description": getattr(c, "description", "") if not isinstance(c, dict) else c.get("description", ""),
                "owner_user_id": str(owner) if owner else None,
                "target_clear_date": target_str,
            }
        )
    return {
        "task_ref": ref,
        "is_ready": len(blockers) == 0,
        "open_count": len(blockers),
        "blockers": blockers,
    }


def is_constraint_blocking_task(
    task_ref: uuid.UUID | str,
    constraints: list[Constraint] | list[Any],
    today: date,
) -> bool:
    """Return True if any open constraint with target_clear_date < today blocks the task.

    Open = status not in (cleared, cannot_clear). Constraints with no
    target_clear_date OR a target in the future are not considered
    blocking (yet) — they're make-ready work in progress.
    """
    ref = str(task_ref)
    for c in constraints:
        if str(c.task_ref) != ref:
            continue
        if c.status in ("cleared", "cannot_clear"):
            continue
        if c.target_clear_date is None:
            continue
        if c.target_clear_date < today:
            return True
    return False


def weeks_from_lookahead(today: date, window_weeks: int = 6) -> list[date]:
    """Return the list of Monday dates covered by an LPS look-ahead window.

    First entry is the Monday of the current week. Subsequent entries
    are Mondays of the following ``window_weeks - 1`` weeks.
    """
    if window_weeks <= 0:
        return []
    monday = today - timedelta(days=today.weekday())
    return [monday + timedelta(weeks=i) for i in range(window_weeks)]


def validate_commitment(
    commitment: dict[str, Any] | Commitment,
    calendar: Calendar | dict[str, Any] | None,
) -> tuple[bool, list[str]]:
    """Validate a commitment against a working calendar.

    Returns ``(ok, errors)``. Checks:
      * planned_start ≤ planned_finish
      * planned_start and planned_finish fall on the calendar's work_days
        (defaults Mon–Fri if calendar is None)
      * planned_start and planned_finish are not holidays
    """
    errors: list[str] = []

    if isinstance(commitment, dict):
        start = _parse_date(commitment.get("planned_start"))
        finish = _parse_date(commitment.get("planned_finish"))
    else:
        start = commitment.planned_start
        finish = commitment.planned_finish

    if start and finish and start > finish:
        errors.append("planned_start must be on or before planned_finish")

    work_days: list[int] = [0, 1, 2, 3, 4]
    holidays: list[str] = []
    if calendar is not None:
        if isinstance(calendar, dict):
            work_days = calendar.get("work_days") or work_days
            holidays = calendar.get("holidays") or []
        else:
            work_days = list(calendar.work_days or work_days)
            holidays = list(calendar.holidays or [])
    holiday_set = {str(h)[:10] for h in holidays}

    for label, d in (("planned_start", start), ("planned_finish", finish)):
        if d is None:
            continue
        if d.weekday() not in work_days:
            errors.append(f"{label} ({d.isoformat()}) falls on a non-working day")
        if d.isoformat() in holiday_set:
            errors.append(f"{label} ({d.isoformat()}) falls on a holiday")

    return (len(errors) == 0, errors)


# ── State machines ─────────────────────────────────────────────────────────

_PHASE_TRANSITIONS: dict[str, set[str]] = {
    "in_planning": {"pulled", "in_planning"},
    "pulled": {"active", "in_planning", "pulled"},
    "active": {"completed", "active"},
    "completed": {"completed"},
}

_LOOK_AHEAD_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"reviewed", "draft"},
    "reviewed": {"published", "draft", "reviewed"},
    "published": {"published"},
}

_CONSTRAINT_TRANSITIONS: dict[str, set[str]] = {
    "open": {"in_progress", "cleared", "escalated", "cannot_clear", "open"},
    "in_progress": {"cleared", "escalated", "cannot_clear", "in_progress"},
    "escalated": {"cleared", "cannot_clear", "in_progress", "escalated"},
    "cleared": {"cleared"},
    "cannot_clear": {"cannot_clear", "open"},
}

_COMMITMENT_TRANSITIONS: dict[str, set[str]] = {
    "planned": {"committed", "planned", "at_risk"},
    "committed": {"in_progress", "completed", "missed", "at_risk", "committed"},
    "in_progress": {"completed", "missed", "at_risk", "in_progress"},
    "at_risk": {"in_progress", "completed", "missed", "at_risk"},
    "completed": {"completed"},
    "missed": {"missed"},
}

_WEEKLY_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"committed", "draft"},
    "committed": {"in_progress", "closed", "committed"},
    "in_progress": {"closed", "in_progress"},
    "closed": {"closed"},
}

_BASELINE_TRANSITIONS: dict[str, set[str]] = {
    "active": {"superseded", "archived", "active"},
    "superseded": {"archived", "superseded"},
    "archived": {"archived"},
}


def allowed_phase_transitions(current: str) -> set[str]:
    """Return the legal next states for a PhasePlan in ``current`` state."""
    return _PHASE_TRANSITIONS.get(current, set())


def allowed_look_ahead_transitions(current: str) -> set[str]:
    """Return the legal next states for a LookAheadPlan in ``current`` state."""
    return _LOOK_AHEAD_TRANSITIONS.get(current, set())


def allowed_constraint_transitions(current: str) -> set[str]:
    """Return the legal next states for a Constraint in ``current`` state."""
    return _CONSTRAINT_TRANSITIONS.get(current, set())


def allowed_commitment_transitions(current: str) -> set[str]:
    """Return the legal next states for a Commitment in ``current`` state."""
    return _COMMITMENT_TRANSITIONS.get(current, set())


def allowed_weekly_transitions(current: str) -> set[str]:
    """Return the legal next states for a WeeklyWorkPlan in ``current`` state."""
    return _WEEKLY_TRANSITIONS.get(current, set())


def allowed_baseline_transitions(current: str) -> set[str]:
    """Return the legal next states for a Baseline in ``current`` state."""
    return _BASELINE_TRANSITIONS.get(current, set())


# ── Service class ─────────────────────────────────────────────────────────


class ScheduleAdvancedService:
    """Orchestrator for the Schedule Advanced (LPS) module."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.master_repo = MasterScheduleRepository(session)
        self.phase_repo = PhasePlanRepository(session)
        self.look_ahead_repo = LookAheadRepository(session)
        self.constraint_repo = ConstraintRepository(session)
        self.weekly_repo = WeeklyWorkPlanRepository(session)
        self.commitment_repo = CommitmentRepository(session)
        self.rnc_repo = RNCRepository(session)
        self.baseline_repo = BaselineRepository(session)
        self.baseline_delta_repo = BaselineDeltaRepository(session)
        self.calendar_repo = CalendarRepository(session)

    # ── Master schedule ────────────────────────────────────────────────

    async def create_master_schedule(
        self,
        data: MasterScheduleCreate,
        user_id: str | None = None,
    ) -> MasterSchedule:
        m = MasterSchedule(
            project_id=data.project_id,
            name=data.name,
            baseline_date=data.baseline_date,
            planned_start=data.planned_start,
            planned_finish=data.planned_finish,
            status=data.status,
            notes=data.notes,
            created_by=user_id,
        )
        return await self.master_repo.create(m)

    async def get_master_schedule(self, master_id: uuid.UUID) -> MasterSchedule:
        m = await self.master_repo.get_by_id(master_id)
        if m is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="MasterSchedule not found")
        return m

    async def update_master_schedule(
        self,
        master_id: uuid.UUID,
        data: MasterScheduleUpdate,
    ) -> MasterSchedule:
        m = await self.get_master_schedule(master_id)
        fields = data.model_dump(exclude_unset=True)
        if fields:
            await self.master_repo.update_fields(master_id, **fields)
            await self.session.refresh(m)
        return m

    async def delete_master_schedule(self, master_id: uuid.UUID) -> None:
        await self.get_master_schedule(master_id)
        await self.master_repo.delete(master_id)

    # ── Phase plan ─────────────────────────────────────────────────────

    async def create_phase_plan(self, data: PhasePlanCreate) -> PhasePlan:
        p = PhasePlan(**data.model_dump())
        return await self.phase_repo.create(p)

    async def get_phase_plan(self, phase_id: uuid.UUID) -> PhasePlan:
        p = await self.phase_repo.get_by_id(phase_id)
        if p is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PhasePlan not found")
        return p

    async def update_phase_plan(
        self,
        phase_id: uuid.UUID,
        data: PhasePlanUpdate,
    ) -> PhasePlan:
        p = await self.get_phase_plan(phase_id)
        fields = data.model_dump(exclude_unset=True)
        if "pulled_status" in fields and fields["pulled_status"] not in allowed_phase_transitions(p.pulled_status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Illegal phase transition {p.pulled_status} → {fields['pulled_status']}",
            )
        if fields:
            await self.phase_repo.update_fields(phase_id, **fields)
            await self.session.refresh(p)
        return p

    async def delete_phase_plan(self, phase_id: uuid.UUID) -> None:
        await self.get_phase_plan(phase_id)
        await self.phase_repo.delete(phase_id)

    async def pull_phase(self, phase_id: uuid.UUID, user_id: str | None = None) -> PhasePlan:
        """Move a phase plan from ``in_planning`` to ``pulled``.

        Idempotent: a phase already in ``pulled`` is returned unchanged
        without re-stamping ``pull_session_at`` or re-emitting the
        ``phase.pulled`` event. Without this guard a double-click (or a
        retried request) would re-fire the event and downstream
        subscribers would double-process the pull session.
        """
        p = await self.get_phase_plan(phase_id)
        if p.pulled_status == "pulled":
            return p
        if "pulled" not in allowed_phase_transitions(p.pulled_status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Phase cannot be pulled from state {p.pulled_status}",
            )
        await self.phase_repo.update_fields(
            phase_id,
            pulled_status="pulled",
            pull_session_at=datetime.now(UTC),
        )
        await self.session.refresh(p)
        event_bus.publish_detached(
            "schedule_advanced.phase.pulled",
            {
                "phase_id": str(phase_id),
                "master_schedule_id": str(p.master_schedule_id),
                "user_id": user_id,
            },
            source_module="schedule_advanced",
        )
        return p

    async def start_phase(self, phase_id: uuid.UUID) -> PhasePlan:
        p = await self.get_phase_plan(phase_id)
        if "active" not in allowed_phase_transitions(p.pulled_status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Phase cannot transition to active from {p.pulled_status}",
            )
        await self.phase_repo.update_fields(phase_id, pulled_status="active")
        await self.session.refresh(p)
        return p

    async def complete_phase(self, phase_id: uuid.UUID) -> PhasePlan:
        p = await self.get_phase_plan(phase_id)
        if "completed" not in allowed_phase_transitions(p.pulled_status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Phase cannot transition to completed from {p.pulled_status}",
            )
        prior_status = p.pulled_status
        await self.phase_repo.update_fields(phase_id, pulled_status="completed")
        await self.session.refresh(p)

        # Epic H — universal audit trail.
        from app.core.audit_log import log_activity as _log_activity

        await _log_activity(
            self.session,
            actor_id=None,
            entity_type="phase_plan",
            entity_id=str(phase_id),
            action="status_changed",
            from_status=prior_status,
            to_status="completed",
            reason="Phase completed",
            module="schedule_advanced",
            parent_entity_type="project",
            parent_entity_id=str(p.project_id) if getattr(p, "project_id", None) else None,
            before_state={"pulled_status": prior_status},
            after_state={"pulled_status": "completed"},
        )

        return p

    # ── Look-ahead plan ────────────────────────────────────────────────

    async def create_look_ahead(self, data: LookAheadCreate) -> LookAheadPlan:
        la = LookAheadPlan(**data.model_dump())
        return await self.look_ahead_repo.create(la)

    async def get_look_ahead(self, la_id: uuid.UUID) -> LookAheadPlan:
        la = await self.look_ahead_repo.get_by_id(la_id)
        if la is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="LookAheadPlan not found")
        return la

    async def update_look_ahead(
        self,
        la_id: uuid.UUID,
        data: LookAheadUpdate,
    ) -> LookAheadPlan:
        la = await self.get_look_ahead(la_id)
        fields = data.model_dump(exclude_unset=True)
        if "status" in fields and fields["status"] not in allowed_look_ahead_transitions(la.status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Illegal look-ahead transition {la.status} → {fields['status']}",
            )
        if fields:
            await self.look_ahead_repo.update_fields(la_id, **fields)
            await self.session.refresh(la)
        return la

    async def delete_look_ahead(self, la_id: uuid.UUID) -> None:
        await self.get_look_ahead(la_id)
        await self.look_ahead_repo.delete(la_id)

    async def publish_look_ahead(self, la_id: uuid.UUID) -> LookAheadPlan:
        la = await self.get_look_ahead(la_id)
        if "published" not in allowed_look_ahead_transitions(la.status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Look-ahead cannot be published from state {la.status}",
            )
        await self.look_ahead_repo.update_fields(
            la_id,
            status="published",
            generated_at=datetime.now(UTC),
        )
        await self.session.refresh(la)
        return la

    # ── Constraint ─────────────────────────────────────────────────────

    async def create_constraint(self, data: ConstraintCreate) -> Constraint:
        c = Constraint(**data.model_dump())
        return await self.constraint_repo.create(c)

    async def get_constraint(self, cid: uuid.UUID) -> Constraint:
        c = await self.constraint_repo.get_by_id(cid)
        if c is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Constraint not found")
        return c

    async def update_constraint(
        self,
        cid: uuid.UUID,
        data: ConstraintUpdate,
    ) -> Constraint:
        c = await self.get_constraint(cid)
        fields = data.model_dump(exclude_unset=True)
        if "status" in fields and fields["status"] not in allowed_constraint_transitions(c.status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Illegal constraint transition {c.status} → {fields['status']}",
            )
        if fields:
            await self.constraint_repo.update_fields(cid, **fields)
            await self.session.refresh(c)
        return c

    async def delete_constraint(self, cid: uuid.UUID) -> None:
        await self.get_constraint(cid)
        await self.constraint_repo.delete(cid)

    async def clear_constraint(self, cid: uuid.UUID, user_id: str | None = None) -> Constraint:
        """Flip a constraint to ``cleared`` and emit the event.

        Idempotent: an already-``cleared`` constraint is returned
        unchanged. Re-running would otherwise overwrite the original
        ``cleared_at`` / ``cleared_by`` audit trail and re-emit the
        ``constraint.cleared`` event.
        """
        c = await self.get_constraint(cid)
        if c.status == "cleared":
            return c
        if "cleared" not in allowed_constraint_transitions(c.status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Constraint cannot be cleared from state {c.status}",
            )
        cleared_by_uuid = None
        if user_id is not None:
            try:
                cleared_by_uuid = uuid.UUID(str(user_id))
            except (TypeError, ValueError):
                cleared_by_uuid = None
        await self.constraint_repo.update_fields(
            cid,
            status="cleared",
            cleared_at=datetime.now(UTC),
            cleared_by=cleared_by_uuid,
        )
        await self.session.refresh(c)
        event_bus.publish_detached(
            "schedule_advanced.constraint.cleared",
            {
                "constraint_id": str(cid),
                "task_ref": str(c.task_ref),
                "user_id": user_id,
            },
            source_module="schedule_advanced",
        )
        return c

    async def escalate_constraint(self, cid: uuid.UUID) -> Constraint:
        c = await self.get_constraint(cid)
        if "escalated" not in allowed_constraint_transitions(c.status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Constraint cannot be escalated from {c.status}",
            )
        await self.constraint_repo.update_fields(cid, status="escalated")
        await self.session.refresh(c)
        return c

    async def cannot_clear_constraint(self, cid: uuid.UUID) -> Constraint:
        c = await self.get_constraint(cid)
        if "cannot_clear" not in allowed_constraint_transitions(c.status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Constraint cannot transition to cannot_clear from {c.status}",
            )
        await self.constraint_repo.update_fields(cid, status="cannot_clear")
        await self.session.refresh(c)
        return c

    # ── Weekly work plan ───────────────────────────────────────────────

    async def create_weekly_plan(self, data: WeeklyWorkPlanCreate) -> WeeklyWorkPlan:
        w = WeeklyWorkPlan(**data.model_dump())
        return await self.weekly_repo.create(w)

    async def get_weekly_plan(self, wp_id: uuid.UUID) -> WeeklyWorkPlan:
        w = await self.weekly_repo.get_by_id(wp_id)
        if w is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="WeeklyWorkPlan not found")
        return w

    async def update_weekly_plan(
        self,
        wp_id: uuid.UUID,
        data: WeeklyWorkPlanUpdate,
    ) -> WeeklyWorkPlan:
        w = await self.get_weekly_plan(wp_id)
        fields = data.model_dump(exclude_unset=True)
        if "status" in fields and fields["status"] not in allowed_weekly_transitions(w.status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Illegal weekly-plan transition {w.status} → {fields['status']}",
            )
        if fields:
            await self.weekly_repo.update_fields(wp_id, **fields)
            await self.session.refresh(w)
        return w

    async def delete_weekly_plan(self, wp_id: uuid.UUID) -> None:
        await self.get_weekly_plan(wp_id)
        await self.weekly_repo.delete(wp_id)

    async def commit_weekly_plan(self, wp_id: uuid.UUID) -> WeeklyWorkPlan:
        """Flip a weekly plan from ``draft`` to ``committed``.

        Idempotent: an already-``committed`` plan is returned unchanged
        so a retried commit does not reset ``generated_at``.
        """
        w = await self.get_weekly_plan(wp_id)
        if w.status == "committed":
            return w
        if "committed" not in allowed_weekly_transitions(w.status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Weekly plan cannot be committed from {w.status}",
            )
        await self.weekly_repo.update_fields(
            wp_id,
            status="committed",
            generated_at=datetime.now(UTC),
        )
        await self.session.refresh(w)
        return w

    async def close_weekly_plan(
        self,
        wp_id: uuid.UUID,
        today: date | None = None,
    ) -> WeeklyWorkPlan:
        """Close a weekly plan, compute PPC, and emit the closed event.

        Idempotent: an already-``closed`` plan is returned unchanged so
        a retried close does not re-emit ``weekly_plan.closed`` (which
        would double-trigger downstream PPC-trend / notification work).
        """
        _ = today  # reserved for date-window enforcement; not enforced here
        w = await self.get_weekly_plan(wp_id)
        if w.status == "closed":
            return w
        if "closed" not in allowed_weekly_transitions(w.status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Weekly plan cannot be closed from {w.status}",
            )
        commitments = await self.commitment_repo.commitments_for_week(wp_id)
        ppc = compute_ppc(commitments)
        missed_payload = [
            {
                "commitment_id": str(c.id),
                "task_ref": str(c.task_ref),
                "status": c.status,
            }
            for c in commitments
            if c.status == "missed"
        ]
        prior_status = w.status
        await self.weekly_repo.update_fields(wp_id, status="closed", ppc_percent=ppc)
        await self.session.refresh(w)

        # Epic H — universal audit trail.
        from app.core.audit_log import log_activity as _log_activity

        await _log_activity(
            self.session,
            actor_id=None,
            entity_type="weekly_work_plan",
            entity_id=str(wp_id),
            action="status_changed",
            from_status=prior_status,
            to_status="closed",
            reason="Weekly work plan closed",
            metadata={
                "ppc_percent": str(ppc),
                "missed_count": len(missed_payload),
            },
            module="schedule_advanced",
            before_state={"status": prior_status},
            after_state={"status": "closed", "ppc_percent": str(ppc)},
        )

        event_bus.publish_detached(
            "schedule_advanced.weekly_plan.closed",
            {
                "week_plan_id": str(wp_id),
                "master_schedule_id": str(w.master_schedule_id),
                "ppc_percent": str(ppc),
                "missed_commitments": missed_payload,
            },
            source_module="schedule_advanced",
        )
        return w

    # ── Commitment ─────────────────────────────────────────────────────

    async def create_commitment(self, data: CommitmentCreate) -> Commitment:
        c = Commitment(**data.model_dump())
        return await self.commitment_repo.create(c)

    async def get_commitment(self, cid: uuid.UUID) -> Commitment:
        c = await self.commitment_repo.get_by_id(cid)
        if c is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Commitment not found")
        return c

    async def update_commitment(
        self,
        cid: uuid.UUID,
        data: CommitmentUpdate,
    ) -> Commitment:
        c = await self.get_commitment(cid)
        fields = data.model_dump(exclude_unset=True)
        if "status" in fields and fields["status"] not in allowed_commitment_transitions(c.status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Illegal commitment transition {c.status} → {fields['status']}",
            )
        if fields:
            await self.commitment_repo.update_fields(cid, **fields)
            await self.session.refresh(c)
        return c

    async def delete_commitment(self, cid: uuid.UUID) -> None:
        await self.get_commitment(cid)
        await self.commitment_repo.delete(cid)

    async def commit_to_week(
        self,
        cid: uuid.UUID,
        user_id: str | None = None,
    ) -> Commitment:
        """Flip Commitment.status planned → committed; emit the event.

        Idempotent: an already-``committed`` commitment is returned
        unchanged (no re-stamp of ``made_at`` / ``made_by_user_id``,
        no duplicate ``commitment.made`` event on a retried request).
        """
        c = await self.get_commitment(cid)
        if c.status == "committed":
            return c
        if "committed" not in allowed_commitment_transitions(c.status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Commitment cannot transition to committed from {c.status}",
            )
        made_by_uuid = None
        if user_id is not None:
            try:
                made_by_uuid = uuid.UUID(str(user_id))
            except (TypeError, ValueError):
                made_by_uuid = None
        await self.commitment_repo.update_fields(
            cid,
            status="committed",
            made_at=datetime.now(UTC),
            made_by_user_id=made_by_uuid,
        )
        await self.session.refresh(c)
        event_bus.publish_detached(
            "schedule_advanced.commitment.made",
            {
                "commitment_id": str(cid),
                "week_plan_id": str(c.week_plan_id),
                "task_ref": str(c.task_ref),
                "user_id": user_id,
            },
            source_module="schedule_advanced",
        )
        return c

    async def mark_commitment_complete(
        self,
        cid: uuid.UUID,
        actual_qty: Decimal | None = None,
        today: date | None = None,
    ) -> Commitment:
        c = await self.get_commitment(cid)
        if "completed" not in allowed_commitment_transitions(c.status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Commitment cannot be completed from {c.status}",
            )
        completed_at = (
            datetime.combine(today, datetime.min.time(), tzinfo=UTC) if today is not None else datetime.now(UTC)
        )
        await self.commitment_repo.update_fields(
            cid,
            status="completed",
            completed_at=completed_at,
            actual_qty=actual_qty,
        )
        await self.session.refresh(c)
        return c

    async def mark_commitment_missed(
        self,
        cid: uuid.UUID,
        rnc_payload: dict[str, Any] | RNCCreate,
    ) -> tuple[Commitment, ReasonForNonCompletion]:
        """Flip a commitment to ``missed`` and record the paired RNC."""
        c = await self.get_commitment(cid)
        if "missed" not in allowed_commitment_transitions(c.status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Commitment cannot be marked missed from {c.status}",
            )
        await self.commitment_repo.update_fields(cid, status="missed")
        await self.session.refresh(c)

        if isinstance(rnc_payload, RNCCreate):
            payload = rnc_payload.model_dump()
        else:
            payload = dict(rnc_payload)
        payload["commitment_id"] = cid
        rnc = ReasonForNonCompletion(
            commitment_id=cid,
            category=payload.get("category", "other"),
            description=payload.get("description", ""),
            recorded_at=payload.get("recorded_at") or datetime.now(UTC),
            recorded_by=payload.get("recorded_by"),
            root_cause_notes=payload.get("root_cause_notes", ""),
        )
        rnc = await self.rnc_repo.create(rnc)
        return c, rnc

    # ── RNC ────────────────────────────────────────────────────────────

    async def create_rnc(
        self,
        data: RNCCreate,
        user_id: str | None = None,
    ) -> ReasonForNonCompletion:
        recorded_by_uuid = None
        if user_id is not None:
            try:
                recorded_by_uuid = uuid.UUID(str(user_id))
            except (TypeError, ValueError):
                recorded_by_uuid = None
        r = ReasonForNonCompletion(
            commitment_id=data.commitment_id,
            category=data.category,
            description=data.description,
            recorded_at=data.recorded_at or datetime.now(UTC),
            recorded_by=recorded_by_uuid,
            root_cause_notes=data.root_cause_notes,
        )
        return await self.rnc_repo.create(r)

    async def get_rnc(self, rid: uuid.UUID) -> ReasonForNonCompletion:
        r = await self.rnc_repo.get_by_id(rid)
        if r is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="RNC not found")
        return r

    async def update_rnc(
        self,
        rid: uuid.UUID,
        data: RNCUpdate,
    ) -> ReasonForNonCompletion:
        r = await self.get_rnc(rid)
        fields = data.model_dump(exclude_unset=True)
        if fields:
            await self.rnc_repo.update_fields(rid, **fields)
            await self.session.refresh(r)
        return r

    async def delete_rnc(self, rid: uuid.UUID) -> None:
        await self.get_rnc(rid)
        await self.rnc_repo.delete(rid)

    async def rnc_pareto_for_project(
        self,
        project_id: uuid.UUID,
        period_start: date,
        period_end: date,
    ) -> dict[str, int]:
        rncs = await self.rnc_repo.list_for_project_period(project_id, period_start, period_end)
        return compute_rnc_pareto(rncs, period_start, period_end)

    # ── Baseline ───────────────────────────────────────────────────────

    async def capture_baseline(
        self,
        master_schedule_id: uuid.UUID,
        snapshot_tasks_payload: list[dict[str, Any]] | dict[str, Any],
        name: str,
        user_id: str | None = None,
    ) -> Baseline:
        """Capture a new baseline + emit the event."""
        await self.get_master_schedule(master_schedule_id)
        captured_by_uuid = None
        if user_id is not None:
            try:
                captured_by_uuid = uuid.UUID(str(user_id))
            except (TypeError, ValueError):
                captured_by_uuid = None
        snapshot: list[dict[str, Any]] | dict[str, Any]
        if isinstance(snapshot_tasks_payload, list):
            snapshot = [self._normalise_snapshot_row(r) for r in snapshot_tasks_payload]
        else:
            snapshot = snapshot_tasks_payload
        b = Baseline(
            master_schedule_id=master_schedule_id,
            name=name,
            captured_at=datetime.now(UTC),
            captured_by=captured_by_uuid,
            snapshot=snapshot,
            status="active",
        )
        b = await self.baseline_repo.create(b)
        event_bus.publish_detached(
            "schedule_advanced.baseline.captured",
            {
                "baseline_id": str(b.id),
                "master_schedule_id": str(master_schedule_id),
                "name": name,
                "user_id": user_id,
            },
            source_module="schedule_advanced",
        )
        return b

    @staticmethod
    def _normalise_snapshot_row(row: dict[str, Any]) -> dict[str, Any]:
        """Coerce date/datetime values in a snapshot row to ISO strings for JSON storage."""
        out: dict[str, Any] = {}
        for k, v in row.items():
            if isinstance(v, datetime):
                out[k] = v.date().isoformat()
            elif isinstance(v, date):
                out[k] = v.isoformat()
            elif isinstance(v, uuid.UUID):
                out[k] = str(v)
            else:
                out[k] = v
        return out

    async def create_baseline(
        self,
        data: BaselineCreate,
        user_id: str | None = None,
    ) -> Baseline:
        return await self.capture_baseline(
            data.master_schedule_id,
            data.snapshot if data.snapshot else [],
            data.name,
            user_id=user_id,
        )

    async def get_baseline(self, bid: uuid.UUID) -> Baseline:
        b = await self.baseline_repo.get_by_id(bid)
        if b is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate("errors.baseline_not_found", locale=get_locale()),
            )
        return b

    async def update_baseline(
        self,
        bid: uuid.UUID,
        data: BaselineUpdate,
    ) -> Baseline:
        b = await self.get_baseline(bid)
        fields = data.model_dump(exclude_unset=True)
        if "status" in fields and fields["status"] not in allowed_baseline_transitions(b.status):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Illegal baseline transition {b.status} → {fields['status']}",
            )
        if fields:
            await self.baseline_repo.update_fields(bid, **fields)
            await self.session.refresh(b)
        return b

    async def delete_baseline(self, bid: uuid.UUID) -> None:
        await self.get_baseline(bid)
        await self.baseline_repo.delete(bid)

    async def compute_baseline_delta_for_schedule(
        self,
        baseline_id: uuid.UUID,
        current_tasks: list[dict[str, Any]],
    ) -> BaselineDeltaResponse:
        """Compute and persist :class:`BaselineDelta` rows for a baseline.

        Returns the aggregated :class:`BaselineDeltaResponse` (not just the
        persisted rows) so callers don't need a second round-trip.
        """
        b = await self.get_baseline(baseline_id)
        delta_records = compute_baseline_delta(b.snapshot, current_tasks)

        # Persist deltas (idempotency note: this is a re-computation entry
        # point — we wipe prior deltas for this (baseline, current_master)
        # pair before re-inserting).
        prior = await self.baseline_delta_repo.list_for_baseline(baseline_id)
        for old in prior:
            await self.baseline_delta_repo.delete(old.id)

        delayed = 0
        accelerated = 0
        entries: list[BaselineDeltaEntry] = []
        now = datetime.now(UTC)
        for rec in delta_records:
            task_ref_raw = rec["task_ref"]
            try:
                task_ref = uuid.UUID(str(task_ref_raw))
            except (TypeError, ValueError):
                continue
            variance = rec["schedule_variance_days"]
            if variance > 0:
                delayed += 1
            elif variance < 0:
                accelerated += 1
            entries.append(
                BaselineDeltaEntry(
                    task_ref=task_ref,
                    planned_start_baseline=rec["planned_start_baseline"],
                    planned_start_current=rec["planned_start_current"],
                    planned_finish_baseline=rec["planned_finish_baseline"],
                    planned_finish_current=rec["planned_finish_current"],
                    schedule_variance_days=variance,
                )
            )
            row = BaselineDelta(
                baseline_id=baseline_id,
                current_master_id=b.master_schedule_id,
                task_ref=task_ref,
                planned_start_baseline=rec["planned_start_baseline"],
                planned_start_current=rec["planned_start_current"],
                planned_finish_baseline=rec["planned_finish_baseline"],
                planned_finish_current=rec["planned_finish_current"],
                schedule_variance_days=variance,
                computed_at=now,
            )
            await self.baseline_delta_repo.create(row)

        return BaselineDeltaResponse(
            baseline_id=baseline_id,
            current_master_id=b.master_schedule_id,
            entries=entries,
            total_tasks=len(entries),
            delayed_tasks=delayed,
            accelerated_tasks=accelerated,
        )

    # ── Calendar ───────────────────────────────────────────────────────

    async def create_calendar(self, data: CalendarCreate) -> Calendar:
        cal = Calendar(**data.model_dump())
        return await self.calendar_repo.create(cal)

    async def get_calendar(self, cid: uuid.UUID) -> Calendar:
        c = await self.calendar_repo.get_by_id(cid)
        if c is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Calendar not found")
        return c

    async def update_calendar(self, cid: uuid.UUID, data: CalendarUpdate) -> Calendar:
        c = await self.get_calendar(cid)
        fields = data.model_dump(exclude_unset=True)
        if fields:
            await self.calendar_repo.update_fields(cid, **fields)
            await self.session.refresh(c)
        return c

    async def delete_calendar(self, cid: uuid.UUID) -> None:
        await self.get_calendar(cid)
        await self.calendar_repo.delete(cid)

    # ── Dashboard ──────────────────────────────────────────────────────

    async def lps_dashboard_for_project(
        self,
        project_id: uuid.UUID,
        today: date | None = None,
    ) -> dict[str, Any]:
        """Aggregate LPS dashboard data for a project."""
        today = today or datetime.now(UTC).date()
        master_schedules, _ = await self.master_repo.list_for_project(
            project_id,
            offset=0,
            limit=200,
            status=None,
        )
        active_masters = [m for m in master_schedules if m.status == "active"]

        open_constraints = await self.constraint_repo.open_constraints_for_project(project_id)
        constraints_by_type: dict[str, int] = defaultdict(int)
        for c in open_constraints:
            constraints_by_type[c.constraint_type] += 1

        recent_weekly = await self.weekly_repo.last_n_weeks_ppc(project_id, n=12)
        ppc_trend = [
            {
                "week_start_date": w.week_start_date,
                "total_commitments": 0,
                "completed_commitments": 0,
                "ppc_percent": w.ppc_percent or Decimal("0"),
            }
            for w in reversed(recent_weekly)
        ]

        # RNC pareto for last 90 days
        rncs = await self.rnc_repo.list_for_project_period(
            project_id,
            today - timedelta(days=90),
            today,
        )
        rnc_pareto = compute_rnc_pareto(rncs, today - timedelta(days=90), today)

        baselines = await self.baseline_repo.list_for_project(project_id, status="active")

        # Single aggregate query (was an N+1: one current_week_plan +
        # one commitments_for_week round trip per active master).
        current_week_count = await self.weekly_repo.current_week_commitment_count(
            project_id,
            today,
        )

        return {
            "project_id": project_id,
            "ppc_trend": ppc_trend,
            "open_constraints": len(open_constraints),
            "constraints_by_type": dict(constraints_by_type),
            "rnc_pareto": rnc_pareto,
            "active_master_schedules": len(active_masters),
            "active_baselines": len(baselines),
            "current_week_commitments": current_week_count,
        }

    # ── CPM / EVM / TIA endpoints ──────────────────────────────────────

    async def look_ahead_readiness(
        self,
        la_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """Per-task readiness summary for a Look-Ahead's constraints.

        Aggregates every constraint linked to the look-ahead and groups
        them by ``task_ref``, returning one
        :func:`constraint_ready_state` summary per task. Tasks with no
        open constraints are still included (with ``is_ready=True``,
        ``open_count=0``).
        """
        await self.get_look_ahead(la_id)
        rows = await self.constraint_repo.list_for_look_ahead(la_id)
        # Group constraints by task
        task_refs: list[uuid.UUID] = []
        seen: set[str] = set()
        for c in rows:
            key = str(c.task_ref)
            if key in seen:
                continue
            seen.add(key)
            task_refs.append(c.task_ref)
        return [constraint_ready_state(t, rows) for t in task_refs]

    async def rnc_pareto_sorted_for_project(
        self,
        project_id: uuid.UUID,
        period_start: date,
        period_end: date,
    ) -> dict[str, Any]:
        """Return Pareto-sorted RNC counts with cumulative %."""
        rncs = await self.rnc_repo.list_for_project_period(
            project_id,
            period_start,
            period_end,
        )
        rows = compute_rnc_pareto_sorted(rncs)
        return {
            "period_start": period_start,
            "period_end": period_end,
            "rows": rows,
            "total": sum(r["count"] for r in rows),
        }

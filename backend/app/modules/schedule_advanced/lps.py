# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Last Planner board​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ - look-ahead pulled from the schedule, readiness, PPC history, Pareto, validation.

The LPS tables (look-ahead, constraint, weekly plan, commitment, RNC) live in
:mod:`app.modules.schedule_advanced.models`. This module joins them to the rest
of the platform:

* the look-ahead board lists the **schedule activities** (``oe_schedule_activity``)
  whose dates fall in the look-ahead window, week by week, with their
  constraints. A task is *ready* only when every constraint on it is cleared;
* a constraint may name the record that clears it (RFI, submittal, purchase
  order, goods receipt); the board shows that record's number and status;
* committing a commitment whose task still has open constraints is refused,
  and completing a commitment moves the schedule activity's progress to the
  commitment's ``target_progress_pct`` through the schedule service;
* PPC per week and reasons for variance (Pareto) per master schedule, and the
  ``last_planner`` validation rule set over the same data.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.schedule_advanced.models import (
    Commitment,
    Constraint,
    LookAheadPlan,
    MasterSchedule,
    ReasonForNonCompletion,
    WeeklyWorkPlan,
)

logger = logging.getLogger(__name__)

OPEN_CONSTRAINT_STATES = ("open", "in_progress", "escalated")
COMMITTED_STATES = ("committed", "in_progress", "completed", "missed", "at_risk")
LPS_RULE_SET = "last_planner"


def _iso(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def monday(d: date) -> date:
    """The Monday of the week holding ``d``."""
    return d - timedelta(days=d.weekday())


def week_ppc(commitments: list[Any]) -> tuple[int, int, Decimal | None]:
    """``(committed, completed, ppc)``; ppc is ``None`` when nothing was committed."""
    committed = [c for c in commitments if c.status in COMMITTED_STATES]
    done = sum(1 for c in committed if c.status == "completed")
    if not committed:
        return 0, 0, None
    return len(committed), done, (Decimal(done) * 100 / Decimal(len(committed))).quantize(Decimal("0.01"))


def pareto_rows(counts: dict[str, int]) -> list[dict[str, Any]]:
    """Sort categories by count and add the cumulative share, the line on a Pareto chart."""
    total = sum(counts.values())
    rows: list[dict[str, Any]] = []
    running = 0
    for cat, n in sorted(((k, v) for k, v in counts.items() if v > 0), key=lambda kv: (-kv[1], kv[0])):
        running += n
        rows.append(
            {
                "category": cat,
                "count": n,
                "percent": (Decimal(n) * 100 / Decimal(total)).quantize(Decimal("0.1")) if total else Decimal("0"),
                "cumulative_percent": (Decimal(running) * 100 / Decimal(total)).quantize(Decimal("0.1"))
                if total
                else Decimal("0"),
            }
        )
    return rows


class LastPlannerService:
    """Board, PPC history, Pareto and validation over one master schedule."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _master(self, master_id: uuid.UUID) -> MasterSchedule:
        m = await self.session.get(MasterSchedule, master_id)
        if m is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Master schedule not found")
        return m

    async def project_activities(self, project_id: uuid.UUID) -> list[Any]:
        """Leaf activities of every schedule of the project (summaries are left out)."""
        from app.modules.schedule.models import Activity, Schedule  # noqa: PLC0415

        rows = (
            (
                await self.session.execute(
                    select(Activity)
                    .join(Schedule, Schedule.id == Activity.schedule_id)
                    .where(Schedule.project_id == project_id)
                )
            )
            .scalars()
            .all()
        )
        parents = {a.parent_id for a in rows if a.parent_id is not None}
        return [a for a in rows if a.id not in parents]

    async def _linked_labels(self, constraints: list[Constraint]) -> dict[str, dict[str, Any]]:
        """Number/title and status of the RFI, submittal, PO or goods receipt each constraint names."""
        by_type: dict[str, list[uuid.UUID]] = defaultdict(list)
        for c in constraints:
            if c.linked_type and c.linked_id:
                by_type[c.linked_type].append(c.linked_id)
        out: dict[str, dict[str, Any]] = {}

        async def load(model_path: str, cls: str, ids: list[uuid.UUID], label: str) -> None:
            try:
                mod = __import__(model_path, fromlist=[cls])
                model = getattr(mod, cls)
            except (ImportError, AttributeError):
                return
            for row in (await self.session.execute(select(model).where(model.id.in_(ids)))).scalars():
                out[str(row.id)] = {"label": str(getattr(row, label, "") or ""), "status": getattr(row, "status", "")}

        if by_type.get("rfi"):
            await load("app.modules.rfi.models", "RFI", by_type["rfi"], "rfi_number")
        if by_type.get("submittal"):
            await load("app.modules.submittals.models", "Submittal", by_type["submittal"], "title")
        if by_type.get("purchase_order"):
            await load("app.modules.procurement.models", "PurchaseOrder", by_type["purchase_order"], "po_number")
        if by_type.get("goods_receipt"):
            await load("app.modules.procurement.models", "GoodsReceipt", by_type["goods_receipt"], "id")
        return out

    async def board(self, la_id: uuid.UUID) -> dict[str, Any]:
        """The look-ahead board: schedule activities in the window, by week, with readiness."""
        la = await self.session.get(LookAheadPlan, la_id)
        if la is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Look-ahead not found")
        master = await self._master(la.master_schedule_id)
        start, end = la.period_start, la.period_end
        weeks = []
        wk = monday(start)
        while wk <= end:
            weeks.append(wk)
            wk += timedelta(weeks=1)

        activities = []
        for a in await self.project_activities(master.project_id):
            a_start, a_end = _iso(a.start_date), _iso(a.end_date)
            if a_start is None or a_end is None or a_end < start or a_start > end:
                continue
            activities.append((a, a_start, a_end))
        ids = [a.id for a, _s, _e in activities]
        constraints = (
            list(
                (
                    await self.session.execute(
                        select(Constraint).where((Constraint.task_ref.in_(ids)) | (Constraint.look_ahead_id == la_id))
                    )
                ).scalars()
            )
            if ids
            else list(
                (await self.session.execute(select(Constraint).where(Constraint.look_ahead_id == la_id))).scalars()
            )
        )
        links = await self._linked_labels(constraints)
        by_task: dict[str, list[Constraint]] = defaultdict(list)
        for c in constraints:
            by_task[str(c.task_ref)].append(c)

        commitments = (
            list(
                (
                    await self.session.execute(
                        select(Commitment)
                        .join(WeeklyWorkPlan, WeeklyWorkPlan.id == Commitment.week_plan_id)
                        .where(WeeklyWorkPlan.master_schedule_id == master.id, Commitment.task_ref.in_(ids))
                    )
                ).scalars()
            )
            if ids
            else []
        )
        committed_tasks = {str(c.task_ref) for c in commitments}

        tasks = []
        for a, a_start, a_end in sorted(activities, key=lambda t: (t[1], t[0].name)):
            cs = by_task.get(str(a.id), [])
            open_cs = [c for c in cs if c.status in OPEN_CONSTRAINT_STATES]
            tasks.append(
                {
                    "task_ref": a.id,
                    "name": a.name,
                    "wbs_code": a.wbs_code or "",
                    "start_date": a_start,
                    "end_date": a_end,
                    "week_start": max(monday(a_start), weeks[0]) if weeks else monday(a_start),
                    "progress_pct": Decimal(str(a.progress_pct or "0")),
                    "is_ready": not open_cs,
                    "open_constraints": len(open_cs),
                    "committed": str(a.id) in committed_tasks,
                    "constraints": [_constraint_dict(c, links) for c in cs],
                }
            )
        return {
            "look_ahead_id": la.id,
            "master_schedule_id": master.id,
            "project_id": master.project_id,
            "period_start": start,
            "period_end": end,
            "weeks": weeks,
            "tasks": tasks,
            "ready_count": sum(1 for t in tasks if t["is_ready"]),
            "blocked_count": sum(1 for t in tasks if not t["is_ready"]),
        }

    async def constraints_log(self, master_id: uuid.UUID) -> list[dict[str, Any]]:
        """Every constraint on the master's look-aheads or tasks, with its linked record."""
        master = await self._master(master_id)
        la_ids = [
            r
            for r in (
                await self.session.execute(
                    select(LookAheadPlan.id).where(LookAheadPlan.master_schedule_id == master_id)
                )
            ).scalars()
        ]
        act_ids = [a.id for a in await self.project_activities(master.project_id)]
        conds = []
        if la_ids:
            conds.append(Constraint.look_ahead_id.in_(la_ids))
        if act_ids:
            conds.append(Constraint.task_ref.in_(act_ids))
        if not conds:
            return []
        where = conds[0] if len(conds) == 1 else (conds[0] | conds[1])
        rows = list((await self.session.execute(select(Constraint).where(where))).scalars())
        links = await self._linked_labels(rows)
        names = {str(a.id): a.name for a in await self.project_activities(master.project_id)}
        out = []
        for c in sorted(rows, key=lambda c: (c.status not in OPEN_CONSTRAINT_STATES, c.target_clear_date or date.max)):
            d = _constraint_dict(c, links)
            d["task_name"] = names.get(str(c.task_ref), "")
            out.append(d)
        return out

    async def ppc_history(self, master_id: uuid.UUID, *, limit: int = 26) -> dict[str, Any]:
        """PPC per week, oldest first, and the RNC Pareto over the same weeks."""
        await self._master(master_id)
        plans = list(
            (
                await self.session.execute(
                    select(WeeklyWorkPlan)
                    .where(WeeklyWorkPlan.master_schedule_id == master_id)
                    .order_by(WeeklyWorkPlan.week_start_date.desc())
                    .limit(limit)
                )
            ).scalars()
        )
        plans.reverse()
        plan_ids = [p.id for p in plans]
        commits = (
            list(
                (await self.session.execute(select(Commitment).where(Commitment.week_plan_id.in_(plan_ids)))).scalars()
            )
            if plan_ids
            else []
        )
        by_plan: dict[uuid.UUID, list[Commitment]] = defaultdict(list)
        for c in commits:
            by_plan[c.week_plan_id].append(c)
        weeks = []
        for p in plans:
            n, done, computed = week_ppc(by_plan.get(p.id, []))
            weeks.append(
                {
                    "week_plan_id": p.id,
                    "week_start_date": p.week_start_date,
                    "status": p.status,
                    "committed": n,
                    "completed": done,
                    "ppc_percent": p.ppc_percent if p.ppc_percent is not None else computed,
                }
            )
        recorded = [w["ppc_percent"] for w in weeks if w["status"] == "closed" and w["ppc_percent"] is not None]
        avg = (sum(recorded, Decimal("0")) / len(recorded)).quantize(Decimal("0.01")) if recorded else None
        c_ids = [c.id for c in commits]
        rncs = (
            list(
                (
                    await self.session.execute(
                        select(ReasonForNonCompletion).where(ReasonForNonCompletion.commitment_id.in_(c_ids))
                    )
                ).scalars()
            )
            if c_ids
            else []
        )
        counts: dict[str, int] = defaultdict(int)
        for r in rncs:
            counts[r.category] += 1
        return {
            "master_schedule_id": master_id,
            "weeks": weeks,
            "average_ppc": avg,
            "pareto": pareto_rows(dict(counts)),
        }

    async def assert_commitment_ready(self, commitment: Commitment) -> None:
        """Refuse to commit work whose task still has open constraints (LPS make-ready rule)."""
        open_rows = list(
            (
                await self.session.execute(
                    select(Constraint).where(
                        Constraint.task_ref == commitment.task_ref,
                        Constraint.status.in_(OPEN_CONSTRAINT_STATES),
                    )
                )
            )
            .scalars()
            .all()
        )
        if open_rows:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "constraints_open",
                    "message": "This task is not ready: clear its open constraints before committing to it.",
                    "constraint_ids": [str(c.id) for c in open_rows],
                },
            )

    async def apply_commitment_progress(self, commitment: Commitment, actor_id: str | None = None) -> bool:
        """Move the schedule activity to the commitment's target progress. ``True`` when it moved."""
        if getattr(commitment, "target_progress_pct", None) is None:
            return False
        from app.modules.schedule.models import Activity  # noqa: PLC0415
        from app.modules.schedule.service import ScheduleService  # noqa: PLC0415

        activity = await self.session.get(Activity, commitment.task_ref)
        if activity is None:
            return False
        target = float(commitment.target_progress_pct)
        try:
            current = float(activity.progress_pct or 0)
        except ValueError:
            current = 0.0
        if target <= current:
            return False
        await ScheduleService(self.session).update_progress(activity.id, target, actor_id=actor_id)
        return True

    async def project_id_for_week_plan(self, week_plan_id: uuid.UUID) -> uuid.UUID | None:
        """Project of a weekly plan, for event payloads."""
        return (
            (
                await self.session.execute(
                    select(MasterSchedule.project_id)
                    .join(WeeklyWorkPlan, WeeklyWorkPlan.master_schedule_id == MasterSchedule.id)
                    .where(WeeklyWorkPlan.id == week_plan_id)
                )
            )
            .scalars()
            .first()
        )

    async def validation_payload(self, master_id: uuid.UUID, today: date) -> dict[str, Any]:
        """The data the ``last_planner`` rules read."""
        master = await self._master(master_id)
        history = await self.ppc_history(master_id)
        plan_ids = [w["week_plan_id"] for w in history["weeks"]]
        commits = (
            list(
                (await self.session.execute(select(Commitment).where(Commitment.week_plan_id.in_(plan_ids)))).scalars()
            )
            if plan_ids
            else []
        )
        task_ids = list({c.task_ref for c in commits})
        open_by_task: dict[str, int] = defaultdict(int)
        if task_ids:
            for c in (
                await self.session.execute(
                    select(Constraint).where(
                        Constraint.task_ref.in_(task_ids), Constraint.status.in_(OPEN_CONSTRAINT_STATES)
                    )
                )
            ).scalars():
                open_by_task[str(c.task_ref)] += 1
        rnc_ids = (
            {
                r
                for r in (
                    await self.session.execute(
                        select(ReasonForNonCompletion.commitment_id).where(
                            ReasonForNonCompletion.commitment_id.in_([c.id for c in commits])
                        )
                    )
                ).scalars()
            }
            if commits
            else set()
        )
        week_start = {w["week_plan_id"]: w["week_start_date"] for w in history["weeks"]}
        log = await self.constraints_log(master_id)
        return {
            "as_of": today.isoformat(),
            "project_id": str(master.project_id),
            "weeks": [
                {
                    "id": str(w["week_plan_id"]),
                    "week_start_date": w["week_start_date"].isoformat(),
                    "status": w["status"],
                    "committed": w["committed"],
                    "ppc_percent": str(w["ppc_percent"]) if w["ppc_percent"] is not None else None,
                }
                for w in history["weeks"]
            ],
            "commitments": [
                {
                    "id": str(c.id),
                    "task_ref": str(c.task_ref),
                    "status": c.status,
                    "week_start_date": week_start[c.week_plan_id].isoformat(),
                    "open_constraints": open_by_task.get(str(c.task_ref), 0),
                    "has_rnc": c.id in rnc_ids,
                    "worker_or_crew": c.worker_or_crew,
                }
                for c in commits
            ],
            "constraints": [
                {
                    "id": str(c["id"]),
                    "status": c["status"],
                    "description": c["description"],
                    "target_clear_date": c["target_clear_date"].isoformat() if c["target_clear_date"] else None,
                    "owner_user_id": str(c["owner_user_id"]) if c["owner_user_id"] else None,
                }
                for c in log
            ],
        }

    async def validate(self, master_id: uuid.UUID, *, today: date | None = None, locale: str = "en") -> dict[str, Any]:
        """Run the ``last_planner`` rule set over one master schedule."""
        from app.core.validation.engine import validation_engine  # noqa: PLC0415
        from app.modules.schedule_advanced.lps_rules import register_lps_rules  # noqa: PLC0415

        register_lps_rules()
        ref = today or datetime.now(UTC).date()
        payload = await self.validation_payload(master_id, ref)
        report = await validation_engine.validate(
            payload,
            rule_sets=[LPS_RULE_SET],
            target_type="lps_master_schedule",
            target_id=str(master_id),
            project_id=payload["project_id"],
            metadata={"locale": locale},
        )
        return {
            "master_schedule_id": master_id,
            "status": report.status.value,
            "errors": len(report.errors),
            "warnings": len(report.warnings),
            "results": [
                {
                    "rule_id": r.rule_id,
                    "severity": r.severity.value,
                    "passed": r.passed,
                    "message": r.message,
                    "element_ref": r.element_ref,
                    "suggestion": r.suggestion,
                }
                for r in report.results
            ],
        }


def _constraint_dict(c: Constraint, links: dict[str, dict[str, Any]]) -> dict[str, Any]:
    link = links.get(str(c.linked_id)) if c.linked_id else None
    return {
        "id": c.id,
        "task_ref": c.task_ref,
        "constraint_type": c.constraint_type,
        "description": c.description,
        "owner_user_id": c.owner_user_id,
        "target_clear_date": c.target_clear_date,
        "status": c.status,
        "cleared_at": c.cleared_at,
        "linked_type": c.linked_type,
        "linked_id": c.linked_id,
        "linked_label": link["label"] if link else None,
        "linked_status": link["status"] if link else None,
        "link_resolved_at": c.link_resolved_at,
    }

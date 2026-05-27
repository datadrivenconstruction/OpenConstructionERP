"""‌⁠‍Schedule Advanced demo seed data.

Deterministic generator (seed=42) producing:
* 3 master schedules across the supplied project ids
* 12 phase plans
* 6 look-aheads
* ~80 constraints (mixed statuses)
* 12 weekly plans across 12 weeks (most closed with PPC history)
* ~200 commitments (mixed completed / missed)
* ~50 RNC records
* 6 baselines + ~60 baseline delta rows
* default calendars per project
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

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

_RNG_SEED = 42

_CONSTRAINT_TYPES = (
    "info",
    "material",
    "labor",
    "equipment",
    "permit",
    "predecessor",
    "weather",
    "other",
)
_CONSTRAINT_STATUSES = ("open", "in_progress", "cleared", "escalated", "cannot_clear")
_COMMITMENT_STATUSES = (
    "completed",
    "completed",
    "completed",
    "completed",
    "missed",
    "missed",
    "in_progress",
    "committed",
    "at_risk",
)
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


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


async def seed_schedule_advanced_demo(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
) -> dict[str, int]:
    """‌⁠‍Seed deterministic LPS demo data.

    Returns counts of created rows per entity.
    """
    if not project_ids:
        return {}

    rng = random.Random(_RNG_SEED)
    counts: dict[str, int] = {
        "master_schedules": 0,
        "phase_plans": 0,
        "look_aheads": 0,
        "constraints": 0,
        "weekly_plans": 0,
        "commitments": 0,
        "rncs": 0,
        "baselines": 0,
        "baseline_deltas": 0,
        "calendars": 0,
    }

    today = datetime.now(UTC).date()
    project_count = min(3, len(project_ids))
    selected_projects = project_ids[:project_count]

    # ── Calendars (1 per project) ───────────────────────────────────────
    for pid in selected_projects:
        cal = Calendar(
            project_id=pid,
            name="Default Mon-Fri",
            work_days=[0, 1, 2, 3, 4],
            work_hours_per_day=Decimal("8"),
            holidays=[],
            special_shifts={},
            is_default=True,
        )
        session.add(cal)
        counts["calendars"] += 1
    await session.flush()

    # ── Master schedules (1 per project, 3 total) ──────────────────────
    masters: list[MasterSchedule] = []
    for idx, pid in enumerate(selected_projects):
        m = MasterSchedule(
            project_id=pid,
            name=f"Master Schedule v{idx + 1}",
            baseline_date=today - timedelta(days=180),
            planned_start=today - timedelta(days=180),
            planned_finish=today + timedelta(days=365),
            status="active",
            notes="Seed data — LPS demo",
        )
        session.add(m)
        masters.append(m)
        counts["master_schedules"] += 1
    await session.flush()

    # ── Phase plans (12 total — 4 per master) ───────────────────────────
    phase_names = (
        "Site Preparation",
        "Foundations",
        "Superstructure",
        "MEP Rough-in",
        "Cladding",
        "Fit-out",
        "Commissioning",
        "Handover",
    )
    for m in masters:
        for i in range(4):
            name = phase_names[i % len(phase_names)]
            offset_days = i * 60
            p = PhasePlan(
                master_schedule_id=m.id,
                name=f"{name} ({m.name})",
                planned_start=today - timedelta(days=180 - offset_days),
                planned_finish=today - timedelta(days=180 - offset_days - 50),
                pulled_status=rng.choice(["in_planning", "pulled", "active", "completed"]),
                pull_session_at=datetime.now(UTC) - timedelta(days=rng.randint(1, 90)),
            )
            session.add(p)
            counts["phase_plans"] += 1
    await session.flush()

    # ── Look-aheads (2 per master — 6 total) ───────────────────────────
    look_aheads: list[LookAheadPlan] = []
    for m in masters:
        for j in range(2):
            start = _monday(today) - timedelta(weeks=j * 6)
            la = LookAheadPlan(
                master_schedule_id=m.id,
                period_start=start,
                period_end=start + timedelta(weeks=6) - timedelta(days=1),
                window_weeks=6,
                generated_at=datetime.now(UTC) - timedelta(days=j * 30),
                status=rng.choice(["draft", "reviewed", "published"]),
            )
            session.add(la)
            look_aheads.append(la)
            counts["look_aheads"] += 1
    await session.flush()

    # ── Constraints (~80 total, mixed statuses) ────────────────────────
    target_constraints = 80
    per_la = max(1, target_constraints // max(1, len(look_aheads)))
    for la in look_aheads:
        for _ in range(per_la):
            ctype = rng.choice(_CONSTRAINT_TYPES)
            cstatus = rng.choice(_CONSTRAINT_STATUSES)
            target = today + timedelta(days=rng.randint(-30, 60))
            cleared_at = datetime.now(UTC) - timedelta(days=rng.randint(1, 30)) if cstatus == "cleared" else None
            c = Constraint(
                look_ahead_id=la.id,
                task_ref=uuid.uuid4(),
                constraint_type=ctype,
                description=f"Demo {ctype} constraint",
                target_clear_date=target,
                cleared_at=cleared_at,
                status=cstatus,
            )
            session.add(c)
            counts["constraints"] += 1
    await session.flush()

    # ── Weekly plans (~12 weeks across masters, most closed) ──────────
    weekly_plans: list[WeeklyWorkPlan] = []
    weeks_per_master = max(1, 12 // max(1, len(masters)))
    for m in masters:
        for week_offset in range(weeks_per_master):
            wstart = _monday(today) - timedelta(weeks=week_offset)
            is_current = week_offset == 0
            wstatus = "in_progress" if is_current else "closed"
            ppc = None if is_current else Decimal(rng.randint(45, 92))
            w = WeeklyWorkPlan(
                master_schedule_id=m.id,
                week_start_date=wstart,
                week_end_date=wstart + timedelta(days=6),
                generated_at=datetime.now(UTC) - timedelta(weeks=week_offset),
                status=wstatus,
                ppc_percent=ppc,
                notes="Seed weekly plan",
            )
            session.add(w)
            weekly_plans.append(w)
            counts["weekly_plans"] += 1
    await session.flush()

    # ── Commitments (~200, mixed completed/missed) ────────────────────
    target_commitments = 200
    per_wp = max(1, target_commitments // max(1, len(weekly_plans)))
    missed_commitment_ids: list[uuid.UUID] = []
    for w in weekly_plans:
        for _ in range(per_wp):
            cstatus = rng.choice(_COMMITMENT_STATUSES)
            actual = None
            completed_at = None
            if cstatus == "completed":
                actual = Decimal(rng.randint(8, 12))
                completed_at = datetime.now(UTC) - timedelta(days=rng.randint(1, 14))
            c = Commitment(
                week_plan_id=w.id,
                task_ref=uuid.uuid4(),
                worker_or_crew=f"Crew-{rng.randint(1, 9)}",
                promised_qty=Decimal(rng.randint(5, 50)),
                unit=rng.choice(["m2", "m3", "lm", "pcs", "h"]),
                planned_start=w.week_start_date,
                planned_finish=w.week_end_date,
                status=cstatus,
                made_at=datetime.now(UTC) - timedelta(days=rng.randint(1, 21)),
                completed_at=completed_at,
                actual_qty=actual,
            )
            session.add(c)
            counts["commitments"] += 1
            if cstatus == "missed":
                # We need the id post-flush; we'll collect after flush.
                missed_commitment_ids.append(c.id if c.id else uuid.uuid4())
    await session.flush()
    # Re-collect missed ids now they are persisted
    missed_commitment_ids = []
    from sqlalchemy import select

    res = await session.execute(select(Commitment.id).where(Commitment.status == "missed"))
    missed_commitment_ids = [r[0] for r in res.all()]

    # ── RNCs (~50, attached to a subset of missed commitments) ────────
    target_rncs = 50
    sample_size = min(target_rncs, len(missed_commitment_ids))
    if sample_size > 0:
        sampled = rng.sample(missed_commitment_ids, sample_size)
        for cid in sampled:
            cat = rng.choice(_RNC_CATEGORIES)
            r = ReasonForNonCompletion(
                commitment_id=cid,
                category=cat,
                description=f"Demo {cat} RNC",
                recorded_at=datetime.now(UTC) - timedelta(days=rng.randint(1, 14)),
                root_cause_notes=f"Root-cause notes for {cat}",
            )
            session.add(r)
            counts["rncs"] += 1
    await session.flush()

    # ── Baselines (~6 — 2 per master) + deltas ────────────────────────
    delta_target = 60
    deltas_per_baseline = max(1, delta_target // max(1, len(masters) * 2))
    for m in masters:
        for j in range(2):
            snapshot: list[dict] = []
            for _ in range(deltas_per_baseline):
                tid = uuid.uuid4()
                bstart = today - timedelta(days=rng.randint(30, 180))
                bfinish = bstart + timedelta(days=rng.randint(5, 30))
                snapshot.append(
                    {
                        "task_ref": str(tid),
                        "planned_start": bstart.isoformat(),
                        "planned_finish": bfinish.isoformat(),
                    }
                )
            b = Baseline(
                master_schedule_id=m.id,
                name=f"Baseline rev-{j + 1}",
                captured_at=datetime.now(UTC) - timedelta(days=j * 60),
                snapshot=snapshot,
                status="active" if j == 0 else "superseded",
                notes="Seed baseline",
            )
            session.add(b)
            counts["baselines"] += 1
            await session.flush()
            # Generate baseline deltas
            for row in snapshot:
                variance = rng.randint(-10, 20)
                bf = date.fromisoformat(row["planned_finish"])
                bs = date.fromisoformat(row["planned_start"])
                cf = bf + timedelta(days=variance)
                cs = bs + timedelta(days=variance)
                d = BaselineDelta(
                    baseline_id=b.id,
                    current_master_id=m.id,
                    task_ref=uuid.UUID(row["task_ref"]),
                    planned_start_baseline=bs,
                    planned_start_current=cs,
                    planned_finish_baseline=bf,
                    planned_finish_current=cf,
                    schedule_variance_days=variance,
                    computed_at=datetime.now(UTC),
                )
                session.add(d)
                counts["baseline_deltas"] += 1
    await session.flush()

    return counts

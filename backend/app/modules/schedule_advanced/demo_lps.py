# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Last Planner demo data​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ for the demo projects.

Seeds, on top of the project's schedule activities: one master schedule, a
six-week look-ahead from the current Monday, a constraints log (some cleared,
some open, one overdue, one linked to an RFI and one to a purchase order when
the project has them), eight closed weeks of commitments with a PPC that
climbs from the high fifties to the low eighties with reasons for variance,
and the current week's plan with commitments on ready tasks.

Deterministic for a given project (seeded from the project id), idempotent:
rows tagged with the demo id are replaced on reinstall.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.schedule_advanced.models import (
    Commitment,
    Constraint,
    LookAheadPlan,
    MasterSchedule,
    ReasonForNonCompletion,
    WeeklyWorkPlan,
)

#: PPC target per closed week, oldest first: a team learning to plan reliably.
_PPC_CURVE = (58, 62, 55, 67, 71, 69, 76, 82)
_RNC_WEIGHTS = (
    ("material", 9),
    ("predecessor", 7),
    ("manpower", 6),
    ("info", 5),
    ("weather", 3),
    ("equipment", 2),
    ("changes", 2),
    ("quality", 1),
)
_RNC_TEXT = {
    "material": "Delivery arrived late on site",
    "predecessor": "Preceding trade had not finished the area",
    "manpower": "Crew short-staffed this week",
    "info": "Waiting for design clarification",
    "weather": "Rain stopped external work",
    "equipment": "Crane not available as booked",
    "changes": "Client change instructed mid-week",
    "quality": "Rework after failed inspection",
}
_CONSTRAINTS = (
    ("info", "Confirm slab penetration layout with MEP designer", "rfi"),
    ("material", "Rebar delivery for next pour", "purchase_order"),
    ("permit", "Road closure permit for crane lift", None),
    ("labor", "Second formwork crew mobilised", None),
    ("equipment", "Concrete pump booked for pour day", None),
    ("predecessor", "Waterproofing inspection signed off", None),
    ("info", "Approved shop drawings for facade brackets", None),
    ("material", "Window frames released from factory", None),
)


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _pick_rnc(rng: random.Random) -> str:
    bag = [cat for cat, w in _RNC_WEIGHTS for _ in range(w)]
    return rng.choice(bag)


async def seed_lps_demo(
    session: AsyncSession,
    project_id: uuid.UUID,
    owner_id: uuid.UUID | str,
    demo_id: str,
    *,
    today: date | None = None,
    crews: list[str] | None = None,
) -> dict[str, int]:
    """Seed the Last Planner demo for one project. Returns row counts."""
    from app.modules.schedule.models import Activity, Schedule  # noqa: PLC0415

    ref = today or datetime.now(UTC).date()
    rng = random.Random(str(project_id))
    owner = uuid.UUID(str(owner_id))
    tag = f"demo:{demo_id}"

    prior = (
        (
            await session.execute(
                select(MasterSchedule.id).where(
                    MasterSchedule.project_id == project_id, MasterSchedule.created_by == tag
                )
            )
        )
        .scalars()
        .all()
    )
    if prior:
        await session.execute(delete(MasterSchedule).where(MasterSchedule.id.in_(list(prior))))
        await session.flush()

    acts = list(
        (
            await session.execute(
                select(Activity)
                .join(Schedule, Schedule.id == Activity.schedule_id)
                .where(Schedule.project_id == project_id)
            )
        ).scalars()
    )
    parents = {a.parent_id for a in acts if a.parent_id}
    leaves = sorted((a for a in acts if a.id not in parents), key=lambda a: a.start_date)
    if not leaves:
        return {}

    sub_id = None
    try:
        from app.modules.subcontractors.models import Subcontractor  # noqa: PLC0415

        for s in (await session.execute(select(Subcontractor))).scalars():
            if (s.metadata_ or {}).get("demo_id") == demo_id:
                sub_id = s.id
                break
    except ImportError:  # pragma: no cover - module absent
        pass
    crew_names = crews or [
        "Concrete crew",
        "Formwork crew",
        "Rebar crew",
        "MEP rough-in",
        "Drywall crew",
        "Facade crew",
    ]

    this_monday = _monday(ref)
    master = MasterSchedule(
        project_id=project_id,
        name="Last Planner master schedule",
        planned_start=this_monday - timedelta(weeks=9),
        planned_finish=this_monday + timedelta(weeks=12),
        status="active",
        created_by=tag,
    )
    session.add(master)
    await session.flush()

    la = LookAheadPlan(
        master_schedule_id=master.id,
        period_start=this_monday,
        period_end=this_monday + timedelta(weeks=6, days=-1),
        window_weeks=6,
        generated_at=datetime.now(UTC),
        status="published",
    )
    session.add(la)
    await session.flush()

    # Activities the look-ahead covers; when the demo programme has finished or
    # not started yet, the nearest phases stand in so the board is never empty.
    window = [
        a for a in leaves if a.start_date <= la.period_end.isoformat() and a.end_date >= la.period_start.isoformat()
    ]
    if len(window) < 3:
        window = (window + [a for a in leaves if a not in window])[:6]

    rfi_id = po_id = None
    try:
        from app.modules.rfi.models import RFI  # noqa: PLC0415

        rfi_id = (await session.execute(select(RFI.id).where(RFI.project_id == project_id).limit(1))).scalar()
    except ImportError:  # pragma: no cover
        pass
    try:
        from app.modules.procurement.models import PurchaseOrder  # noqa: PLC0415

        po_id = (
            await session.execute(select(PurchaseOrder.id).where(PurchaseOrder.project_id == project_id).limit(1))
        ).scalar()
    except ImportError:  # pragma: no cover
        pass

    constraints: list[Constraint] = []
    for i, (ctype, desc, link) in enumerate(_CONSTRAINTS):
        act = window[i % len(window)]
        due = this_monday + timedelta(days=-4 + i * 4)
        cleared = i in (3, 4)
        c = Constraint(
            look_ahead_id=la.id,
            task_ref=act.id,
            constraint_type=ctype,
            description=desc,
            owner_user_id=owner if i != 6 else None,
            target_clear_date=due,
            status="cleared" if cleared else ("in_progress" if i in (1, 5) else "open"),
            cleared_at=datetime.combine(due, datetime.min.time(), tzinfo=UTC) if cleared else None,
            cleared_by=owner if cleared else None,
            linked_type=link if (link == "rfi" and rfi_id) or (link == "purchase_order" and po_id) else None,
            linked_id=(rfi_id if link == "rfi" else po_id if link == "purchase_order" else None),
        )
        constraints.append(c)
        session.add(c)
    await session.flush()
    blocked = {str(c.task_ref) for c in constraints if c.status != "cleared"}

    weeks = commits = rncs = 0
    for w, target in enumerate(_PPC_CURVE):
        start = this_monday - timedelta(weeks=len(_PPC_CURVE) - w)
        plan = WeeklyWorkPlan(
            master_schedule_id=master.id,
            week_start_date=start,
            week_end_date=start + timedelta(days=4),
            generated_at=datetime.combine(start, datetime.min.time(), tzinfo=UTC),
            facilitator_id=owner,
            status="closed",
            notes="",
        )
        session.add(plan)
        await session.flush()
        n = 10 + rng.randint(0, 2)
        done = round(n * target / 100)
        rows: list[Commitment] = []
        for k in range(n):
            act = leaves[(w + k) % len(leaves)]
            ok = k < done
            c = Commitment(
                week_plan_id=plan.id,
                task_ref=act.id,
                worker_or_crew=crew_names[k % len(crew_names)],
                promised_qty=Decimal(str(20 + 5 * (k % 4))),
                unit="m2",
                planned_start=start,
                planned_finish=start + timedelta(days=4),
                status="completed" if ok else "missed",
                made_by_user_id=owner,
                made_at=datetime.combine(start, datetime.min.time(), tzinfo=UTC),
                completed_at=datetime.combine(start + timedelta(days=4), datetime.min.time(), tzinfo=UTC)
                if ok
                else None,
                subcontractor_id=sub_id if k % 3 == 0 else None,
            )
            rows.append(c)
            session.add(c)
        await session.flush()
        for c in rows:
            if c.status == "missed":
                cat = _pick_rnc(rng)
                session.add(
                    ReasonForNonCompletion(
                        commitment_id=c.id,
                        category=cat,
                        description=_RNC_TEXT[cat],
                        recorded_at=datetime.combine(start + timedelta(days=4), datetime.min.time(), tzinfo=UTC),
                        recorded_by=owner,
                    )
                )
                rncs += 1
        plan.ppc_percent = (Decimal(done) * 100 / Decimal(n)).quantize(Decimal("0.01"))
        weeks += 1
        commits += n

    current = WeeklyWorkPlan(
        master_schedule_id=master.id,
        week_start_date=this_monday,
        week_end_date=this_monday + timedelta(days=4),
        generated_at=datetime.now(UTC),
        facilitator_id=owner,
        status="committed",
    )
    session.add(current)
    await session.flush()
    ready = [a for a in window if str(a.id) not in blocked] or window[:1]
    for k, act in enumerate(ready[:6]):
        try:
            prog = Decimal(str(act.progress_pct or "0"))
        except ArithmeticError:
            prog = Decimal("0")
        session.add(
            Commitment(
                week_plan_id=current.id,
                task_ref=act.id,
                worker_or_crew=crew_names[k % len(crew_names)],
                promised_qty=Decimal("25"),
                unit="m2",
                planned_start=this_monday,
                planned_finish=this_monday + timedelta(days=4),
                status="committed" if str(act.id) not in blocked else "planned",
                made_by_user_id=owner,
                made_at=datetime.now(UTC),
                subcontractor_id=sub_id if k % 2 == 0 else None,
                target_progress_pct=min(Decimal("100"), prog + Decimal("15")),
            )
        )
        commits += 1
    await session.flush()
    result: dict[str, Any] = {
        "lps_weeks": weeks + 1,
        "lps_commitments": commits,
        "lps_constraints": len(constraints),
        "lps_rncs": rncs,
    }
    return result

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Last Planner and subcontractor insurance across modules, on PostgreSQL​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.

Last Planner: the look-ahead board lists the project's schedule activities with
their constraints; a task with an open constraint linked to an RFI is not ready
and a commitment on it is refused; the RFI being answered stamps the constraint
and notifies its owner; once cleared the commitment is accepted, completing it
moves the schedule activity's progress, closing the week records a PPC, and the
dashboard widget and the validation rules read the same history. The demo seed
builds a board, a constraints log and eight closed weeks.

Insurance: a lapsed mandatory certificate blocks finance approval and payment
through the ``subcontractor_insurance`` rule set; a manager override with a
reason is written to the override log and the audit log and lets the payment
through; the project dashboard and the alert run (notifications) see the same
certificates.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

pytestmark = pytest.mark.asyncio


@pytest.fixture
def captured_events(monkeypatch):
    """Record detached events instead of scheduling subscribers on a factory this lane never binds."""
    from app.core.events import event_bus

    seen: list[tuple[str, dict]] = []
    monkeypatch.setattr(event_bus, "publish_detached", lambda name, data=None, **_kw: seen.append((name, data or {})))
    return seen


async def _project(session):
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    tag = uuid.uuid4().hex[:8]
    owner = User(email=f"lps-{tag}@site.example", hashed_password="x", full_name="Site manager", role="manager")
    session.add(owner)
    await session.flush()
    project = Project(name=f"Tower {tag}", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    return owner, project


async def _schedule(session, project_id, today: date):
    from app.modules.schedule.models import Activity, Schedule

    sched = Schedule(project_id=project_id, name="Main programme")
    session.add(sched)
    await session.flush()
    acts = []
    for i, name in enumerate(("Level 3 slab", "Level 3 columns", "Level 4 formwork")):
        a = Activity(
            schedule_id=sched.id,
            name=name,
            wbs_code=f"1.{i + 1}",
            start_date=(today + timedelta(days=i * 7)).isoformat(),
            end_date=(today + timedelta(days=i * 7 + 5)).isoformat(),
            progress_pct="10",
            status="in_progress",
        )
        session.add(a)
        acts.append(a)
    await session.flush()
    return acts


async def test_last_planner_board_gate_progress_and_ppc(pg_session, captured_events) -> None:
    from app.modules.dashboard.service import compute_project_lps_ppc
    from app.modules.notifications.models import Notification
    from app.modules.rfi.models import RFI
    from app.modules.schedule.models import Activity
    from app.modules.schedule_advanced.events import mark_linked_constraints_resolved
    from app.modules.schedule_advanced.lps import LastPlannerService
    from app.modules.schedule_advanced.models import (
        Commitment,
        Constraint,
        LookAheadPlan,
        MasterSchedule,
        WeeklyWorkPlan,
    )
    from app.modules.schedule_advanced.service import ScheduleAdvancedService

    session = pg_session
    today = datetime.now(UTC).date()
    week = today - timedelta(days=today.weekday())
    owner, project = await _project(session)
    acts = await _schedule(session, project.id, week)

    master = MasterSchedule(project_id=project.id, name="LPS")
    session.add(master)
    await session.flush()
    la = LookAheadPlan(master_schedule_id=master.id, period_start=week, period_end=week + timedelta(weeks=6, days=-1))
    session.add(la)
    rfi = RFI(
        project_id=project.id, rfi_number="RFI-001", subject="Slab openings", question="Where?", raised_by=owner.id
    )
    session.add(rfi)
    await session.flush()
    constraint = Constraint(
        look_ahead_id=la.id,
        task_ref=acts[0].id,
        constraint_type="info",
        description="Confirm slab openings",
        owner_user_id=owner.id,
        target_clear_date=week + timedelta(days=2),
        linked_type="rfi",
        linked_id=rfi.id,
    )
    session.add(constraint)
    plan = WeeklyWorkPlan(
        master_schedule_id=master.id, week_start_date=week, week_end_date=week + timedelta(days=4), status="committed"
    )
    session.add(plan)
    await session.flush()

    lps = LastPlannerService(session)
    board = await lps.board(la.id)
    by_name = {t["name"]: t for t in board["tasks"]}
    assert set(by_name) == {"Level 3 slab", "Level 3 columns", "Level 4 formwork"}
    assert by_name["Level 3 slab"]["is_ready"] is False
    assert by_name["Level 3 slab"]["constraints"][0]["linked_label"] == "RFI-001"
    assert by_name["Level 3 columns"]["is_ready"] is True

    svc = ScheduleAdvancedService(session)
    commitment = Commitment(
        week_plan_id=plan.id, task_ref=acts[0].id, worker_or_crew="Concrete crew", target_progress_pct=Decimal("60")
    )
    session.add(commitment)
    await session.flush()
    with pytest.raises(HTTPException) as refused:
        await svc.commit_to_week(commitment.id)
    assert refused.value.status_code == 409
    assert refused.value.detail["code"] == "constraints_open"

    # The RFI is answered elsewhere: the constraint is stamped and its owner told.
    resolved = await mark_linked_constraints_resolved(session, "rfi", rfi.id)
    assert [c.id for c in resolved] == [constraint.id]
    notes = (await session.execute(select(Notification).where(Notification.user_id == owner.id))).scalars().all()
    assert any(n.title_key == "notifications.lps.constraint_resolvable_title" for n in notes)

    await svc.clear_constraint(constraint.id, user_id=str(owner.id))
    assert any(
        name == "schedule_advanced.constraint.cleared" and d["project_id"] == str(project.id)
        for name, d in captured_events
    )
    await svc.commit_to_week(commitment.id)
    await svc.mark_commitment_complete(commitment.id)
    await session.refresh(acts[0])
    assert float(acts[0].progress_pct) == pytest.approx(60.0)
    done = [d for name, d in captured_events if name == "schedule_advanced.commitment.completed"]
    assert done and done[0]["schedule_progress_updated"] is True

    other = Commitment(week_plan_id=plan.id, task_ref=acts[1].id, worker_or_crew="Formwork crew", status="committed")
    session.add(other)
    await session.flush()
    await svc.mark_commitment_missed(other.id, {"category": "material", "description": "Late delivery"})
    await svc.close_weekly_plan(plan.id)

    history = await lps.ppc_history(master.id)
    assert history["weeks"][-1]["ppc_percent"] == Decimal("50.00")
    assert history["pareto"][0]["category"] == "material"
    widget = await compute_project_lps_ppc(session, [project])
    assert widget["items"][0]["weeks"][-1]["ppc_percent"] == "50.00"

    verdict = await lps.validate(master.id)
    assert verdict["errors"] == 0
    assert any(r["rule_id"] == "last_planner.constraint_owner" for r in verdict["results"])
    activity = await session.get(Activity, acts[0].id)
    assert activity is not None


async def _sub_with_payment(session, project, owner, *, status: str = "foreman_approved"):
    from app.modules.subcontractors.models import Certificate, PaymentApplication, SubcontractAgreement, Subcontractor

    sub = Subcontractor(legal_name="Steelworks Ltd", trade_name="Steelworks", created_by=str(owner.id))
    session.add(sub)
    await session.flush()
    agr = SubcontractAgreement(
        subcontractor_id=sub.id,
        project_id=project.id,
        title="Steel frame",
        total_value=Decimal("100000"),
        currency="EUR",
        retention_percent=Decimal("5"),
        status="active",
    )
    session.add(agr)
    await session.flush()
    pay = PaymentApplication(
        agreement_id=agr.id,
        application_number="PA-001",
        gross_amount=Decimal("1000"),
        retention_amount=Decimal("50"),
        net_amount=Decimal("950"),
        currency="EUR",
        status=status,
    )
    session.add(pay)
    today = date.today()
    for cert_type, days in (
        ("employers_liability", -10),
        ("public_liability", 12),
        ("insurance", 300),
        ("license", 300),
    ):
        session.add(
            Certificate(
                subcontractor_id=sub.id,
                cert_type=cert_type,
                valid_until=today + timedelta(days=days),
                is_mandatory=cert_type in ("employers_liability", "public_liability"),
                policy_number="P-1",
                coverage_amount=Decimal("1000000"),
                status="valid",
            )
        )
    await session.flush()
    return sub, pay


async def test_insurance_blocks_payment_until_manager_override(pg_session, captured_events) -> None:
    from app.core.audit import AuditEntry
    from app.modules.dashboard.service import compute_project_sub_insurance
    from app.modules.notifications.models import Notification
    from app.modules.subcontractors.insurance import InsuranceComplianceService
    from app.modules.subcontractors.models import PaymentComplianceOverride
    from app.modules.subcontractors.service import SubcontractorService

    session = pg_session
    owner, project = await _project(session)
    sub, pay = await _sub_with_payment(session, project, owner)

    svc = SubcontractorService(session)
    with pytest.raises(HTTPException) as blocked:
        await svc.approve_payment_application_finance(pay.id, user_id=str(owner.id))
    assert blocked.value.status_code == 409
    assert blocked.value.detail["code"] == "insurance_compliance_blocked"
    assert blocked.value.detail["reasons"][0].startswith("expired_mandatory_certificate:employers_liability:")

    ins = InsuranceComplianceService(session)
    card = await ins.subcontractor_status(sub.id)
    assert card["status"] == "non_compliant"
    dash = await ins.project_dashboard(project.id)
    assert dash["counts"]["non_compliant"] == 1
    assert dash["certificate_buckets"]["expired"] == 1 and dash["certificate_buckets"]["due_14"] == 1
    assert dash["gated_payments"][0]["blocked"] is True
    widget = await compute_project_sub_insurance(session, [project])
    assert widget["blocked_payments"] == 1

    row = await ins.override(
        pay.id, reason="Renewal confirmed by broker, certificate in the post", user_id=str(owner.id)
    )
    assert row.covered_reasons == blocked.value.detail["reasons"]
    logged = (await session.execute(select(PaymentComplianceOverride))).scalars().all()
    assert [r.id for r in logged] == [row.id]
    audit = (await session.execute(select(AuditEntry).where(AuditEntry.entity_id == str(pay.id)))).scalars().all()
    assert any(a.action == "override" for a in audit)
    assert any(name == "subcontractors.payment.insurance_overridden" for name, _ in captured_events)

    status_after = await ins.payment_status(pay.id)
    assert status_after["blocked"] is False and status_after["overridden"] is True

    sent = await ins.run_expiry_alerts()
    assert sent >= 2
    notes = (await session.execute(select(Notification).where(Notification.user_id == owner.id))).scalars().all()
    keys = {n.title_key for n in notes}
    assert "notifications.subcontractor_insurance.expired_title" in keys
    assert "notifications.subcontractor_insurance.due_14_title" in keys
    assert await ins.run_expiry_alerts() == 0


async def test_demo_seed_builds_board_and_insurance_file(pg_session, captured_events) -> None:
    from app.modules.schedule_advanced.demo_lps import seed_lps_demo
    from app.modules.schedule_advanced.lps import LastPlannerService
    from app.modules.schedule_advanced.models import LookAheadPlan, MasterSchedule
    from app.modules.subcontractors.demo_insurance import seed_insurance_demo
    from app.modules.subcontractors.insurance import InsuranceComplianceService
    from app.modules.subcontractors.models import Subcontractor

    session = pg_session
    today = datetime.now(UTC).date()
    owner, project = await _project(session)
    await _schedule(session, project.id, today - timedelta(days=today.weekday()))
    sub, pay = await _sub_with_payment(session, project, owner, status="finance_approved")
    sub.metadata_ = {"demo_id": "demo-x"}
    await session.flush()

    counts = await seed_lps_demo(session, project.id, owner.id, "demo-x")
    assert counts["lps_weeks"] == 9 and counts["lps_constraints"] == 8
    master = (
        (await session.execute(select(MasterSchedule).where(MasterSchedule.project_id == project.id))).scalars().one()
    )
    history = await LastPlannerService(session).ppc_history(master.id)
    closed = [w for w in history["weeks"] if w["status"] == "closed"]
    assert len(closed) >= 6 and closed[-1]["ppc_percent"] > closed[0]["ppc_percent"]
    assert history["pareto"]
    la = (
        (await session.execute(select(LookAheadPlan).where(LookAheadPlan.master_schedule_id == master.id)))
        .scalars()
        .one()
    )
    board = await LastPlannerService(session).board(la.id)
    assert board["tasks"] and board["blocked_count"] >= 1

    assert (await seed_insurance_demo(session, "demo-x", "EUR"))["insurance_certificates"] == 4
    st = await InsuranceComplianceService(session).payment_status(pay.id)
    assert st["blocked"] is True
    assert (await session.get(Subcontractor, sub.id)) is not None

# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Delay analysis service: windows are persisted with dates, issue freezes, one EOT claim holds it.

PostgreSQL because windows and events cascade from the analysis row.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.modules.projects.models import Project
from app.modules.schedule.models import Activity, Schedule, ScheduleRelationship
from app.modules.schedule_advanced.delay_report import run_analysis
from app.modules.schedule_advanced.delay_service import DelayAnalysisService
from app.modules.schedule_advanced.models import Baseline, MasterSchedule
from app.modules.schedule_advanced.router import _build_str_network, _load_schedule_rows, _windows_plan
from app.modules.schedule_advanced.schemas import DelayAnalysisCreate, DelayEventCreate
from app.modules.users.models import User
from app.modules.variations.models import ExtensionOfTimeClaim

pytestmark = pytest.mark.asyncio


async def _project(session) -> uuid.UUID:
    owner_id = uuid.uuid4()
    session.add(
        User(
            id=owner_id,
            email=f"{uuid.uuid4().hex[:8]}@example.test",
            hashed_password="x",
            full_name="Owner",
            role="manager",
            locale="en",
            is_active=True,
            metadata_={},
        )
    )
    await session.flush()
    project_id = uuid.uuid4()
    session.add(
        Project(
            id=project_id,
            name="Delay",
            description="",
            currency="EUR",
            status="active",
            owner_id=owner_id,
            metadata_={},
        )
    )
    await session.flush()
    return project_id


async def _schedule(session, project_id) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    sched = Schedule(project_id=project_id, name="Main", start_date="2026-01-05", end_date="2026-03-27")
    session.add(sched)
    await session.flush()
    a = Activity(schedule_id=sched.id, name="Pour", start_date="2026-01-05", end_date="2026-01-30", duration_days=20)
    b = Activity(schedule_id=sched.id, name="Fit-out", start_date="2026-02-02", end_date="2026-03-27", duration_days=40)
    session.add_all([a, b])
    await session.flush()
    session.add(
        ScheduleRelationship(schedule_id=sched.id, predecessor_id=a.id, successor_id=b.id, relationship_type="FS")
    )
    await session.flush()
    return sched.id, a.id, b.id


async def test_windows_keep_their_dates_and_the_concurrency_note(pg_session) -> None:
    project_id = await _project(pg_session)
    sched_id, a_id, _ = await _schedule(pg_session, project_id)
    svc = DelayAnalysisService(pg_session)
    analysis = await svc.create_analysis(
        project_id, DelayAnalysisCreate(name="EOT 1", method="windows", schedule_id=sched_id), None
    )
    await svc.add_event(analysis.id, DelayEventCreate(title="Late drawings", insert_at_activity_ref=str(a_id)))
    result = run_analysis(
        "windows",
        events=await svc.build_event_specs(analysis.id),
        snapshots=_two_networks(str(a_id)),
        window_bounds=[(0, 60)],
    )
    result["windows"][0]["window_start"] = "2026-01-05"
    result["windows"][0]["window_end"] = "2026-03-01"
    await svc.persist_compute(analysis, result)
    wins = await svc.list_windows(analysis.id)
    assert [(w.window_start, w.window_end, w.gross_slip_days) for w in wins] == [("2026-01-05", "2026-03-01", 5)]
    assert analysis.status == "computed"
    assert analysis.result_json["concurrency"]["present"] is False


def _two_networks(a_id: str):
    from app.modules.schedule_advanced.cpm import Activity as CpmActivity

    plan = [CpmActivity(id=a_id, duration=20)]
    late = [CpmActivity(id=a_id, duration=25)]
    return [plan, late]


async def test_snapshot_windows_read_the_durations_each_baseline_recorded(pg_session) -> None:
    project_id = await _project(pg_session)
    sched_id, a_id, b_id = await _schedule(pg_session, project_id)
    master = MasterSchedule(project_id=project_id, name="Master")
    pg_session.add(master)
    await pg_session.flush()
    now = datetime.now(UTC)
    for name, days_ago, dur in (("BL-1", 90, 20), ("BL-2", 40, 28)):
        pg_session.add(
            Baseline(
                master_schedule_id=master.id,
                name=name,
                captured_at=now - timedelta(days=days_ago),
                snapshot=[{"task_ref": str(a_id), "duration_days": dur}, {"task_ref": str(b_id), "duration_days": 40}],
            )
        )
    await pg_session.flush()
    svc = DelayAnalysisService(pg_session)
    analysis = await svc.create_analysis(
        project_id, DelayAnalysisCreate(name="W", method="windows", schedule_id=sched_id), None
    )
    act_rows, rel_rows = await _load_schedule_rows(sched_id, pg_session)
    current = _build_str_network(act_rows, rel_rows).activities
    plan, nets, bounds = await _windows_plan(analysis, "snapshot", act_rows, current, pg_session)
    assert plan and len(nets) == len(plan) + 1 and len(bounds) == len(plan)
    assert plan[0].snapshot_open == "BL-1"
    # First boundary sits on BL-1 (20 days), a later one on BL-2 (28 days), the last is the current plan.
    first = {a.id: a.duration for a in nets[0]}
    assert first[str(a_id)] == 20
    assert any({a.id: a.duration for a in n}[str(a_id)] == 28 for n in nets[1:-1])
    assert {a.id: a.duration for a in nets[-1]}[str(a_id)] == 20


async def test_issue_freezes_and_a_live_eot_claim_holds_the_analysis(pg_session) -> None:
    project_id = await _project(pg_session)
    svc = DelayAnalysisService(pg_session)
    analysis = await svc.create_analysis(project_id, DelayAnalysisCreate(name="Issue", method="tia"), None)
    await svc.refuse_if_eot_claim_raised(analysis, doing="be deleted")  # no claim yet: fine

    await svc.issue(
        analysis,
        user_id=None,
        signature_sha256="a" * 64,
        signature_snapshot={"total_entitlement_days": 0},
        issued_at="2026-11-04T10:00:00+00:00",
    )
    assert analysis.status == "issued" and analysis.signature_sha256 == "a" * 64

    claim = ExtensionOfTimeClaim(project_id=project_id)
    pg_session.add(claim)
    await pg_session.flush()
    await svc.set_eot_claim(analysis, claim.id)
    with pytest.raises(HTTPException) as exc:
        await svc.refuse_if_eot_claim_raised(analysis, doing="be deleted")
    assert exc.value.status_code == 409

    await pg_session.delete(claim)
    await pg_session.flush()
    await svc.refuse_if_eot_claim_raised(analysis, doing="be deleted")  # claim gone: released


async def test_validation_ties_each_fragnet_loop_to_its_own_event(pg_session) -> None:
    from app.modules.schedule_advanced.router import validate_delay_analysis

    project_id = await _project(pg_session)
    sched_id, a_id, b_id = await _schedule(pg_session, project_id)
    owner_id = (await pg_session.get(Project, project_id)).owner_id
    svc = DelayAnalysisService(pg_session)
    analysis = await svc.create_analysis(
        project_id, DelayAnalysisCreate(name="EOT 2", method="windows", schedule_id=sched_id), None
    )
    looping = await svc.add_event(analysis.id, DelayEventCreate(title="Loop", code="D-LOOP"))
    clean = await svc.add_event(analysis.id, DelayEventCreate(title="Clean", code="D-CLEAN"))
    await svc.add_fragnet(
        clean.id,
        insert_mode="insert_parallel",
        insert_at_activity_ref=str(b_id),
        added_duration_days=0,
        fragnet_activities=[{"id": "M", "duration": 2, "predecessors": [(str(b_id), "FS", 0)]}],
        rewires=[],
    )
    await svc.add_fragnet(
        looping.id,
        insert_mode="insert_parallel",
        insert_at_activity_ref=str(b_id),
        added_duration_days=0,
        fragnet_activities=[{"id": "N", "duration": 2, "predecessors": [(str(b_id), "FS", 0)]}],
        rewires=[{"successor_id": str(a_id), "pred_id": "N", "op": "add"}],
    )
    out = await validate_delay_analysis(analysis.id, pg_session, owner_id, None)
    cycle = {r["element_ref"]: r["passed"] for r in out["results"] if r["rule_id"].endswith("fragnet_cycle")}
    assert cycle == {str(looping.id): False, str(clean.id): True}

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Permits spec rules on real PostgreSQL: binding roadmap, frame documents, corrections, validity, sweep, seed."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.permits import guards, jobs
from app.modules.permits.errors import PermitError
from app.modules.permits.models import (
    ConditionDischarge,
    ConditionEvidence,
    Permit,
    PermitApplication,
    PermitCondition,
    PermitDecision,
    PermitRequirement,
    PermitRoadmap,
)
from app.modules.permits.service import PermitService
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import add_container, add_revision, add_user
from tests.pg.permits_fixtures import (
    World,
    add_project,
    application,
    build_world,
    cond,
    decide,
    file,
    move,
    requirement,
)

TODAY = date(2026, 10, 11)

pytestmark = pytest.mark.asyncio

BUILDING = "baugenehmigung"
NOW = datetime.now(UTC).date()


@pytest_asyncio.fixture
async def world():
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory)


@pytest.fixture
def blob_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the file store at a temp root through the product's own setting, never the checkout."""
    from app.core.storage import reset_storage_backend_cache, resolve_data_dir

    checkout_root = resolve_data_dir() / "permits"
    monkeypatch.setenv("OE_DATA_DIR", str(tmp_path))
    reset_storage_backend_cache()
    yield tmp_path, checkout_root
    reset_storage_backend_cache()


async def _code(coro) -> tuple[int, str]:
    with pytest.raises(PermitError) as exc:
        await coro
    return exc.value.status_code, exc.value.code


async def _frame_model(w: World, catalogue_id: str = "elf_module_framework") -> uuid.UUID:
    """Pin a shipped governance model; return the id of the frame document it hosts permits in."""
    from app.modules.project_governance import public
    from app.modules.project_governance.service import GovernanceService

    async with w.factory() as s:
        await GovernanceService(s).set_model(
            w.project_id,
            source="shipped",
            catalogue_id=catalogue_id,
            version=None,
            four_eyes=True,
            actor_id=w.manager,
            tenant_id=str(w.manager),
        )
        await s.commit()
        host = await public.host_for(s, w.project_id, "permits")
        return next(d.id for d in await public.project_documents(s, w.project_id) if d.code == host.doc_type)


# ── finding 17: one approved change request licenses one structural change ──


async def test_an_approved_change_request_is_spent_by_the_change_it_licenses(world: World) -> None:
    from app.modules.project_governance.models import GovernanceChangeRequest, GovernanceDocument

    doc_id = await _frame_model(world)
    async with world.factory() as s:
        doc = await s.get(GovernanceDocument, doc_id)
        doc.status = "binding"
        cr = GovernanceChangeRequest(
            project_id=world.project_id,
            document_id=doc_id,
            proposed_revision_id=uuid.uuid4(),
            reason="Add the road occupation",
            status="approved",
            requested_by=world.manager,
        )
        s.add(cr)
        await s.commit()
        cr_id = cr.id
    body = {"permit_type_code": BUILDING, "responsible_user_id": world.manager}
    async with world.factory() as s:
        svc = PermitService(s)
        assert await _code(svc.create_requirement(world.project_id, dict(body), actor_id=world.manager)) == (
            409,
            "roadmap_binding_change_request_required",
        )
    async with world.factory() as s:
        row = await PermitService(s).create_requirement(
            world.project_id, {**body, "change_request_id": cr_id}, actor_id=world.manager
        )
        await s.commit()
    async with world.factory() as s:
        svc = PermitService(s)
        assert await _code(
            svc.create_requirement(world.project_id, {**body, "change_request_id": cr_id}, actor_id=world.manager)
        ) == (409, "change_request_already_used")
        assert await _code(
            svc.delete_requirement(world.project_id, row.id, actor_id=world.manager, change_request_id=cr_id)
        ) == (409, "change_request_already_used")
        roadmap = await svc.repo.get_roadmap(world.project_id)
        assert roadmap.consumed_change_request_ids == [str(cr_id)]


# ── finding 10, rule 18: the register export becomes a CDE revision of the frame document ──


async def test_the_register_export_is_stored_as_a_revision_of_its_frame_document(
    world: World, blob_root: tuple[Path, Path]
) -> None:
    from app.modules.cde.models import DocumentRevision
    from app.modules.project_governance.models import GovernanceDocument

    await requirement(world, BUILDING)
    doc_id = await _frame_model(world, "neutral")
    p = world.project_id
    async with world.factory() as s:
        svc = PermitService(s)
        assert await _code(svc.publish_frame_document(p, "everything", actor_id=world.manager)) == (
            422,
            "register_invalid",
        )
        assert await _code(svc.publish_frame_document(p, "roadmap", actor_id=world.manager)) == (
            409,
            "frame_document_without_container",
        )
    async with world.factory() as s:
        container = await add_container(s, p, "permit_roadmap")
        doc = await s.get(GovernanceDocument, doc_id)
        doc.container_id = container
        await s.commit()
    async with world.factory() as s:
        out = await PermitService(s).publish_frame_document(p, "roadmap", actor_id=world.manager)
        await s.commit()
    async with world.factory() as s:
        revision = await s.get(DocumentRevision, uuid.UUID(out["revision_id"]))
    assert revision.container_id == container and revision.content_hash == out["content_hash"]
    assert out["register"] == "roadmap" and len(out["content_hash"]) == 64
    tmp_root, checkout_root = blob_root
    stored = list((tmp_root / "permits" / str(p) / "frame").glob(f"*/{out['content_hash']}.pdf"))
    assert len(stored) == 1 and stored[0].read_bytes().startswith(b"%PDF")
    # Nothing is written outside the temp root: the checkout's data dir gets no folder for this project.
    assert not (checkout_root / str(p)).exists()


# ── finding 10: decision correction, interruption, jurisdiction ───────────


async def test_a_correction_is_a_new_revision_and_the_permit_follows_it(world: World) -> None:
    rid = await requirement(world, BUILDING)
    out = await decide(world, await file(world, rid), "granted", reference="AZ-OLD")
    p = world.project_id
    async with world.factory() as s:
        svc = PermitService(s)
        assert await _code(
            svc.correct_decision(p, out["decision"].id, {"reference": "AZ-1"}, actor_id=world.manager)
        ) == (
            422,
            "correction_needs_reason",
        )
        new = await svc.correct_decision(
            p, out["decision"].id, {"reference": "AZ-NEW", "reason": "Typing error"}, actor_id=world.manager
        )
        await s.commit()
    assert new.revision == 2 and new.supersedes_id == out["decision"].id and new.outcome == "granted"
    async with world.factory() as s:
        svc = PermitService(s)
        permit = await svc.repo.get_permit(p, out["permit"].id)
        assert permit.decision_id == new.id
        assert await _code(
            svc.correct_decision(p, out["decision"].id, {"reference": "x", "reason": "again"}, actor_id=world.manager)
        ) == (409, "decision_superseded")
        assert await svc.requirement_state(p, rid) == "granted"


async def test_interrupted_work_puts_the_permit_back_on_a_lapse_clock(world: World) -> None:
    rid = await requirement(world, BUILDING)
    out = await decide(world, await file(world, rid), "granted", served_date=TODAY - timedelta(days=9))
    p, pid = world.project_id, out["permit"].id
    async with world.factory() as s:
        svc = PermitService(s)
        assert await _code(svc.notify_interruption(p, pid, NOW, resumed=False, actor_id=world.manager)) == (
            409,
            "work_not_started",
        )
        await svc.notify_start(p, pid, NOW - timedelta(days=5), actor_id=world.manager)
        assert await _code(svc.notify_start(p, pid, NOW, actor_id=world.manager)) == (409, "start_already_notified")
        assert await _code(svc.notify_start(p, pid, NOW + timedelta(days=3), actor_id=world.manager)) == (
            422,
            "date_in_future",
        )
        permit = await svc.notify_interruption(p, pid, NOW - timedelta(days=2), resumed=False, actor_id=world.manager)
        validity = await svc._validity(permit)
        assert permit.paused_since == NOW - timedelta(days=2)
        assert (permit.valid_until is not None) == (getattr(validity, "lapse_if_paused", None) is not None)
        assert await _code(svc.notify_interruption(p, pid, NOW, resumed=False, actor_id=world.manager)) == (
            409,
            "work_already_interrupted",
        )
        permit = await svc.notify_interruption(p, pid, NOW, resumed=True, actor_id=world.manager)
        assert permit.paused_since is None and permit.valid_until is None


async def test_the_default_catalogue_follows_the_projects_subdivision(world: World) -> None:
    from app.modules.projects.models import Project

    async with world.factory() as s:
        pid = await add_project(s, world.manager, [])
        (await s.get(Project, pid)).subdivision_code = "DE-BY"
        await s.commit()
    async with world.factory() as s:
        roadmap = await PermitService(s).set_roadmap(pid, tenant_id=None, actor_id=world.manager)
        await s.commit()
    assert roadmap.catalogue_id == "de_by" and roadmap.jurisdiction == "DE-BY"


# ── finding 14: a granted requirement shows the decision date and no conflict ──


async def test_a_granted_requirement_raises_no_schedule_conflict(world: World) -> None:
    # The catalogue gives a building permit no statutory period: the forecast is the expected day.
    rid = await requirement(
        world, BUILDING, needed_by_date=TODAY + timedelta(days=5), expected_decision_date=TODAY + timedelta(days=30)
    )
    aid = await file(world, rid, TODAY - timedelta(days=20))
    async with world.factory() as s:
        before = {r["requirement_id"]: r for r in (await PermitService(s).timeline(world.project_id, TODAY))["items"]}
    assert before[str(rid)]["schedule_conflict"] is True
    await decide(world, aid, "granted", decision_date=TODAY - timedelta(days=2))
    async with world.factory() as s:
        after = {r["requirement_id"]: r for r in (await PermitService(s).timeline(world.project_id, TODAY))["items"]}
    row = after[str(rid)]
    assert row["schedule_conflict"] is False and row["forecast_decision"] == (TODAY - timedelta(days=2)).isoformat()


# ── findings 18 and 21: the deemed discharge runs on the discharge type's own clock ──


async def test_a_deemed_discharge_is_proposed_and_recorded_with_its_notice() -> None:
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as s:
            manager = await add_user(s, "manager")
            pid = await add_project(s, manager, [], country="GB")
            await PermitService(s).set_roadmap(pid, tenant_id=None, actor_id=manager, jurisdiction="GB-ENG")
            container = await add_container(s, pid, "notice")
            notice = await add_revision(s, container, 2, "b" * 64)
            await s.commit()
        w = World(factory, pid, manager, manager, manager, manager, manager, uuid.uuid4())
        main = await requirement(w, "full_planning_permission")
        out = await decide(
            w,
            await file(w, main),
            "granted_with_conditions",
            conditions=[cond("1", "suspensive", requires_authority_approval=True)],
        )
        async with factory() as s:
            (c,) = await PermitService(s).repo.conditions_of_permit(pid, out["permit"].id)
        discharge_req = await requirement(w, "discharge_of_conditions")
        body = {
            "kind": "discharge_of_conditions",
            "parent_permit_id": out["permit"].id,
            "discharges_condition_ids": [c.id],
        }
        # Filed under a requirement of the discharge type, the application runs on that type's own clock.
        aid = await application(w, discharge_req, **body)
        await move(w, aid, "preparing")
        await move(w, aid, "submitted", TODAY - timedelta(days=120))
        async with factory() as s:
            status = await PermitService(s).deemed_status(pid, aid, TODAY)
        assert status["proposal"] == "deemed_discharged" and status["requires_notice"] is True
        with pytest.raises(PermitError) as exc:
            await decide(w, aid, "deemed_granted")
        assert exc.value.code == "deemed_needs_notice"
        res = await decide(w, aid, "deemed_granted", document_revision_id=notice)
        assert res["decision"].deemed is True and res["permit"] is None
        async with factory() as s:
            svc = PermitService(s)
            assert (await svc.repo.get_condition(pid, c.id)).status == "discharged"
            (row,) = await svc.repo.list_discharges(pid, c.id)
            assert row.mode == "deemed_discharged"


# ── finding 10, rule 17 and finding 22: the scheduled sweep ───────────────


async def test_the_sweep_handles_each_row_in_its_own_transaction(world: World, monkeypatch, caplog) -> None:
    rid = await requirement(world, BUILDING)
    out = await decide(
        world,
        await file(world, rid),
        "granted_with_conditions",
        served_date=TODAY - timedelta(days=9),
        conditions=[
            cond("1", owner_user_id=world.owner_user, due_date=NOW - timedelta(days=60)),
            cond("2", owner_user_id=world.owner_user, due_date=NOW - timedelta(days=60)),
        ],
    )
    p = world.project_id
    async with world.factory() as s:
        permit = await s.get(Permit, out["permit"].id)
        permit.valid_until = NOW - timedelta(days=1)
        ids = {c.number: c.id for c in await PermitService(s).repo.conditions_of_permit(p, permit.id)}
        await s.commit()
    real = PermitService.sweep_condition

    async def flaky(self, project_id, cid, today):
        if cid == ids["1"]:
            raise RuntimeError("boom")
        return await real(self, project_id, cid, today)

    monkeypatch.setattr(PermitService, "sweep_condition", flaky)
    with caplog.at_level(logging.WARNING, logger="app.modules.permits.jobs"):
        counts = await jobs.run_sweep_once(world.factory, NOW)
    assert counts["failed"] == 1 and counts["lapsed"] == 1 and counts["projects"] == 1
    assert any("permits sweep failed" in r.message for r in caplog.records)
    async with world.factory() as s:
        assert (await s.get(Permit, out["permit"].id)).status == "lapsed"
        one, two = await s.get(PermitCondition, ids["1"]), await s.get(PermitCondition, ids["2"])
        assert one.overdue_notified_at is None and two.overdue_notified_at is not None
        # The project has no governance model, so nobody could be told: it stays due for escalation.
        assert two.escalated_at is None
    assert counts["notified"] + counts["unescalated"] >= 1


# ── finding 22: the demo seed fills every list and reads forwards in time ──


async def test_the_demo_seed_fills_every_list_in_a_plausible_order(world: World) -> None:
    from app.modules.permits.seed import seed_permits_demo
    from app.modules.projects.models import Project

    async with world.factory() as s:
        pid = await add_project(s, world.manager, [])
        (await s.get(Project, pid)).metadata_ = {"demo_id": "permits-review"}
        await s.commit()
    async with world.factory() as s:
        totals = await seed_permits_demo(s, [pid])
        await s.commit()
    assert totals["projects"] == 1
    async with world.factory() as s:
        repo = PermitService(s).repo
        apps = await repo.list_applications(pid)
        decisions = {d.application_id: d for d in await repo.list_decisions(pid)}
        reqs = {r.id: r for r in await repo.list_requirements(pid)}
        permits = await repo.list_permits(pid)
        for name, rows in (
            ("requirements", reqs),
            ("dependencies", await repo.list_dependencies(pid)),
            ("applications", apps),
            ("clock events", await repo.list_clock_events(pid)),
            ("decisions", decisions),
            ("permits", permits),
            ("conditions", await repo.list_conditions(pid)),
            ("evidence", await repo.list_evidence(pid)),
            ("discharges", await repo.list_discharges(pid)),
        ):
            assert len(rows) > 0, name
    for a in apps:
        d = decisions.get(a.id)
        if d is not None and a.submitted_at is not None:
            assert a.submitted_at <= d.decision_date, a.authority_reference
    by_scope = {p.scope: decisions_of for p in permits for decisions_of in [p]}
    if "early_start" in by_scope and "full" in by_scope:
        early = next(d for d in decisions.values() if d.id == by_scope["early_start"].decision_id)
        full = max(
            (d for d in decisions.values() if d.id in {p.decision_id for p in permits if p.scope == "full"}),
            key=lambda d: d.decision_date,
        )
        assert early.decision_date < full.decision_date


async def test_before_the_construction_gate_the_seed_tells_the_pre_construction_story(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    """Demo timeline: one before-start condition open and one confirmation away, the early start under review."""
    from app.modules.permits import evidence as permits_evidence
    from app.modules.permits.seed import seed_permits_demo
    from app.modules.project_governance import public
    from app.modules.project_governance.evidence import GateAttempt
    from app.modules.project_governance.models import GovernanceGate
    from app.modules.project_governance.service import GovernanceService
    from app.modules.projects.models import Project

    async with world.factory() as s:
        second = await add_user(s, "editor")
        # Somebody else's account on the same installation, on no team of this project.
        stranger = await add_user(s, "manager")
        pid = await add_project(s, world.manager, [second])
        (await s.get(Project, pid)).metadata_ = {"demo_id": "permits-before-construction"}
        # Recognised by the project's state alone: a pinned model whose gate into construction is undecided.
        await GovernanceService(s).set_model(
            pid,
            source="shipped",
            catalogue_id="neutral",
            version=None,
            four_eyes=True,
            actor_id=world.manager,
            tenant_id=str(world.manager),
        )
        # The gate into construction is planned three weeks out, as in the demo timeline.
        phases = await public.phases_enabling(s, pid, "construction_start")
        planned = next(g for g in await public.project_gates(s, pid) if g.to_phase in phases)
        (await s.get(GovernanceGate, planned.id)).target_date = (NOW + timedelta(days=21)).isoformat()
        await s.commit()
    async with world.factory() as s:
        with caplog.at_level(logging.INFO, logger="app.modules.permits"):
            assert (await seed_permits_demo(s, [pid]))["projects"] == 1
        await s.commit()
    # A healthy install: the seeder says nothing above info.
    assert [r.getMessage() for r in caplog.records if r.levelno > logging.INFO and "permits" in r.name] == []
    async with world.factory() as s:
        # Only the project's owner and its team members are on a seeded row, in any column.
        people = {world.manager, second}
        for model in (
            PermitRequirement,
            PermitApplication,
            PermitDecision,
            Permit,
            PermitCondition,
            ConditionEvidence,
            ConditionDischarge,
            PermitRoadmap,
        ):
            for row in (await s.execute(select(model).where(model.project_id == pid))).scalars():
                for column in model.__table__.columns:
                    value = getattr(row, column.key)
                    assert value != stranger, (model.__name__, column.key)
                    if column.key.endswith("_user_id") or column.key.endswith("_by"):
                        assert value is None or value in people, (model.__name__, column.key, value)
    async with world.factory() as s:
        svc = PermitService(s)
        types = await svc._types(await svc.get_roadmap(pid))
        reqs = {r.id: r for r in await svc.repo.list_requirements(pid)}
        apps = await svc.repo.list_applications(pid)
        permits = await svc.repo.list_permits(pid)
        conditions = [c for c in await svc.repo.list_conditions(pid) if c.confirmed]
        # Nothing of the execution has happened: no early start permit, its application is with the authority.
        assert sorted(p.scope for p in permits) == ["full", "preliminary"]
        early = [a for a in apps if types[reqs[a.requirement_id].permit_type_code].scope == "early_start"]
        assert [a.status for a in early] == ["under_review"]
        assert sorted(a.status for a in apps if a.kind == "new" and a not in early) == [
            "decided",
            "decided",
            "preparing",
        ]
        occupancy = [r for r in reqs.values() if types[r.permit_type_code].category == "occupancy"]
        assert occupancy and not [a for a in apps if a.requirement_id == occupancy[0].id]
        # Exactly one before-start condition is open; every other one is discharged.
        before = {c.number: c for c in conditions if c.trigger == "before_start"}
        still_open = [c for c in before.values() if c.status != "discharged"]
        assert len(before) == 2 and len(still_open) == 1
        (fence,) = still_open
        assert fence.status == "evidence_submitted" and len(await svc.repo.list_evidence(pid, fence.id)) == 1
        assert fence.owner_user_id == second and fence.evidence_submitted_by == second
        # Ongoing and before-occupation conditions stay open and do not hold this gate.
        assert {c.trigger for c in conditions if c.status == "open"} >= {"ongoing", "before_occupation"}
        host = await public.host_for(s, pid, "permits")
        phases = await public.phases_enabling(s, pid, "construction_start")
        gate = next(g for g in await public.project_gates(s, pid) if g.to_phase in phases)
        area = next(a for a in await public.project_areas(s, pid) if a.code == host.area_code)
        attempt = GateAttempt(gate.id, gate.code, 1)
        items = {i.code.split(":")[0]: i for i in await permits_evidence.start_and_handover(s, pid, attempt, area)}
        # The one blocker is the fence. The road occupation is needed at mobilisation, long after the
        # gate date: it is an item of its own that names the day and does not hold the gate.
        # The seeder takes its own "today"; a long run can cross midnight after NOW was taken at import.
        (road,) = [r for r in reqs.values() if r.title == "Road occupation for crane and site access"]
        assert (road.needed_by_date - NOW).days in (175, 176)
        road_needed = road.needed_by_date.isoformat()
        assert items["permits_start"].state == "not_met"
        assert [d.split(":")[0] for d in items["permits_start"].detail.split(", ")] == ["before_start_obligation_open"]
        assert sorted(items) == ["permits_due_later", "permits_start"]
        due = items["permits_due_later"]
        assert due.state == permits_evidence.WARNING_STATE
        assert due.detail == f"Road occupation for crane and site access {road_needed}"
        # One confirmation by the project owner, who is neither the owner of the condition nor the submitter.
        can = svc.condition_can(
            fence, guards.Caller(world.manager, edit=True, manage=True, verify=True), 1, await svc._involved(fence)
        )
        assert can["discharge"]["self_certified"] == {"allowed": True, "applies": True, "reason": None}
        await svc.discharge(pid, fence.id, {"mode": "self_certified"}, actor_id=world.manager)
        await s.commit()
    async with world.factory() as s:
        items = {i.code.split(":")[0]: i for i in await permits_evidence.start_and_handover(s, pid, attempt, area)}
        # Discharged: the area is met, with exactly one warning, the same item as before.
        assert (items["permits_start"].state, items["permits_start"].detail) == ("met", "")
        assert sorted(items) == ["permits_due_later", "permits_start"]
        assert items["permits_due_later"].code == due.code
        # The permits screen and the site readiness port ask for the same day as the gate.
        svc = PermitService(s)
        start = await svc.readiness(pid, "start", NOW)
        assert start["status"] == "ready" and start["needed_from"] == (NOW + timedelta(days=21)).isoformat()
        assert [(i["code"], i["state"], i.get("needed_by")) for i in start["items"] if i["state"] != "met"] == [
            ("permit_due_later", "warning", road_needed)
        ]
        # A gate without a planned day cannot show that anything is needed later: the permit blocks.
        (await s.get(GovernanceGate, gate.id)).target_date = ""
        await s.flush()
        undated = await svc.readiness(pid, "start", NOW)
        assert undated["status"] == "not_ready" and undated["needed_from"] is None
        assert [i["code"] for i in undated["items"] if i["state"] == "not_met"] == ["permit_missing"]
        undated_items = await permits_evidence.start_and_handover(s, pid, attempt, area)
        assert [(i.code.split(":")[0], i.state) for i in undated_items] == [("permits_start", "not_met")]
        await s.rollback()


# ── finding 10, rules 2, 20, 21, 22: the ports other modules call ─────────


async def test_the_ports_answer_for_site_readiness_closeout_and_release(world: World) -> None:
    from app.modules.permits import public

    async def allocation(_session, _project_id, category: str) -> str | None:
        return "contractor" if category == "permit_conditions_change" else None

    rid = await requirement(world, BUILDING)
    out = await decide(
        world,
        await file(world, rid),
        "granted_with_conditions",
        conditions=[cond("1", "suspensive", trigger="before_occupation", requires_authority_approval=True)],
    )
    p = world.project_id
    async with world.factory() as s:
        (c,) = await PermitService(s).repo.conditions_of_permit(p, out["permit"].id)
    public.register_applicant_resolver("test_allocation", allocation)
    try:
        aid = await application(
            world,
            rid,
            kind="discharge_of_conditions",
            parent_permit_id=out["permit"].id,
            discharges_condition_ids=[c.id],
        )
    finally:
        public.unregister_applicant_resolver("test_allocation")
    await move(world, aid, "preparing")
    await move(world, aid, "submitted", TODAY - timedelta(days=20))
    await decide(world, aid, "granted")
    async with world.factory() as s:
        app = await PermitService(s).repo.get_application(p, aid)
        assert (app.applicant_role, app.applicant_source) == ("contractor", "allocation")
        assert await public.requirement_state(s, p, rid) == "granted"
        assert await public.requirement_state(s, p, uuid.uuid4()) is None
        start = await public.start_readiness(s, p)
        assert start["gate"] == "start" and start["status"] == "ready"
        (entry,) = await public.closeout_entries(s, p)
        (condition,) = entry["conditions"]
        assert condition["state"] == "discharged" and len(condition["discharges"]) == 1


# ── review round 2: who may be named, cleared fields, breach references, clearing links ──


async def test_only_a_person_on_the_project_is_named_and_a_cleared_field_is_validated(world: World) -> None:
    p = world.project_id
    rid = await requirement(world, BUILDING)
    due = TODAY + timedelta(days=30)
    out = await decide(
        world,
        await file(world, rid),
        "granted_with_conditions",
        conditions=[cond("1", trigger="by_date", due_date=due), cond("2", trigger="ongoing")],
    )
    async with world.factory() as s:
        svc = PermitService(s)
        by_number = {c.number: c for c in await svc.repo.conditions_of_permit(p, out["permit"].id)}
        one, two = by_number["1"].id, by_number["2"].id
        # The outsider is a manager elsewhere but has no access to this project.
        named = {"responsible_user_id": world.outsider}
        assert await _code(svc.update_requirement(p, rid, dict(named), actor_id=world.manager, can_manage=True)) == (
            422,
            "user_not_on_project",
        )
        assert await _code(
            svc.create_requirement(p, {"permit_type_code": BUILDING, **named}, actor_id=world.manager)
        ) == (422, "user_not_on_project")
        assert await _code(
            svc.create_condition(p, out["permit"].id, cond("7", owner_user_id=world.outsider), actor_id=world.manager)
        ) == (422, "user_not_on_project")
        assert await _code(
            svc.update_condition(p, one, {"owner_user_id": world.outsider}, actor_id=world.manager, can_manage=True)
        ) == (422, "user_not_on_project")
        # A team member is accepted.
        await svc.update_condition(p, one, {"owner_user_id": world.editor}, actor_id=world.manager, can_manage=True)
        # Clearing the date a ``by_date`` condition runs on is refused like creating one without it.
        assert await _code(
            svc.update_condition(p, one, {"due_date": None}, actor_id=world.manager, can_manage=True)
        ) == (422, "date_trigger_needs_due_date")
        assert (await svc.repo.get_condition(p, one)).due_date == due
        # A breach that points at a record names it.
        assert await _code(
            svc.ongoing(p, two, "breach", {"ref_kind": "inspection"}, actor_id=world.manager, can_manage=True)
        ) == (422, "breach_ref_required")
        assert (await svc.repo.get_condition(p, two)).status == "open"


async def test_a_roadmap_link_is_cleared_with_null_and_a_setting_cannot_be(world: World) -> None:
    p = world.project_id

    async def put(**settings) -> object:
        async with world.factory() as s:
            row = await PermitService(s).set_roadmap(p, tenant_id=None, actor_id=world.manager, settings=settings)
            await s.commit()
            return row

    assert (await put(route_assessment_id=world.assessment_id)).route_assessment_id == world.assessment_id
    assert (await put(buffer_days=7)).route_assessment_id == world.assessment_id
    assert (await put(route_assessment_id=None)).route_assessment_id is None
    assert (await put(roadmap_area_code=None)).roadmap_area_code == ""
    async with world.factory() as s:
        assert await _code(
            PermitService(s).set_roadmap(p, tenant_id=None, actor_id=world.manager, settings={"buffer_days": None})
        ) == (422, "field_not_nullable")

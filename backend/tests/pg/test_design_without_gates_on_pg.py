# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Design management on a project that does not use gates, walked to the end on PostgreSQL.

Nothing in design is approved by a gate decision: approval points and releases
are decided on approval routes, reports are accepted by hand. So a project
without a phase model must reach every final state, and the read must say that
no gate is in use instead of leaving the screen to guess.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.design_management.errors import DesignError
from app.modules.design_management.models import DesignApprovalPoint, DesignRelease, DesignReport
from app.modules.design_management.service import DesignService
from tests._pg import isolated_engine
from tests.pg.design_fixtures import (
    DesignWorld,
    approved_release,
    build_design_world,
    decide_instance,
    drawing_with_revision,
)
from tests.pg.governance_fixtures import add_route
from tests.pg.test_design_idor import BASE, client_as

pytestmark = pytest.mark.asyncio

PHASE = "concept"


@pytest_asyncio.fixture
async def factory():
    from app.modules.design_management import on_startup

    await on_startup()
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def test_a_project_without_a_phase_model_reaches_every_final_state(factory) -> None:
    """Setup, register, approval point, release, report and readiness: none of them waits for a gate."""
    world: DesignWorld = await build_design_world(factory, governance=None)
    pid = world.project_id
    async with world.factory() as s:
        svc = DesignService(s)
        assert await svc.phases(pid) == []
        assert await svc.gates_in_use(pid) is False
        assert await svc.binding_refusal(pid) is None, "no frame document can freeze the registers here"
    _drawing, rev = await drawing_with_revision(world, "ARCH")
    async with world.factory() as s:
        svc = DesignService(s)
        await svc.create_dist_rule(pid, {"recipient_role_id": str(world.roles["ARCH"])}, actor_id=world.manager)
        # Phases are the project's own words where no model lists them.
        await svc.create_deliverable(pid, {"title": "Concept plans", "phase_code": PHASE}, actor_id=world.editor)
        report = await svc.create_report(
            pid,
            {"kind_code": "geotechnical", "phase_code": PHASE, "author_role_id": str(world.roles["ARCH"])},
            actor_id=world.editor,
        )
        for step in ("commissioned", "in_progress", "submitted"):
            await svc.report_transition(pid, report.id, step, actor_id=world.editor)
        assert report.code in (await svc.readiness(pid, PHASE)).reports
        await svc.report_transition(pid, report.id, "accepted", actor_id=world.manager)
        assert report.code not in (await svc.readiness(pid, PHASE)).reports

        point = await svc.create_approval_point(pid, {"kind": "owner_approval"}, actor_id=world.editor)
        await add_route(s, pid, "design_approval_point", world.approver)
        sent = await svc.submit_approval_point(pid, point.id, actor_id=world.editor)
        await decide_instance(s, sent.approval_instance_id, world.approver)
        assert await svc.catch_up_approvals(pid) == 1
        await s.commit()
    release_id = await approved_release(world, [rev])
    async with world.factory() as s:
        svc = DesignService(s)
        issued = await svc.issue_release(pid, release_id, actor_id=world.manager)
        await s.commit()
    async with world.factory() as s:
        assert (await s.get(DesignApprovalPoint, point.id)).status == "approved"
        assert (await s.get(DesignReport, report.id)).status == "accepted"
        row = await s.get(DesignRelease, release_id)
        assert (row.status, row.approval_status, row.approved_by) == ("issued", "approved", world.approver)
        assert issued.transmittal_ids


async def test_the_register_cannot_become_a_frame_document_without_a_model_and_says_so(factory) -> None:
    """The one thing that needs a governance model is refused by name and leaves the registers alone."""
    world = await build_design_world(factory, governance=None)
    async with world.factory() as s:
        svc = DesignService(s)
        with pytest.raises(DesignError) as refused:
            await svc.generate_frame_document(
                world.project_id,
                "register",
                actor_id=world.manager,
                file_bytes=b"register",
                file_name="register.pdf",
                governance_manager=True,
            )
        assert (refused.value.code, refused.value.status_code) == ("frame_document_missing", 404)


async def test_the_setup_read_says_whether_gates_are_in_use(factory) -> None:
    """Over HTTP: false and no phases without a model, true with one."""
    bare = await build_design_world(factory, governance=None)
    gated = await build_design_world(factory)
    async with client_as(bare, bare.manager, "manager") as c:
        without = await c.get(f"{BASE}/projects/{bare.project_id}/setup")
        made = await c.post(
            f"{BASE}/projects/{bare.project_id}/deliverables", json={"title": "Plans", "phase_code": PHASE}
        )
    async with client_as(gated, gated.manager, "manager") as c:
        with_gates = await c.get(f"{BASE}/projects/{gated.project_id}/setup")
    assert without.status_code == 200, without.text
    assert (without.json()["gates_in_use"], without.json()["phases"]) == (False, [])
    assert made.status_code == 201, made.text
    assert with_gates.status_code == 200, with_gates.text
    assert with_gates.json()["gates_in_use"] is True and with_gates.json()["phases"]


async def test_a_phase_may_stay_empty_only_where_the_project_has_no_phases(factory) -> None:
    """Over HTTP: schedule lines and reviews without a phase on a bare project, the named refusal with a model."""
    bare = await build_design_world(factory, governance=None)
    gated = await build_design_world(factory)
    async with client_as(bare, bare.manager, "manager") as c:
        base = f"{BASE}/projects/{bare.project_id}"
        line = await c.post(f"{base}/deliverables", json={"title": "Plans", "phase_code": None})
        absent = await c.post(f"{base}/deliverables", json={"title": "Sections"})
        review = await c.post(f"{base}/reviews", json={"title": "Review", "phase_code": None})
        worded = await c.post(f"{base}/deliverables", json={"title": "Details", "phase_code": PHASE})
        cleared = await c.patch(f"{base}/deliverables/{worded.json()['id']}", json={"phase_code": None})
        ready = await c.get(f"{base}/readiness")
    for response in (line, absent, review, worded):
        assert response.status_code == 201, response.text
    assert (line.json()["phase_code"], absent.json()["phase_code"], review.json()["phase_code"]) == (None, None, None)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["phase_code"] is None
    assert ready.status_code == 200, ready.text
    rows = ready.json()["items"]
    assert [row["code"] for row in rows] == [None], "one row for the whole project, under no phase"
    assert len(rows[0]["open_deliverables"]) == 3 and rows[0]["met"] is False
    async with client_as(gated, gated.manager, "manager") as c:
        base = f"{BASE}/projects/{gated.project_id}"
        phase = (await c.get(f"{base}/setup")).json()["phases"][0]["code"]
        no_line = await c.post(f"{base}/deliverables", json={"title": "Plans"})
        no_review = await c.post(f"{base}/reviews", json={"title": "Review", "phase_code": None})
        kept = await c.post(f"{base}/deliverables", json={"title": "Plans", "phase_code": phase})
        emptied = await c.patch(f"{base}/deliverables/{kept.json()['id']}", json={"phase_code": None})
        phased = await c.get(f"{base}/readiness")
    for response in (no_line, no_review, emptied):
        assert response.status_code == 422, response.text
        assert response.json()["detail"]["code"] == "phase_required"
    assert kept.status_code == 201, kept.text
    assert None not in [row["code"] for row in phased.json()["items"]]

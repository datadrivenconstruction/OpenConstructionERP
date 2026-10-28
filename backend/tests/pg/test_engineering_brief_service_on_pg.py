# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The engineering brief service against PostgreSQL.

The requirements really live in the requirements module, the framework schedule really lands in the schedule
module, and the gates really take the schedule activity as the owner of their date. Each test builds its own
throwaway database, so commits and row locks behave as in production.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.engineering_brief.errors import EngineeringBriefError
from app.modules.engineering_brief.permissions import register_engineering_brief_permissions
from app.modules.engineering_brief.service import EngineeringBriefService
from tests._pg import isolated_engine
from tests.pg.engineering_brief_fixtures import OPERATION_PROOF, build_world, call, complete_brief

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def factory():
    register_engineering_brief_permissions()
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def test_an_empty_brief_cannot_be_submitted_and_names_what_is_missing(factory) -> None:
    w = await build_world(factory)
    with pytest.raises(EngineeringBriefError) as err:
        await call(w, "submit", w.manager)
    assert err.value.status_code == 422
    codes = {v["code"] for v in err.value.violations}
    assert {"no_requirements", "programme_missing"} <= codes


async def test_requirements_are_rows_of_the_requirements_module(factory) -> None:
    from app.modules.requirements.models import Requirement

    w = await build_world(factory)
    await complete_brief(w)
    async with w.factory() as s:
        brief = await EngineeringBriefService(s).require_brief(w.project_id)
        stmt = (
            select(func.count())
            .select_from(Requirement)
            .where(Requirement.requirement_set_id == brief.requirement_set_id)
        )
        n = (await s.execute(stmt)).scalar_one()
    assert n >= 1
    assert len(await call(w, "requirement_views")) == n


async def test_a_complete_brief_is_submitted_and_approved_by_hand_by_someone_else(factory) -> None:
    w = await build_world(factory)
    await complete_brief(w)
    brief = await call(w, "submit", w.manager)
    assert brief.status == "in_review"
    with pytest.raises(EngineeringBriefError) as same:
        await call(w, "approve_by_hand", w.manager)
    assert same.value.status_code == 403
    approved = await call(w, "approve_by_hand", w.decider)
    assert approved.status == "binding"
    assert approved.bound_requirements_hash
    # Editing a bound brief opens a revision; the bound hash stays as approved.
    line = {"kind_code": "gross_floor_area", "label": "x", "unit": "m2", "quantity": "1"}
    await call(w, "create_programme", line, w.manager)
    assert (await call(w, "require_brief")).status == "revising"


async def test_publishing_writes_milestones_into_the_schedule_once(factory) -> None:
    from app.modules.schedule.models import Activity

    w = await build_world(factory)
    await complete_brief(w)
    first = await call(w, "publish_schedule", w.manager)
    assert first["created"] > 0 and first["moved"] == 0
    second = await call(w, "publish_schedule", w.manager)
    assert second["created"] == 0
    async with w.factory() as s:
        stmt = select(func.count()).select_from(Activity).where(Activity.schedule_id == first["schedule_id"])
        n = (await s.execute(stmt)).scalar_one()
    assert n == first["created"]


async def test_backplan_moves_milestones_back_from_the_operation_proof(factory) -> None:
    w = await build_world(factory)
    await complete_brief(w)
    preview = await call(w, "backplan", False, w.manager)
    assert preview["unreached"] == [] and preview["applied"] is False
    applied = await call(w, "backplan", True, w.manager)
    assert applied["applied"] is True
    rows = await call(w, "milestone_views")
    assert max(r["planned_date"] for r in rows if r["planned_date"]) <= OPERATION_PROOF.isoformat()


async def test_gates_get_one_milestone_each_and_take_the_schedule_activity(factory) -> None:
    w = await build_world(factory, governance=True)
    await complete_brief(w, with_gates=True)
    result = await call(w, "publish_schedule", w.manager)
    assert result["gates_bound"], result
    gates = await call(w, "_gates")
    assert all(g["schedule_activity_id"] for g in gates if g["status"] != "decided")
    assert not [f for f in await call(w, "submission_findings") if f.code == "gate_without_milestone"]


async def test_the_specification_is_issued_as_a_document_version_and_goes_stale_on_edit(factory) -> None:
    from app.modules.documents.models import Document

    w = await build_world(factory)
    await complete_brief(w)
    with pytest.raises(EngineeringBriefError) as early:
        await call(w, "issue_specification", w.manager)
    assert early.value.code == "brief_not_submitted"
    await call(w, "submit", w.manager)
    first = await call(w, "issue_specification", w.manager, "First", "de")
    assert first.version_no == 1 and first.document_id
    views = await call(w, "issue_views")
    assert views["current"] and not views["stale"]
    with pytest.raises(EngineeringBriefError) as same:
        await call(w, "issue_specification", w.manager)
    assert same.value.code == "specification_unchanged"
    async with w.factory() as s:
        doc = await s.get(Document, first.document_id)
    assert doc.category == "specification" and doc.name.endswith(".pdf")


async def test_a_study_needs_its_own_projects_document_and_backs_the_criterion(factory) -> None:
    from app.modules.engineering_brief import rules

    w = await build_world(factory)
    with pytest.raises(EngineeringBriefError) as foreign:
        await call(
            w,
            "create_study",
            {"kind": "site_analysis", "title": "Site", "document_id": "00000000-0000-0000-0000-000000000001"},
            w.manager,
        )
    assert foreign.value.code == "document_not_found"
    row = await call(
        w,
        "create_study",
        {"kind": "site_analysis", "title": "Site", "result": "ok", "conclusion": "suitable"},
        w.manager,
    )
    views = await call(w, "study_views")
    assert rules.study_state("site_analysis", views) == ("not_met", "study_without_document:" + row.code)

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The demo seed tells each demo project its own brief from the pack story, on a governance model with gates.

The shipped gates carry no target date, which is what once made publishing refuse with ``milestone_date_missing``
and left the showcase project without a brief. Both stories are seeded here on a world with the real model.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.engineering_brief import seed as brief_seed
from app.modules.engineering_brief.permissions import register_engineering_brief_permissions
from app.modules.engineering_brief.service import EngineeringBriefService
from tests._pg import isolated_engine
from tests.pg.engineering_brief_fixtures import build_world

pytestmark = pytest.mark.asyncio

_DEMO = next((Path(__file__).resolve().parents[3] / "packs" / "eleven-areas-framework" / "src").glob("*/demo"))


@pytest_asyncio.fixture
async def factory():
    register_engineering_brief_permissions()
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _story(slug: str) -> dict:
    return json.loads((_DEMO / f"{slug}-engineering_brief.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("slug", ["residential-regensburg", "school-ludwigsburg"])
async def test_each_demo_project_gets_its_own_complete_brief(factory, slug: str) -> None:
    w = await build_world(factory, governance=True, brief=False)
    story = _story(slug)
    async with w.factory() as s:
        counts = await brief_seed._seed_project(s, w.project_id, story)
        await s.commit()
    assert counts["milestones"] > 0 and counts["studies"] == len(story["studies"])
    async with w.factory() as s:
        svc = EngineeringBriefService(s)
        brief = await svc.require_brief(w.project_id)
        assert brief.title == story["title"]
        assert await svc.milestone_views(w.project_id)
        assert await svc.concept_views(w.project_id)
        assert (await svc.issue_views(w.project_id))["items"], counts
    assert counts["submitted"] == 1 and counts["gates_bound"] > 0, counts


def test_the_two_stories_are_different_projects() -> None:
    a, b = _story("residential-regensburg"), _story("school-ludwigsburg")
    assert a["title"] != b["title"] and a["topics"] != b["topics"]
    assert not {s["title"] for s in a["studies"]} & {s["title"] for s in b["studies"]}


def test_a_demo_project_without_a_story_gets_no_brief() -> None:
    assert brief_seed._story_of("a-demo-project-the-pack-does-not-know") is None


async def test_a_package_near_a_milestone_is_bound_to_it_and_the_others_stay_put(factory) -> None:
    import uuid
    from datetime import date, timedelta

    from sqlalchemy import select

    from app.modules.procurement_concept.models import AwardPackage
    from app.modules.schedule.models import Activity

    w = await build_world(factory, governance=True, brief=False)
    story = _story("residential-regensburg")
    async with w.factory() as s:
        await brief_seed._seed_project(s, w.project_id, story)
        await s.commit()
    async with w.factory() as s:
        start = (await s.execute(select(Activity.start_date).where(Activity.start_date.is_not(None)))).scalars().first()
        near, far = uuid.uuid4(), uuid.uuid4()
        day = date.fromisoformat(str(start)[:10])
        s.add(AwardPackage(id=near, project_id=w.project_id, need_date=str(day + timedelta(days=2))))
        s.add(AwardPackage(id=far, project_id=w.project_id, need_date=str(day + timedelta(days=400))))
        await s.flush()
        assert await brief_seed._bind_nearest_package(s, w.project_id) == 1
        await s.commit()
    async with w.factory() as s:
        bound = await s.get(AwardPackage, near)
        loose = await s.get(AwardPackage, far)
        assert bound.need_activity_id is not None and bound.need_date == str(day)
        assert loose.need_activity_id is None and loose.need_date == str(day + timedelta(days=400))


@pytest.mark.parametrize("demo_id", ["residential-regensburg", "school-ludwigsburg"])
async def test_the_pack_apply_entry_point_leaves_each_demo_project_with_a_brief(factory, demo_id: str) -> None:
    from sqlalchemy import select

    from app.modules.engineering_brief.models import EngineeringBrief
    from app.modules.projects.models import Project

    w = await build_world(factory, governance=True, brief=False)
    async with w.factory() as s:
        project = await s.get(Project, w.project_id)
        project.metadata_ = {**(project.metadata_ or {}), "demo_id": demo_id}
        await s.flush()
        totals = await brief_seed.seed_engineering_brief_demo(s, [w.project_id])
        await s.commit()
    assert totals["projects"] == 1, totals
    async with w.factory() as s:
        found = (
            await s.execute(select(EngineeringBrief.id).where(EngineeringBrief.project_id == w.project_id))
        ).scalar_one_or_none()
    assert found is not None

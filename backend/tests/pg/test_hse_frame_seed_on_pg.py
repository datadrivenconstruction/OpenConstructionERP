# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The HSE frame demo seed, through the service, for the two German demo stories.

What is asserted is what a person sees on the screens: the Bavarian residential
frame is complete and in review without a blocker, the Baden-Wuerttemberg school
frame is under way with the execution coordinator only proposed and the notice,
the plan and one clearance still open, no screen is empty, and a project outside
Germany or one that already has a frame is left alone.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.hse_frame.models import HseFrame, HseItem, HseRole
from app.modules.hse_frame.seed import seed_hse_frame_demo
from app.modules.hse_frame.service import HseFrameService
from tests.pg.governance_fixtures import add_project, add_user

pytestmark = pytest.mark.asyncio


async def _project(session, owner: uuid.UUID, country: str, subdivision: str | None) -> uuid.UUID:
    from app.modules.projects.models import Project

    pid = await add_project(session, owner, [])
    project = await session.get(Project, pid)
    project.country_code = country
    project.subdivision_code = subdivision
    await session.flush()
    return pid


async def _errors(svc: HseFrameService, pid: uuid.UUID) -> list[str]:
    payload = await svc.validation_payload(pid)
    return sorted(f["code"] for f in payload["findings"] if f["severity"] == "error")


async def test_the_residential_story_is_ready_and_the_school_story_has_blockers(pg_session) -> None:
    owner = await add_user(pg_session, "manager")
    residential = await _project(pg_session, owner, "DE", "DE-BY")
    school = await _project(pg_session, owner, "DE", "DE-BW")
    totals = await seed_hse_frame_demo(pg_session, [residential, school])
    assert totals["projects"] == 2
    svc = HseFrameService(pg_session)

    ready = await svc.frame(residential)
    assert ready is not None and ready.state == "in_review"
    assert await _errors(svc, residential) == []
    roles = await svc.repo.list(HseRole, residential)
    assert {r.role_code for r in roles if r.status == "appointed"} >= {
        "safety_coordinator_design",
        "safety_coordinator_execution",
    }

    under_way = await svc.frame(school)
    assert under_way is not None and under_way.state == "draft"
    school_roles = {r.role_code: r.status for r in await svc.repo.list(HseRole, school)}
    assert school_roles["safety_coordinator_execution"] == "proposed"

    # Neither screen is empty, and every register row reads in German or carries a person's text.
    for pid in (residential, school):
        items = await svc.repo.list(HseItem, pid)
        assert len(items) >= 10
        assert any(i.status == "met" for i in items)
        assert all(i.title.strip() for i in items)
    assert any(i.status != "met" and i.obligation == "mandatory" for i in await svc.repo.list(HseItem, school))


async def test_the_seed_skips_foreign_projects_and_never_writes_twice(pg_session) -> None:
    owner = await add_user(pg_session, "manager")
    abroad = await _project(pg_session, owner, "GB", None)
    home = await _project(pg_session, owner, "DE", "DE-BY")
    first = await seed_hse_frame_demo(pg_session, [abroad, home])
    assert first["projects"] == 1
    svc = HseFrameService(pg_session)
    assert await svc.frame(abroad) is None
    items_before = len(await svc.repo.list(HseItem, home))
    second = await seed_hse_frame_demo(pg_session, [abroad, home])
    assert second["projects"] == 0
    assert len(await svc.repo.list(HseItem, home)) == items_before
    frames = await svc.repo.list(HseFrame, home)
    assert len(frames) == 1

"""PG: the analytics overview computes totals from the same filtered project set as its rows (#567).

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.costmodel.models import BudgetLine
from app.modules.projects.models import Project
from app.modules.users.models import User


async def _seed(session) -> User:
    owner = User(email=f"facet-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    session.add(owner)
    await session.flush()
    for name, phase, ptype, planned in [
        ("A", "tender", "office", "1000"),
        ("B", "construction", "office", "2000"),
        ("C", None, "housing", "4000"),
    ]:
        project = Project(name=name, owner_id=owner.id, currency="EUR", phase=phase, project_type=ptype)
        session.add(project)
        await session.flush()
        session.add(
            BudgetLine(
                project_id=project.id, category="material", description="x", planned_amount=planned, actual_amount="0"
            )
        )
    await session.flush()
    return owner


async def _overview(session, owner, **filters) -> dict:
    from app.modules.projects.router import analytics_overview

    return await analytics_overview(
        session=session,
        _user_id=str(owner.id),
        payload={"sub": str(owner.id), "role": "editor"},
        phase=filters.get("phase"),
        project_type=filters.get("project_type"),
    )


@pytest.mark.asyncio
async def test_unfiltered_overview_totals_everything(pg_session) -> None:
    owner = await _seed(pg_session)
    overview = await _overview(pg_session, owner)
    assert overview["total_projects"] == overview["unfiltered_total"] == 3
    assert overview["total_planned"] == 7000.0


@pytest.mark.asyncio
async def test_phase_filter_narrows_every_summary_figure(pg_session) -> None:
    owner = await _seed(pg_session)
    overview = await _overview(pg_session, owner, phase="tender")
    assert [p["name"] for p in overview["projects"]] == ["A"]
    assert overview["total_projects"] == 1
    assert overview["projects_with_budget"] == 1
    assert overview["total_planned"] == 1000.0
    assert overview["totals_by_currency"][0]["total_planned"] == 1000.0
    assert overview["unfiltered_total"] == 3


@pytest.mark.asyncio
async def test_type_filter_and_unset_phase(pg_session) -> None:
    owner = await _seed(pg_session)
    office = await _overview(pg_session, owner, project_type="office")
    assert office["total_planned"] == 3000.0
    unset = await _overview(pg_session, owner, phase="__unset__")
    assert [p["name"] for p in unset["projects"]] == ["C"]
    assert unset["total_planned"] == 4000.0
    # Options stay those of the whole portfolio so a filter can be changed.
    assert {p["phase"] for p in unset["facet_projects"]} == {"tender", "construction", None}

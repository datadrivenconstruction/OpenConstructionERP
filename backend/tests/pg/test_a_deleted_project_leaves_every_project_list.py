"""PG: a deleted project is gone from every cross-project list that offers it.

Deleting a project archives it (``status = "archived"``) and keeps the row so
it can be restored. The projects list and the dashboard already leave archived
rows out; the analytics overview did not, so a deleted demo or test project
stayed in the "Project Comparison" table and the "Budget Breakdown" chart, and
clicking it answered "Project not found". The two BCF project lists, the
portal project picker and the rows behind the "active projects" KPI had the
same hole.

Each test seeds a live project and a deleted one with the same data, deletes
through ``ProjectService.delete_project`` (the path the UI uses) and asserts
the live one is still listed, so a list that went empty does not pass.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid

import pytest

from app.config import get_settings
from app.modules.costmodel.models import BudgetLine
from app.modules.projects.models import Project
from app.modules.projects.service import ProjectService
from app.modules.users.models import User


async def _owner(session) -> User:
    owner = User(email=f"deleted-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    session.add(owner)
    await session.flush()
    return owner


async def _project_with_budget(session, owner: User, name: str) -> Project:
    """A project with a budget line, so it has a bar in the budget chart."""
    project = Project(name=name, owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    session.add(
        BudgetLine(
            project_id=project.id,
            description="Structure",
            planned_amount="1000",
            actual_amount="400",
        )
    )
    await session.flush()
    return project


async def _live_and_deleted(session) -> tuple[User, Project, Project]:
    owner = await _owner(session)
    live = await _project_with_budget(session, owner, "Live project")
    deleted = await _project_with_budget(session, owner, "Deleted demo project")
    await ProjectService(session, get_settings()).delete_project(deleted.id, changed_by=str(owner.id))
    await session.flush()
    return owner, live, deleted


@pytest.mark.asyncio
async def test_the_analytics_overview_leaves_out_a_deleted_project(pg_session) -> None:
    """Comparison table and budget chart both read ``projects`` from here."""
    from app.modules.projects.router import analytics_overview

    owner, live, deleted = await _live_and_deleted(pg_session)

    overview = await analytics_overview(
        session=pg_session,
        _user_id=str(owner.id),
        payload={"sub": str(owner.id), "role": "editor"},
    )

    ids = {p["id"] for p in overview["projects"]}
    assert str(live.id) in ids
    assert str(deleted.id) not in ids
    assert overview["total_projects"] == 1
    assert overview["projects_with_budget"] == 1
    # The deleted project's budget is not in the headline totals either.
    assert overview["total_planned"] == 1000.0


@pytest.mark.asyncio
async def test_the_admin_analytics_overview_leaves_out_a_deleted_project(pg_session) -> None:
    """Admins see every project, but a deleted one is still not a project."""
    from app.modules.projects.router import analytics_overview

    owner, live, deleted = await _live_and_deleted(pg_session)

    overview = await analytics_overview(
        session=pg_session,
        _user_id=str(owner.id),
        payload={"sub": str(owner.id), "role": "admin"},
    )

    ids = {p["id"] for p in overview["projects"]}
    assert str(live.id) in ids
    assert str(deleted.id) not in ids


@pytest.mark.asyncio
async def test_the_bcf_project_lists_leave_out_a_deleted_project(pg_session) -> None:
    from app.modules.bcf.opencde_service import OpenCDEService as BCFOpenCDEService
    from app.modules.opencde_api.service import OpenCDEService

    owner, live, deleted = await _live_and_deleted(pg_session)

    foundation = {p.project_id for p in await OpenCDEService(pg_session).list_projects()}
    assert str(live.id) in foundation
    assert str(deleted.id) not in foundation

    bcf = {
        p.project_id for p in await BCFOpenCDEService(pg_session).list_projects(user_id=str(owner.id), role="editor")
    }
    assert str(live.id) in bcf
    assert str(deleted.id) not in bcf


@pytest.mark.asyncio
async def test_the_active_projects_kpi_rows_leave_out_a_deleted_project(pg_session) -> None:
    """The count never counted it; the drill-down rows under it listed it."""
    from app.modules.bi_dashboards.kpis import _projects_active_records, project_count_active_kpi

    _owner_row, live, deleted = await _live_and_deleted(pg_session)
    allowed = {live.id, deleted.id}

    rows = await _projects_active_records(pg_session, None, 50, allowed_project_ids=allowed)
    ids = {r["id"] for r in rows}
    assert str(live.id) in ids
    assert str(deleted.id) not in ids

    count = await project_count_active_kpi(pg_session, allowed_project_ids=allowed)
    assert count.value == len(rows) == 1


@pytest.mark.asyncio
async def test_the_portal_project_picker_leaves_out_a_deleted_project(pg_session, monkeypatch) -> None:
    """A portal user keeps an access rule to a project after it is deleted."""
    from app.modules.portal.service import PortalService

    _owner_row, live, deleted = await _live_and_deleted(pg_session)
    service = PortalService(pg_session)

    async def _both_rules(_portal_user_id, _resource_type):
        return [live.id, deleted.id]

    monkeypatch.setattr(service, "list_accessible_resources", _both_rules)

    ids = {p.id for p in await service.list_accessible_projects(uuid.uuid4())}
    assert ids == {live.id}

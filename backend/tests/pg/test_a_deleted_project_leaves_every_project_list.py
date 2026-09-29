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
            category="material",
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


@pytest.mark.asyncio
async def test_the_portfolio_tree_leaves_out_a_deleted_project(pg_session) -> None:
    """The membership row outlives the soft delete; the tree must not list it."""
    from app.modules.portfolio.models import PortfolioMembership, PortfolioNode
    from app.modules.portfolio.service import PortfolioService

    owner, live, deleted = await _live_and_deleted(pg_session)
    node = PortfolioNode(name="Programme", owner_id=owner.id)
    pg_session.add(node)
    await pg_session.flush()
    pg_session.add_all(
        [
            PortfolioMembership(node_id=node.id, project_id=live.id),
            PortfolioMembership(node_id=node.id, project_id=deleted.id),
        ]
    )
    await pg_session.flush()

    tree = await PortfolioService(pg_session).get_tree(str(owner.id))

    mine = [n for n in tree if n["id"] == str(node.id)]
    assert len(mine) == 1
    assert mine[0]["project_ids"] == [str(live.id)]


# ── Listing scopes built on the access rule ────────────────────────────────
# The access rule itself still reaches an archived project (restore and the
# per-project checks rely on it); the listings ask for ``live_only``.


@pytest.mark.asyncio
async def test_accessible_project_ids_keeps_its_contract_and_drops_deleted_when_live_only(pg_session) -> None:
    from app.dependencies import accessible_project_ids

    owner, live, deleted = await _live_and_deleted(pg_session)

    everything = await accessible_project_ids(pg_session, str(owner.id))
    assert {live.id, deleted.id} <= everything

    listed = await accessible_project_ids(pg_session, str(owner.id), live_only=True)
    assert live.id in listed
    assert deleted.id not in listed


@pytest.mark.asyncio
async def test_an_admin_listing_scope_is_every_live_project(pg_session) -> None:
    from app.dependencies import accessible_project_ids

    owner, live, deleted = await _live_and_deleted(pg_session)
    admin = User(email=f"admin-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", role="admin")
    pg_session.add(admin)
    await pg_session.flush()

    assert await accessible_project_ids(pg_session, str(admin.id)) is None
    listed = await accessible_project_ids(pg_session, str(admin.id), live_only=True)
    assert listed is not None
    assert live.id in listed
    assert deleted.id not in listed


@pytest.mark.asyncio
async def test_a_team_member_listing_scope_drops_a_deleted_project(pg_session) -> None:
    from sqlalchemy import select

    from app.modules.search.service import _accessible_project_ids as search_scope
    from app.modules.teams.access import member_project_ids_subquery
    from app.modules.teams.models import Team, TeamMembership

    _owner_row, live, deleted = await _live_and_deleted(pg_session)
    member = await _owner(pg_session)
    for project in (live, deleted):
        team = Team(project_id=project.id, name="Site team")
        pg_session.add(team)
        await pg_session.flush()
        pg_session.add(TeamMembership(team_id=team.id, user_id=member.id))
    await pg_session.flush()

    async def _members(**kwargs) -> set[uuid.UUID]:
        stmt = select(Project.id).where(Project.id.in_(member_project_ids_subquery(member.id, **kwargs)))
        return set((await pg_session.execute(stmt)).scalars())

    assert await _members() == {live.id, deleted.id}
    assert await _members(live_only=True) == {live.id}

    assert await search_scope(pg_session, str(member.id)) == {live.id}


@pytest.mark.asyncio
async def test_change_orders_across_projects_leave_out_a_deleted_project(pg_session) -> None:
    from app.modules.changeorders.models import ChangeOrder
    from app.modules.changeorders.repository import ChangeOrderRepository

    owner, live, deleted = await _live_and_deleted(pg_session)
    for project in (live, deleted):
        pg_session.add(ChangeOrder(project_id=project.id, code="CO-001", title="Extra footing"))
    await pg_session.flush()

    rows, total = await ChangeOrderRepository(pg_session).list_for_owner(owner.id)
    assert {r.project_id for r in rows} == {live.id}
    assert total == 1


@pytest.mark.asyncio
async def test_file_search_and_smart_view_scopes_leave_out_a_deleted_project(pg_session) -> None:
    from app.modules.file_distribution.router import _resolve_accessible_project_ids
    from app.modules.smart_views.service import SmartViewService

    owner, live, deleted = await _live_and_deleted(pg_session)

    files_scope = set(await _resolve_accessible_project_ids(pg_session, owner.id))
    assert live.id in files_scope
    assert deleted.id not in files_scope

    service = SmartViewService(pg_session)
    assert set(await service._accessible_project_ids(owner.id, live_only=True)) == {live.id}
    # Read checks keep the plain ownership rule.
    assert set(await service._accessible_project_ids(owner.id)) == {live.id, deleted.id}


@pytest.mark.asyncio
async def test_portfolio_kpi_fan_out_leaves_out_a_deleted_project(pg_session) -> None:
    from app.modules.bi_dashboards.kpis import _cost_portfolio_project_ids

    _owner_row, live, deleted = await _live_and_deleted(pg_session)

    scoped = set(await _cost_portfolio_project_ids(pg_session, {live.id, deleted.id}))
    assert scoped == {live.id}
    unrestricted = set(await _cost_portfolio_project_ids(pg_session, None))
    assert live.id in unrestricted
    assert deleted.id not in unrestricted


@pytest.mark.asyncio
async def test_a_purged_demo_project_leaves_the_analytics_overview(pg_session) -> None:
    """The hard path: removing demo data deletes the row and its children."""
    from sqlalchemy import func, select

    from app.modules.projects.router import analytics_overview

    owner = await _owner(pg_session)
    live = await _project_with_budget(pg_session, owner, "Live project")
    demo = await _project_with_budget(pg_session, owner, "Demo project")
    demo.metadata_ = {"demo_id": f"demo-{uuid.uuid4().hex[:8]}"}
    await pg_session.flush()
    # The purge expires every instance in the session; read ids first.
    demo_id, live_id, owner_id = demo.id, live.id, owner.id

    await ProjectService(pg_session, get_settings()).purge_demo_projects()

    overview = await analytics_overview(
        session=pg_session,
        _user_id=str(owner_id),
        payload={"sub": str(owner_id), "role": "editor"},
    )
    ids = {p["id"] for p in overview["projects"]}
    assert ids == {str(live_id)}
    assert overview["total_planned"] == 1000.0
    # No budget line is left behind for the purged project.
    orphans = await pg_session.scalar(
        select(func.count()).select_from(BudgetLine).where(BudgetLine.project_id == demo_id)
    )
    assert orphans == 0

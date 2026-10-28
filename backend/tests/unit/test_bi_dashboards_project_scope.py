# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The BI list endpoints answer for the project in the address bar.

``/projects/{id}/bi-dashboards`` used to render the company-wide page: the
five list endpoints had no project dimension, so the route claimed a project
and showed everything. These tests pin the rule that replaced it - a project
view shows that project's own rows plus the company-wide ones (``project_id
IS NULL``), and never another project's.

Every test drives the *service*, which is the layer the router calls. The
repository has carried a ``project_id`` argument on ``list_dashboards`` for
some time and nothing ever passed it, so a test written against the
repository would have gone green while the endpoint stayed broken.

Run:
    cd backend
    python -m pytest tests/unit/test_bi_dashboards_project_scope.py -v
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """PostgreSQL session inside an outer transaction rolled back on teardown."""
    async with transactional_session() as s:
        yield s


def _code() -> str:
    """A unique code for the globally-UNIQUE ``code`` columns."""
    return f"scope_{uuid.uuid4().hex[:10]}"


# ── Dashboards ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_dashboards_shows_the_project_and_the_company_wide_only(
    session: AsyncSession,
) -> None:
    from app.modules.bi_dashboards.schemas import DashboardCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    owner = uuid.uuid4()
    project_a = uuid.uuid4()
    project_b = uuid.uuid4()

    await svc.create_dashboard(
        DashboardCreate(name="board-a", scope="project", project_id=project_a),
        owner_user_id=owner,
    )
    await svc.create_dashboard(
        DashboardCreate(name="board-b", scope="project", project_id=project_b),
        owner_user_id=owner,
    )
    await svc.create_dashboard(
        DashboardCreate(name="board-company", scope="personal"),
        owner_user_id=owner,
    )

    names = {d.name for d in await svc.list_dashboards(owner_user_id=owner, project_id=project_a)}
    assert names == {"board-a", "board-company"}


@pytest.mark.asyncio
async def test_list_dashboards_without_a_project_is_unchanged(
    session: AsyncSession,
) -> None:
    """The plain module route keeps showing every dashboard the caller owns."""
    from app.modules.bi_dashboards.schemas import DashboardCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    owner = uuid.uuid4()
    project_a = uuid.uuid4()
    project_b = uuid.uuid4()

    for name, pid in (("board-a", project_a), ("board-b", project_b), ("board-company", None)):
        await svc.create_dashboard(
            DashboardCreate(name=name, scope="personal", project_id=pid),
            owner_user_id=owner,
        )

    names = {d.name for d in await svc.list_dashboards(owner_user_id=owner)}
    assert names == {"board-a", "board-b", "board-company"}


@pytest.mark.asyncio
async def test_a_project_view_does_not_widen_who_sees_what(
    session: AsyncSession,
) -> None:
    """Naming a project must not hand a caller someone else's dashboard.

    The project clause is ANDed onto the ownership rule, so a colleague's
    personal dashboard on the same project stays invisible.
    """
    from app.modules.bi_dashboards.schemas import DashboardCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    alice = uuid.uuid4()
    bob = uuid.uuid4()
    project_a = uuid.uuid4()

    await svc.create_dashboard(
        DashboardCreate(name="alice-board", scope="personal", project_id=project_a),
        owner_user_id=alice,
    )
    await svc.create_dashboard(
        DashboardCreate(name="bob-board", scope="personal", project_id=project_a),
        owner_user_id=bob,
    )

    names = {d.name for d in await svc.list_dashboards(owner_user_id=alice, project_id=project_a)}
    assert names == {"alice-board"}


# ── Reports ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_reports_shows_the_project_and_the_company_wide_only(
    session: AsyncSession,
) -> None:
    from app.modules.bi_dashboards.schemas import ReportDefinitionCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    owner = uuid.uuid4()
    project_a = uuid.uuid4()
    project_b = uuid.uuid4()

    code_a, code_b, code_company = _code(), _code(), _code()
    await svc.create_report(
        ReportDefinitionCreate(code=code_a, name="report-a", project_id=project_a),
        owner_user_id=owner,
    )
    await svc.create_report(
        ReportDefinitionCreate(code=code_b, name="report-b", project_id=project_b),
        owner_user_id=owner,
    )
    await svc.create_report(
        ReportDefinitionCreate(code=code_company, name="report-company"),
        owner_user_id=owner,
    )

    codes = {r.code for r in await svc.list_reports(owner_user_id=owner, project_id=project_a)}
    assert codes == {code_a, code_company}


# ── Schedules ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_schedules_follows_the_project_of_its_report(
    session: AsyncSession,
) -> None:
    """A schedule inherits the audience of the report it hangs off."""
    from app.modules.bi_dashboards.schemas import (
        ReportDefinitionCreate,
        ReportScheduleCreate,
    )
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    owner = uuid.uuid4()
    project_a = uuid.uuid4()
    project_b = uuid.uuid4()

    made: dict[str, uuid.UUID] = {}
    for label, pid in (("a", project_a), ("b", project_b), ("company", None)):
        report = await svc.create_report(
            ReportDefinitionCreate(code=_code(), name=f"report-{label}", project_id=pid),
            owner_user_id=owner,
        )
        schedule = await svc.create_schedule(
            ReportScheduleCreate(report_definition_id=report.id, frequency="daily"),
        )
        assert schedule is not None
        made[label] = schedule.id

    visible = {s.id for s in await svc.list_schedules_visible_to(owner_user_id=owner, project_id=project_a)}
    assert visible == {made["a"], made["company"]}


@pytest.mark.asyncio
async def test_a_schedule_pinned_elsewhere_does_not_ride_in_on_a_company_report(
    session: AsyncSession,
) -> None:
    """The project scope is checked on the schedule as well as its report.

    A company-wide report is listed on every project, so filtering only by
    the parent would carry every schedule hanging off it into every project
    view - including one somebody deliberately narrowed to another project.
    """
    from app.modules.bi_dashboards.schemas import (
        ReportDefinitionCreate,
        ReportScheduleCreate,
    )
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    owner = uuid.uuid4()
    project_a = uuid.uuid4()
    project_b = uuid.uuid4()

    report = await svc.create_report(
        ReportDefinitionCreate(code=_code(), name="report-company"),
        owner_user_id=owner,
    )
    for_a = await svc.create_schedule(
        ReportScheduleCreate(report_definition_id=report.id, frequency="daily", project_id=project_a),
    )
    for_b = await svc.create_schedule(
        ReportScheduleCreate(report_definition_id=report.id, frequency="weekly", project_id=project_b),
    )
    for_everyone = await svc.create_schedule(
        ReportScheduleCreate(report_definition_id=report.id, frequency="monthly"),
    )
    assert for_a is not None and for_b is not None and for_everyone is not None

    visible = {s.id for s in await svc.list_schedules_visible_to(owner_user_id=owner, project_id=project_a)}
    assert visible == {for_a.id, for_everyone.id}


# ── Saved filters ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_filters_shows_the_project_and_the_company_wide_only(
    session: AsyncSession,
) -> None:
    from app.modules.bi_dashboards.schemas import SavedFilterCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    owner = uuid.uuid4()
    project_a = uuid.uuid4()
    project_b = uuid.uuid4()

    for name, pid in (("filter-a", project_a), ("filter-b", project_b), ("filter-company", None)):
        await svc.create_filter(
            SavedFilterCreate(name=name, module="boq", project_id=pid),
            owner_user_id=owner,
        )

    names = {f.name for f in await svc.list_filters(owner_user_id=owner, project_id=project_a)}
    assert names == {"filter-a", "filter-company"}


@pytest.mark.asyncio
async def test_a_shared_filter_obeys_the_project_view_too(
    session: AsyncSession,
) -> None:
    """Sharing must not smuggle another project's filter back into the view.

    The shared-with-me set is collected by a second query, in Python, so it
    needs the project clause of its own or the exclusion is undone.
    """
    from app.modules.bi_dashboards.schemas import SavedFilterCreate
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    alice = uuid.uuid4()
    bob = uuid.uuid4()
    project_a = uuid.uuid4()
    project_b = uuid.uuid4()

    await svc.create_filter(
        SavedFilterCreate(
            name="bobs-filter-on-b",
            module="boq",
            project_id=project_b,
            shared_with_user_ids=[alice],
        ),
        owner_user_id=bob,
    )
    await svc.create_filter(
        SavedFilterCreate(
            name="bobs-filter-on-a",
            module="boq",
            project_id=project_a,
            shared_with_user_ids=[alice],
        ),
        owner_user_id=bob,
    )

    names = {f.name for f in await svc.list_filters(owner_user_id=alice, project_id=project_a)}
    assert names == {"bobs-filter-on-a"}


# ── KPI library ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_kpi_definitions_shows_the_project_and_the_company_wide_only(
    session: AsyncSession,
) -> None:
    """Seeded system KPIs carry no project, so they stay on every board."""
    from app.modules.bi_dashboards.models import KPIDefinition
    from app.modules.bi_dashboards.service import BIDashboardsService

    svc = BIDashboardsService(session)
    project_a = uuid.uuid4()
    project_b = uuid.uuid4()

    code_a, code_b, code_system = _code(), _code(), _code()
    for code, pid in ((code_a, project_a), (code_b, project_b), (code_system, None)):
        session.add(
            KPIDefinition(
                code=code,
                name=code,
                formula_ref="noop",
                category="operational",
                project_id=pid,
            ),
        )
    await session.flush()

    listed = {k.code for k in await svc.list_kpi_definitions(project_id=project_a)}
    assert code_a in listed
    assert code_system in listed
    assert code_b not in listed

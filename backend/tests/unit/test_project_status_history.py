"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the project status-history audit trail.

Pins the contract behind GET /api/v1/projects/{id}/status-history:

* ``update_project`` records a row (old -> new) when the PATCH changes
  ``status``, and records NOTHING when the PATCH leaves status untouched.
* ``delete_project`` (archive) records (active -> archived).
* ``restore_project`` records (archived -> active).
* ``create_project`` seeds the initial row (None -> created status).
* ``list_status_history`` returns rows newest-first.

All tests use a transaction-isolated PostgreSQL session (rolled back on
teardown) via ``tests._pg.transactional_session`` - the same fast isolation
primitive the other projects unit suites use. The status-history table is
materialised into the shared unit schema by ``_import_all_models``.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.modules.projects import service as project_service_module
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate
from app.modules.projects.service import ProjectService
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Transaction-isolated PostgreSQL session (rolled back on teardown)."""
    async with transactional_session() as s:
        yield s


@pytest.fixture(autouse=True)
def _clear_reservation_set():
    """Isolate the process-global project-code reservation set per test.

    ``create_project`` reserves codes in a module-level set; clearing it keeps
    tests from bleeding reservation state into one another.
    """
    project_service_module._PROJECT_CODE_RESERVED.clear()
    yield
    project_service_module._PROJECT_CODE_RESERVED.clear()


@pytest_asyncio.fixture
async def owner_id(session: AsyncSession) -> uuid.UUID:
    """Insert a single owner User row and return its id."""
    from app.modules.users.models import User

    user = User(
        email=f"owner-{uuid.uuid4().hex}@test.local",
        hashed_password="x",
        full_name="Owner",
    )
    session.add(user)
    await session.flush()
    return user.id


def _service(session: AsyncSession) -> ProjectService:
    return ProjectService(session, Settings(_env_file=None))


async def _make_project(
    service: ProjectService,
    owner_id: uuid.UUID,
    *,
    status: str = "active",
):
    """Create a project, optionally moving it off the default status.

    ``create_project`` always seeds an initial (None -> active) row; when a
    non-default starting status is requested we PATCH it once and return the
    project so the caller starts from a known state.
    """
    project = await service.create_project(
        ProjectCreate(name="History Test"),
        owner_id,
    )
    if status != "active":
        await service.update_project(
            project.id,
            ProjectUpdate(status=status),
            changed_by=str(owner_id),
        )
    return project


@pytest.mark.asyncio
async def test_create_project_seeds_initial_history_row(
    session: AsyncSession,
    owner_id: uuid.UUID,
) -> None:
    """A freshly created project has one row: None -> active."""
    service = _service(session)
    project = await service.create_project(ProjectCreate(name="Fresh"), owner_id)

    rows = await service.list_status_history(project.id)
    assert len(rows) == 1
    assert rows[0].from_status is None
    assert rows[0].to_status == "active"
    assert str(rows[0].changed_by) == str(owner_id)


@pytest.mark.asyncio
async def test_update_project_status_change_inserts_row(
    session: AsyncSession,
    owner_id: uuid.UUID,
) -> None:
    """A PATCH that changes status records old -> new with the actor."""
    service = _service(session)
    project = await service.create_project(ProjectCreate(name="Movable"), owner_id)

    await service.update_project(
        project.id,
        ProjectUpdate(status="on_hold"),
        changed_by=str(owner_id),
    )

    rows = await service.list_status_history(project.id)
    # Newest first: the on_hold transition, then the initial seed.
    assert len(rows) == 2
    assert rows[0].from_status == "active"
    assert rows[0].to_status == "on_hold"
    assert str(rows[0].changed_by) == str(owner_id)
    assert rows[1].from_status is None
    assert rows[1].to_status == "active"


@pytest.mark.asyncio
async def test_update_project_without_status_change_inserts_nothing(
    session: AsyncSession,
    owner_id: uuid.UUID,
) -> None:
    """A PATCH that does not touch status adds no history row."""
    service = _service(session)
    project = await service.create_project(ProjectCreate(name="Renamed"), owner_id)
    before = await service.list_status_history(project.id)

    # Rename only - status untouched.
    await service.update_project(
        project.id,
        ProjectUpdate(name="Renamed Again"),
        changed_by=str(owner_id),
    )

    after = await service.list_status_history(project.id)
    assert len(after) == len(before) == 1


@pytest.mark.asyncio
async def test_update_project_status_noop_inserts_nothing(
    session: AsyncSession,
    owner_id: uuid.UUID,
) -> None:
    """Re-PATCHing the same status value records nothing (no real change)."""
    service = _service(session)
    project = await service.create_project(ProjectCreate(name="Same"), owner_id)

    await service.update_project(
        project.id,
        ProjectUpdate(status="active"),
        changed_by=str(owner_id),
    )

    rows = await service.list_status_history(project.id)
    assert len(rows) == 1  # only the initial seed


@pytest.mark.asyncio
async def test_delete_project_records_archived_transition(
    session: AsyncSession,
    owner_id: uuid.UUID,
) -> None:
    """Archiving records active -> archived."""
    service = _service(session)
    project = await service.create_project(ProjectCreate(name="To Archive"), owner_id)
    # delete_project soft-deletes and (unlike update/restore) does not re-fetch
    # the project, so its update_fields() expire_all() leaves this `project`
    # expired. Capture the id up front so the assertions below don't trigger a
    # lazy reload of the expired instance (MissingGreenlet under the async session).
    project_id = project.id

    await service.delete_project(project_id, changed_by=str(owner_id))

    rows = await service.list_status_history(project_id)
    assert rows[0].from_status == "active"
    assert rows[0].to_status == "archived"
    assert str(rows[0].changed_by) == str(owner_id)


@pytest.mark.asyncio
async def test_restore_project_records_archived_to_active(
    session: AsyncSession,
    owner_id: uuid.UUID,
) -> None:
    """Restoring an archived project records archived -> active."""
    service = _service(session)
    project = await _make_project(service, owner_id, status="archived")

    await service.restore_project(project.id, changed_by=str(owner_id))

    rows = await service.list_status_history(project.id)
    assert rows[0].from_status == "archived"
    assert rows[0].to_status == "active"
    assert str(rows[0].changed_by) == str(owner_id)


@pytest.mark.asyncio
async def test_list_status_history_is_newest_first(
    session: AsyncSession,
    owner_id: uuid.UUID,
) -> None:
    """Multiple transitions come back ordered newest-first."""
    service = _service(session)
    project = await service.create_project(ProjectCreate(name="Lifecycle"), owner_id)

    for to_status in ("on_hold", "active", "finished"):
        await service.update_project(
            project.id,
            ProjectUpdate(status=to_status),
            changed_by=str(owner_id),
        )

    rows = await service.list_status_history(project.id)
    # 1 initial seed + 3 transitions.
    assert len(rows) == 4
    assert [r.to_status for r in rows] == ["finished", "active", "on_hold", "active"]


# ── Custom-status list filtering ("all" view + curated statuses) ──────────


@pytest.mark.asyncio
async def test_list_all_includes_archived(
    session: AsyncSession,
    owner_id: uuid.UUID,
) -> None:
    """The "all" view (status_filter=None, include_archived=True) spans
    every status, archived included, while the default excludes archived."""
    service = _service(session)
    active = await service.create_project(ProjectCreate(name="Active One"), owner_id)
    archived = await _make_project(service, owner_id, status="archived")

    # Default listing (no status, no include_archived) hides the archived one.
    default_rows, default_total = await service.list_projects(owner_id)
    default_ids = {p.id for p in default_rows}
    assert active.id in default_ids
    assert archived.id not in default_ids

    # "all" view surfaces both.
    all_rows, all_total = await service.list_projects(
        owner_id,
        status_filter=None,
        include_archived=True,
    )
    all_ids = {p.id for p in all_rows}
    assert active.id in all_ids
    assert archived.id in all_ids
    assert all_total >= default_total + 1


@pytest.mark.asyncio
async def test_list_filters_to_exact_custom_status(
    session: AsyncSession,
    owner_id: uuid.UUID,
) -> None:
    """status_filter='on_hold' returns exactly the on-hold projects."""
    service = _service(session)
    await service.create_project(ProjectCreate(name="Stays Active"), owner_id)
    on_hold = await _make_project(service, owner_id, status="on_hold")

    rows, total = await service.list_projects(owner_id, status_filter="on_hold")

    assert total == 1
    assert {p.id for p in rows} == {on_hold.id}
    assert all(p.status == "on_hold" for p in rows)

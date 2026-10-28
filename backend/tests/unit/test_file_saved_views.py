# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for the file-saved-views (W5) module.

Covers the full CRUD + telemetry surface against PostgreSQL:

* ``test_create_then_list_returns_pinned_first`` — pinning floats a
  view above unpinned siblings regardless of ``sort_order``.
* ``test_use_bumps_use_count_and_last_used_at`` — telemetry persists.
* ``test_duplicate_creates_name_copy_suffix`` — duplicate twice in a
  row → "(copy)" then "(copy) 2".
* ``test_delete_removes_view``.
* ``test_unique_constraint_blocks_dup_name`` — conflict surface.
* ``test_shared_view_visible_to_other_user_in_same_project``.
* ``test_non_owner_cannot_update_or_delete_shared_view``.

Each test runs on a transaction-isolated PostgreSQL session from
``tests._pg.transactional_session`` (the shared schema-loaded
``oe_test_unit`` database, rolled back on teardown) so the tests stay
fast and never touch the production database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.file_saved_views.schemas import (
    FilterSnapshot,
    SavedViewCreate,
    SavedViewUpdate,
)
from app.modules.file_saved_views.service import (
    SavedViewConflictError,
    SavedViewNotFoundError,
    SavedViewService,
)
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

# ── DB fixture ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Transaction-isolated PostgreSQL session (rolled back on teardown)."""
    async with transactional_session() as s:
        yield s


async def _seed_user_and_project(session) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert one user + one project. Returns (user_id, project_id)."""
    user = User(
        email=f"sv-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Saved-View Tester",
    )
    session.add(user)
    await session.flush()
    project = Project(name="SV Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    return user.id, project.id


async def _seed_user(session) -> uuid.UUID:
    """Insert one extra user. Returns user_id."""
    user = User(
        email=f"sv-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Other Tester",
    )
    session.add(user)
    await session.flush()
    return user.id


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_then_list_returns_pinned_first(db_session):
    user_id, project_id = await _seed_user_and_project(db_session)
    svc = SavedViewService(db_session)

    # Three views: unpinned A, pinned B, unpinned C.
    await svc.create(
        SavedViewCreate(
            name="A Documents",
            project_id=project_id,
            filter_json=FilterSnapshot(kind="document"),
            is_pinned=False,
            sort_order=10,
        ),
        user_id,
    )
    pinned = await svc.create(
        SavedViewCreate(
            name="B Pinned",
            project_id=project_id,
            filter_json=FilterSnapshot(kind="sheet"),
            is_pinned=True,
            sort_order=99,
        ),
        user_id,
    )
    await svc.create(
        SavedViewCreate(
            name="C Photos",
            project_id=project_id,
            filter_json=FilterSnapshot(kind="photo"),
            is_pinned=False,
            sort_order=5,
        ),
        user_id,
    )
    await db_session.commit()

    rows = await svc.list_views(user_id=user_id, project_id=project_id)
    assert len(rows) == 3
    # Pinned ALWAYS first (regardless of huge sort_order=99).
    assert rows[0].id == pinned.id
    # Then by sort_order ascending → C (5) before A (10).
    assert rows[1].name == "C Photos"
    assert rows[2].name == "A Documents"


@pytest.mark.asyncio
async def test_use_bumps_use_count_and_last_used_at(db_session):
    user_id, project_id = await _seed_user_and_project(db_session)
    svc = SavedViewService(db_session)
    view = await svc.create(
        SavedViewCreate(
            name="Telemetry Probe",
            project_id=project_id,
            filter_json=FilterSnapshot(kind="document", q="foundation"),
        ),
        user_id,
    )
    await db_session.commit()

    assert view.use_count == 0
    assert view.last_used_at is None

    before = datetime.now(UTC)
    bumped = await svc.use(view.id, user_id)
    await db_session.commit()
    assert bumped.use_count == 1
    assert bumped.last_used_at is not None
    # Normalise to tz-aware before comparing, just in case.
    last = bumped.last_used_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    assert last >= before - timedelta(seconds=1)

    bumped_again = await svc.use(view.id, user_id)
    await db_session.commit()
    assert bumped_again.use_count == 2


@pytest.mark.asyncio
async def test_duplicate_creates_name_copy_suffix(db_session):
    user_id, project_id = await _seed_user_and_project(db_session)
    svc = SavedViewService(db_session)
    view = await svc.create(
        SavedViewCreate(
            name="Drawings",
            project_id=project_id,
            filter_json=FilterSnapshot(kind="sheet"),
            is_pinned=True,
        ),
        user_id,
    )
    await db_session.commit()

    clone1 = await svc.duplicate(view.id, user_id)
    await db_session.commit()
    assert clone1.name == "Drawings (copy)"
    # ``is_pinned`` MUST NOT carry over to the duplicate.
    assert clone1.is_pinned is False

    clone2 = await svc.duplicate(view.id, user_id)
    await db_session.commit()
    assert clone2.name == "Drawings (copy) 2"

    clone3 = await svc.duplicate(view.id, user_id)
    await db_session.commit()
    assert clone3.name == "Drawings (copy) 3"


@pytest.mark.asyncio
async def test_delete_removes_view(db_session):
    user_id, project_id = await _seed_user_and_project(db_session)
    svc = SavedViewService(db_session)
    view = await svc.create(
        SavedViewCreate(
            name="Doomed",
            project_id=project_id,
            filter_json=FilterSnapshot(kind="document"),
        ),
        user_id,
    )
    await db_session.commit()
    await svc.delete(view.id, user_id)
    await db_session.commit()

    with pytest.raises(SavedViewNotFoundError):
        await svc.get(view.id, user_id)


@pytest.mark.asyncio
async def test_unique_constraint_blocks_dup_name(db_session):
    user_id, project_id = await _seed_user_and_project(db_session)
    svc = SavedViewService(db_session)
    await svc.create(
        SavedViewCreate(
            name="Unique Probe",
            project_id=project_id,
            filter_json=FilterSnapshot(kind="document"),
        ),
        user_id,
    )
    await db_session.commit()

    with pytest.raises(SavedViewConflictError):
        await svc.create(
            SavedViewCreate(
                name="Unique Probe",
                project_id=project_id,
                filter_json=FilterSnapshot(kind="sheet"),
            ),
            user_id,
        )


@pytest.mark.asyncio
async def test_shared_view_visible_to_other_user_in_same_project(db_session):
    owner_id, project_id = await _seed_user_and_project(db_session)
    other_id = await _seed_user(db_session)
    svc = SavedViewService(db_session)

    private = await svc.create(
        SavedViewCreate(
            name="Private",
            project_id=project_id,
            filter_json=FilterSnapshot(kind="document"),
            is_shared=False,
        ),
        owner_id,
    )
    shared = await svc.create(
        SavedViewCreate(
            name="Shared",
            project_id=project_id,
            filter_json=FilterSnapshot(kind="sheet"),
            is_shared=True,
        ),
        owner_id,
    )
    await db_session.commit()

    # Owner sees both.
    owner_visible = await svc.list_views(user_id=owner_id, project_id=project_id)
    owner_names = {v.name for v in owner_visible}
    assert {"Private", "Shared"}.issubset(owner_names)

    # Other user sees ONLY the shared one.
    other_visible = await svc.list_views(user_id=other_id, project_id=project_id)
    other_names = {v.name for v in other_visible}
    assert "Shared" in other_names
    assert "Private" not in other_names

    # The non-owner can read the shared view directly...
    fetched = await svc.get(shared.id, other_id)
    assert fetched.id == shared.id
    # ...but NOT the private one.
    with pytest.raises(SavedViewNotFoundError):
        await svc.get(private.id, other_id)


@pytest.mark.asyncio
async def test_non_owner_cannot_update_or_delete_shared_view(db_session):
    owner_id, project_id = await _seed_user_and_project(db_session)
    other_id = await _seed_user(db_session)
    svc = SavedViewService(db_session)
    shared = await svc.create(
        SavedViewCreate(
            name="Read-only For Others",
            project_id=project_id,
            filter_json=FilterSnapshot(kind="document"),
            is_shared=True,
        ),
        owner_id,
    )
    await db_session.commit()

    with pytest.raises(SavedViewNotFoundError):
        await svc.update(
            shared.id,
            SavedViewUpdate(name="Hijacked"),
            other_id,
        )
    with pytest.raises(SavedViewNotFoundError):
        await svc.delete(shared.id, other_id)

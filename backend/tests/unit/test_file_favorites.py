# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for the file-favourites module (W11 — file-manager cluster).

Covers the service layer end-to-end against a transaction-isolated
PostgreSQL session so the dead-code follow-up that re-introduced router +
service has at least one regression net before it gets composed into the
dashboard.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.file_favorites.service import (
    get_favorite,
    list_favorites,
    toggle_favorite,
    unstar,
)
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Transaction-isolated PostgreSQL session (rolled back on teardown)."""
    async with transactional_session() as s:
        yield s


async def _seed(session) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(
        email=f"fv-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Favourite Tester",
    )
    session.add(user)
    await session.flush()
    project = Project(name="FV Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    return user.id, project.id


@pytest.mark.asyncio
async def test_toggle_inserts_then_is_idempotent(db_session):
    user_id, project_id = await _seed(db_session)

    row1, created1 = await toggle_favorite(
        db_session,
        user_id=user_id,
        project_id=project_id,
        file_kind="document",
        file_id="doc-123",
    )
    assert created1 is True
    assert row1.pinned is False

    row2, created2 = await toggle_favorite(
        db_session,
        user_id=user_id,
        project_id=project_id,
        file_kind="document",
        file_id="doc-123",
    )
    assert created2 is False
    assert row2.id == row1.id


@pytest.mark.asyncio
async def test_pin_flag_updates_in_place(db_session):
    user_id, project_id = await _seed(db_session)
    row, _ = await toggle_favorite(
        db_session,
        user_id=user_id,
        project_id=project_id,
        file_kind="bim_model",
        file_id="bim-9",
    )
    assert row.pinned is False

    updated, created = await toggle_favorite(
        db_session,
        user_id=user_id,
        project_id=project_id,
        file_kind="bim_model",
        file_id="bim-9",
        pinned=True,
    )
    assert created is False
    assert updated.id == row.id
    assert updated.pinned is True


@pytest.mark.asyncio
async def test_list_returns_pinned_first(db_session):
    user_id, project_id = await _seed(db_session)
    await toggle_favorite(
        db_session,
        user_id=user_id,
        project_id=project_id,
        file_kind="document",
        file_id="d1",
    )
    await toggle_favorite(
        db_session,
        user_id=user_id,
        project_id=project_id,
        file_kind="document",
        file_id="d2",
        pinned=True,
    )
    rows = await list_favorites(db_session, user_id=user_id, project_id=project_id)
    assert len(rows) == 2
    assert rows[0].file_id == "d2"
    assert rows[0].pinned is True


@pytest.mark.asyncio
async def test_unstar_is_idempotent(db_session):
    user_id, project_id = await _seed(db_session)
    await toggle_favorite(
        db_session,
        user_id=user_id,
        project_id=project_id,
        file_kind="photo",
        file_id="p1",
    )
    deleted = await unstar(
        db_session,
        user_id=user_id,
        project_id=project_id,
        file_kind="photo",
        file_id="p1",
    )
    assert deleted is True
    # Second call: nothing left to delete.
    deleted2 = await unstar(
        db_session,
        user_id=user_id,
        project_id=project_id,
        file_kind="photo",
        file_id="p1",
    )
    assert deleted2 is False
    assert (
        await get_favorite(
            db_session,
            user_id=user_id,
            project_id=project_id,
            file_kind="photo",
            file_id="p1",
        )
        is None
    )


@pytest.mark.asyncio
async def test_unknown_kind_raises(db_session):
    user_id, project_id = await _seed(db_session)
    with pytest.raises(ValueError, match="Unknown favourite kind"):
        await toggle_favorite(
            db_session,
            user_id=user_id,
            project_id=project_id,
            file_kind="nonsense",
            file_id="x",
        )

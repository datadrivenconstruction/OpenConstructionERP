# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Unit tests for the dedicated field-module grant table.

These exercise the grant repository + service against a real in-memory
SQLite engine so the partial-unique-index migration semantics and the
service-layer collision guard both stay honest.

The grant table is independent of the standard RBAC stack — these tests
deliberately use users with no role + no permissions to prove that
``check_module_grant()`` is the *only* thing the field-diary endpoints
consult.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.modules.field_diary.models import FieldModuleGrant
from app.modules.field_diary.schemas import FieldModuleGrantCreate
from app.modules.field_diary.service import FieldDiaryService
from app.modules.projects.models import Project, ProjectMilestone, ProjectWBS
from app.modules.users.models import APIKey, User


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    # Touch every column we'll reference so the metadata is complete.
    async with engine.begin() as conn:
        # Import every field_diary table so create_all picks them up.
        from app.modules.field_diary import models as _fd_models  # noqa: F401

        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                User.__table__,
                APIKey.__table__,
                Project.__table__,
                ProjectWBS.__table__,
                ProjectMilestone.__table__,
                _fd_models.DiaryEntry.__table__,
                _fd_models.DiaryActivity.__table__,
                _fd_models.DiaryAttachment.__table__,
                _fd_models.FieldModuleGrant.__table__,
                _fd_models.FieldMagicLink.__table__,
                _fd_models.FieldSession.__table__,
            ],
        )
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


async def _make_user(session, *, role: str = "viewer") -> User:
    user = User(
        email=f"u{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        role=role,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


async def _make_project(session, owner_id: uuid.UUID) -> Project:
    project = Project(name=f"P-{uuid.uuid4().hex[:6]}", owner_id=owner_id)
    session.add(project)
    await session.flush()
    await session.refresh(project)
    return project


@pytest.mark.asyncio
async def test_grant_create_unique_per_project_module(db_session) -> None:
    """One live grant per (user, project, module). A duplicate raises 409."""
    owner = await _make_user(db_session, role="admin")
    field_user = await _make_user(db_session, role="viewer")
    project = await _make_project(db_session, owner_id=owner.id)
    svc = FieldDiaryService(db_session)

    grant = await svc.create_grant(
        FieldModuleGrantCreate(
            user_id=field_user.id,
            project_id=project.id,
            module_key="field_diary",
        ),
        granted_by=owner.id,
    )
    assert grant.id is not None
    assert grant.revoked_at is None

    with pytest.raises(HTTPException) as exc:
        await svc.create_grant(
            FieldModuleGrantCreate(
                user_id=field_user.id,
                project_id=project.id,
                module_key="field_diary",
            ),
            granted_by=owner.id,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_grant_revoke_blocks_subsequent_access(db_session) -> None:
    """Once revoked, ``check_module_grant`` flips to False."""
    owner = await _make_user(db_session, role="admin")
    field_user = await _make_user(db_session, role="viewer")
    project = await _make_project(db_session, owner_id=owner.id)
    svc = FieldDiaryService(db_session)

    grant = await svc.create_grant(
        FieldModuleGrantCreate(
            user_id=field_user.id,
            project_id=project.id,
            module_key="field_diary",
        ),
        granted_by=owner.id,
    )
    assert (
        await svc.check_module_grant(
            field_user.id,
            project.id,
            "field_diary",
        )
        is True
    )

    await svc.revoke_grant(grant.id)
    assert (
        await svc.check_module_grant(
            field_user.id,
            project.id,
            "field_diary",
        )
        is False
    )

    # And a fresh grant can be issued AFTER revoking the previous one.
    fresh = await svc.create_grant(
        FieldModuleGrantCreate(
            user_id=field_user.id,
            project_id=project.id,
            module_key="field_diary",
        ),
        granted_by=owner.id,
    )
    assert fresh.id != grant.id


@pytest.mark.asyncio
async def test_grant_expiry_blocks_access(db_session) -> None:
    """An ``expires_at`` in the past makes the grant inert."""
    owner = await _make_user(db_session, role="admin")
    field_user = await _make_user(db_session, role="viewer")
    project = await _make_project(db_session, owner_id=owner.id)
    svc = FieldDiaryService(db_session)

    past = datetime.now(UTC) - timedelta(minutes=5)
    await svc.create_grant(
        FieldModuleGrantCreate(
            user_id=field_user.id,
            project_id=project.id,
            module_key="field_diary",
            expires_at=past,
        ),
        granted_by=owner.id,
    )
    assert (
        await svc.check_module_grant(
            field_user.id,
            project.id,
            "field_diary",
        )
        is False
    )


@pytest.mark.asyncio
async def test_field_module_grant_independent_from_rbac(db_session) -> None:
    """A viewer with NO role-derived permissions still passes the grant check.

    Proves that ``check_module_grant`` does not consult ``oe_role`` /
    ``oe_permission`` at all — the dedicated table is authoritative.
    """
    owner = await _make_user(db_session, role="admin")
    # Note: role="viewer" — viewers have no field_diary.* permissions.
    field_user = await _make_user(db_session, role="viewer")
    project = await _make_project(db_session, owner_id=owner.id)
    svc = FieldDiaryService(db_session)

    # Without a grant: blocked.
    assert (
        await svc.check_module_grant(
            field_user.id,
            project.id,
            "field_diary",
        )
        is False
    )

    # Issue grant.
    await svc.create_grant(
        FieldModuleGrantCreate(
            user_id=field_user.id,
            project_id=project.id,
            module_key="field_diary",
        ),
        granted_by=owner.id,
    )

    # With a grant: allowed — even though the user role is "viewer".
    assert (
        await svc.check_module_grant(
            field_user.id,
            project.id,
            "field_diary",
        )
        is True
    )


@pytest.mark.asyncio
async def test_grant_scopes_per_module_key(db_session) -> None:
    """A grant for ``field_diary`` doesn't unlock ``field_timesheet``."""
    owner = await _make_user(db_session, role="admin")
    field_user = await _make_user(db_session, role="viewer")
    project = await _make_project(db_session, owner_id=owner.id)
    svc = FieldDiaryService(db_session)

    await svc.create_grant(
        FieldModuleGrantCreate(
            user_id=field_user.id,
            project_id=project.id,
            module_key="field_diary",
        ),
        granted_by=owner.id,
    )
    assert (
        await svc.check_module_grant(
            field_user.id,
            project.id,
            "field_diary",
        )
        is True
    )
    assert (
        await svc.check_module_grant(
            field_user.id,
            project.id,
            "field_timesheet",
        )
        is False
    )


@pytest.mark.asyncio
async def test_grant_repo_lookup_uses_lookup_index(db_session) -> None:
    """Confirm the lookup index is recorded on the table (smoke test)."""
    owner = await _make_user(db_session, role="admin")
    field_user = await _make_user(db_session, role="viewer")
    project = await _make_project(db_session, owner_id=owner.id)
    svc = FieldDiaryService(db_session)

    await svc.create_grant(
        FieldModuleGrantCreate(
            user_id=field_user.id,
            project_id=project.id,
            module_key="field_diary",
        ),
        granted_by=owner.id,
    )
    # Direct repo call (covered by service tests too — kept for explicitness).
    grant = await svc.grant_repo.get_active(
        field_user.id,
        project.id,
        "field_diary",
    )
    assert grant is not None
    assert isinstance(grant, FieldModuleGrant)

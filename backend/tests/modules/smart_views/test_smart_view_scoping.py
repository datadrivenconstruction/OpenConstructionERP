# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Smart Views scoping tests.

Cross-cuts the user-/project-/federation- scoping rules from the
service layer:

* User-scoped views are invisible to other users.
* Project-scoped views are visible to anyone who owns (or admins) the
  project — and only to them.
* Cross-project leakage is blocked at the list endpoint.
"""

from __future__ import annotations

import uuid

import pytest

# itsdangerous (share-link token signing) is not in the base or [dev]
# dependency closure, only arriving via fastapi[all]/starlette[full]. The
# smart_views service imports it at module top, so guard the whole module so a
# [dev]-only install (the CI test job) skips it cleanly instead of erroring
# during collection.
pytest.importorskip("itsdangerous", reason="itsdangerous is not in the [dev] install")

import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.smart_views.schemas import (
    SmartViewActionArgs,
    SmartViewCreate,
    SmartViewRule,
    SmartViewSelector,
)
from app.modules.smart_views.service import SmartViewService
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Transaction-isolated PostgreSQL session (rolled back on teardown)."""
    async with transactional_session() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        owner_a = User(
            id=uuid.uuid4(),
            email=f"a-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="A",
        )
        owner_b = User(
            id=uuid.uuid4(),
            email=f"b-{uuid.uuid4().hex[:6]}@test.io",
            hashed_password="x",
            full_name="B",
        )
        s.add_all([owner_a, owner_b])
        await s.flush()
        project_a = Project(
            id=uuid.uuid4(),
            name="Project A",
            owner_id=owner_a.id,
            currency="EUR",
        )
        project_b = Project(
            id=uuid.uuid4(),
            name="Project B",
            owner_id=owner_b.id,
            currency="EUR",
        )
        s.add_all([project_a, project_b])
        await s.commit()
        s.info["owner_a_id"] = owner_a.id
        s.info["owner_b_id"] = owner_b.id
        s.info["project_a_id"] = project_a.id
        s.info["project_b_id"] = project_b.id
        yield s


def _basic_rule() -> SmartViewRule:
    return SmartViewRule(
        id="r1",
        selector=SmartViewSelector(ifc_class="IfcWall"),
        action="hide",
        action_args=SmartViewActionArgs(),
        order=0,
    )


# ── 1. User-scoped views are invisible to other users ────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_user_scoped_view_invisible_to_other_users(
    session: AsyncSession,
) -> None:
    owner_a: uuid.UUID = session.info["owner_a_id"]
    owner_b: uuid.UUID = session.info["owner_b_id"]
    service = SmartViewService(session)

    # owner_a creates two user-scoped views.
    for n in ("private-1", "private-2"):
        await service.create_view(
            SmartViewCreate(
                scope_type="user",
                scope_id=owner_a,
                name=n,
                rules=[_basic_rule()],
            ),
            user_id=owner_a,
        )
    await session.commit()

    # owner_a sees both.
    a_list = await service.list_views(user_id=owner_a)
    assert {v.name for v in a_list} == {"private-1", "private-2"}

    # owner_b sees nothing.
    b_list = await service.list_views(user_id=owner_b)
    assert b_list == []


# ── 2. Project-scoped view is visible to the project owner ───────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_project_scoped_view_visible_to_project_owner(
    session: AsyncSession,
) -> None:
    owner_a: uuid.UUID = session.info["owner_a_id"]
    project_a: uuid.UUID = session.info["project_a_id"]
    service = SmartViewService(session)

    created = await service.create_view(
        SmartViewCreate(
            scope_type="project",
            scope_id=project_a,
            name="proj-A-shared",
            rules=[_basic_rule()],
        ),
        user_id=owner_a,
    )
    await session.commit()

    fetched = await service.get_view(created.id, user_id=owner_a)
    assert fetched.name == "proj-A-shared"

    listed = await service.list_views(user_id=owner_a)
    assert any(v.id == created.id for v in listed)


# ── 3. Project-scoped view is invisible to non-member ────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_project_scoped_view_invisible_to_non_member(
    session: AsyncSession,
) -> None:
    owner_a: uuid.UUID = session.info["owner_a_id"]
    owner_b: uuid.UUID = session.info["owner_b_id"]
    project_a: uuid.UUID = session.info["project_a_id"]
    service = SmartViewService(session)

    created = await service.create_view(
        SmartViewCreate(
            scope_type="project",
            scope_id=project_a,
            name="A-only",
            rules=[_basic_rule()],
        ),
        user_id=owner_a,
    )
    await session.commit()

    # owner_b cannot read A's project view.
    with pytest.raises(HTTPException) as exc:
        await service.get_view(created.id, user_id=owner_b)
    assert exc.value.status_code == 404

    # And it does not show up in B's list.
    b_list = await service.list_views(user_id=owner_b)
    assert not any(v.id == created.id for v in b_list)


# ── 4. Cross-project list does not leak ──────────────────────────────────


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_cross_project_list_does_not_leak(
    session: AsyncSession,
) -> None:
    owner_a: uuid.UUID = session.info["owner_a_id"]
    owner_b: uuid.UUID = session.info["owner_b_id"]
    project_a: uuid.UUID = session.info["project_a_id"]
    project_b: uuid.UUID = session.info["project_b_id"]
    service = SmartViewService(session)

    await service.create_view(
        SmartViewCreate(
            scope_type="project",
            scope_id=project_a,
            name="A-shared",
            rules=[_basic_rule()],
        ),
        user_id=owner_a,
    )
    await service.create_view(
        SmartViewCreate(
            scope_type="project",
            scope_id=project_b,
            name="B-shared",
            rules=[_basic_rule()],
        ),
        user_id=owner_b,
    )
    await service.create_view(
        SmartViewCreate(
            scope_type="user",
            scope_id=owner_a,
            name="A-private",
            rules=[_basic_rule()],
        ),
        user_id=owner_a,
    )
    await session.commit()

    a_names = {v.name for v in await service.list_views(user_id=owner_a)}
    b_names = {v.name for v in await service.list_views(user_id=owner_b)}

    # Owner A sees: their own user-scoped + their project-scoped.
    assert a_names == {"A-private", "A-shared"}
    # Owner B sees: only their project-scoped (no user view for B).
    assert b_names == {"B-shared"}


# ── 5. List filter by scope_type ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_filter_by_scope_type(session: AsyncSession) -> None:
    owner_a: uuid.UUID = session.info["owner_a_id"]
    project_a: uuid.UUID = session.info["project_a_id"]
    service = SmartViewService(session)

    await service.create_view(
        SmartViewCreate(
            scope_type="user",
            scope_id=owner_a,
            name="usr-1",
            rules=[_basic_rule()],
        ),
        user_id=owner_a,
    )
    await service.create_view(
        SmartViewCreate(
            scope_type="project",
            scope_id=project_a,
            name="prj-1",
            rules=[_basic_rule()],
        ),
        user_id=owner_a,
    )
    await session.commit()

    user_only = await service.list_views(user_id=owner_a, scope_type="user")
    proj_only = await service.list_views(user_id=owner_a, scope_type="project")
    assert {v.name for v in user_only} == {"usr-1"}
    assert {v.name for v in proj_only} == {"prj-1"}


# ── 6. List filter by scope_id (single project) ──────────────────────────


@pytest.mark.asyncio
async def test_list_filter_by_scope_id(session: AsyncSession) -> None:
    owner_a: uuid.UUID = session.info["owner_a_id"]
    project_a: uuid.UUID = session.info["project_a_id"]
    service = SmartViewService(session)

    await service.create_view(
        SmartViewCreate(
            scope_type="project",
            scope_id=project_a,
            name="prj-A1",
            rules=[_basic_rule()],
        ),
        user_id=owner_a,
    )
    await service.create_view(
        SmartViewCreate(
            scope_type="user",
            scope_id=owner_a,
            name="usr-1",
            rules=[_basic_rule()],
        ),
        user_id=owner_a,
    )
    await session.commit()

    only_proj_a = await service.list_views(
        user_id=owner_a,
        scope_type="project",
        scope_id=project_a,
    )
    assert {v.name for v in only_proj_a} == {"prj-A1"}


# ── 7. Federation scope without a federation row → 404 at create ─────────


@pytest.mark.asyncio
async def test_federation_scope_requires_federation_row(
    session: AsyncSession,
) -> None:
    owner_a: uuid.UUID = session.info["owner_a_id"]
    service = SmartViewService(session)

    with pytest.raises(HTTPException) as exc:
        await service.create_view(
            SmartViewCreate(
                scope_type="federation",
                scope_id=uuid.uuid4(),  # does not exist
                name="ghost",
                rules=[_basic_rule()],
            ),
            user_id=owner_a,
        )
    assert exc.value.status_code in (403, 404)

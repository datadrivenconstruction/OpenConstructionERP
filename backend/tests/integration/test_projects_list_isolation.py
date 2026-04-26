"""Project list scoping (BUG-RBAC04 regression).

The QA report ``BUGS_R2_R3_R4_2026_04_25.md`` flagged that a self-registered
viewer could ``GET /api/v1/projects/`` and see every project on the
instance. The repository layer already filters by ``owner_id`` when the
caller is not admin (see ``ProjectRepository.list_for_user``), so the
fix in v2.5.x was implicit. These tests pin the behaviour so it cannot
regress silently.

Three cases covered:
* viewer A creates a project → viewer B (different account) does not see it
* admin always sees both A's and B's projects
* viewer cannot read another user's project by direct ``GET /{id}``
  (this part is enforced in the router; here we cover the repository-list
  scope. The router ownership check has its own test elsewhere.)
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@pytest_asyncio.fixture
async def session():
    """Per-test fresh SQLite DB with users + projects tables registered."""
    tmp_db = Path(tempfile.mkdtemp()) / "list_iso.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401
    from app.database import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s

    await engine.dispose()
    try:
        tmp_db.unlink(missing_ok=True)
        tmp_db.parent.rmdir()
    except OSError:
        pass


def _new_user(email: str):
    """Build a User row directly — bypassing the registration mode test surface."""
    from app.modules.users.models import User
    from app.modules.users.service import hash_password

    return User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password("ListIsoPass1234!"),
        full_name="List Iso",
        role="viewer",
        locale="en",
        is_active=True,
        metadata_={},
    )


def _new_project(owner_id: uuid.UUID, name: str):
    from app.modules.projects.models import Project

    return Project(
        id=uuid.uuid4(),
        owner_id=owner_id,
        name=name,
        status="active",
    )


@pytest.mark.asyncio
async def test_viewer_only_sees_own_projects(session):
    """Two viewers, two projects, each sees only their own."""
    from app.modules.projects.repository import ProjectRepository

    user_a = _new_user(f"a-{uuid.uuid4().hex[:6]}@iso.io")
    user_b = _new_user(f"b-{uuid.uuid4().hex[:6]}@iso.io")
    session.add_all([user_a, user_b])
    await session.flush()

    proj_a = _new_project(user_a.id, "Project A")
    proj_b = _new_project(user_b.id, "Project B")
    session.add_all([proj_a, proj_b])
    await session.commit()

    repo = ProjectRepository(session)

    a_list, a_total = await repo.list_for_user(user_a.id, is_admin=False)
    b_list, b_total = await repo.list_for_user(user_b.id, is_admin=False)

    assert a_total == 1
    assert {p.id for p in a_list} == {proj_a.id}
    assert b_total == 1
    assert {p.id for p in b_list} == {proj_b.id}


@pytest.mark.asyncio
async def test_admin_sees_all_projects(session):
    """is_admin=True bypasses the owner_id filter — by design."""
    from app.modules.projects.repository import ProjectRepository

    user_a = _new_user(f"a-{uuid.uuid4().hex[:6]}@iso.io")
    user_b = _new_user(f"b-{uuid.uuid4().hex[:6]}@iso.io")
    admin = _new_user(f"admin-{uuid.uuid4().hex[:6]}@iso.io")
    admin.role = "admin"
    session.add_all([user_a, user_b, admin])
    await session.flush()

    proj_a = _new_project(user_a.id, "Project A")
    proj_b = _new_project(user_b.id, "Project B")
    session.add_all([proj_a, proj_b])
    await session.commit()

    repo = ProjectRepository(session)
    admin_list, admin_total = await repo.list_for_user(admin.id, is_admin=True)

    assert admin_total == 2
    assert {p.id for p in admin_list} == {proj_a.id, proj_b.id}


@pytest.mark.asyncio
async def test_viewer_with_no_projects_sees_empty(session):
    """A freshly self-registered viewer with no projects sees none.

    This is the QA-reported scenario: the new account ``GET /projects/``
    must not list seed projects belonging to other users.
    """
    from app.modules.projects.repository import ProjectRepository

    seed_owner = _new_user(f"seed-{uuid.uuid4().hex[:6]}@iso.io")
    seed_owner.role = "admin"
    fresh_viewer = _new_user(f"fresh-{uuid.uuid4().hex[:6]}@iso.io")
    session.add_all([seed_owner, fresh_viewer])
    await session.flush()

    # 5 seed projects owned by an admin (mimicking the demo seed)
    for i in range(5):
        session.add(_new_project(seed_owner.id, f"Seed Project {i}"))
    await session.commit()

    repo = ProjectRepository(session)
    viewer_list, viewer_total = await repo.list_for_user(
        fresh_viewer.id, is_admin=False
    )

    assert viewer_total == 0
    assert viewer_list == []


@pytest.mark.asyncio
async def test_archive_excluded_by_default_in_user_scope(session):
    """exclude_archived=True (the default) hides soft-deleted projects.

    Confirms the scoping logic still respects the archived filter when the
    caller is non-admin — i.e. the security filter and the soft-delete
    filter compose, not override.
    """
    from app.modules.projects.repository import ProjectRepository

    user = _new_user(f"u-{uuid.uuid4().hex[:6]}@iso.io")
    session.add(user)
    await session.flush()

    active = _new_project(user.id, "Active")
    archived = _new_project(user.id, "Archived")
    archived.status = "archived"
    session.add_all([active, archived])
    await session.commit()

    repo = ProjectRepository(session)
    visible, total = await repo.list_for_user(user.id, is_admin=False)

    assert total == 1
    assert {p.id for p in visible} == {active.id}

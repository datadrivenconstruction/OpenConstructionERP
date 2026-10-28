# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Partner-pack project scoping: an active pack shows its own + untagged projects.

When a pack is active the workspace presents a focused view. Projects tagged
with the active pack's slug AND projects that carry no pack tag at all are
shown. Only projects tagged with a *different* pack are hidden. This prevents
pre-existing projects from silently disappearing when a pack is first
activated. Deactivating the pack untags its projects so the normal listing
returns. These tests run against the real embedded PostgreSQL the suite boots,
so the ``metadata_ ->> 'partner_pack'`` JSON filter is exercised against an
actual database, not a mock.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from tests._pg import transactional_session

PACK_SLUG = "batimatech-ca"
OTHER_PACK_SLUG = "other-partner"

ADMIN_ID = uuid.uuid4()
REGULAR_ID = uuid.uuid4()

P_TAGGED_ADMIN = uuid.uuid4()
P_UNTAGGED_ADMIN = uuid.uuid4()
P_TAGGED_REGULAR = uuid.uuid4()
P_OTHER_PACK_ADMIN = uuid.uuid4()
P_NULL_META_ADMIN = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    """A PG session seeded with one admin + one regular user and five projects.

    * P_TAGGED_ADMIN      - owner=admin,   metadata partner_pack=batimatech-ca
    * P_UNTAGGED_ADMIN    - owner=admin,   metadata={} (no pack tag)
    * P_TAGGED_REGULAR    - owner=regular, metadata partner_pack=batimatech-ca
    * P_OTHER_PACK_ADMIN  - owner=admin,   metadata partner_pack=other-partner
    * P_NULL_META_ADMIN   - owner=admin,   metadata_=None
    """
    async with transactional_session() as s:
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        s.add(User(id=ADMIN_ID, email="admin@test.io", hashed_password="x", full_name="Admin"))
        s.add(User(id=REGULAR_ID, email="reg@test.io", hashed_password="x", full_name="Reg"))
        await s.flush()

        s.add(
            Project(
                id=P_TAGGED_ADMIN,
                name="Tagged Admin",
                owner_id=ADMIN_ID,
                currency="CAD",
                status="active",
                metadata_={"partner_pack": PACK_SLUG},
            )
        )
        s.add(
            Project(
                id=P_UNTAGGED_ADMIN,
                name="Untagged Admin",
                owner_id=ADMIN_ID,
                currency="EUR",
                status="active",
                metadata_={},
            )
        )
        s.add(
            Project(
                id=P_TAGGED_REGULAR,
                name="Tagged Regular",
                owner_id=REGULAR_ID,
                currency="CAD",
                status="active",
                metadata_={"partner_pack": PACK_SLUG},
            )
        )
        s.add(
            Project(
                id=P_OTHER_PACK_ADMIN,
                name="Other Pack Admin",
                owner_id=ADMIN_ID,
                currency="USD",
                status="active",
                metadata_={"partner_pack": OTHER_PACK_SLUG},
            )
        )
        s.add(
            Project(
                id=P_NULL_META_ADMIN,
                name="Null Metadata Admin",
                owner_id=ADMIN_ID,
                currency="EUR",
                status="active",
                metadata_=None,
            )
        )
        await s.commit()
        yield s


def _ids(projects) -> set[uuid.UUID]:  # noqa: ANN001
    return {p.id for p in projects}


async def _async_true(*_args, **_kwargs) -> bool:  # noqa: ANN002, ANN003
    return True


@pytest.mark.asyncio
async def test_no_active_pack_admin_sees_all(session, monkeypatch) -> None:
    """With no pack active, the admin listing is unscoped (sees all five)."""
    monkeypatch.setattr("app.core.partner_pack.scope.active_pack_slug", lambda: None)
    from app.modules.projects.repository import ProjectRepository

    repo = ProjectRepository(session)
    projects, total = await repo.list_for_user(ADMIN_ID, is_admin=True)
    ids = _ids(projects)
    assert {P_TAGGED_ADMIN, P_UNTAGGED_ADMIN, P_TAGGED_REGULAR, P_OTHER_PACK_ADMIN, P_NULL_META_ADMIN} <= ids
    assert total >= 5


@pytest.mark.asyncio
async def test_active_pack_shows_tagged_and_untagged_hides_other_pack(session, monkeypatch) -> None:
    """An active pack shows its own projects AND untagged projects, hides other packs."""
    monkeypatch.setattr("app.core.partner_pack.scope.active_pack_slug", lambda: PACK_SLUG)
    from app.modules.projects.repository import ProjectRepository

    repo = ProjectRepository(session)
    projects, total = await repo.list_for_user(ADMIN_ID, is_admin=True)
    ids = _ids(projects)

    # Both tagged projects are visible (admin sees all tagged, regardless of owner).
    assert P_TAGGED_ADMIN in ids
    assert P_TAGGED_REGULAR in ids
    # Untagged projects (no pack tag) remain visible - they were created before
    # any pack was activated and must not silently disappear.
    assert P_UNTAGGED_ADMIN in ids
    # Projects with NULL metadata_ also remain visible.
    assert P_NULL_META_ADMIN in ids
    # Projects tagged with a DIFFERENT pack are hidden.
    assert P_OTHER_PACK_ADMIN not in ids
    assert total == 4


@pytest.mark.asyncio
async def test_active_pack_scopes_regular_user_to_owned_and_visible(session, monkeypatch) -> None:
    """A regular user sees only projects they own AND that are not tagged with another pack."""
    monkeypatch.setattr("app.core.partner_pack.scope.active_pack_slug", lambda: PACK_SLUG)
    from app.modules.projects.repository import ProjectRepository

    repo = ProjectRepository(session)
    projects, total = await repo.list_for_user(REGULAR_ID, is_admin=False)
    ids = _ids(projects)

    # Regular user only owns P_TAGGED_REGULAR; the pack scope does not add
    # other people's untagged projects - ownership still gates access.
    assert ids == {P_TAGGED_REGULAR}
    assert total == 1


@pytest.mark.asyncio
async def test_untagging_makes_project_visible_as_untagged(session, monkeypatch) -> None:
    """Removing the pack tag (the deactivation effect) keeps a project visible.

    Simulates what ``unapply`` does (clears ``metadata_['partner_pack']``) and
    confirms the now-untagged project is still visible because untagged projects
    are never hidden by pack scoping.
    """
    from app.modules.projects.models import Project
    from app.modules.projects.repository import ProjectRepository

    # Untag the admin's tagged project, mirroring _untag_pack_projects.
    proj = await session.get(Project, P_TAGGED_ADMIN)
    md = dict(proj.metadata_ or {})
    md.pop("partner_pack", None)
    proj.metadata_ = md
    await session.flush()

    monkeypatch.setattr("app.core.partner_pack.scope.active_pack_slug", lambda: PACK_SLUG)
    repo = ProjectRepository(session)
    projects, _ = await repo.list_for_user(ADMIN_ID, is_admin=True)
    ids = _ids(projects)

    # The freshly untagged project is now visible as an untagged project.
    assert P_TAGGED_ADMIN in ids
    # The still-tagged one remains visible too.
    assert P_TAGGED_REGULAR in ids
    # Other-pack project is still hidden.
    assert P_OTHER_PACK_ADMIN not in ids


@pytest.mark.asyncio
async def test_dashboard_rollup_no_pack_sees_all(session, monkeypatch) -> None:
    """With no pack active, the dashboard rollup access list is unscoped."""
    monkeypatch.setattr("app.core.partner_pack.scope.active_pack_slug", lambda: None)
    monkeypatch.setattr("app.modules.dashboard.service.is_admin", _async_true)
    from app.modules.dashboard.service import accessible_projects

    projects = await accessible_projects(session, str(ADMIN_ID))
    ids = _ids(projects)
    assert {P_TAGGED_ADMIN, P_UNTAGGED_ADMIN, P_TAGGED_REGULAR, P_OTHER_PACK_ADMIN, P_NULL_META_ADMIN} <= ids


@pytest.mark.asyncio
async def test_dashboard_rollup_active_pack_hides_other_pack_only(session, monkeypatch) -> None:
    """The dashboard rollup hides only projects tagged with a different pack.

    Without ``scope_project_query`` in ``accessible_projects`` the rollup widgets
    (boq_summary, budget_variance, ...) would aggregate every non-archived project,
    including those from other packs. The scoping hides other-pack projects but
    keeps untagged ones visible so pre-existing work is not lost.
    """
    monkeypatch.setattr("app.core.partner_pack.scope.active_pack_slug", lambda: PACK_SLUG)
    monkeypatch.setattr("app.modules.dashboard.service.is_admin", _async_true)
    from app.modules.dashboard.service import accessible_projects

    projects = await accessible_projects(session, str(ADMIN_ID))
    ids = _ids(projects)
    # Pack-tagged projects remain.
    assert P_TAGGED_ADMIN in ids
    assert P_TAGGED_REGULAR in ids
    # Untagged projects remain visible (pre-existing work).
    assert P_UNTAGGED_ADMIN in ids
    assert P_NULL_META_ADMIN in ids
    # Other-pack project is hidden from the rollup.
    assert P_OTHER_PACK_ADMIN not in ids

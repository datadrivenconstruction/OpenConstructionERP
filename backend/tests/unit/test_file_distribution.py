# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tests for the file-distribution (W10) module.

Covers both sub-features:

* Distribution lists:
  - create list with 3 members → list/get returns them
  - add / remove member; duplicate email blocked
* Subscriptions:
  - subscribe a user to a project's documents → list returns it
  - unsubscribe → list is empty
  - duplicate (project,kind,email) raises conflict
  - unknown notify_on event surfaced as validation error
* Cross-project search:
  - canonical_name match across two projects returns hits
  - graceful fallback when ``file_search`` content index is absent
    (mocked via a service-level patch)
  - empty / whitespace query → no hits, never raises

Like ``test_file_saved_views.py``, we build only the tables this
suite needs against a per-test temp SQLite so the mapper-init flake
that hits suites going through ``create_app`` + module-loader does
not apply here.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-file-dist-"))
_TMP_DB = _TMP_DIR / "file_distribution.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base  # noqa: E402
from app.modules.documents.models import Document  # noqa: E402
from app.modules.file_distribution.models import (  # noqa: E402
    FileDistributionList,
    FileDistributionMember,
    FileDistributionSubscription,
)
from app.modules.file_distribution.schemas import (  # noqa: E402
    DistributionListCreate,
    DistributionMemberCreate,
    SubscriptionCreate,
)
from app.modules.file_distribution.service import (  # noqa: E402
    CrossProjectSearchService,
    DistributionConflictError,
    DistributionListService,
    DistributionValidationError,
    SubscriptionService,
)
from app.modules.projects.models import Project  # noqa: E402
from app.modules.users.models import User  # noqa: E402

# ── DB fixture ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    db_path = _TMP_DIR / f"dist-{uuid.uuid4().hex[:8]}.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path.as_posix()}",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            Base.metadata.create_all,
            tables=[
                User.__table__,
                Project.__table__,
                Document.__table__,
                FileDistributionList.__table__,
                FileDistributionMember.__table__,
                FileDistributionSubscription.__table__,
            ],
        )
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


async def _seed_user_and_project(
    session,
    *,
    project_name: str = "Dist Project",
) -> tuple[uuid.UUID, uuid.UUID]:
    user = User(
        email=f"dist-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Distribution Tester",
    )
    session.add(user)
    await session.flush()
    project = Project(name=project_name, owner_id=user.id)
    session.add(project)
    await session.flush()
    return user.id, project.id


# ── Distribution lists ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_list_with_three_members_then_list(db_session):
    user_id, project_id = await _seed_user_and_project(db_session)
    svc = DistributionListService(db_session)
    payload = DistributionListCreate(
        name="Structural Review",
        project_id=project_id,
        description="Structural drawings for review",
        is_shared=False,
        members=[
            DistributionMemberCreate(
                email="lena@example.com",
                display_name="Lena Schmidt",
                role="for_review",
            ),
            DistributionMemberCreate(
                email="raj@example.com",
                display_name="Raj Patel",
                role="for_review",
            ),
            DistributionMemberCreate(
                email="ana@example.com",
                display_name="Ana Costa",
                role="fyi",
            ),
        ],
    )
    row = await svc.create(payload, user_id)
    await db_session.commit()
    assert len(row.members) == 3
    emails = {m.email for m in row.members}
    assert emails == {"lena@example.com", "raj@example.com", "ana@example.com"}
    assert {m.role for m in row.members} == {"for_review", "fyi"}

    listed = await svc.list_for_user(user_id=user_id, project_id=project_id)
    assert any(r.id == row.id for r in listed)


@pytest.mark.asyncio
async def test_add_and_remove_member(db_session):
    user_id, project_id = await _seed_user_and_project(db_session)
    svc = DistributionListService(db_session)
    row = await svc.create(
        DistributionListCreate(name="MEP Coordination", project_id=project_id),
        user_id,
    )
    await db_session.commit()
    assert row.members == []

    member = await svc.add_member(
        row.id,
        DistributionMemberCreate(email="mep@example.com", role="for_review"),
        user_id,
    )
    await db_session.commit()
    # Snapshot ids BEFORE the conflict branch — that branch rolls the
    # session back which expires all attached instances, so a later
    # ``member.id`` access would trigger a lazy refresh outside the
    # greenlet context.
    member_id = member.id
    row_id = row.id
    assert member.email == "mep@example.com"

    # Duplicate email on the same list → conflict.
    with pytest.raises(DistributionConflictError):
        await svc.add_member(
            row_id,
            DistributionMemberCreate(email="MEP@Example.com"),
            user_id,
        )

    await svc.remove_member(row_id, member_id, user_id)
    await db_session.commit()
    refreshed = await svc.get(row.id, user_id)
    await db_session.refresh(refreshed, attribute_names=["members"])
    assert refreshed.members == []


# ── Subscriptions ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_subscribe_and_unsubscribe(db_session):
    user_id, project_id = await _seed_user_and_project(db_session)
    svc = SubscriptionService(db_session)

    sub = await svc.create(
        SubscriptionCreate(
            project_id=project_id,
            file_kind="document",
            subscriber_email="reviewer@example.com",
            subscriber_user_id=user_id,
            notify_on=["created", "updated"],
        ),
        user_id,
    )
    await db_session.commit()
    assert sub.file_kind == "document"
    assert sub.notify_on == ["created", "updated"]
    # Snapshot the id BEFORE the conflict branch's rollback expires
    # the instance.
    sub_id = sub.id

    listed = await svc.list_for_project(project_id=project_id, user_id=user_id)
    assert any(r.id == sub_id for r in listed)

    # Duplicate (project_id, file_kind, email) → conflict.
    with pytest.raises(DistributionConflictError):
        await svc.create(
            SubscriptionCreate(
                project_id=project_id,
                file_kind="document",
                subscriber_email="reviewer@example.com",
            ),
            user_id,
        )

    await svc.delete(sub_id, user_id)
    await db_session.commit()
    after = await svc.list_for_project(project_id=project_id, user_id=user_id)
    assert all(r.id != sub_id for r in after)


@pytest.mark.asyncio
async def test_subscribe_rejects_unknown_notify_event(db_session):
    user_id, project_id = await _seed_user_and_project(db_session)
    svc = SubscriptionService(db_session)
    with pytest.raises(DistributionValidationError):
        await svc.create(
            SubscriptionCreate(
                project_id=project_id,
                file_kind="document",
                subscriber_email="bad@example.com",
                notify_on=["created", "wat"],
            ),
            user_id,
        )


# ── Cross-project search ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_finds_documents_across_projects(db_session):
    user_id, project_a = await _seed_user_and_project(
        db_session,
        project_name="Project Alpha",
    )
    _, project_b = await _seed_user_and_project(
        db_session,
        project_name="Project Beta",
    )

    db_session.add(
        Document(
            project_id=project_a,
            name="Foundation Plan 2026.pdf",
            uploaded_by=str(user_id),
            file_path="/tmp/a.pdf",
        ),
    )
    db_session.add(
        Document(
            project_id=project_b,
            name="Foundation Reinforcement Schedule.xlsx",
            uploaded_by=str(user_id),
            file_path="/tmp/b.xlsx",
        ),
    )
    db_session.add(
        Document(
            project_id=project_a,
            name="Site Photos.zip",
            uploaded_by=str(user_id),
            file_path="/tmp/c.zip",
        ),
    )
    await db_session.commit()

    svc = CrossProjectSearchService(db_session)
    # Force the content-index path off so this test is deterministic
    # regardless of whether file_search ships in this build.
    svc._content_index_available = False

    hits, used_index = await svc.search(
        q="Foundation",
        allowed_project_ids=[project_a, project_b],
        kinds=["document"],
    )
    assert used_index is False
    # Both Foundation* documents are returned; the Site Photos one is not.
    names = {h.canonical_name for h in hits}
    assert "Foundation Plan 2026.pdf" in names
    assert "Foundation Reinforcement Schedule.xlsx" in names
    assert "Site Photos.zip" not in names

    # Cross-project: every hit MUST belong to one of the two seeded
    # projects (and we got hits from BOTH, proving cross-project).
    project_ids = {h.project_id for h in hits}
    assert project_a in project_ids
    assert project_b in project_ids

    # Project names are populated.
    for h in hits:
        if h.project_id == project_a:
            assert h.project_name == "Project Alpha"
        else:
            assert h.project_name == "Project Beta"


@pytest.mark.asyncio
async def test_search_falls_back_when_file_search_absent(db_session, monkeypatch):
    """If the optional file_search module can't be probed, we still
    return canonical_name matches and flag used_content_index=False."""
    user_id, project_id = await _seed_user_and_project(
        db_session,
        project_name="Fallback Project",
    )
    db_session.add(
        Document(
            project_id=project_id,
            name="Specification Volume 2.pdf",
            uploaded_by=str(user_id),
            file_path="/tmp/spec.pdf",
        ),
    )
    await db_session.commit()

    svc = CrossProjectSearchService(db_session)

    async def _no_index(_self):
        return False

    monkeypatch.setattr(
        CrossProjectSearchService,
        "_has_content_index",
        _no_index,
    )

    hits, used_index = await svc.search(
        q="specification",
        allowed_project_ids=[project_id],
        kinds=["document"],
    )
    assert used_index is False
    assert len(hits) == 1
    assert hits[0].canonical_name == "Specification Volume 2.pdf"
    assert hits[0].snippet == ""


@pytest.mark.asyncio
async def test_search_empty_query_returns_no_hits(db_session):
    _, project_id = await _seed_user_and_project(
        db_session,
        project_name="Empty Q Project",
    )
    svc = CrossProjectSearchService(db_session)
    svc._content_index_available = False
    hits, _ = await svc.search(
        q="   ",
        allowed_project_ids=[project_id],
        kinds=["document"],
    )
    assert hits == []

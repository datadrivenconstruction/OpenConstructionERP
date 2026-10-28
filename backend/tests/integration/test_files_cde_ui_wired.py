# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the Files CDE UI splice + W3/W10 hooks.

Covers the v3.12.0 Stream-E deliverables that the unit suites do not:

* SavedViewsRail / TagFilterFacet are spliced into the file manager,
  but the underlying CRUD must keep working — we exercise the service
  surfaces end-to-end so a future regression on those services
  surfaces here too (the FE wiring is React; covered by the existing
  vitest suites).
* ``POST /v1/file-versions/{id}/restore/`` — restoring a historical
  row demotes the prior current and promotes the target.
* :func:`purge_expired_trash` — only rows past their retention window
  are hard-deleted; younger rows stay put.
* :func:`on_file_new_revision` — every active subscription on a
  matching project + kind receives an in-app notification when a
  new version supersedes the current row.

The suite runs on a transaction-isolated PostgreSQL session (rolled back on
teardown by ``tests._pg.transactional_session``) so it stays insulated from the
FastAPI lifespan / module-loader mapper-init flake.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.file_distribution.schemas import SubscriptionCreate
from app.modules.file_distribution.service import (
    SubscriptionService,
    on_file_new_revision,
)
from app.modules.file_saved_views.schemas import (
    FilterSnapshot,
    SavedViewCreate,
)
from app.modules.file_saved_views.service import SavedViewService
from app.modules.file_tags.schemas import TagCreate
from app.modules.file_tags.service import (
    assign_tag,
    create_tag,
    tags_for_file,
)
from app.modules.file_trash.models import FileTrash
from app.modules.file_trash.service import (
    FileTrashService,
    purge_expired_trash,
)
from app.modules.file_versions.models import FileVersion
from app.modules.file_versions.schemas import FileVersionCreate
from app.modules.file_versions.service import FileVersionService
from app.modules.notifications.models import Notification
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

# ── DB fixture ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """Transaction-isolated PostgreSQL session (rolled back on teardown)."""
    async with transactional_session() as session:
        yield session


async def _seed_user_and_project(
    session: AsyncSession,
    *,
    project_name: str = "CDE Suite",
) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert one User + one Project and return their ids."""
    user = User(
        email=f"cde-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="CDE Tester",
        role="admin",
    )
    session.add(user)
    await session.flush()
    project = Project(name=project_name, owner_id=user.id)
    session.add(project)
    await session.flush()
    return user.id, project.id


# ── SavedViews CRUD smoke (unchanged after splice) ─────────────────────────


@pytest.mark.asyncio
async def test_saved_view_crud_round_trip_survives_splice(
    db_session: AsyncSession,
) -> None:
    """SavedViewsRail relies on this surface — keep it green."""
    user_id, project_id = await _seed_user_and_project(db_session)
    svc = SavedViewService(db_session)

    created = await svc.create(
        SavedViewCreate(
            name="Structural Review",
            project_id=project_id,
            filter_json=FilterSnapshot(
                kind="sheet",
                q="S-",
                sort="modified",
                tag_ids=[],
            ),
            is_pinned=True,
        ),
        user_id=user_id,
    )
    await db_session.commit()
    assert created.is_pinned is True
    assert created.filter_json["kind"] == "sheet"

    listing = await svc.list_views(user_id=user_id, project_id=project_id)
    assert any(v.id == created.id for v in listing)

    # Saved-view application (``use``) bumps the use_count — the FE
    # rail uses this to sort the most-recent at the top.
    bumped = await svc.use(created.id, user_id)
    await db_session.commit()
    assert bumped.use_count == 1
    assert bumped.last_used_at is not None


# ── Tag assignment via API still works after splice ────────────────────────


@pytest.mark.asyncio
async def test_tag_assign_and_lookup_after_splice(
    db_session: AsyncSession,
) -> None:
    """TagFilterFacet relies on the assign + tags_for_file path."""
    user_id, project_id = await _seed_user_and_project(db_session)
    tag = await create_tag(
        db_session,
        TagCreate(
            project_id=project_id,
            display_name="Structural",
            color="#94a3b8",
            category="discipline",
        ),
        user_id=user_id,
    )
    await db_session.commit()
    assert tag.display_name == "Structural"

    # Assign the tag to two file ids — same kind, different ids.
    file_id_a = uuid.uuid4().hex
    file_id_b = uuid.uuid4().hex
    result = await assign_tag(
        db_session,
        project_id=project_id,
        tag_id=tag.id,
        file_kind="document",
        file_ids=[file_id_a, file_id_b],
        user_id=user_id,
    )
    await db_session.commit()
    assert result.changed == 2
    assert result.already_done == 0

    # Per-file lookup — the FE TagFilterFacet uses this exact endpoint
    # to populate the badges next to file rows.
    tags_for_a = await tags_for_file(
        db_session,
        project_id=project_id,
        file_kind="document",
        file_id=file_id_a,
    )
    assert [t.id for t in tags_for_a] == [tag.id]


# ── Version restore round-trip (W1) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_version_restore_demotes_prior_current(
    db_session: AsyncSession,
) -> None:
    """``POST /v1/file-versions/{id}/restore/`` flips the chain head."""
    user_id, project_id = await _seed_user_and_project(db_session)
    svc = FileVersionService(db_session)
    file_id = uuid.uuid4().hex

    v1 = await svc.register_new_version(
        FileVersionCreate(
            project_id=project_id,
            file_kind="document",
            file_id=file_id,
            canonical_name="contract.pdf",
            file_size=1234,
        ),
        uploaded_by_id=user_id,
    )
    v2 = await svc.register_new_version(
        FileVersionCreate(
            project_id=project_id,
            file_kind="document",
            file_id=file_id,
            canonical_name="contract.pdf",
            file_size=2345,
        ),
        uploaded_by_id=user_id,
    )
    await db_session.commit()
    assert v1.version_number == 1
    assert v2.version_number == 2
    assert v2.is_current is True

    # Restore v1. v1 becomes current; v2 demoted with a fresh
    # ``superseded_at`` + back-pointer.
    restored = await svc.restore_version(v1.id, actor_id=user_id)
    await db_session.commit()
    assert restored.id == v1.id
    assert restored.is_current is True

    # Re-fetch v2 and assert it was demoted in the same transaction.
    refreshed_v2 = await db_session.get(FileVersion, v2.id)
    assert refreshed_v2 is not None
    assert refreshed_v2.is_current is False
    assert refreshed_v2.superseded_by_id == v1.id


# ── Retention purge job (W3) ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_purge_expired_trash_only_deletes_expired_rows(
    db_session: AsyncSession,
) -> None:
    """Rows past ``trashed_at + retention_days`` are purged; others stay."""
    user_id, project_id = await _seed_user_and_project(db_session)
    svc = FileTrashService(db_session)

    # Two trash rows — one trashed 31 days ago with 30-day retention,
    # one trashed yesterday. Only the older row should disappear after
    # the purge tick.
    # ``kind`` is arbitrary here - this covers the retention window, not
    # the kind - but a caller-supplied snapshot has to carry the kind's
    # NOT NULL columns or ``soft_delete`` refuses it, on the grounds that
    # such a row could never be restored. For a report that is
    # ``project_id``, ``report_type``, ``title`` and ``generated_at``.
    def _report_snapshot(name: str) -> dict:
        return {
            "name": name,
            "size_bytes": 4096,
            "project_id": str(project_id),
            "report_type": "manual",
            "title": name,
            "generated_at": "2026-01-01T00:00:00+00:00",
        }

    old = await svc.soft_delete(
        project_id=project_id,
        kind="report",
        original_id=uuid.uuid4().hex,
        canonical_name="ancient.pdf",
        payload=_report_snapshot("ancient.pdf"),
        retention_days=30,
        actor_id=user_id,
    )
    young = await svc.soft_delete(
        project_id=project_id,
        kind="report",
        original_id=uuid.uuid4().hex,
        canonical_name="fresh.pdf",
        payload=_report_snapshot("fresh.pdf"),
        retention_days=30,
        actor_id=user_id,
    )
    # Back-date the older row so its retention window has lapsed.
    old.trashed_at = datetime.now(UTC) - timedelta(days=31)
    await db_session.flush()
    await db_session.commit()

    purged = await purge_expired_trash(db_session)
    await db_session.commit()
    assert purged == 1

    survivors = (await db_session.execute(select(FileTrash).where(FileTrash.project_id == project_id))).scalars().all()
    assert {r.id for r in survivors} == {young.id}


# ── Subscription notification fan-out on new revision (W10) ────────────────


@pytest.mark.asyncio
async def test_on_file_new_revision_notifies_active_subscribers(
    db_session: AsyncSession,
) -> None:
    """A new version supersedes the prior current → matching subs notified."""
    user_id, project_id = await _seed_user_and_project(db_session)

    # Second user — the subscriber. The author is also a notification
    # candidate but the subscription targets the second user
    # explicitly so we can assert delivery to the right uid.
    subscriber = User(
        email=f"sub-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Subscriber",
        role="editor",
    )
    db_session.add(subscriber)
    await db_session.flush()

    sub_svc = SubscriptionService(db_session)
    await sub_svc.create(
        SubscriptionCreate(
            project_id=project_id,
            file_kind="document",
            subscriber_email=subscriber.email,
            subscriber_user_id=subscriber.id,
            notify_on=["created", "updated", "deleted"],
            active=True,
        ),
        user_id=subscriber.id,
    )
    await db_session.commit()

    svc = FileVersionService(db_session)
    file_id = uuid.uuid4().hex

    # v1 doesn't fan out — the hook only fires on a true supersede.
    await svc.register_new_version(
        FileVersionCreate(
            project_id=project_id,
            file_kind="document",
            file_id=file_id,
            canonical_name="spec.pdf",
            file_size=1024,
        ),
        uploaded_by_id=user_id,
    )
    await db_session.commit()
    first_pass = (
        (
            await db_session.execute(
                select(Notification).where(Notification.user_id == subscriber.id),
            )
        )
        .scalars()
        .all()
    )
    assert first_pass == []

    # v2 supersedes v1 → exactly one notification for the subscriber.
    await svc.register_new_version(
        FileVersionCreate(
            project_id=project_id,
            file_kind="document",
            file_id=file_id,
            canonical_name="spec.pdf",
            file_size=2048,
            notes="Reissued for tender",
        ),
        uploaded_by_id=user_id,
    )
    await db_session.commit()

    notes = (
        (
            await db_session.execute(
                select(Notification).where(Notification.user_id == subscriber.id),
            )
        )
        .scalars()
        .all()
    )
    assert len(notes) == 1
    assert notes[0].notification_type == "file_revision"
    assert notes[0].entity_type == "file_document"
    assert notes[0].entity_id == file_id


@pytest.mark.asyncio
async def test_on_file_new_revision_respects_notify_on_filter(
    db_session: AsyncSession,
) -> None:
    """Subscribers that only listen for "created" do NOT receive revision pings."""
    user_id, project_id = await _seed_user_and_project(db_session)
    subscriber = User(
        email=f"sub-co-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Created-Only Sub",
        role="editor",
    )
    db_session.add(subscriber)
    await db_session.flush()

    sub_svc = SubscriptionService(db_session)
    await sub_svc.create(
        SubscriptionCreate(
            project_id=project_id,
            file_kind="document",
            subscriber_email=subscriber.email,
            subscriber_user_id=subscriber.id,
            notify_on=["created"],  # ← explicitly skips "updated"
            active=True,
        ),
        user_id=subscriber.id,
    )
    await db_session.commit()

    file_id = uuid.uuid4().hex
    # Direct hook invocation — simulates the version supersede path.
    created = await on_file_new_revision(
        db_session,
        project_id=project_id,
        file_kind="document",
        file_id=file_id,
        canonical_name="spec.pdf",
        version_number=2,
        actor_id=user_id,
    )
    await db_session.commit()
    assert created == 0

    notes = (
        (
            await db_session.execute(
                select(Notification).where(Notification.user_id == subscriber.id),
            )
        )
        .scalars()
        .all()
    )
    assert notes == []

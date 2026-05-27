# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for :mod:`app.modules.file_comments`.

Coverage:
    * top-level comment + reply build a two-tier thread.
    * resolving a top-level comment hides it from include_resolved=False.
    * ``@username`` is extracted and persisted as a FileCommentMention.
    * unread inbox returns it; acknowledge removes it.
    * soft-delete preserves the row but replaces body + clears mentions.
    * cross-thread parent_id is rejected.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.modules.file_comments.models import (  # noqa: F401 — registers ORM
    FileComment,
    FileCommentMention,
)
from app.modules.file_comments.schemas import (
    FileCommentCreate,
    FileCommentUpdate,
)
from app.modules.file_comments.service import (
    acknowledge_mention,
    create_comment,
    list_threads,
    list_unread_mentions,
    soft_delete_comment,
    update_comment,
)

# Epic C: FileComment now has an FK to oe_file_version — the test's
# Base.metadata.create_all() needs the version table registered too.
from app.modules.file_versions.models import FileVersion  # noqa: F401 — registers ORM
from app.modules.projects.models import Project  # noqa: F401 — registers ORM
from app.modules.users.models import User  # noqa: F401 — registers ORM


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Per-test in-memory SQLite with full schema applied."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with sm() as s:
        yield s
    await engine.dispose()


async def _seed_user(
    session: AsyncSession,
    email: str | None = None,
    full_name: str = "Test User",
) -> User:
    user = User(
        email=email or f"user-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        full_name=full_name,
        role="admin",
    )
    session.add(user)
    await session.flush()
    return user


async def _seed_project(session: AsyncSession, owner: User) -> Project:
    project = Project(name="Comments Project", owner_id=owner.id)
    session.add(project)
    await session.flush()
    return project


@pytest.mark.asyncio
async def test_post_top_level_and_reply_build_thread(
    session: AsyncSession,
) -> None:
    """A reply attaches to its parent as a nested node in the response."""
    author = await _seed_user(session)
    project = await _seed_project(session, author)

    file_id = uuid.uuid4().hex
    top, _ = await create_comment(
        session,
        FileCommentCreate(
            project_id=project.id,
            file_kind="document",
            file_id=file_id,
            body="Top-level note about the drawing.",
        ),
        author_id=author.id,
    )

    reply, _ = await create_comment(
        session,
        FileCommentCreate(
            project_id=project.id,
            file_kind="document",
            file_id=file_id,
            parent_id=top.id,
            body="Reply to that note.",
        ),
        author_id=author.id,
    )

    threads, total = await list_threads(
        session,
        project_id=project.id,
        file_kind="document",
        file_id=file_id,
    )
    assert total == 1
    assert len(threads) == 1
    assert threads[0].id == top.id
    assert len(threads[0].replies) == 1
    assert threads[0].replies[0].id == reply.id
    assert threads[0].replies[0].parent_id == top.id


@pytest.mark.asyncio
async def test_resolve_hides_top_level_when_include_resolved_false(
    session: AsyncSession,
) -> None:
    """Resolving a thread root drops it from the default list."""
    author = await _seed_user(session)
    project = await _seed_project(session, author)
    file_id = uuid.uuid4().hex

    top, _ = await create_comment(
        session,
        FileCommentCreate(
            project_id=project.id,
            file_kind="document",
            file_id=file_id,
            body="To be resolved.",
        ),
        author_id=author.id,
    )

    result = await update_comment(
        session,
        top.id,
        FileCommentUpdate(resolved=True),
        actor_id=author.id,
    )
    assert result is not None
    updated, _ = result
    assert updated.resolved is True
    assert updated.resolved_at is not None
    assert updated.resolved_by_id == author.id

    threads, total = await list_threads(
        session,
        project_id=project.id,
        file_kind="document",
        file_id=file_id,
        include_resolved=False,
    )
    assert total == 0
    assert threads == []

    # With include_resolved=True it comes back.
    threads_all, total_all = await list_threads(
        session,
        project_id=project.id,
        file_kind="document",
        file_id=file_id,
        include_resolved=True,
    )
    assert total_all == 1
    assert threads_all[0].id == top.id


@pytest.mark.asyncio
async def test_mention_extracted_and_unread_inbox_returns_it(
    session: AsyncSession,
) -> None:
    """@email-local-part triggers a mention row + inbox query returns it."""
    author = await _seed_user(session, "alice@acme.example", "Alice Smith")
    mentioned = await _seed_user(session, "bob@acme.example", "Bob Jones")
    project = await _seed_project(session, author)
    file_id = uuid.uuid4().hex

    comment, mentions = await create_comment(
        session,
        FileCommentCreate(
            project_id=project.id,
            file_kind="sheet",
            file_id=file_id,
            body="Hey @bob, please review.",
        ),
        author_id=author.id,
    )

    assert len(mentions) == 1
    assert mentions[0].mentioned_user_id == mentioned.id
    assert mentions[0].comment_id == comment.id
    assert mentions[0].notified_at is None

    # Inbox for the mentioned user returns the row.
    items, total = await list_unread_mentions(session, mentioned.id)
    assert total == 1
    assert items[0].comment_id == comment.id
    assert items[0].mention_id == mentions[0].id
    assert items[0].file_kind == "sheet"
    assert items[0].file_id == file_id
    assert "@bob" in items[0].body_excerpt

    # The author themself has no unread inbox entry (self-mentions filtered).
    items_author, total_author = await list_unread_mentions(session, author.id)
    assert total_author == 0
    assert items_author == []


@pytest.mark.asyncio
async def test_acknowledge_mention_removes_it_from_inbox(
    session: AsyncSession,
) -> None:
    """Once acknowledged, the mention drops out of the unread query."""
    author = await _seed_user(session, "carol@acme.example", "Carol")
    mentioned = await _seed_user(session, "dave@acme.example", "Dave")
    project = await _seed_project(session, author)
    file_id = uuid.uuid4().hex

    _, mentions = await create_comment(
        session,
        FileCommentCreate(
            project_id=project.id,
            file_kind="photo",
            file_id=file_id,
            body="Cc @dave on this.",
        ),
        author_id=author.id,
    )
    assert len(mentions) == 1

    ok = await acknowledge_mention(session, mentions[0].id, mentioned.id)
    assert ok is True

    items, total = await list_unread_mentions(session, mentioned.id)
    assert total == 0
    assert items == []

    # Acknowledging a stranger's mention id returns False (IDOR shield).
    other = await _seed_user(session, "eve@acme.example", "Eve")
    bad = await acknowledge_mention(session, mentions[0].id, other.id)
    assert bad is False


@pytest.mark.asyncio
async def test_soft_delete_preserves_thread_and_clears_mentions(
    session: AsyncSession,
) -> None:
    """Tombstones keep the row + child replies; mentions are pruned."""
    author = await _seed_user(session, "felix@acme.example", "Felix")
    mentioned = await _seed_user(session, "gina@acme.example", "Gina")
    project = await _seed_project(session, author)
    file_id = uuid.uuid4().hex

    top, mentions = await create_comment(
        session,
        FileCommentCreate(
            project_id=project.id,
            file_kind="document",
            file_id=file_id,
            body="Heads up @gina.",
        ),
        author_id=author.id,
    )
    assert len(mentions) == 1
    reply, _ = await create_comment(
        session,
        FileCommentCreate(
            project_id=project.id,
            file_kind="document",
            file_id=file_id,
            parent_id=top.id,
            body="Got it.",
        ),
        author_id=author.id,
    )

    ok = await soft_delete_comment(session, top.id, actor_id=author.id)
    assert ok is True

    # Row still present, body replaced.
    row = (await session.execute(select(FileComment).where(FileComment.id == top.id))).scalar_one_or_none()
    assert row is not None
    assert row.body == "[deleted]"

    # Reply still hangs off the tombstoned parent.
    reply_row = (await session.execute(select(FileComment).where(FileComment.id == reply.id))).scalar_one_or_none()
    assert reply_row is not None
    assert reply_row.parent_id == top.id

    # Mention rows are gone — inbox empty.
    items, total = await list_unread_mentions(session, mentioned.id)
    assert total == 0
    assert items == []


@pytest.mark.asyncio
async def test_cross_thread_parent_is_rejected(session: AsyncSession) -> None:
    """A reply may not parent across (project, kind, file) tuples."""
    author = await _seed_user(session)
    project = await _seed_project(session, author)

    file_a, _ = await create_comment(
        session,
        FileCommentCreate(
            project_id=project.id,
            file_kind="document",
            file_id="file-a",
            body="Thread A root.",
        ),
        author_id=author.id,
    )

    with pytest.raises(ValueError, match="different file"):
        await create_comment(
            session,
            FileCommentCreate(
                project_id=project.id,
                file_kind="document",
                file_id="file-b",
                parent_id=file_a.id,
                body="Reply trying to cross threads.",
            ),
            author_id=author.id,
        )


@pytest.mark.asyncio
async def test_anchor_xy_must_be_paired(session: AsyncSession) -> None:
    """A pin needs both coordinates — half a pin is rejected."""
    author = await _seed_user(session)
    project = await _seed_project(session, author)

    with pytest.raises(ValueError, match="anchor_x and anchor_y"):
        await create_comment(
            session,
            FileCommentCreate(
                project_id=project.id,
                file_kind="document",
                file_id="x",
                body="half-pin",
                page_number=1,
                anchor_x=0.5,
                anchor_y=None,
            ),
            author_id=author.id,
        )


@pytest.mark.asyncio
async def test_only_author_can_edit_body(session: AsyncSession) -> None:
    """A non-author edit raises PermissionError; resolve is open."""
    author = await _seed_user(session, "owner@acme.example", "Owner")
    other = await _seed_user(session, "lurker@acme.example", "Lurker")
    project = await _seed_project(session, author)
    file_id = uuid.uuid4().hex

    top, _ = await create_comment(
        session,
        FileCommentCreate(
            project_id=project.id,
            file_kind="document",
            file_id=file_id,
            body="Author note.",
        ),
        author_id=author.id,
    )

    with pytest.raises(PermissionError):
        await update_comment(
            session,
            top.id,
            FileCommentUpdate(body="Stranger edit."),
            actor_id=other.id,
        )

    # Resolve by a non-author succeeds (service layer doesn't gate; the
    # router enforces the file_comments.resolve permission).
    result = await update_comment(
        session,
        top.id,
        FileCommentUpdate(resolved=True),
        actor_id=other.id,
    )
    assert result is not None
    updated, _ = result
    assert updated.resolved is True
    assert updated.resolved_by_id == other.id


@pytest.mark.asyncio
async def test_body_edit_replaces_mention_rows(session: AsyncSession) -> None:
    """Re-extracting mentions on body edit replaces stale rows."""
    author = await _seed_user(session, "kim@acme.example", "Kim")
    alpha = await _seed_user(session, "alpha@acme.example", "Alpha")
    beta = await _seed_user(session, "beta@acme.example", "Beta")
    project = await _seed_project(session, author)
    file_id = uuid.uuid4().hex

    top, mentions = await create_comment(
        session,
        FileCommentCreate(
            project_id=project.id,
            file_kind="document",
            file_id=file_id,
            body="Cc @alpha please.",
        ),
        author_id=author.id,
    )
    assert {m.mentioned_user_id for m in mentions} == {alpha.id}

    result = await update_comment(
        session,
        top.id,
        FileCommentUpdate(body="Now Cc @beta instead."),
        actor_id=author.id,
    )
    assert result is not None
    _, new_mentions = result
    assert {m.mentioned_user_id for m in new_mentions} == {beta.id}

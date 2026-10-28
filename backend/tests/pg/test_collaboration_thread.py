"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG regression: collaboration comment thread/list serialization (no MissingGreenlet).

``CommentResponse.replies`` is a self-referential schema Pydantic serializes
recursively. The model relationships are ``lazy="selectin"`` which pre-loads only
ONE level, so on asyncpg a deeper ``replies`` access during synchronous
serialization raised ``MissingGreenlet`` (SQLite silently tolerated it). The repo
now pins the reply tree in memory with ``set_committed_value``. These tests run on
a REAL PostgreSQL cluster and fail if that regression returns.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.collaboration.models import Comment
from app.modules.collaboration.repository import CommentRepository
from app.modules.collaboration.schemas import CommentResponse
from app.modules.users.models import User


async def _seed_thread(session) -> tuple[uuid.UUID, str, str]:
    """Insert an author + a root comment with two replies. Returns (root_id, etype, eid)."""
    author = User(email=f"collab-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    session.add(author)
    await session.flush()

    etype, eid = "project", uuid.uuid4().hex
    root = Comment(entity_type=etype, entity_id=eid, author_id=author.id, text="root")
    session.add(root)
    await session.flush()

    for i in range(2):
        session.add(
            Comment(
                entity_type=etype,
                entity_id=eid,
                author_id=author.id,
                text=f"reply {i}",
                parent_comment_id=root.id,
            )
        )
    await session.flush()
    return root.id, etype, eid


@pytest.mark.asyncio
async def test_get_thread_serializes_flat_without_greenlet(pg_session) -> None:
    """get_thread returns a flat list and each CommentResponse serializes IO-free."""
    root_id, _etype, _eid = await _seed_thread(pg_session)
    repo = CommentRepository(pg_session)

    thread = await repo.get_thread(root_id)
    assert len(thread) == 3, "root + 2 descendants, flat"

    # The crux: sync Pydantic serialization of the pinned tree must NOT emit IO.
    # Without the fix this raises pydantic ValidationError(MissingGreenlet).
    responses = [CommentResponse.model_validate(c) for c in thread]
    assert all(r.replies == [] for r in responses), "flat thread: no nested replies"
    assert {str(root_id)} <= {str(r.id) for r in responses}


@pytest.mark.asyncio
async def test_list_for_entity_serializes_nested_without_greenlet(pg_session) -> None:
    """list_for_entity returns top-level comments with replies nested + serializable."""
    root_id, etype, eid = await _seed_thread(pg_session)
    repo = CommentRepository(pg_session)

    top_level, total = await repo.list_for_entity(etype, eid)
    assert total == 1, "one top-level comment"
    assert len(top_level) == 1

    resp = CommentResponse.model_validate(top_level[0])  # would MissingGreenlet pre-fix
    assert str(resp.id) == str(root_id)
    assert len(resp.replies) == 2, "two replies nested in-memory"


@pytest.mark.asyncio
async def test_get_with_reply_tree_serializes_without_greenlet(pg_session) -> None:
    """The PATCH return path (get_with_reply_tree) is serialization-safe too."""
    root_id, _etype, _eid = await _seed_thread(pg_session)
    repo = CommentRepository(pg_session)

    comment = await repo.get_with_reply_tree(root_id)
    assert comment is not None
    resp = CommentResponse.model_validate(comment)
    assert len(resp.replies) == 2

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode an ``@mention`` only finds project members (gate E1).

A file comment resolves ``@handle`` against every user on the install, by the
local part of the email or the squashed full name, writes a mention row and
publishes ``file_comments.mention.created``, which the notifications module
turns into a notification for the mentioned user. On an academy box that lets
one learner find another by guessing a handle and ping them. In academy mode
the candidates are narrowed to the people who can access the comment's project
before the handle is matched.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.modules.file_comments.models import FileCommentMention
from app.modules.file_comments.schemas import FileCommentCreate, FileCommentUpdate
from app.modules.file_comments.service import create_comment, update_comment
from tests.pg.academy_isolation.rows import add_member, make_project, make_user

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

MENTION = "file_comments.mention.created"


async def _setup(session):
    tag = uuid.uuid4().hex[:6]
    alice = await make_user(session, name="Alice", email=f"alice{tag}@academy.example")
    bob = await make_user(session, name="Bob", email=f"bob{tag}@academy.example")
    carol = await make_user(session, name="Carol", email=f"carol{tag}@academy.example")
    project = await make_project(session, alice)
    await add_member(session, project, carol)
    return tag, project, alice, bob, carol


async def _comment(session, project, author, body: str):
    payload = FileCommentCreate(project_id=project.id, file_kind="document", file_id="doc-1", body=body)
    return await create_comment(session, payload, author.id)


async def _mentioned(session, comment_id) -> set[uuid.UUID]:
    rows = await session.execute(
        select(FileCommentMention.mentioned_user_id).where(FileCommentMention.comment_id == comment_id)
    )
    return set(rows.scalars().all())


def _pinged(events) -> set[str]:
    return {data["mentioned_user_id"] for name, data in events if name == MENTION}


async def test_academy_on_other_learner_not_mentioned(pg_session, academy, events) -> None:
    academy(True)
    tag, project, alice, bob, _carol = await _setup(pg_session)

    comment, mentions = await _comment(pg_session, project, alice, f"@bob{tag} please check")
    assert mentions == []
    assert await _mentioned(pg_session, comment.id) == set()
    assert _pinged(events) == set()

    # Editing the body re-resolves mentions through the same narrowing.
    await update_comment(pg_session, comment.id, FileCommentUpdate(body=f"@bob{tag} again"), alice.id)
    assert await _mentioned(pg_session, comment.id) == set()
    assert _pinged(events) == set()


async def test_academy_on_a_project_member_is_still_mentioned(pg_session, academy, events) -> None:
    academy(True)
    tag, project, alice, bob, carol = await _setup(pg_session)

    comment, _ = await _comment(pg_session, project, alice, f"@carol{tag} and @bob{tag}")
    assert await _mentioned(pg_session, comment.id) == {carol.id}
    assert _pinged(events) == {str(carol.id)}


async def test_academy_off_behaviour_unchanged(pg_session, academy, events) -> None:
    academy(False)
    tag, project, alice, bob, carol = await _setup(pg_session)

    comment, mentions = await _comment(pg_session, project, alice, f"@bob{tag} and @carol{tag}")
    assert {m.mentioned_user_id for m in mentions} == {bob.id, carol.id}
    assert await _mentioned(pg_session, comment.id) == {bob.id, carol.id}
    assert _pinged(events) == {str(bob.id), str(carol.id)}

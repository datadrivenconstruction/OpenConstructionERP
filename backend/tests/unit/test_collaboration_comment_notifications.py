"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Tests for Project Discussion comment notifications (issue #279).

Two halves:

* ``create_comment`` publishes a detached ``collaboration.comment.created``
  event carrying entity/project/author hints (pure - patched publish, stub
  repositories, no DB).

* the notifications subscriber ``_on_collaboration_comment_created`` notifies
  the OTHER participants of the thread (prior commenters + project owner) and
  never the author (DB-backed, transaction-isolated PostgreSQL session).

The DB-backed half uses ``tests._pg.transactional_session`` (rolled back on
teardown) exactly like ``test_notifications_dispatcher.py``.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event
from app.modules.notifications.models import Notification
from tests._pg import transactional_session

# ════════════════════════════════════════════════════════════════════════════
# Part 1 (pure): create_comment publishes the detached event
# ════════════════════════════════════════════════════════════════════════════


class _StubCommentRepo:
    def __init__(self) -> None:
        self.created: list[Any] = []

    async def get(self, _cid: uuid.UUID) -> Any:  # pragma: no cover - not hit
        return None

    async def create(self, comment: Any) -> Any:
        if getattr(comment, "id", None) is None:
            comment.id = uuid.uuid4()
        self.created.append(comment)
        return comment


class _NoopSession:
    async def refresh(self, _obj: object) -> None:
        return None


def _make_collab_service() -> Any:
    from app.modules.collaboration.service import CollaborationService

    svc = CollaborationService.__new__(CollaborationService)
    svc.session = _NoopSession()
    svc.comment_repo = _StubCommentRepo()
    svc.mention_repo = SimpleNamespace()
    svc.viewpoint_repo = SimpleNamespace()
    return svc


@pytest.mark.asyncio
async def test_create_comment_publishes_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_comment fires collaboration.comment.created with the right payload."""
    from app.modules.collaboration import service as collab_service
    from app.modules.collaboration.schemas import CommentCreate

    published: list[tuple[str, dict]] = []

    async def _capture(name: str, data: dict, source_module: str = "oe_collaboration") -> None:
        published.append((name, data))

    monkeypatch.setattr(collab_service, "_safe_publish", _capture)

    svc = _make_collab_service()
    author_id = uuid.uuid4()
    project_id = uuid.uuid4()
    entity_id = str(uuid.uuid4())

    data = CommentCreate(
        entity_type="task",
        entity_id=entity_id,
        text="Please review the latest revision",
    )
    await svc.create_comment(data, author_id, project_id=project_id)

    matches = [d for (n, d) in published if n == "collaboration.comment.created"]
    assert len(matches) == 1
    payload = matches[0]
    assert payload["entity_type"] == "task"
    assert payload["entity_id"] == entity_id
    assert payload["author_id"] == str(author_id)
    assert payload["project_id"] == str(project_id)
    assert payload["body_excerpt"] == "Please review the latest revision"


@pytest.mark.asyncio
async def test_create_comment_publishes_event_without_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """project_id is optional - the event still fires, carrying None."""
    from app.modules.collaboration import service as collab_service
    from app.modules.collaboration.schemas import CommentCreate

    published: list[tuple[str, dict]] = []

    async def _capture(name: str, data: dict, source_module: str = "oe_collaboration") -> None:
        published.append((name, data))

    monkeypatch.setattr(collab_service, "_safe_publish", _capture)

    svc = _make_collab_service()
    data = CommentCreate(entity_type="rfi", entity_id=str(uuid.uuid4()), text="hi")
    await svc.create_comment(data, uuid.uuid4())

    matches = [d for (n, d) in published if n == "collaboration.comment.created"]
    assert len(matches) == 1
    assert matches[0]["project_id"] is None


# ════════════════════════════════════════════════════════════════════════════
# Part 2 (DB-backed): the subscriber notifies other participants, not the author
# ════════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


class _CMFactory:
    """async context manager returning a fixed session (test isolation helper).

    Routes the subscriber's ``async_session_factory()`` at the transactional
    test session so its writes land in (and roll back with) the test's
    transaction instead of opening a real pooled connection.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *_: object) -> None:
        # Do not close/commit - the transactional fixture owns the lifecycle.
        return None


@pytest.mark.asyncio
async def test_subscriber_notifies_other_participants_not_author(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prior commenters + project owner get a notification; the author does not."""
    import app.modules.notifications._collaboration_subscribers as subs
    from app.modules.collaboration.models import Comment
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    author = uuid.uuid4()
    other_commenter = uuid.uuid4()
    owner = uuid.uuid4()

    for uid, email in (
        (author, "author@example.com"),
        (other_commenter, "other@example.com"),
        (owner, "owner@example.com"),
    ):
        session.add(User(id=uid, email=email, hashed_password="x", full_name=email))
    # Flush the users first so the comment/project FK targets exist (there is no
    # ORM relationship to drive insert ordering automatically).
    await session.flush()

    project = Project(id=uuid.uuid4(), name="Discussion Project", owner_id=owner)
    session.add(project)
    await session.flush()

    entity_type = "project"
    entity_id = str(project.id)

    # Prior comments on the same entity: one by the author, one by another user.
    session.add(
        Comment(
            entity_type=entity_type,
            entity_id=entity_id,
            author_id=author,
            text="first post",
        )
    )
    session.add(
        Comment(
            entity_type=entity_type,
            entity_id=entity_id,
            author_id=other_commenter,
            text="a reply",
        )
    )
    await session.commit()

    # Route the subscriber's isolated session at our transactional test session.
    monkeypatch.setattr(
        subs,
        "async_session_factory",
        lambda: _CMFactory(session),
    )

    event = Event(
        name="collaboration.comment.created",
        data={
            "comment_id": str(uuid.uuid4()),
            "entity_type": entity_type,
            "entity_id": entity_id,
            "project_id": str(project.id),
            "author_id": str(author),
            "body_excerpt": "newest comment",
        },
    )
    await subs._on_collaboration_comment_created(event)

    rows = list(
        (
            await session.execute(
                select(Notification).where(Notification.entity_type == entity_type),
            )
        )
        .scalars()
        .all()
    )
    notified = {str(r.user_id) for r in rows}

    # Other commenter + project owner notified; author excluded.
    assert str(other_commenter) in notified
    assert str(owner) in notified
    assert str(author) not in notified
    # All rows are the discussion comment type.
    assert all(r.notification_type == "comment_added" for r in rows)


@pytest.mark.asyncio
async def test_subscriber_noop_when_only_author_present(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A brand-new thread where only the author has posted notifies nobody.

    (No prior commenters, and no project owner because we pass no project_id.)
    """
    import app.modules.notifications._collaboration_subscribers as subs
    from app.modules.collaboration.models import Comment
    from app.modules.users.models import User

    author = uuid.uuid4()
    session.add(User(id=author, email="solo@example.com", hashed_password="x", full_name="Solo"))
    await session.flush()  # ensure the FK target exists before the comment insert
    entity_id = str(uuid.uuid4())
    session.add(Comment(entity_type="task", entity_id=entity_id, author_id=author, text="only me"))
    await session.commit()

    monkeypatch.setattr(subs, "async_session_factory", lambda: _CMFactory(session))

    event = Event(
        name="collaboration.comment.created",
        data={
            "comment_id": str(uuid.uuid4()),
            "entity_type": "task",
            "entity_id": entity_id,
            "project_id": None,
            "author_id": str(author),
            "body_excerpt": "only me",
        },
    )
    await subs._on_collaboration_comment_created(event)

    rows = list(
        (await session.execute(select(Notification).where(Notification.entity_id == entity_id))).scalars().all()
    )
    assert rows == []

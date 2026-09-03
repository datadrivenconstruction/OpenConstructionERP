# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Private / public tasks (PostgreSQL, py3.12).

The rail is server-side. A private task reaches its creator, its
assignee and admins - through the board, the log, comments and files -
and nobody else, on any path. Each test is the leak it exists to catch.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.team_standup import board_service, service
from app.modules.team_standup.models import LINK_KINDS, TASK_VISIBILITIES, StandupTask
from app.modules.team_standup.schemas import TaskPatch, TaskRead, TaskWrite
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _user(session: AsyncSession, *, name: str, role: str = "editor") -> User:
    user = User(
        email=f"vis-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name=name,
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _project(session: AsyncSession) -> Project:
    owner = await _user(session, name="owner")
    proj = Project(
        name="Acme Holdings - Switchroom",
        owner_id=owner.id,
        currency="AUD",
        status="active",
        project_code="25406",
    )
    session.add(proj)
    await session.flush()
    return proj


async def _cast(session: AsyncSession):
    """Creator, assignee, an outsider and an admin on a seeded board."""
    await board_service.ensure_seeded(session)
    creator = await _user(session, name="Alex Example")
    assignee = await _user(session, name="Sam Example")
    outsider = await _user(session, name="Pat Example")
    admin = await _user(session, name="Boss Example", role="admin")
    proj = await _project(session)
    return creator, assignee, outsider, admin, proj


async def _private_task(session: AsyncSession, creator: User, assignee: User, proj: Project) -> StandupTask:
    [task] = await board_service.create_tasks(
        session,
        [
            {
                "title": "Quiet word about the switchboard",
                "project_id": str(proj.id),
                "assignee_id": str(assignee.id),
                "visibility": "private",
            }
        ],
        user_id=str(creator.id),
    )
    return task


def _ids(tasks) -> set[str]:
    return {str(t.id) for t in tasks}


# ── vocabulary ───────────────────────────────────────────────────────────


def test_request_is_a_link_kind_everywhere() -> None:
    """The model tuple and the schema Literal must agree - the schema is
    what the wire validates against, the model is what the service does."""
    assert "request" in LINK_KINDS
    assert TaskWrite(title="x", project_id="p", link_kind="request").link_kind == "request"
    assert TaskPatch(link_kind="request").link_kind == "request"
    with pytest.raises(ValueError):
        TaskWrite(title="x", project_id="p", link_kind="ticket")
    assert TASK_VISIBILITIES == ("public", "private")
    with pytest.raises(ValueError):
        TaskWrite(title="x", project_id="p", visibility="secret")


@pytest.mark.asyncio
async def test_task_created_with_request_link_kind(session: AsyncSession) -> None:
    creator, assignee, _, _, proj = await _cast(session)
    request_id = str(uuid.uuid4())
    [task] = await board_service.create_tasks(
        session,
        [
            {
                "title": "Chase the workshop",
                "project_id": str(proj.id),
                "link_kind": "request",
                "link_ref": "WR-WKS-000007",
                "link_target_id": request_id,
            }
        ],
        user_id=str(creator.id),
    )
    assert (task.link_kind, task.link_ref, task.link_target_id) == (
        "request",
        "WR-WKS-000007",
        request_id,
    )
    assert TaskRead.model_validate(task).link_kind == "request"


# ── the default, and who sees what ───────────────────────────────────────


@pytest.mark.asyncio
async def test_tasks_are_public_by_default(session: AsyncSession) -> None:
    creator, _, outsider, _, proj = await _cast(session)
    [task] = await board_service.create_tasks(
        session,
        [{"title": "Everyone's business", "project_id": str(proj.id)}],
        user_id=str(creator.id),
    )
    assert task.visibility == "public"
    assert TaskRead.model_validate(task).visibility == "public"
    assert str(task.id) in _ids(await board_service.board_tasks(session, viewer_id=str(outsider.id)))


@pytest.mark.asyncio
async def test_private_task_reaches_creator_assignee_and_admin_only(
    session: AsyncSession,
) -> None:
    creator, assignee, outsider, admin, proj = await _cast(session)
    task = await _private_task(session, creator, assignee, proj)
    tid = str(task.id)

    assert tid in _ids(await board_service.board_tasks(session, viewer_id=str(creator.id)))
    assert tid in _ids(await board_service.board_tasks(session, viewer_id=str(assignee.id)))
    assert tid in _ids(await board_service.board_tasks(session, viewer_id=str(admin.id), is_admin=True))
    # The leak: a non-admin member outside the task must not get it.
    assert tid not in _ids(await board_service.board_tasks(session, viewer_id=str(outsider.id)))
    # And an anonymous/internal read never carries private rows either.
    assert tid not in _ids(await board_service.board_tasks(session))


@pytest.mark.asyncio
async def test_outsider_cannot_touch_a_private_task_on_any_path(
    session: AsyncSession,
) -> None:
    """Hidden must mean hidden: edit, move, delete, comment and restore
    all answer "not found" to someone outside the task."""
    creator, assignee, outsider, _, proj = await _cast(session)
    task = await _private_task(session, creator, assignee, proj)
    stages = await board_service.stages_ordered(session)
    tid, uid = str(task.id), str(outsider.id)

    with pytest.raises(service.StandupError, match="not found"):
        await board_service.update_task(session, task_id=tid, fields={"title": "Seen you"}, user_id=uid)
    with pytest.raises(service.StandupError, match="not found"):
        await board_service.move_task(session, task_id=tid, stage_id=str(stages[1].id), user_id=uid)
    with pytest.raises(service.StandupError, match="not found"):
        await board_service.add_task_comment(session, task_id=tid, user_id=uid, body="hello?")
    with pytest.raises(service.StandupError, match="not found"):
        await board_service.delete_task(session, task_id=tid, user_id=uid)

    # The people inside it work as normal.
    comment = await board_service.add_task_comment(session, task_id=tid, user_id=str(assignee.id), body="on it")
    # ...and an outsider cannot reach the comment through its own id.
    with pytest.raises(service.StandupError, match="not found"):
        await board_service.delete_task_comment(session, comment_id=str(comment.id), user_id=uid, role="editor")
    await board_service.delete_task(session, task_id=tid, user_id=str(creator.id))
    with pytest.raises(service.StandupError):
        await board_service.restore_task(session, task_id=tid, user_id=uid)
    restored = await board_service.restore_task(session, task_id=tid, user_id=str(creator.id))
    assert not restored.deleted


# ── flipping visibility ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_visibility_flip_is_creator_assignee_or_admin_only(
    session: AsyncSession,
) -> None:
    creator, assignee, outsider, admin, proj = await _cast(session)
    [task] = await board_service.create_tasks(
        session,
        [
            {
                "title": "Public for now",
                "project_id": str(proj.id),
                "assignee_id": str(assignee.id),
            }
        ],
        user_id=str(creator.id),
    )
    tid = str(task.id)

    # A public task is visible to the outsider - but not theirs to hide.
    with pytest.raises(PermissionError):
        await board_service.update_task(
            session, task_id=tid, fields={"visibility": "private"}, user_id=str(outsider.id)
        )
    assert task.visibility == "public"

    # The assignee may make it private; the creator may make it public
    # again; an admin may do either.
    await board_service.update_task(session, task_id=tid, fields={"visibility": "private"}, user_id=str(assignee.id))
    assert task.visibility == "private"
    await board_service.update_task(session, task_id=tid, fields={"visibility": "public"}, user_id=str(creator.id))
    assert task.visibility == "public"
    await board_service.update_task(
        session,
        task_id=tid,
        fields={"visibility": "private"},
        user_id=str(admin.id),
        is_admin=True,
    )
    assert task.visibility == "private"

    with pytest.raises(service.StandupError, match="Visibility"):
        await board_service.update_task(session, task_id=tid, fields={"visibility": "secret"}, user_id=str(creator.id))
    # Other fields ride along untouched when visibility is not in the patch.
    await board_service.update_task(session, task_id=tid, fields={"priority": "high"}, user_id=str(creator.id))
    assert task.visibility == "private" and task.priority == "high"


# ── what a private task creates stays private ────────────────────────────


@pytest.mark.asyncio
async def test_followups_and_repeats_inherit_visibility(session: AsyncSession) -> None:
    creator, assignee, outsider, _, proj = await _cast(session)
    stages = await board_service.stages_ordered(session)
    ordered = next(s for s in stages if s.name == "Ordered")
    [task] = await board_service.create_tasks(
        session,
        [
            {
                "title": "Private monthly claim",
                "project_id": str(proj.id),
                "assignee_id": str(assignee.id),
                "visibility": "private",
                "due": "2026-09-25",
                "repeat_rule": "monthly",
            }
        ],
        user_id=str(creator.id),
    )
    moved = await board_service.move_task(
        session, task_id=str(task.id), stage_id=str(ordered.id), user_id=str(creator.id)
    )
    assert moved["spawned"], "Ordered has a template"
    assert all(t.visibility == "private" for t in moved["spawned"])
    closed = await board_service.move_task(
        session, task_id=str(task.id), stage_id=str(stages[-1].id), user_id=str(creator.id)
    )
    assert closed["repeated"] is not None
    assert closed["repeated"].visibility == "private"
    visible_to_outsider = _ids(await board_service.board_tasks(session, viewer_id=str(outsider.id)))
    assert not (_ids(moved["spawned"]) & visible_to_outsider)
    assert str(closed["repeated"].id) not in visible_to_outsider


# ── the log follows the task ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_log_lines_about_a_private_task_follow_it(session: AsyncSession) -> None:
    creator, assignee, outsider, admin, proj = await _cast(session)
    task = await _private_task(session, creator, assignee, proj)
    await board_service.update_task(
        session, task_id=str(task.id), fields={"priority": "urgent"}, user_id=str(creator.id)
    )
    [public] = await board_service.create_tasks(
        session,
        [{"title": "Public notice", "project_id": str(proj.id)}],
        user_id=str(creator.id),
    )

    def whats(rows) -> list[str]:
        return [r.what for r in rows]

    outsider_log = whats(await board_service.recent_log(session, viewer_id=str(outsider.id)))
    assert not any("Quiet word" in w for w in outsider_log), outsider_log
    assert any('Created "Public notice"' in w for w in outsider_log)

    for viewer, admin_flag in ((creator, False), (assignee, False), (admin, True)):
        seen = whats(await board_service.recent_log(session, viewer_id=str(viewer.id), is_admin=admin_flag))
        assert any('Created "Quiet word' in w for w in seen), viewer.full_name
        assert any('Edited "Quiet word' in w for w in seen), viewer.full_name
    assert str(public.id) not in {
        r.task_id for r in await board_service.recent_log(session, viewer_id=str(outsider.id)) if "Quiet" in r.what
    }

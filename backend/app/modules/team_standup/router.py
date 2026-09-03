# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Team Standup API routes.

Mounted by the module loader at ``/api/v1/team-standup/``.

Endpoints:
    GET    /                              - module ping
    GET    /board?day=YYYY-MM-DD          - one day: entries + roster + me
    PUT    /entries                       - upsert MY entry for a day
    GET    /entries?from_day=&to_day=&user_id=  - history range
    GET    /blockers?from_day=&to_day=    - open-blockers digest
    POST   /entries/{entry_id}/comments   - comment on an entry
    DELETE /comments/{comment_id}         - delete own comment (admin: any)

There is no project scoping here on purpose: a standup is team-level.
Every authenticated reader sees the same board; the write rails
(own-entry-only, own-comment-only) live in the service.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import module_uploads_dir
from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.projects.models import Project
from app.modules.team_standup import board_service, service
from app.modules.team_standup.models import (
    StandupEntry,
    StandupEntryFile,
    StandupTask,
    StandupTaskFile,
)
from app.modules.team_standup.permissions import register_team_standup_permissions
from app.modules.team_standup.schemas import (
    ActivitiesReplace,
    ActivityRead,
    BlockerListResponse,
    BlockerRead,
    BoardJobRead,
    BoardMe,
    BoardRead,
    CommentCreate,
    CommentRead,
    EntryListResponse,
    EntryRead,
    EntryUpsert,
    FileRead,
    FullBoardRead,
    JobRead,
    LastEntryRead,
    LogListResponse,
    LogRead,
    PersonRead,
    StageRead,
    StagesReplace,
    TaskCommentRead,
    TaskLite,
    TaskMove,
    TaskMoveResult,
    TaskMoveUndo,
    TaskPatch,
    TaskRead,
    TasksCreate,
    TeamMember,
    WaitsReplace,
    WeekRead,
)
from app.modules.users.models import User

router = APIRouter(tags=["team_standup"])
logger = logging.getLogger(__name__)

# The module loader imports router/models/hooks/events - never
# permissions.py - and the registry fails closed on unknown permission
# names, so an unregistered module is silently admin-only. This used to
# be a side-effect import, which a ruff import-sort autofix silently
# dropped once (every editor got 403 on the whole board while the
# admin-path tests stayed green). An explicit CALL cannot be "unused":
# no autofix will ever remove it. Idempotent - permissions.py also
# calls it at import for anything that does import it directly.
register_team_standup_permissions()


@router.get("/")
async def module_info() -> dict[str, str]:
    """Health-style ping so operators can confirm the module mounted."""
    return {"module": "oe_team_standup", "status": "active"}


@router.get("/board", response_model=BoardRead)
async def board(
    day: str,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.read")),
) -> BoardRead:
    try:
        canonical_day = service.parse_day(day).isoformat()
        entries = await service.day_entries(session, canonical_day)
        roster = await service.roster(session, day=canonical_day, include_user_id=user_id)
    except service.StandupError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    me = await session.get(User, user_id)
    me_name = (me.full_name or me.email) if me else ""

    member_ids = [m["user_id"] for m in roster]
    tasks_by_user = await service.open_tasks_for(session, member_ids)
    last_by_user = await service.last_entries_before(session, member_ids, day=canonical_day)
    members = []
    for m in roster:
        bucket = tasks_by_user.get(m["user_id"], {"tasks": [], "total": 0})
        last = last_by_user.get(m["user_id"])
        members.append(
            TeamMember(
                **m,
                open_tasks=[TaskLite(**t) for t in bucket["tasks"]],
                open_tasks_total=bucket["total"],
                last_entry=(
                    LastEntryRead(
                        day=last.day,
                        status=last.status,
                        today=last.today,
                        blockers=last.blockers,
                    )
                    if last is not None and not m["has_posted"]
                    else None
                ),
            )
        )
    return BoardRead(
        day=canonical_day,
        me=BoardMe(user_id=str(user_id), name=me_name),
        entries=[EntryRead.model_validate(e) for e in entries],
        roster=members,
        jobs=[JobRead(**j) for j in await service.jobs_catalogue(session)],
    )


@router.put("/entries", response_model=EntryRead)
async def upsert_entry(
    payload: EntryUpsert,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.post")),
) -> EntryRead:
    """Create or update the caller's own entry. The payload carries no
    user id - whose entry this is comes from the token alone."""
    try:
        entry = await service.upsert_entry(
            session,
            user_id=user_id,
            day=payload.day,
            status=payload.status,
            yesterday=payload.yesterday,
            today=payload.today,
            blockers=payload.blockers,
            job_ids=payload.job_ids,
            activities=payload.activities,
            blocker_by=payload.blocker_by,
        )
        await board_service._log(
            session,
            user_id=user_id,
            what="Saved their standup",
            where="Standup",
            kind="standup",
            color="blue",
        )
    except service.StandupError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    await session.commit()
    # Reload with comments eagerly present for serialisation.
    refreshed = await service.day_entries(session, entry.day)
    entry = next((e for e in refreshed if str(e.id) == str(entry.id)), entry)
    return EntryRead.model_validate(entry)


@router.get("/entries", response_model=EntryListResponse)
async def list_entries(
    from_day: str,
    to_day: str,
    session: SessionDep,
    user_id: CurrentUserId,
    for_user: str | None = Query(default=None, alias="user_id"),
    limit: int = Query(default=500, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _perm: None = Depends(RequirePermission("team_standup.read")),
) -> EntryListResponse:
    try:
        rows = await service.history(session, from_day=from_day, to_day=to_day, user_id=for_user)
    except service.StandupError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    window = rows[offset : offset + limit]
    return EntryListResponse(
        items=[EntryRead.model_validate(r) for r in window],
        total=len(rows),
        limit=limit,
        offset=offset,
    )


@router.get("/blockers", response_model=BlockerListResponse)
async def list_blockers(
    from_day: str,
    to_day: str,
    session: SessionDep,
    user_id: CurrentUserId,
    limit: int = Query(default=500, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _perm: None = Depends(RequirePermission("team_standup.read")),
) -> BlockerListResponse:
    try:
        rows = await service.blockers(session, from_day=from_day, to_day=to_day)
    except service.StandupError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    window = rows[offset : offset + limit]
    return BlockerListResponse(
        items=[BlockerRead.model_validate(r) for r in window],
        total=len(rows),
        limit=limit,
        offset=offset,
    )


@router.post(
    "/entries/{entry_id}/comments",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_comment(
    entry_id: uuid.UUID,
    payload: CommentCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.comment")),
) -> CommentRead:
    try:
        comment = await service.add_comment(session, entry_id=str(entry_id), user_id=user_id, body=payload.body)
    except service.StandupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    await session.commit()
    return CommentRead.model_validate(comment)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.comment")),
) -> None:
    # Live role from the DB, not the JWT - a demoted admin should lose
    # moderation on their next request, not their next login.
    caller = await session.get(User, user_id)
    role = caller.role if caller else ""
    try:
        await service.delete_comment(session, comment_id=str(comment_id), user_id=user_id, role=role)
    except service.StandupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    await session.commit()


@router.post("/nudge")
async def nudge_missing(
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.post")),
) -> dict:
    """Send a real ERP notification to everyone who has not posted today.

    The SERVER decides who is missing - the client sends no user ids and
    no text, so this cannot be turned into a spam endpoint. The sender's
    name rides in the notification body, and the whole thing is logged
    like every other board action.
    """
    day = date.today().isoformat()
    roster = await service.roster(session, day=day, include_user_id=user_id)
    missing = [m for m in roster if not m["has_posted"] and m["user_id"] != str(user_id)]
    if not missing:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Everyone has already posted today")
    caller = await session.get(User, user_id)
    sender = (caller.full_name or caller.email) if caller else "A teammate"

    from app.modules.notifications.service import NotificationService

    await NotificationService(session).notify_users(
        [m["user_id"] for m in missing],
        "info",
        "notification.standup_nudge_title",
        body_key="notification.standup_nudge_body",
        body_context={"sender": sender},
        action_url="/team-standup",
        entity_type="team_standup",
        entity_id=day,
    )
    names = ", ".join(m["name"] for m in missing)
    await board_service._log(
        session,
        user_id=user_id,
        what=f"Nudged {names} to post",
        where="Standup",
        kind="standup",
        color="blue",
    )
    await session.commit()
    return {"nudged": [m["name"] for m in missing]}


# ===================================================================
# Delivery board (V3) - the full board, tasks, config, files, log.
# ===================================================================

#: Sized for site video, not just photos - same cap as field_diary.
MAX_ATTACHMENT_BYTES = 200 * 1024 * 1024

ATTACHMENTS_DIR = module_uploads_dir("team_standup", "attachments")

#: Types a browser may render inline; everything else downloads.
_INLINE_MEDIA_PREFIXES = ("image/", "video/", "audio/")
_INLINE_MEDIA_TYPES = {"application/pdf", "text/plain"}


def _week_bounds(day: str) -> tuple[str, str]:
    anchor = date.fromisoformat(day)
    start = anchor - timedelta(days=anchor.weekday())
    return start.isoformat(), (start + timedelta(days=6)).isoformat()


async def _is_admin(session: AsyncSession, user_id: str) -> bool:
    """Live role from the DB, not the JWT - a demoted admin loses the
    private-task override on their next request, not their next login."""
    caller = await session.get(User, user_id)
    return bool(caller and caller.role == "admin")


async def _visible_task_file(session: AsyncSession, file_id: uuid.UUID, user_id: str) -> StandupTaskFile:
    """A task attachment the caller may see - files follow their task's
    visibility, and a private task's files are 404 to outsiders."""
    row = await session.get(StandupTaskFile, str(file_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    task = await session.get(StandupTask, row.task_id)
    if task is not None and not board_service.can_see_task(task, str(user_id), await _is_admin(session, user_id)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return row


@router.get("/full-board", response_model=FullBoardRead)
async def full_board(
    day: str,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.read")),
) -> FullBoardRead:
    """One round trip: the day's entries, the week around it, the whole
    delivery board, its config and the log."""
    try:
        canonical_day = service.parse_day(day).isoformat()
        await board_service.ensure_seeded(session)
        entries = await service.day_entries(session, canonical_day)
        week_start, week_end = _week_bounds(canonical_day)
        week_entries = await service.history(session, from_day=week_start, to_day=week_end)
        roster = await service.roster(session, day=canonical_day, include_user_id=user_id)
    except service.StandupError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    await session.commit()  # persist first-run seeds

    me = await session.get(User, user_id)
    me_name = (me.full_name or me.email) if me else ""
    is_admin = bool(me and me.role == "admin")

    # The visibility rail: a private task reaches only its creator, its
    # assignee and admins - filtered HERE, before anything derives from
    # the list (people, the log), never left to the client.
    tasks = await board_service.board_tasks(session, viewer_id=str(user_id), is_admin=is_admin)

    # People = the self-selecting roster, plus anyone holding a task,
    # plus the caller. Names for pure assignees come off the task's
    # denormalised copy, so the list never needs a users join.
    names: dict[str, str] = {m["user_id"]: m["name"] for m in roster}
    for t in tasks:
        if t.assignee_id and t.assignee_id not in names:
            names[t.assignee_id] = t.assignee_name or "?"
    names.setdefault(str(user_id), me_name)
    people = [
        PersonRead(
            id=uid,
            name=name,
            initials=board_service.person_initials(name),
            color=board_service.person_color(uid),
        )
        for uid, name in names.items()
    ]
    people.sort(key=lambda p: p.name.lower())

    projects = await session.scalars(select(Project).where(Project.status != "archived").order_by(Project.name))
    jobs = [BoardJobRead(**j) for j in await board_service.job_payloads(session, list(projects))]

    return FullBoardRead(
        day=canonical_day,
        today=date.today().isoformat(),
        me=BoardMe(user_id=str(user_id), name=me_name),
        people=people,
        entries=[EntryRead.model_validate(e) for e in entries],
        week=WeekRead(
            start=week_start,
            entries=[EntryRead.model_validate(e) for e in week_entries],
        ),
        stages=[StageRead.model_validate(s) for s in await board_service.stages_ordered(session)],
        stage_overrides={
            pid: [StageRead.model_validate(s) for s in rows]
            for pid, rows in (await board_service.stage_overrides(session)).items()
        },
        activities=[ActivityRead.model_validate(a) for a in await board_service.activities_ordered(session)],
        waits=await board_service.wait_reasons(session),
        tasks=[TaskRead.model_validate(t) for t in tasks],
        jobs=jobs,
        log=[
            LogRead.model_validate(entry)
            for entry in await board_service.recent_log(session, viewer_id=str(user_id), is_admin=is_admin)
        ],
    )


@router.post("/tasks", response_model=list[TaskRead], status_code=status.HTTP_201_CREATED)
async def create_tasks(
    payload: TasksCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.tasks")),
) -> list[TaskRead]:
    try:
        made = await board_service.create_tasks(session, [t.model_dump() for t in payload.tasks], user_id=user_id)
    except service.StandupError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    await session.commit()
    return [TaskRead.model_validate(t) for t in made]


@router.patch("/tasks/{task_id}", response_model=TaskRead)
async def patch_task(
    task_id: uuid.UUID,
    payload: TaskPatch,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.tasks")),
) -> TaskRead:
    try:
        task = await board_service.update_task(
            session,
            task_id=str(task_id),
            fields=payload.model_dump(exclude_unset=True),
            user_id=user_id,
            is_admin=await _is_admin(session, user_id),
        )
    except service.StandupError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    await session.commit()
    return TaskRead.model_validate(task)


@router.post("/tasks/{task_id}/move", response_model=TaskMoveResult)
async def move_task(
    task_id: uuid.UUID,
    payload: TaskMove,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.tasks")),
) -> TaskMoveResult:
    try:
        result = await board_service.move_task(
            session,
            task_id=str(task_id),
            stage_id=payload.stage_id,
            user_id=user_id,
            is_admin=await _is_admin(session, user_id),
        )
    except service.StandupError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    await session.commit()
    return TaskMoveResult(
        task=TaskRead.model_validate(result["task"]),
        spawned=[TaskRead.model_validate(t) for t in result["spawned"]],
        repeated=(TaskRead.model_validate(result["repeated"]) if result["repeated"] is not None else None),
    )


@router.post("/tasks/{task_id}/move-undo", response_model=TaskRead)
async def move_undo(
    task_id: uuid.UUID,
    payload: TaskMoveUndo,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.tasks")),
) -> TaskRead:
    try:
        task = await board_service.undo_move(
            session,
            task_id=str(task_id),
            to_stage_id=payload.to_stage_id,
            spawned_ids=payload.spawned_ids,
            repeated_id=payload.repeated_id,
            user_id=user_id,
            is_admin=await _is_admin(session, user_id),
        )
    except service.StandupError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    await session.commit()
    return TaskRead.model_validate(task)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.tasks")),
) -> None:
    try:
        await board_service.delete_task(
            session,
            task_id=str(task_id),
            user_id=user_id,
            is_admin=await _is_admin(session, user_id),
        )
    except service.StandupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    await session.commit()


@router.post("/tasks/{task_id}/restore", response_model=TaskRead)
async def restore_task(
    task_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.tasks")),
) -> TaskRead:
    try:
        task = await board_service.restore_task(
            session,
            task_id=str(task_id),
            user_id=user_id,
            is_admin=await _is_admin(session, user_id),
        )
    except service.StandupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    await session.commit()
    return TaskRead.model_validate(task)


@router.post(
    "/tasks/{task_id}/comments",
    response_model=TaskCommentRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_task_comment(
    task_id: uuid.UUID,
    payload: CommentCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.comment")),
) -> TaskCommentRead:
    try:
        comment = await board_service.add_task_comment(
            session,
            task_id=str(task_id),
            user_id=user_id,
            body=payload.body,
            is_admin=await _is_admin(session, user_id),
        )
    except service.StandupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    await session.commit()
    return TaskCommentRead.model_validate(comment)


@router.delete("/task-comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_comment(
    comment_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.comment")),
) -> None:
    # Live role from the DB, not the JWT (see delete_comment above).
    caller = await session.get(User, user_id)
    role = caller.role if caller else ""
    try:
        await board_service.delete_task_comment(session, comment_id=str(comment_id), user_id=user_id, role=role)
    except service.StandupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    await session.commit()


# ------------------------------------------------------------ config


@router.put("/config/stages", response_model=list[StageRead])
async def put_stages(
    payload: StagesReplace,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.config")),
) -> list[StageRead]:
    try:
        rows = await board_service.replace_stages(session, [s.model_dump() for s in payload.stages], user_id=user_id)
    except service.StandupError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    await session.commit()
    return [StageRead.model_validate(s) for s in rows]


@router.put("/config/stages/{project_id}", response_model=list[StageRead])
async def put_job_stages(
    project_id: str,
    payload: StagesReplace,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.config")),
) -> list[StageRead]:
    """Give ONE job its own stage run (create or replace). The standard
    stages are untouched; the job's tasks follow by stage name."""
    try:
        rows = await board_service.replace_stages(
            session,
            [s.model_dump() for s in payload.stages],
            user_id=user_id,
            project_id=project_id,
        )
    except service.StandupError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    await session.commit()
    return [StageRead.model_validate(s) for s in rows]


@router.delete("/config/stages/{project_id}", response_model=list[StageRead])
async def delete_job_stages(
    project_id: str,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.config")),
) -> list[StageRead]:
    """Drop a job's own stage run - it goes back to the standard set,
    which is what comes back."""
    try:
        rows = await board_service.remove_stage_override(session, project_id=project_id, user_id=user_id)
    except service.StandupError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    await session.commit()
    return [StageRead.model_validate(s) for s in rows]


@router.post("/config/stages/reset", response_model=list[StageRead])
async def reset_stages(
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.config")),
) -> list[StageRead]:
    rows = await board_service.reset_stages(session, user_id=user_id)
    await session.commit()
    return [StageRead.model_validate(s) for s in rows]


@router.put("/config/activities", response_model=list[ActivityRead])
async def put_activities(
    payload: ActivitiesReplace,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.config")),
) -> list[ActivityRead]:
    try:
        rows = await board_service.replace_activities(
            session, [a.model_dump() for a in payload.activities], user_id=user_id
        )
    except service.StandupError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    await session.commit()
    return [ActivityRead.model_validate(a) for a in rows]


@router.put("/config/waits", response_model=WaitsReplace)
async def put_waits(
    payload: WaitsReplace,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.config")),
) -> WaitsReplace:
    try:
        labels = await board_service.replace_waits(session, payload.reasons, user_id=user_id)
    except service.StandupError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    await session.commit()
    return WaitsReplace(reasons=labels)


# ------------------------------------------------------------- files


def _display_name(raw: str | None) -> str:
    """The client's filename, kept as DISPLAY metadata only. The on-disk
    name is server-derived, so a path here cannot traverse anything -
    but a stored "../../evil.png" would still echo into the download's
    Content-Disposition, so strip it to a basename anyway."""
    name = (raw or "attachment").replace("\\", "/").rsplit("/", 1)[-1].strip()
    return (name or "attachment")[:255]


async def _store_upload(file: UploadFile, prefix: str) -> tuple[str, bytes]:
    """Read, cap and write an upload; returns (storage_key, content).

    The client's filename is metadata only - the on-disk name is
    server-derived, which defuses path traversal by construction.
    """
    try:
        content = await file.read()
    except Exception as exc:  # pragma: no cover - transport failure
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Unable to read uploaded file") from exc
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is empty")
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"Attachment exceeds {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB cap",
        )
    ext = Path(file.filename or "file.bin").suffix or ".bin"
    ext = ext.replace("/", "").replace("\\", "")[:16]
    safe_name = f"{prefix}_{uuid.uuid4().hex[:8]}{ext}"
    filepath = ATTACHMENTS_DIR / safe_name
    # mkdir inside the try - it is the call that fails on an unwritable
    # storage root, and outside it the failure never reaches this handler.
    try:
        ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
        filepath.write_bytes(content)
    except Exception as exc:  # pragma: no cover - storage failure
        logger.exception("Unable to save standup attachment")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Unable to save attachment") from exc
    return f"team_standup/attachments/{safe_name}", content


def _serve_file(storage_key: str, filename: str, mime_type: str) -> FileResponse:
    base = module_uploads_dir().resolve()
    path = (module_uploads_dir() / storage_key).resolve()
    # storage_key is server-written, but verify anyway - defence in depth.
    if not path.is_file() or not path.is_relative_to(base):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File missing from storage")
    inline = mime_type in _INLINE_MEDIA_TYPES or mime_type.startswith(_INLINE_MEDIA_PREFIXES)
    return FileResponse(
        path,
        media_type=mime_type or "application/octet-stream",
        filename=filename or "attachment",
        content_disposition_type="inline" if inline else "attachment",
    )


@router.post(
    "/tasks/{task_id}/files",
    response_model=FileRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_task_file(
    task_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    file: UploadFile = File(...),
    _perm: None = Depends(RequirePermission("team_standup.tasks")),
) -> FileRead:
    try:
        task = await board_service.get_task(
            session,
            str(task_id),
            viewer_id=str(user_id),
            is_admin=await _is_admin(session, user_id),
        )
    except service.StandupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    storage_key, content = await _store_upload(file, str(task_id))
    row = StandupTaskFile(
        task_id=task.id,
        filename=_display_name(file.filename),
        mime_type=(file.content_type or "application/octet-stream")[:120],
        size_bytes=len(content),
        storage_key=storage_key,
        uploaded_by=str(user_id),
    )
    task.files.append(row)
    await board_service._log(
        session,
        user_id=user_id,
        what=f'Attached "{row.filename}" to "{task.title}"',
        where=await board_service._job_code(session, task.project_id),
        kind="task",
        color="teal",
        task_id=str(task.id),
    )
    await session.commit()
    return FileRead.model_validate(row)


@router.delete("/task-files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_file(
    file_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.tasks")),
) -> None:
    row = await _visible_task_file(session, file_id, user_id)
    task = await session.get(StandupTask, row.task_id)
    await board_service._log(
        session,
        user_id=user_id,
        what=f'Removed "{row.filename}"' + (f' from "{task.title}"' if task is not None else ""),
        where=await board_service._job_code(session, task.project_id) if task else "",
        kind="task",
        color="red",
        task_id=str(task.id) if task else "",
    )
    await session.delete(row)
    await session.commit()


@router.get("/task-files/{file_id}/download")
async def download_task_file(
    file_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.read")),
) -> FileResponse:
    row = await _visible_task_file(session, file_id, user_id)
    return _serve_file(row.storage_key, row.filename, row.mime_type)


@router.post(
    "/entries/{entry_id}/files",
    response_model=FileRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_entry_file(
    entry_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    file: UploadFile = File(...),
    _perm: None = Depends(RequirePermission("team_standup.post")),
) -> FileRead:
    entry = await session.get(StandupEntry, str(entry_id))
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entry not found")
    # Own-entry-only: attachments on MY update are mine to add.
    if entry.user_id != str(user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the author can attach to their update")
    storage_key, content = await _store_upload(file, str(entry_id))
    row = StandupEntryFile(
        entry_id=entry.id,
        filename=_display_name(file.filename),
        mime_type=(file.content_type or "application/octet-stream")[:120],
        size_bytes=len(content),
        storage_key=storage_key,
        uploaded_by=str(user_id),
    )
    entry.files.append(row)
    await board_service._log(
        session,
        user_id=user_id,
        what=f'Attached "{row.filename}" to their standup',
        where="Standup",
        kind="standup",
        color="teal",
    )
    await session.commit()
    return FileRead.model_validate(row)


@router.delete("/entry-files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry_file(
    file_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.post")),
) -> None:
    row = await session.get(StandupEntryFile, str(file_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    entry = await session.get(StandupEntry, row.entry_id)
    caller = await session.get(User, user_id)
    role = caller.role if caller else ""
    if entry is not None and entry.user_id != str(user_id) and role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the author (or an admin) can remove it")
    await board_service._log(
        session,
        user_id=user_id,
        what=f'Removed "{row.filename}" from a standup',
        where="Standup",
        kind="standup",
        color="red",
    )
    await session.delete(row)
    await session.commit()


@router.get("/entry-files/{file_id}/download")
async def download_entry_file(
    file_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("team_standup.read")),
) -> FileResponse:
    row = await session.get(StandupEntryFile, str(file_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return _serve_file(row.storage_key, row.filename, row.mime_type)


@router.get("/log", response_model=LogListResponse)
async def read_log(
    session: SessionDep,
    user_id: CurrentUserId,
    limit: int = Query(default=150, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    _perm: None = Depends(RequirePermission("team_standup.read")),
) -> LogListResponse:
    rows = await board_service.recent_log(
        session,
        limit=limit,
        offset=offset,
        viewer_id=str(user_id),
        is_admin=await _is_admin(session, user_id),
    )
    return LogListResponse(
        items=[LogRead.model_validate(entry) for entry in rows],
        total=await board_service.count_log(session),
        limit=limit,
        offset=offset,
    )

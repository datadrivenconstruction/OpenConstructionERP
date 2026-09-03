# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Delivery-board service - stages, tasks, config and the activity log.

House rails, all enforced HERE (server-side), not in the UI:

* moveToStage is ONE code path: every stage change - drag, menu, tick,
  dialog - goes through ``move_task``, which is where stage templates
  spawn follow-ups and a closed recurring task mints its next
  occurrence. A client cannot reach a stage change that skips the
  templates.
* Undo is verified, not trusted: move-undo only deletes tasks whose
  ``origin_task_id`` says this exact move created them, and only while
  they are minutes old.
* Every mutation writes its own log row with the authenticated user's
  name - the log is server-owned and survives a refresh.
* Vocabulary tightens: unknown priorities, repeat rules, link kinds,
  colours, activity ids and job ids are refused, never coerced.
* Private tasks are private on the wire, not just in the UI: every read
  path (the board, the log) filters them to their creator, their
  assignee and admins, and every write path (edit, move, delete,
  comment, files) refuses anyone else as "Task not found" - a task you
  may not see does not exist for you. Only creator/assignee/admin can
  flip a task's visibility.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contacts.models import Contact
from app.modules.projects.models import Project
from app.modules.team_standup.models import (
    LINK_KINDS,
    REPEAT_RULES,
    TASK_PRIORITIES,
    TASK_VISIBILITIES,
    StandupActivity,
    StandupLog,
    StandupStage,
    StandupTask,
    StandupTaskComment,
    StandupWaitReason,
)
from app.modules.team_standup.recurrence import next_occurrence
from app.modules.team_standup.service import (
    MAX_COMMENT_CHARS,
    StandupError,
    _author_name,
    parse_day,
)

#: The 12 palette keys the UI paints with. Colours tighten like any
#: other vocabulary.
COLORS = (
    "slate",
    "violet",
    "indigo",
    "blue",
    "cyan",
    "teal",
    "green",
    "lime",
    "amber",
    "orange",
    "rose",
    "red",
)

#: Avatar colours, assigned by a stable hash of the user id.
PEOPLE_COLORS = (
    "#7b4bc4",
    "#1f7a5c",
    "#b4622a",
    "#2f6fb8",
    "#a83a68",
    "#3a7ca8",
    "#6d6a1f",
    "#54606e",
)

MAX_TITLE_CHARS = 500
MAX_NOTES_CHARS = 4000
MAX_WAIT_CHARS = 200
MAX_BULK_TASKS = 20
MAX_STAGES = 20
MAX_ACTIVITIES = 20
MAX_WAIT_REASONS = 40
#: Follow-ups spawned by a stage template default to due this many days out.
SPAWN_DUE_DAYS = 3
#: move-undo only trusts spawn/repeat tasks younger than this.
UNDO_WINDOW_MINUTES = 30
#: Closed tasks stay on the board this long (the digest's look-back).
CLOSED_KEEP_DAYS = 14
LOG_LIMIT = 150

#: The electrical delivery run - the stage seed for a fresh install,
#: and what "Reset to the electrical run" restores.
DEFAULT_STAGES: list[dict] = [
    {"name": "To do", "color": "slate", "wip_limit": None, "is_done": False, "spawn": []},
    {
        "name": "Design & approvals",
        "color": "violet",
        "wip_limit": None,
        "is_done": False,
        "spawn": ["Get the shop drawings approved"],
    },
    {"name": "Pricing", "color": "indigo", "wip_limit": None, "is_done": False, "spawn": []},
    {
        "name": "Ordered",
        "color": "blue",
        "wip_limit": None,
        "is_done": False,
        "spawn": ["Confirm delivery date", "Book the unload"],
    },
    {
        "name": "Delivered",
        "color": "cyan",
        "wip_limit": None,
        "is_done": False,
        "spawn": ["Check delivery against the order"],
    },
    {"name": "Scheduled", "color": "teal", "wip_limit": None, "is_done": False, "spawn": ["Confirm labour and access"]},
    {"name": "On site", "color": "lime", "wip_limit": 4, "is_done": False, "spawn": []},
    {
        "name": "Test & commission",
        "color": "amber",
        "wip_limit": None,
        "is_done": False,
        "spawn": ["Issue the ITP", "Book the client witness point"],
    },
    {
        "name": "Handover",
        "color": "orange",
        "wip_limit": None,
        "is_done": False,
        "spawn": ["Issue as-builts", "Issue the O&M manuals"],
    },
    {"name": "Closed out", "color": "green", "wip_limit": None, "is_done": True, "spawn": []},
]

DEFAULT_ACTIVITIES: list[dict] = [
    {"name": "In the office", "color": "blue", "exclusive": False},
    {"name": "On site", "color": "green", "exclusive": False},
    {"name": "Working from home", "color": "violet", "exclusive": False},
    {"name": "Travelling", "color": "amber", "exclusive": False},
    {"name": "Client meeting", "color": "rose", "exclusive": False},
    {"name": "On leave", "color": "slate", "exclusive": True},
]

DEFAULT_WAITS = [
    "Supplier price",
    "Supplier delivery date",
    "Client approval",
    "Builder site access",
    "Another trade",
    "Engineer sign-off",
]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _clean(value: str, *, field: str, limit: int) -> str:
    text = (value or "").strip()
    if len(text) > limit:
        raise StandupError(f"{field} is longer than {limit} characters")
    return text


def _clean_day(value: str | None, *, field: str) -> str:
    """'' means no date; anything else must be a strict ISO day."""
    text = (value or "").strip()
    if not text:
        return ""
    return parse_day(text).isoformat()


def person_color(user_id: str) -> str:
    return PEOPLE_COLORS[sum(str(user_id).encode()) % len(PEOPLE_COLORS)]


def person_initials(name: str) -> str:
    parts = [p for p in (name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


async def _log(
    session: AsyncSession,
    *,
    user_id: str,
    what: str,
    where: str = "",
    kind: str = "task",
    color: str = "slate",
    task_id: str = "",
) -> None:
    session.add(
        StandupLog(
            user_id=str(user_id),
            author_name=await _author_name(session, user_id),
            what=what[:500],
            where_label=(where or "")[:120],
            kind=kind,
            color=color if color in COLORS else "slate",
            task_id=str(task_id or "")[:36],
        )
    )


# ---------------------------------------------------------------- config


async def stages_ordered(session: AsyncSession, project_id: str = "") -> list[StandupStage]:
    """The stage rows of ONE scope: the standard set ('' - the default)
    or a job's own override rows (its project id). Empty when the job
    has no override - see :func:`stages_for` for the fallback."""
    rows = await session.scalars(
        select(StandupStage)
        .where(StandupStage.project_id == (project_id or "").strip())
        .order_by(StandupStage.position, StandupStage.created_at)
    )
    return list(rows)


async def stages_for(session: AsyncSession, project_id: str) -> list[StandupStage]:
    """The stages a job's board actually shows: its own override when it
    has one, else the standard set. Every stage-validating path (create,
    move, undo) reads THIS, so a task can only ever sit on a stage its
    job's board has a column for."""
    if (project_id or "").strip():
        own = await stages_ordered(session, project_id)
        if own:
            return own
    return await stages_ordered(session)


async def stage_overrides(session: AsyncSession) -> dict[str, list[StandupStage]]:
    """Every job's own stage run, keyed by project id, in column order."""
    rows = await session.scalars(
        select(StandupStage)
        .where(StandupStage.project_id != "")
        .order_by(StandupStage.position, StandupStage.created_at)
    )
    out: dict[str, list[StandupStage]] = {}
    for s in rows:
        out.setdefault(s.project_id, []).append(s)
    return out


def _rehome_by_name(
    tasks: Iterable[StandupTask],
    old_names: dict[str, str],
    targets: Sequence[StandupStage],
) -> int:
    """Move ``tasks`` onto ``targets`` by their stage's NAME, else the
    first target. Returns how many moved. The one mapping rule for every
    cross-scope hop (standard -> override, override -> standard, reset)."""
    by_name = {s.name: str(s.id) for s in targets}
    target_ids = set(by_name.values())
    first_id = str(targets[0].id)
    moved = 0
    for t in tasks:
        current = str(t.stage_id)
        if current in target_ids:
            continue
        t.stage_id = by_name.get(old_names.get(current, ""), first_id)
        moved += 1
    return moved


async def activities_ordered(session: AsyncSession) -> list[StandupActivity]:
    rows = await session.scalars(select(StandupActivity).order_by(StandupActivity.position, StandupActivity.created_at))
    return list(rows)


async def wait_reasons(session: AsyncSession) -> list[str]:
    rows = await session.scalars(
        select(StandupWaitReason).order_by(StandupWaitReason.position, StandupWaitReason.created_at)
    )
    return [r.label for r in rows]


async def ensure_seeded(session: AsyncSession) -> None:
    """First board load on a fresh install plants the defaults."""
    if not await stages_ordered(session):
        for i, s in enumerate(DEFAULT_STAGES):
            session.add(StandupStage(position=i, **s))
    if not await activities_ordered(session):
        for i, a in enumerate(DEFAULT_ACTIVITIES):
            session.add(StandupActivity(position=i, **a))
    if not await wait_reasons(session):
        for i, w in enumerate(DEFAULT_WAITS):
            session.add(StandupWaitReason(label=w, position=i))
    await session.flush()


def _validate_color(color: str) -> str:
    if color not in COLORS:
        raise StandupError(f"Unknown colour {color!r}")
    return color


async def replace_stages(
    session: AsyncSession,
    payload: list[dict],
    *,
    user_id: str,
    project_id: str = "",
) -> list[StandupStage]:
    """Replace the stage list wholesale - the customise panel's save.

    Existing stages are matched by id (renames keep their tasks); stages
    missing from the payload are deleted after their tasks are moved to
    the nearest surviving earlier stage. At least two stages must remain.

    With ``project_id`` the replace is scoped to THAT job's own stage
    run: rows are created under the project, the standard set is not
    touched, and the job's tasks that still sit on standard stages are
    carried across by stage name (else the first override stage) - so
    the first save of an override moves the whole job onto its own board.
    """
    if not 2 <= len(payload) <= MAX_STAGES:
        raise StandupError(f"A board needs between 2 and {MAX_STAGES} stages")
    project_id = (project_id or "").strip()
    if project_id:
        project_id = await _validate_project(session, project_id)
    current = await stages_ordered(session, project_id)
    by_id = {str(s.id): s for s in current}
    result: list[StandupStage] = []
    for pos, item in enumerate(payload):
        name = _clean(str(item.get("name", "")), field="Stage name", limit=120)
        if not name:
            raise StandupError("A stage needs a name")
        color = _validate_color(str(item.get("color", "slate")))
        wip = item.get("wip_limit")
        if wip is not None:
            wip = max(0, int(wip))
        spawn = [
            _clean(str(t), field="Follow-up title", limit=MAX_TITLE_CHARS)
            for t in (item.get("spawn") or [])
            if str(t).strip()
        ][:10]
        row = by_id.get(str(item.get("id") or ""))
        if row is None:
            # An id from another scope (a standard stage id echoed back
            # into a job's override) is NOT an update of that row: the
            # job gets its own copy, the standard set stays as it was.
            row = StandupStage(project_id=project_id)
            session.add(row)
        row.name = name
        row.color = color
        row.position = pos
        row.wip_limit = wip
        row.is_done = bool(item.get("is_done"))
        row.spawn = spawn
        result.append(row)
    await session.flush()
    keep_ids = {str(r.id) for r in result}

    # Delete the dropped stages, moving their tasks to the nearest
    # surviving stage that sat EARLIER in the old order (the preview's
    # "row above" semantics), falling back to the new first stage.
    old_order = [str(s.id) for s in current]
    for sid in old_order:
        if sid in keep_ids:
            continue
        target_id = str(result[0].id)
        for earlier in reversed(old_order[: old_order.index(sid)]):
            if earlier in keep_ids:
                target_id = earlier
                break
        moved = await session.scalars(select(StandupTask).where(StandupTask.stage_id == sid))
        count = 0
        for t in moved:
            t.stage_id = target_id
            count += 1
        stage = by_id[sid]
        await _log(
            session,
            user_id=user_id,
            what=f'Deleted the "{stage.name}" stage' + (f" ({count} task(s) moved)" if count else ""),
            where="Settings",
            kind="config",
            color="red",
        )
        await session.delete(stage)
    if project_id:
        # The job's tasks still sitting on standard stages (its first
        # override save, or a task created before one existed) follow by
        # stage name, so "Pricing" stays "Pricing" on the job's own board.
        standard = await stages_ordered(session)
        old_names = {str(s.id): s.name for s in standard}
        own_tasks = await session.scalars(select(StandupTask).where(StandupTask.project_id == project_id))
        _rehome_by_name(own_tasks, old_names, result)
    await _log(
        session,
        user_id=user_id,
        what=(
            f"Changed the delivery stages for {await _job_code(session, project_id)}"
            if project_id
            else "Changed the delivery stages"
        ),
        where="Settings",
        kind="config",
        color="slate",
    )
    await session.flush()
    return await stages_ordered(session, project_id)


async def remove_stage_override(session: AsyncSession, *, project_id: str, user_id: str) -> list[StandupStage]:
    """Put a job back on the standard stages. Its tasks cross by stage
    NAME (else the first standard stage), then the override rows go.
    Returns the standard set. A job with no override is a no-op."""
    project_id = (project_id or "").strip()
    own = await stages_ordered(session, project_id) if project_id else []
    standard = await stages_ordered(session)
    if not own:
        return standard
    if not standard:
        raise StandupError("The board has no standard stages to fall back to")
    old_names = {str(s.id): s.name for s in own}
    tasks = await session.scalars(select(StandupTask).where(StandupTask.stage_id.in_([str(s.id) for s in own])))
    moved = _rehome_by_name(tasks, old_names, standard)
    for s in own:
        await session.delete(s)
    await _log(
        session,
        user_id=user_id,
        what=f"Put {await _job_code(session, project_id)} back on the standard stages"
        + (f" ({moved} task(s) moved)" if moved else ""),
        where="Settings",
        kind="config",
        color="slate",
    )
    await session.flush()
    return standard


async def reset_stages(session: AsyncSession, *, user_id: str) -> list[StandupStage]:
    """Back to the electrical run. Tasks follow their stage NAME where a
    default of the same name exists; anything else lands in the first
    stage rather than being lost."""
    current = await stages_ordered(session)
    old_names = {str(s.id): s.name for s in current}
    fresh: list[StandupStage] = []
    for i, s in enumerate(DEFAULT_STAGES):
        row = StandupStage(position=i, **s)
        session.add(row)
        fresh.append(row)
    await session.flush()
    # Only the tasks on the standard run move; a job on its own override
    # stages keeps its board exactly as it was.
    tasks = await session.scalars(select(StandupTask).where(StandupTask.stage_id.in_(list(old_names))))
    _rehome_by_name(tasks, old_names, fresh)
    for s in current:
        await session.delete(s)
    await _log(
        session,
        user_id=user_id,
        what="Reset the stages to the electrical run",
        where="Settings",
        kind="config",
        color="slate",
    )
    await session.flush()
    return await stages_ordered(session)


async def replace_activities(session: AsyncSession, payload: list[dict], *, user_id: str) -> list[StandupActivity]:
    if not 2 <= len(payload) <= MAX_ACTIVITIES:
        raise StandupError(f"Keep between 2 and {MAX_ACTIVITIES} activities")
    current = await activities_ordered(session)
    by_id = {str(a.id): a for a in current}
    result: list[StandupActivity] = []
    for pos, item in enumerate(payload):
        name = _clean(str(item.get("name", "")), field="Activity name", limit=120)
        if not name:
            raise StandupError("An activity needs a name")
        row = by_id.get(str(item.get("id") or ""))
        if row is None:
            row = StandupActivity()
            session.add(row)
        row.name = name
        row.color = _validate_color(str(item.get("color", "slate")))
        row.position = pos
        row.exclusive = bool(item.get("exclusive"))
        result.append(row)
    await session.flush()
    keep = {str(r.id) for r in result}
    for a in current:
        if str(a.id) not in keep:
            await session.delete(a)
    await _log(
        session,
        user_id=user_id,
        what="Changed the activity list",
        where="Settings",
        kind="config",
        color="slate",
    )
    await session.flush()
    return await activities_ordered(session)


async def replace_waits(session: AsyncSession, labels: list[str], *, user_id: str) -> list[str]:
    cleaned: list[str] = []
    for raw in labels:
        label = _clean(str(raw), field="Waiting reason", limit=160)
        if label and label not in cleaned:
            cleaned.append(label)
    if len(cleaned) > MAX_WAIT_REASONS:
        raise StandupError(f"Keep the waiting-on list under {MAX_WAIT_REASONS} entries")
    for row in await session.scalars(select(StandupWaitReason)):
        await session.delete(row)
    for i, label in enumerate(cleaned):
        session.add(StandupWaitReason(label=label, position=i))
    await _log(
        session,
        user_id=user_id,
        what="Edited the waiting-on list",
        where="Settings",
        kind="config",
        color="amber",
    )
    await session.flush()
    return await wait_reasons(session)


# ----------------------------------------------------------------- tasks


async def _job_code(session: AsyncSession, project_id: str) -> str:
    if not project_id:
        return ""
    p = await session.get(Project, project_id)
    if p is None:
        return ""
    return p.project_code or str(p.id)[:8]


async def _validate_project(session: AsyncSession, project_id: str) -> str:
    project_id = str(project_id or "").strip()
    if not project_id:
        raise StandupError("A task needs a job")
    p = await session.get(Project, project_id)
    if p is None or p.status == "archived":
        raise StandupError("That job does not exist or is archived")
    return str(p.id)


async def _assignee(session: AsyncSession, assignee_id: str, fallback: str) -> tuple[str, str]:
    uid = str(assignee_id or "").strip() or str(fallback)
    return uid, await _author_name(session, uid)


def _validate_priority(p: str) -> str:
    if p not in TASK_PRIORITIES:
        raise StandupError(f"Priority must be one of {', '.join(TASK_PRIORITIES)}")
    return p


def _validate_repeat(r: str) -> str:
    if r not in REPEAT_RULES:
        raise StandupError("Unknown repeat rule")
    return r


#: Record kinds a task may link to - the model's vocabulary, which now
#: names the Work requests module's ``request`` too (a department request
#: - engineering, drafting, workshop, automation, hazardous area). That
#: module ships as its own package with its own tables; the board only
#: accepts the kind and carries the request's id in ``link_target_id`` so
#: the chip can open it.
ACCEPTED_LINK_KINDS: frozenset[str] = frozenset(LINK_KINDS)


def _validate_link_kind(k: str) -> str:
    if k not in ACCEPTED_LINK_KINDS:
        raise StandupError("Unknown record type")
    return k


def _validate_visibility(v: str) -> str:
    if v not in TASK_VISIBILITIES:
        raise StandupError("Visibility must be public or private")
    return v


def can_see_task(task: StandupTask, viewer_id: str, is_admin: bool = False) -> bool:
    """THE visibility rule. A public task is everyone's; a private one
    belongs to its creator, its assignee and admins. Every read filter
    and every write guard calls this - there is no second definition."""
    if task.visibility != "private" or is_admin:
        return True
    viewer = str(viewer_id or "")
    return bool(viewer) and viewer in (str(task.created_by), str(task.assignee_id))


def can_set_visibility(task: StandupTask, user_id: str, is_admin: bool = False) -> bool:
    """Who may flip public/private: the same three parties."""
    if is_admin:
        return True
    uid = str(user_id or "")
    return bool(uid) and uid in (str(task.created_by), str(task.assignee_id))


async def get_task(
    session: AsyncSession,
    task_id: str,
    *,
    viewer_id: str | None = None,
    is_admin: bool = False,
) -> StandupTask:
    """A live task. With ``viewer_id`` the visibility rail applies: a
    private task the viewer may not see is "not found" - its existence
    is not confirmed to anyone outside it."""
    task = await session.get(StandupTask, task_id)
    if task is None or task.deleted:
        raise StandupError("Task not found")
    if viewer_id is not None and not can_see_task(task, viewer_id, is_admin):
        raise StandupError("Task not found")
    return task


async def create_tasks(session: AsyncSession, items: list[dict], *, user_id: str) -> list[StandupTask]:
    """The multi-row composer's save - up to MAX_BULK_TASKS in one call."""
    if not items:
        raise StandupError("Nothing to create")
    if len(items) > MAX_BULK_TASKS:
        raise StandupError(f"At most {MAX_BULK_TASKS} tasks per call")
    if not await stages_ordered(session):
        raise StandupError("The board has no stages yet")
    made: list[StandupTask] = []
    for item in items:
        title = _clean(str(item.get("title", "")), field="Task", limit=MAX_TITLE_CHARS)
        if not title:
            raise StandupError("A task needs a description")
        project_id = await _validate_project(session, item.get("project_id", ""))
        # The job's own board decides which stages exist for its tasks.
        stages = await stages_for(session, project_id)
        stage_ids = {str(s.id) for s in stages}
        stage_id = str(item.get("stage_id") or stages[0].id)
        if stage_id not in stage_ids:
            raise StandupError("Unknown stage")
        assignee_id, assignee_name = await _assignee(session, item.get("assignee_id", ""), user_id)
        task = StandupTask(
            title=title,
            project_id=project_id,
            stage_id=stage_id,
            assignee_id=assignee_id,
            assignee_name=assignee_name,
            due=_clean_day(item.get("due"), field="Due"),
            priority=_validate_priority(str(item.get("priority", "medium"))),
            waiting_on=_clean(str(item.get("waiting_on", "")), field="Waiting on", limit=MAX_WAIT_CHARS),
            notes=_clean(str(item.get("notes", "")), field="Notes", limit=MAX_NOTES_CHARS),
            repeat_rule=_validate_repeat(str(item.get("repeat_rule", ""))),
            link_kind=_validate_link_kind(str(item.get("link_kind", ""))),
            link_ref=_clean(str(item.get("link_ref", "")), field="Reference", limit=80),
            link_target_id=str(item.get("link_target_id", "") or "")[:36],
            is_sub=False,
            visibility=_validate_visibility(str(item.get("visibility") or "public")),
            created_by=str(user_id),
            comments=[],
            files=[],
        )
        session.add(task)
        made.append(task)
    await session.flush()
    where = await _job_code(session, made[0].project_id)
    # A bulk line names no title, so it carries no task; a single-task
    # line names the title and follows that task's visibility.
    await _log(
        session,
        user_id=user_id,
        what=f"Created {len(made)} task(s)" if len(made) > 1 else f'Created "{made[0].title}"',
        where=where,
        kind="task",
        color="green",
        task_id=str(made[0].id) if len(made) == 1 else "",
    )
    await session.flush()
    return made


async def update_task(
    session: AsyncSession,
    *,
    task_id: str,
    fields: dict,
    user_id: str,
    is_admin: bool = False,
) -> StandupTask:
    """The edit dialog's save. Stage is NOT accepted here - stage changes
    go through move_task so the templates always fire. ``visibility`` is
    accepted only from the creator, the assignee or an admin."""
    task = await get_task(session, task_id, viewer_id=user_id, is_admin=is_admin)
    changes: list[str] = []

    if "visibility" in fields and fields["visibility"] is not None:
        v = _validate_visibility(str(fields["visibility"]))
        if v != task.visibility:
            if not can_set_visibility(task, user_id, is_admin):
                raise PermissionError("Only the task's creator, its assignee or an admin can change who sees it")
            changes.append("made private" if v == "private" else "made public")
            task.visibility = v

    if "title" in fields:
        v = _clean(str(fields["title"] or ""), field="Task", limit=MAX_TITLE_CHARS)
        if v and v != task.title:
            changes.append(f'renamed to "{v}"')
            task.title = v
    if "project_id" in fields:
        v = await _validate_project(session, fields["project_id"])
        if v != task.project_id:
            changes.append(f"moved to job {await _job_code(session, v)}")
            task.project_id = v
    if "assignee_id" in fields:
        uid, name = await _assignee(session, fields["assignee_id"], task.assignee_id)
        if uid != task.assignee_id:
            changes.append(f"assigned to {name}")
            task.assignee_id, task.assignee_name = uid, name
    if "due" in fields:
        v = _clean_day(fields["due"], field="Due")
        if v != task.due:
            changes.append(f"due {v}" if v else "due date cleared")
            task.due = v
    if "priority" in fields:
        v = _validate_priority(str(fields["priority"]))
        if v != task.priority:
            changes.append(f"priority {v}")
            task.priority = v
    if "waiting_on" in fields:
        v = _clean(str(fields["waiting_on"] or ""), field="Waiting on", limit=MAX_WAIT_CHARS)
        if v != task.waiting_on:
            changes.append(f"waiting on {v}" if v else "waiting cleared")
            task.waiting_on = v
    if "notes" in fields:
        v = _clean(str(fields["notes"] or ""), field="Notes", limit=MAX_NOTES_CHARS)
        if v != task.notes:
            changes.append("notes updated")
            task.notes = v
    if "repeat_rule" in fields:
        v = _validate_repeat(str(fields["repeat_rule"] or ""))
        if v != task.repeat_rule:
            changes.append(f"repeats {v}" if v else "no longer repeats")
            task.repeat_rule = v
    if "link_kind" in fields or "link_ref" in fields:
        kind = _validate_link_kind(str(fields.get("link_kind", task.link_kind) or ""))
        ref = _clean(str(fields.get("link_ref", task.link_ref) or ""), field="Reference", limit=80)
        target = str(fields.get("link_target_id", task.link_target_id) or "")[:36]
        if not kind or not ref:
            kind, ref, target = "", "", ""
        if (kind, ref) != (task.link_kind, task.link_ref):
            changes.append(f"linked to {kind.upper()} {ref}" if ref else "link removed")
        task.link_kind, task.link_ref, task.link_target_id = kind, ref, target

    if changes:
        await _log(
            session,
            user_id=user_id,
            what=f'Edited "{task.title}": {", ".join(changes)}',
            where=await _job_code(session, task.project_id),
            kind="task",
            color="blue",
            task_id=str(task.id),
        )
    await session.flush()
    return task


async def move_task(
    session: AsyncSession,
    *,
    task_id: str,
    stage_id: str,
    user_id: str,
    is_admin: bool = False,
) -> dict:
    """THE stage-change path. Spawns the target stage's template
    follow-ups (skipping any open task with the same title on the same
    job) and, when the target closes the task and it repeats, mints the
    next occurrence FROM THE SCHEDULED DATE. Follow-ups and the next
    occurrence inherit the task's visibility."""
    task = await get_task(session, task_id, viewer_id=user_id, is_admin=is_admin)
    stages = await stages_for(session, task.project_id)
    by_id = {str(s.id): s for s in stages}
    target = by_id.get(str(stage_id))
    if target is None:
        raise StandupError("Unknown stage")
    if str(task.stage_id) == str(target.id):
        return {"task": task, "spawned": [], "repeated": None}
    entry_stage = stages[0]

    task.stage_id = str(target.id)
    task.completed_at = _utcnow() if target.is_done else None
    where = await _job_code(session, task.project_id)
    await _log(
        session,
        user_id=user_id,
        what=f'Moved "{task.title}" to {target.name}',
        where=where,
        kind="task",
        color=target.color,
        task_id=str(task.id),
    )

    spawned: list[StandupTask] = []
    if target.spawn:
        open_titles = {
            t.title
            for t in await session.scalars(
                select(StandupTask).where(
                    StandupTask.project_id == task.project_id,
                    StandupTask.deleted.is_(False),
                )
            )
            if not by_id.get(str(t.stage_id), target).is_done
        }
        for title in target.spawn:
            if title in open_titles:
                continue
            follow = StandupTask(
                title=title,
                project_id=task.project_id,
                stage_id=str(entry_stage.id),
                assignee_id=task.assignee_id,
                assignee_name=task.assignee_name,
                due=(date.today() + timedelta(days=SPAWN_DUE_DAYS)).isoformat(),
                priority="medium",
                notes=f"From the {target.name} template.",
                link_kind=task.link_kind,
                link_ref=task.link_ref,
                link_target_id=task.link_target_id,
                is_sub=True,
                visibility=task.visibility,
                origin="spawn",
                origin_task_id=str(task.id),
                created_by=str(user_id),
                comments=[],
                files=[],
            )
            session.add(follow)
            spawned.append(follow)
        if spawned:
            await _log(
                session,
                user_id=user_id,
                what=f"Stage template added {len(spawned)} follow-up(s)",
                where=where,
                kind="task",
                color="cyan",
                task_id=str(task.id),
            )

    repeated: StandupTask | None = None
    if target.is_done and task.repeat_rule:
        next_due = next_occurrence(task.due or date.today().isoformat(), task.repeat_rule)
        if next_due:
            repeated = StandupTask(
                title=task.title,
                project_id=task.project_id,
                stage_id=str(entry_stage.id),
                assignee_id=task.assignee_id,
                assignee_name=task.assignee_name,
                due=next_due,
                priority=task.priority,
                notes=task.notes,
                repeat_rule=task.repeat_rule,
                link_kind=task.link_kind,
                link_ref=task.link_ref,
                link_target_id=task.link_target_id,
                is_sub=task.is_sub,
                visibility=task.visibility,
                origin="repeat",
                origin_task_id=str(task.id),
                created_by=str(user_id),
                comments=[],
                files=[],
            )
            session.add(repeated)
            await _log(
                session,
                user_id=user_id,
                what=f'"{task.title}" repeats - next one due {next_due}',
                where=where,
                kind="task",
                color="cyan",
                task_id=str(task.id),
            )

    await session.flush()
    return {"task": task, "spawned": spawned, "repeated": repeated}


async def undo_move(
    session: AsyncSession,
    *,
    task_id: str,
    to_stage_id: str,
    spawned_ids: list[str],
    repeated_id: str | None,
    user_id: str,
    is_admin: bool = False,
) -> StandupTask:
    """Reverse one move. Only deletes tasks this exact move created -
    verified by origin_task_id + origin + age - so a stale or forged undo
    cannot reach anything else."""
    task = await get_task(session, task_id, viewer_id=user_id, is_admin=is_admin)
    stage_rows = {str(s.id): s for s in await stages_for(session, task.project_id)}
    if str(to_stage_id) not in stage_rows:
        raise StandupError("Unknown stage")
    cutoff = _utcnow() - timedelta(minutes=UNDO_WINDOW_MINUTES)

    async def _created_by_move(cid: str, origin: str) -> StandupTask | None:
        child = await session.get(StandupTask, cid)
        if child is None:
            return None
        created = child.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        if child.origin != origin or child.origin_task_id != str(task.id) or created < cutoff:
            raise StandupError("That undo has expired")
        return child

    for cid in spawned_ids[:10]:
        child = await _created_by_move(str(cid), "spawn")
        if child is not None:
            await session.delete(child)
    if repeated_id:
        child = await _created_by_move(str(repeated_id), "repeat")
        if child is not None:
            await session.delete(child)

    task.stage_id = str(to_stage_id)
    task.completed_at = _utcnow() if stage_rows[str(to_stage_id)].is_done else None
    await _log(
        session,
        user_id=user_id,
        what=f'Moved "{task.title}" back',
        where=await _job_code(session, task.project_id),
        kind="task",
        color="slate",
        task_id=str(task.id),
    )
    await session.flush()
    return task


async def delete_task(session: AsyncSession, *, task_id: str, user_id: str, is_admin: bool = False) -> None:
    task = await get_task(session, task_id, viewer_id=user_id, is_admin=is_admin)
    task.deleted = True
    await _log(
        session,
        user_id=user_id,
        what=f'Deleted "{task.title}"',
        where=await _job_code(session, task.project_id),
        kind="task",
        color="red",
        task_id=str(task.id),
    )
    await session.flush()


async def restore_task(session: AsyncSession, *, task_id: str, user_id: str, is_admin: bool = False) -> StandupTask:
    task = await session.get(StandupTask, task_id)
    if task is None or not task.deleted or not can_see_task(task, user_id, is_admin):
        raise StandupError("Nothing to restore")
    task.deleted = False
    await _log(
        session,
        user_id=user_id,
        what=f'Restored "{task.title}"',
        where=await _job_code(session, task.project_id),
        kind="task",
        color="green",
        task_id=str(task.id),
    )
    await session.flush()
    return task


async def add_task_comment(
    session: AsyncSession,
    *,
    task_id: str,
    user_id: str,
    body: str,
    is_admin: bool = False,
) -> StandupTaskComment:
    task = await get_task(session, task_id, viewer_id=user_id, is_admin=is_admin)
    body = _clean(body, field="Comment", limit=MAX_COMMENT_CHARS)
    if not body:
        raise StandupError("Comment is empty")
    comment = StandupTaskComment(
        task_id=task.id,
        user_id=str(user_id),
        author_name=await _author_name(session, user_id),
        body=body,
    )
    task.comments.append(comment)
    await _log(
        session,
        user_id=user_id,
        what=f'Commented on "{task.title}"',
        where=await _job_code(session, task.project_id),
        kind="task",
        color="violet",
        task_id=str(task.id),
    )
    await session.flush()
    return comment


async def delete_task_comment(session: AsyncSession, *, comment_id: str, user_id: str, role: str) -> None:
    comment = await session.get(StandupTaskComment, comment_id)
    if comment is None:
        raise StandupError("Comment not found")
    task = await session.get(StandupTask, comment.task_id)
    # A comment on a private task follows the task: outside its circle
    # it does not exist, and only its author or an admin removes it.
    if task is not None and not can_see_task(task, user_id, role == "admin"):
        raise StandupError("Comment not found")
    if comment.user_id != str(user_id) and role != "admin":
        raise PermissionError("Only the author (or an admin) can delete a comment")
    if task is not None:
        task.comments.remove(comment)
        await _log(
            session,
            user_id=user_id,
            what=f'Deleted a comment on "{task.title}"',
            where=await _job_code(session, task.project_id),
            kind="task",
            color="red",
            task_id=str(task.id),
        )
    else:  # pragma: no cover - orphan safety
        await session.delete(comment)
    await session.flush()


async def board_tasks(session: AsyncSession, *, viewer_id: str = "", is_admin: bool = False) -> list[StandupTask]:
    """Everything live FOR THIS VIEWER: open tasks, plus tasks closed in
    the last CLOSED_KEEP_DAYS (the digest's look-back), never deleted
    rows - and never a private task the viewer is outside of. With no
    viewer (internal callers) private tasks are dropped altogether."""
    cutoff = _utcnow() - timedelta(days=CLOSED_KEEP_DAYS)
    rows = await session.scalars(
        select(StandupTask).where(StandupTask.deleted.is_(False)).order_by(StandupTask.created_at)
    )
    out = []
    for t in rows:
        if not can_see_task(t, viewer_id, is_admin):
            continue
        if t.completed_at is not None:
            completed = t.completed_at
            if completed.tzinfo is None:
                completed = completed.replace(tzinfo=UTC)
            if completed < cutoff:
                continue
        out.append(t)
    return out


async def count_log(session: AsyncSession) -> int:
    """How many log lines exist. Privacy redacts lines from a page after
    it is read, so this counts the log rather than one viewer's view of
    it: the number says how far back the feed goes, not how much of it
    any one person will be served."""
    return int((await session.execute(select(func.count()).select_from(StandupLog))).scalar_one())


async def recent_log(
    session: AsyncSession,
    limit: int = LOG_LIMIT,
    *,
    offset: int = 0,
    viewer_id: str = "",
    is_admin: bool = False,
) -> list[StandupLog]:
    """The latest log lines the viewer may read. A line about a private
    task names its title, so it is served only to those who may see the
    task (the task's CURRENT circle - a reassignment moves the history
    with it). Lines about no task at all are everyone's."""
    rows = list(
        await session.scalars(
            select(StandupLog).order_by(StandupLog.created_at.desc()).limit(limit).offset(max(0, offset))
        )
    )
    if is_admin:
        return rows
    ids = {r.task_id for r in rows if r.task_id}
    if not ids:
        return rows
    hidden: set[str] = set()
    private = await session.scalars(
        select(StandupTask).where(StandupTask.id.in_(list(ids)), StandupTask.visibility == "private")
    )
    for t in private:
        if not can_see_task(t, viewer_id, is_admin):
            hidden.add(str(t.id))
    return [r for r in rows if r.task_id not in hidden]


def _as_uuid(value: str | None) -> uuid.UUID | None:
    """The UUID a ``client_id`` names, or None for empty / legacy free text."""
    raw = (value or "").strip()
    if len(raw) != 36:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


def _contact_name(company: str | None, first: str | None, last: str | None) -> str:
    """Company name first, else the person's name - the label a client shows as."""
    company = (company or "").strip()
    if company:
        return company
    return " ".join(part for part in ((first or "").strip(), (last or "").strip()) if part)


_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def brand_color_of(custom_properties: dict | None) -> str:
    """The client's brand colour off its contact, as a hex string, or ''.

    The contacts module keeps it in ``custom_properties.brand_color``;
    a module-namespaced bucket carrying the same key is honoured too.
    Anything that is not a ``#rgb`` / ``#rrggbb`` hex is treated as unset
    - the board paints it straight into an inline style.
    """
    props = custom_properties or {}
    candidates = [props.get("brand_color")]
    candidates += [v.get("brand_color") for v in props.values() if isinstance(v, dict)]
    for raw in candidates:
        text = str(raw or "").strip()
        if text and _HEX_COLOR.match(text):
            return text.lower()
    return ""


async def client_rows_for(session: AsyncSession, projects: Iterable[Project]) -> dict[str, tuple[str, str]]:
    """Resolve every project's contact-backed client in ONE query.

    Returns ``{lowercased client_id: (display name, brand colour)}`` for
    the ``client_id`` values that are UUIDs naming an
    ``oe_contacts_contact`` row. Legacy free-text ids and dangling UUIDs
    are simply absent, so the caller falls through to the next rule.
    """
    wanted: dict[uuid.UUID, str] = {}
    for p in projects:
        cid = _as_uuid(p.client_id)
        if cid is not None:
            wanted[cid] = (p.client_id or "").strip().lower()
    if not wanted:
        return {}
    rows = await session.execute(
        select(
            Contact.id,
            Contact.company_name,
            Contact.first_name,
            Contact.last_name,
            Contact.custom_properties,
        ).where(Contact.id.in_(list(wanted)))
    )
    found: dict[str, tuple[str, str]] = {}
    for cid, company, first, last, props in rows:
        label = _contact_name(company, first, last)
        if label:
            found[str(cid).lower()] = (label, brand_color_of(props))
    return found


async def client_names_for(session: AsyncSession, projects: Iterable[Project]) -> dict[str, str]:
    """:func:`client_rows_for` reduced to ``{client_id: display name}``."""
    return {k: v[0] for k, v in (await client_rows_for(session, projects)).items()}


def resolved_client(p: Project, names: dict[str, str]) -> str:
    """The client a project's ``client_id`` says it has, or '' to fall back.

    * a UUID that ``names`` resolved -> the contact's name
    * a non-empty value that is not a UUID -> that text, verbatim (a client
      typed before the picker existed)
    * empty, or a UUID no contact answers to -> '' (the caller reads the name)
    """
    raw = (p.client_id or "").strip()
    if not raw:
        return ""
    if _as_uuid(raw) is not None:
        return names.get(raw.lower(), "")
    return raw


def job_payload(p: Project, client_name: str | None = None, client_color: str = "") -> dict:
    """A job as the board wants it: short code, client, work description.

    ``client_name`` is what the project's ``client_id`` resolves to (see
    :func:`resolved_client`) and wins when present. Otherwise many projects
    carry "Client - what the job is" names; where that pattern holds, the
    part before the first " - " renders as the client family (and drives
    the colour); otherwise the whole name is the label and the client
    column stays quiet. The label is always the name-derived work
    description, whichever way the client was found.

    ``client_color`` is the client contact's brand colour (a hex string,
    '' when unset) - the board paints the job's chips with it.
    """
    name = p.name or ""
    client, label = "", name
    if " - " in name:
        client, label = name.split(" - ", 1)
    resolved = (client_name or "").strip()
    return {
        "id": str(p.id),
        "code": p.project_code or str(p.id)[:8],
        "client": resolved or client.strip(),
        "client_color": client_color if resolved else "",
        "label": label.strip(),
        "name": name,
    }


async def job_payloads(session: AsyncSession, projects: Sequence[Project]) -> list[dict]:
    """:func:`job_payload` for a batch, with clients resolved in one query."""
    rows = await client_rows_for(session, projects)
    names = {k: v[0] for k, v in rows.items()}
    out = []
    for p in projects:
        key = (p.client_id or "").strip().lower()
        color = rows[key][1] if key in rows else ""
        out.append(job_payload(p, resolved_client(p, names), color))
    return out

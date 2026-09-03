# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Team Standup service - validation rails and queries.

House rails, all enforced HERE (server-side), not in the UI:

* You can only ever write YOUR OWN entry - the caller's user id comes
  from the token, never from the payload.
* An unreadable day tightens, never loosens: junk, impossible dates and
  far-future days are refused, not coerced.
* The roster is self-selecting: whoever posted in the trailing window is
  "the team". No config screen, no stale member list, and service
  accounts that never post never appear.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.tasks.models import Task
from app.modules.team_standup.models import (
    ENTRY_STATUSES,
    MAX_COMMENT_CHARS,
    MAX_FIELD_CHARS,
    StandupActivity,
    StandupComment,
    StandupEntry,
)
from app.modules.users.models import User

#: How far ahead an entry may be posted. One day of slack covers every
#: timezone offset between the server clock and someone posting from
#: site; a standup for next week is a typo, not a plan.
MAX_FUTURE_DAYS = 1

#: How far back an entry may be backfilled (catch-up after leave is
#: fine; editing last year's history is not).
MAX_BACKFILL_DAYS = 366

#: Anyone who posted in this trailing window counts as "on the team"
#: for the roster / not-posted-yet line.
ROSTER_WINDOW_DAYS = 45

#: Widest from/to range a history or blockers query will serve.
MAX_RANGE_DAYS = 92

#: Most jobs one entry may tag - a person is not on 21 jobs in one day.
MAX_JOBS_PER_ENTRY = 20

#: Open tasks shown per person on the board (total count still reported).
MAX_TASKS_PER_MEMBER = 8


class StandupError(Exception):
    """Validation refusal - the router answers 422 with this message."""


def parse_day(value: str) -> date:
    """Parse a strict ISO ``YYYY-MM-DD`` day or refuse."""
    text = (value or "").strip()
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        raise StandupError(f"Day must be a real date in YYYY-MM-DD form, got {text!r}") from None
    # fromisoformat accepts e.g. "20260901"; the board keys on the dashed
    # form, so hold the exact shape.
    if parsed.isoformat() != text:
        raise StandupError(f"Day must be in YYYY-MM-DD form, got {text!r}")
    return parsed


def _validate_writable_day(value: str) -> str:
    parsed = parse_day(value)
    today = date.today()
    if parsed > today + timedelta(days=MAX_FUTURE_DAYS):
        raise StandupError("A standup can be posted for today, not the future")
    if parsed < today - timedelta(days=MAX_BACKFILL_DAYS):
        raise StandupError("That day is too far in the past to backfill")
    return parsed.isoformat()


def _clean_text(value: str, *, field: str, limit: int = MAX_FIELD_CHARS) -> str:
    text = (value or "").strip()
    if len(text) > limit:
        raise StandupError(f"{field} is longer than {limit} characters")
    return text


async def _author_name(session: AsyncSession, user_id: str) -> str:
    user = await session.get(User, user_id)
    if user is None:
        raise StandupError("Unknown user")
    return user.full_name or user.email


async def _entry_for(session: AsyncSession, user_id: str, day: str) -> StandupEntry | None:
    return await session.scalar(
        select(StandupEntry).where(StandupEntry.user_id == str(user_id), StandupEntry.day == day)
    )


async def _validate_job_ids(session: AsyncSession, job_ids: list[str]) -> list[str]:
    """Job tags must name real, non-archived projects - junk tightens."""
    cleaned = [str(j).strip() for j in job_ids if str(j).strip()]
    if len(cleaned) > MAX_JOBS_PER_ENTRY:
        raise StandupError(f"An entry can tag at most {MAX_JOBS_PER_ENTRY} jobs")
    if not cleaned:
        return []
    rows = await session.execute(select(Project.id).where(Project.id.in_(cleaned), Project.status != "archived"))
    known = {str(r[0]) for r in rows}
    unknown = [j for j in cleaned if j not in known]
    if unknown:
        raise StandupError("One of the tagged jobs does not exist or is archived")
    # Preserve the caller's order, drop duplicates.
    seen: set[str] = set()
    return [j for j in cleaned if not (j in seen or seen.add(j))]


async def _validate_activities(session: AsyncSession, activity_ids: list[str]) -> list[str]:
    """Activity picks must name real activities, and an exclusive pick
    ("on leave") must stand alone - invalid combinations tighten."""
    cleaned = [str(a).strip() for a in activity_ids if str(a).strip()]
    if not cleaned:
        return []
    rows = list(await session.scalars(select(StandupActivity).where(StandupActivity.id.in_(cleaned))))
    known = {str(r.id): r for r in rows}
    if any(a not in known for a in cleaned):
        raise StandupError("One of the picked activities does not exist")
    seen: set[str] = set()
    ordered = [a for a in cleaned if not (a in seen or seen.add(a))]
    if len(ordered) > 1 and any(known[a].exclusive for a in ordered):
        raise StandupError("An exclusive activity (like leave) stands alone")
    return ordered


async def upsert_entry(
    session: AsyncSession,
    *,
    user_id: str,
    day: str,
    status: str = "office",
    yesterday: str = "",
    today: str = "",
    blockers: str = "",
    job_ids: list[str] | None = None,
    activities: list[str] | None = None,
    blocker_by: str = "",
) -> StandupEntry:
    """Create or update the caller's entry for ``day``. Never anyone else's."""
    user_id = str(user_id)
    day = _validate_writable_day(day)
    if status not in ENTRY_STATUSES:
        raise StandupError(f"Status must be one of {', '.join(ENTRY_STATUSES)}, got {status!r}")
    yesterday = _clean_text(yesterday, field="Yesterday")
    today = _clean_text(today, field="Today")
    blockers = _clean_text(blockers, field="Blockers")
    job_ids = await _validate_job_ids(session, job_ids or [])
    activities = await _validate_activities(session, activities or [])
    blocker_by = (blocker_by or "").strip()
    if blocker_by:
        blocker_by = parse_day(blocker_by).isoformat()
    author_name = await _author_name(session, user_id)

    row = await _entry_for(session, user_id, day)
    if row is None:
        row = StandupEntry(
            user_id=user_id,
            author_name=author_name,
            day=day,
            status=status,
            yesterday=yesterday,
            today=today,
            blockers=blockers,
            job_ids=job_ids,
            activities=activities,
            blocker_by=blocker_by,
        )
        try:
            # SAVEPOINT so a lost double-submit race leaves the session
            # usable - the failed INSERT rolls back to here, then the row
            # the concurrent writer created is updated instead of 500ing.
            async with session.begin_nested():
                session.add(row)
        except IntegrityError:
            row = await _entry_for(session, user_id, day)
            if row is None:  # pragma: no cover - constraint fired for another reason
                raise
        else:
            return row

    row.author_name = author_name
    row.status = status
    row.yesterday = yesterday
    row.today = today
    row.blockers = blockers
    row.job_ids = job_ids
    row.activities = activities
    row.blocker_by = blocker_by
    await session.flush()
    return row


async def day_entries(session: AsyncSession, day: str) -> list[StandupEntry]:
    day = parse_day(day).isoformat()
    rows = await session.scalars(
        select(StandupEntry).where(StandupEntry.day == day).order_by(StandupEntry.author_name, StandupEntry.created_at)
    )
    return list(rows)


async def roster(session: AsyncSession, *, day: str, include_user_id: str) -> list[dict]:
    """Active users who posted within the trailing window, plus the caller.

    Returns ``[{user_id, name, has_posted}]`` where ``has_posted`` is for
    the requested day.
    """
    anchor = parse_day(day)
    window_start = (anchor - timedelta(days=ROSTER_WINDOW_DAYS)).isoformat()
    window_end = (anchor + timedelta(days=MAX_FUTURE_DAYS)).isoformat()

    recent = await session.execute(
        select(StandupEntry.user_id).where(StandupEntry.day >= window_start, StandupEntry.day <= window_end).distinct()
    )
    member_ids = {row[0] for row in recent} | {str(include_user_id)}

    users = await session.scalars(select(User).where(User.id.in_(list(member_ids))))
    posted_today = {e.user_id for e in await day_entries(session, day)}

    members = []
    for user in users:
        if not user.is_active or user.deleted_at is not None:
            continue
        members.append(
            {
                "user_id": str(user.id),
                "name": user.full_name or user.email,
                "has_posted": str(user.id) in posted_today,
            }
        )
    members.sort(key=lambda m: m["name"].lower())
    return members


async def jobs_catalogue(session: AsyncSession) -> list[dict]:
    """Non-archived projects for the job picker and chip labels."""
    rows = await session.scalars(select(Project).where(Project.status != "archived").order_by(Project.name))
    return [{"id": str(p.id), "name": p.name, "code": p.project_code or ""} for p in rows]


async def open_tasks_for(session: AsyncSession, user_ids: list[str]) -> dict[str, dict]:
    """Each member's open native tasks (oe_tasks), for the board.

    Private tasks are excluded for EVERYONE - including their owner -
    because this is a shared surface; a task someone marked private must
    not appear on a board the whole team reads. Completed tasks are done,
    draft/open/in_progress are live work.

    Returns ``{user_id: {"tasks": [...], "total": int}}`` with at most
    ``MAX_TASKS_PER_MEMBER`` rows each (most-urgent first) and the true
    total so the card can say "and 4 more".
    """
    if not user_ids:
        return {}
    rows = await session.scalars(
        select(Task).where(
            Task.responsible_id.in_([str(u) for u in user_ids]),
            Task.status != "completed",
            Task.is_private.is_(False),
        )
    )
    tasks = list(rows)
    today = date.today().isoformat()

    def urgency(t: Task) -> tuple:
        # Overdue first, then nearest due date, then in_progress before open.
        due = t.due_date or "9999-99-99"
        return (due >= today, due, 0 if t.status == "in_progress" else 1)

    by_user: dict[str, dict] = {}
    for t in sorted(tasks, key=urgency):
        bucket = by_user.setdefault(str(t.responsible_id), {"tasks": [], "total": 0})
        bucket["total"] += 1
        if len(bucket["tasks"]) < MAX_TASKS_PER_MEMBER:
            bucket["tasks"].append(
                {
                    "id": str(t.id),
                    "project_id": str(t.project_id),
                    "title": t.title,
                    "status": t.status,
                    "priority": t.priority,
                    "due_date": t.due_date,
                    "overdue": bool(t.due_date and t.due_date < today),
                }
            )
    return by_user


async def last_entries_before(session: AsyncSession, user_ids: list[str], *, day: str) -> dict[str, StandupEntry]:
    """Each member's most recent entry ON OR BEFORE ``day`` - what the
    board shows for someone who has not posted yet."""
    if not user_ids:
        return {}
    # Roster membership means "posted within the trailing window", so the
    # scan is bounded to that window rather than all of history.
    floor = (parse_day(day) - timedelta(days=ROSTER_WINDOW_DAYS)).isoformat()
    rows = await session.scalars(
        select(StandupEntry)
        .where(
            StandupEntry.user_id.in_([str(u) for u in user_ids]),
            StandupEntry.day <= day,
            StandupEntry.day >= floor,
        )
        .order_by(StandupEntry.day.desc())
    )
    latest: dict[str, StandupEntry] = {}
    for entry in rows:
        latest.setdefault(entry.user_id, entry)
    return latest


def _validate_range(from_day: str, to_day: str) -> tuple[str, str]:
    start = parse_day(from_day)
    end = parse_day(to_day)
    if end < start:
        raise StandupError("to_day is before from_day")
    if (end - start).days > MAX_RANGE_DAYS:
        raise StandupError(f"Range is wider than {MAX_RANGE_DAYS} days")
    return start.isoformat(), end.isoformat()


async def history(
    session: AsyncSession,
    *,
    from_day: str,
    to_day: str,
    user_id: str | None = None,
) -> list[StandupEntry]:
    start, end = _validate_range(from_day, to_day)
    stmt = (
        select(StandupEntry)
        .where(StandupEntry.day >= start, StandupEntry.day <= end)
        .order_by(StandupEntry.day.desc(), StandupEntry.author_name)
    )
    if user_id:
        stmt = stmt.where(StandupEntry.user_id == str(user_id))
    rows = await session.scalars(stmt)
    return list(rows)


async def blockers(session: AsyncSession, *, from_day: str, to_day: str) -> list[StandupEntry]:
    start, end = _validate_range(from_day, to_day)
    rows = await session.scalars(
        select(StandupEntry)
        .where(
            StandupEntry.day >= start,
            StandupEntry.day <= end,
            StandupEntry.blockers != "",
        )
        .order_by(StandupEntry.day.desc(), StandupEntry.author_name)
    )
    return list(rows)


async def add_comment(session: AsyncSession, *, entry_id: str, user_id: str, body: str) -> StandupComment:
    user_id = str(user_id)
    body = _clean_text(body, field="Comment", limit=MAX_COMMENT_CHARS)
    if not body:
        raise StandupError("Comment is empty")
    entry = await session.get(StandupEntry, entry_id)
    if entry is None:
        raise StandupError("Entry not found")
    comment = StandupComment(
        entry_id=entry.id,
        user_id=user_id,
        author_name=await _author_name(session, user_id),
        body=body,
    )
    entry.comments.append(comment)
    await session.flush()
    return comment


async def delete_comment(session: AsyncSession, *, comment_id: str, user_id: str, role: str) -> None:
    """Delete a comment - your own, or anyone's if you are an admin."""
    comment = await session.get(StandupComment, comment_id)
    if comment is None:
        raise StandupError("Comment not found")
    if comment.user_id != str(user_id) and role != "admin":
        raise PermissionError("Only the author (or an admin) can delete a comment")
    entry = await session.get(StandupEntry, comment.entry_id)
    if entry is not None:
        entry.comments.remove(comment)
    else:  # pragma: no cover - orphan safety
        await session.delete(comment)
    await session.flush()

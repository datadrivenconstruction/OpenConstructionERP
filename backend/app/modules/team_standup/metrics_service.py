# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Team metrics - presence pings and the per-person / per-job rollup.

Presence is the ONE thing this file writes. A ping says "this user was
on this path, on this job, for this many seconds since the last ping";
the row for (user, today, module, job) accumulates. Seconds per ping
are capped so a stalled tab that fires once after an hour cannot claim
the hour, and the caller's user id always comes from the token.

The rollup only reads: the delivery board's tasks, the standup entries
and the presence rows, over a trailing window of days.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.team_standup.models import StandupEntry, StandupTask
from app.modules.team_standup.presence_models import (
    MAX_MODULE_KEY_CHARS,
    SESSION_EVENTS,
    SESSION_SOURCES,
    PresenceSlot,
    SessionEvent,
)
from app.modules.teams.models import Team, TeamMembership
from app.modules.users.models import User

#: Most seconds a single ping may add. The beacon pings every 60 s, so
#: anything past two minutes is a tab that was asleep, not a person.
MAX_SECONDS_PER_PING = 120

#: A ping inside this many seconds means the person is on right now.
ONLINE_WINDOW_SECONDS = 180

#: Two identical session events closer than this are one event (a login
#: page that double-fires, a pagehide that fires twice on one close).
EVENT_DEDUP_SECONDS = 60

#: Window bounds for the rollup.
MIN_WINDOW_DAYS = 1
MAX_WINDOW_DAYS = 365

#: What the ERP root ("/") counts as.
ROOT_MODULE_KEY = "dashboard"

_SEGMENT_RX = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def module_key_from_path(path: str) -> str:
    """The first path segment, lower-cased, or a safe fallback.

    ``/team-standup/metrics?x=1`` -> ``team-standup``; ``/`` -> ``dashboard``;
    anything that is not a plain slug -> ``other`` (never stored raw).
    """
    text = (path or "").strip()
    text = text.split("?", 1)[0].split("#", 1)[0]
    first = text.strip("/").split("/", 1)[0].strip().lower()
    if not first:
        return ROOT_MODULE_KEY
    if len(first) > MAX_MODULE_KEY_CHARS or not _SEGMENT_RX.match(first):
        return "other"
    return first


def clamp_seconds(value: int | float | None) -> int:
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(MAX_SECONDS_PER_PING, n))


def _clean_project_id(value: str | None) -> str | None:
    raw = (value or "").strip()
    return raw if 0 < len(raw) <= 36 else None


async def record_ping(
    session: AsyncSession,
    *,
    user_id: str,
    path: str,
    project_id: str | None,
    seconds: int,
    today: str | None = None,
    now: datetime | None = None,
) -> PresenceSlot:
    """Add ``seconds`` (capped) to the caller's slot for today.

    The first ping of a day also mints that day's ``start`` session event;
    every ping refreshes ``last_seen`` on it (that is what "online" and
    "last seen" read from).
    """
    day = today or date.today().isoformat()
    module_key = module_key_from_path(path)
    pid = _clean_project_id(project_id)
    add = clamp_seconds(seconds)
    await touch_day_start(session, user_id=str(user_id), day=day, now=now)

    stmt = select(PresenceSlot).where(
        PresenceSlot.user_id == str(user_id),
        PresenceSlot.day == day,
        PresenceSlot.module_key == module_key,
    )
    stmt = stmt.where(PresenceSlot.project_id.is_(None)) if pid is None else stmt.where(PresenceSlot.project_id == pid)
    slot = await session.scalar(stmt.limit(1))
    if slot is None:
        slot = PresenceSlot(
            user_id=str(user_id),
            day=day,
            module_key=module_key,
            project_id=pid,
            seconds=0,
        )
        session.add(slot)
    slot.seconds = int(slot.seconds or 0) + add
    await session.flush()
    return slot


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    value = _as_utc(value)
    return value.isoformat() if value else None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


# ── Session events ───────────────────────────────────────────────────────


async def touch_day_start(
    session: AsyncSession, *, user_id: str, day: str, now: datetime | None = None
) -> SessionEvent:
    """Mint the day's ``start`` on the first ping; refresh ``last_seen`` after.

    Exactly one ``start`` per (user, day): its ``at`` never moves, its
    ``meta.last_seen`` follows the newest ping.
    """
    at = _as_utc(now) or _utcnow()
    start = await session.scalar(
        select(SessionEvent)
        .where(
            SessionEvent.user_id == user_id,
            SessionEvent.day == day,
            SessionEvent.event == "start",
        )
        .limit(1)
    )
    if start is None:
        start = SessionEvent(
            user_id=user_id,
            event="start",
            at=at,
            day=day,
            source="beacon",
            meta={"last_seen": at.isoformat()},
        )
        session.add(start)
    else:
        previous = _parse_iso((start.meta or {}).get("last_seen"))
        if previous is None or at > previous:
            # A fresh dict so the ORM sees the change (JSON is not mutable-tracked).
            start.meta = {**(start.meta or {}), "last_seen": at.isoformat()}
    await session.flush()
    return start


async def record_session_event(
    session: AsyncSession,
    *,
    user_id: str,
    event: str,
    at: datetime | None = None,
    source: str = "auth",
    meta: dict | None = None,
    today: str | None = None,
) -> tuple[SessionEvent, bool]:
    """Store a client-emitted session event; returns ``(row, created)``.

    De-duplication: ``start`` is one per day (delegated to
    :func:`touch_day_start`); any other event within ``EVENT_DEDUP_SECONDS``
    of a same-kind event for the user is the same event and returns the
    existing row with ``created=False``. The client's ``at`` may not be in
    the future or more than two days stale - such values are replaced by now.
    """
    if event not in SESSION_EVENTS:
        raise ValueError(f"unknown session event {event!r}")
    if source not in SESSION_SOURCES:
        source = "auth"
    now = _utcnow()
    when = _as_utc(at) or now
    if when > now + timedelta(seconds=30) or when < now - timedelta(days=2):
        when = now
    day = today or date.today().isoformat()

    if event == "start":
        before = await session.scalar(
            select(SessionEvent.id).where(
                SessionEvent.user_id == user_id,
                SessionEvent.day == day,
                SessionEvent.event == "start",
            )
        )
        row = await touch_day_start(session, user_id=user_id, day=day, now=when)
        return row, before is None

    window = timedelta(seconds=EVENT_DEDUP_SECONDS)
    twin = await session.scalar(
        select(SessionEvent)
        .where(
            SessionEvent.user_id == user_id,
            SessionEvent.event == event,
            SessionEvent.at >= when - window,
            SessionEvent.at <= when + window,
        )
        .order_by(SessionEvent.at.desc())
        .limit(1)
    )
    if twin is not None:
        return twin, False

    row = SessionEvent(user_id=user_id, event=event, at=when, day=day, source=source, meta=meta)
    session.add(row)
    await session.flush()
    return row, True


def _attendance_blank(user_id: str, day: str) -> dict:
    return {
        "user_id": user_id,
        "name": "",
        "day": day,
        "first_seen": None,
        "last_seen": None,
        "logins": [],
        "logouts": [],
        "ends": [],
        "active_seconds": 0,
        "still_on": False,
        "_first": None,
        "_last": None,
    }


def _seen(bucket: dict, when: datetime | None) -> None:
    if when is None:
        return
    if bucket["_first"] is None or when < bucket["_first"]:
        bucket["_first"] = when
    if bucket["_last"] is None or when > bucket["_last"]:
        bucket["_last"] = when


def _person_blank(user_id: str, name: str) -> dict:
    return {
        "user_id": user_id,
        "name": name,
        "tasks_completed": 0,
        "tasks_open": 0,
        "tasks_overdue": 0,
        "avg_days_to_close": None,
        "standups_posted": 0,
        "blockers_raised": 0,
        "seconds_by_module": {},
        "seconds_by_job": [],
        "_close_days": [],
    }


def _job_blank(project_id: str) -> dict:
    # ``code`` and ``name`` stay EMPTY until a real project row fills them.
    # They used to fall back to the first 8 characters of the project's
    # GUID, which put a raw id on screen ("a3f19c02") wearing a job
    # number's clothes - unreadable, and indistinguishable from a real
    # code. An empty string tells the client "this job has no code", and
    # the client says so in words.
    return {
        "project_id": project_id,
        "code": "",
        "name": "",
        "open_tasks": 0,
        "completed": 0,
        "overdue": 0,
        "seconds_total": 0,
        "people": [],
    }


# ── Today's presence only (viewer-safe) ──────────────────────────────────
#
# Deliberately a SEPARATE read from :func:`team_metrics`, and deliberately
# much smaller. ``team_metrics`` is management information ABOUT people -
# task throughput, average days to close, blockers raised, hours by module
# and by job, and a multi-day attendance table - so its endpoint sits at
# MANAGER. Knowing that a colleague is online right now, and when they were
# last seen, is ordinary team awareness: the project-team tile and its
# availability popup show it to everybody on the job.
#
# Keeping the two apart is what lets the endpoints have different
# permissions. Do not "reuse" ``team_metrics`` here and slice the result -
# that would compute (and, one refactor later, return) the manager-only
# figures on a viewer-level request. Nothing below reads a task, a standup
# entry or a day other than today.


async def _project_member_ids(session: AsyncSession, project_id: str) -> set[str]:
    """User ids on a project: its teams' memberships plus the owner.

    Read-only on purpose - ``member_service`` lazily CREATES a default team,
    which a GET must never do. An unknown or malformed id scopes to nobody
    rather than falling back to "everyone".
    """
    try:
        pid = uuid.UUID(str(project_id))
    except (TypeError, ValueError):
        return set()
    owner_id = await session.scalar(select(Project.owner_id).where(Project.id == pid))
    if owner_id is None:
        return set()
    ids = {str(owner_id)}
    team_ids = list(await session.scalars(select(Team.id).where(Team.project_id == pid)))
    if team_ids:
        rows = await session.scalars(select(TeamMembership.user_id).where(TeamMembership.team_id.in_(team_ids)))
        ids.update(str(u) for u in rows)
    return ids


async def presence_today(
    session: AsyncSession,
    *,
    project_id: str | None = None,
    include_user_id: str | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """Today's ``online`` / ``first_seen`` / ``last_seen`` per person.

    ``online`` is the same rule the rollup uses: a ping inside
    :data:`ONLINE_WINDOW_SECONDS`. When ``project_id`` is given the list is
    scoped to that project's members, so the tile only ever names people the
    caller can already see on the job. The caller is always included.

    Five keys per row and no more - any counter, average or per-day history
    added here belongs in :func:`team_metrics` behind the manager gate.
    """
    now_utc = _as_utc(now) or _utcnow()
    online_after = now_utc - timedelta(seconds=ONLINE_WINDOW_SECONDS)
    today_iso = date.today().isoformat()

    scope: set[str] | None = None
    if project_id:
        scope = await _project_member_ids(session, project_id)
        if include_user_id:
            scope.add(str(include_user_id))

    seen: dict[str, dict] = {}

    def bucket(uid: str) -> dict:
        return seen.setdefault(uid, {"_first": None, "_last": None})

    events = await session.scalars(
        select(SessionEvent).where(SessionEvent.day == today_iso).order_by(SessionEvent.at.asc())
    )
    for ev in events:
        uid = str(ev.user_id)
        if scope is not None and uid not in scope:
            continue
        b = bucket(uid)
        _seen(b, _as_utc(ev.at))
        if ev.event == "start":
            _seen(b, _parse_iso((ev.meta or {}).get("last_seen")))

    if include_user_id:
        bucket(str(include_user_id))

    names: dict[str, str] = {}
    if seen:
        users = await session.scalars(select(User).where(User.id.in_(list(seen))))
        for u in users:
            names[str(u.id)] = u.full_name or u.email

    out = []
    for uid, b in seen.items():
        first, last = b["_first"], b["_last"]
        out.append(
            {
                "user_id": uid,
                "name": names.get(uid) or "Former member",
                "online": bool(last is not None and last >= online_after),
                "first_seen": _iso(first),
                "last_seen": _iso(last),
            }
        )
    out.sort(key=lambda r: r["name"].lower())
    return out


async def team_metrics(
    session: AsyncSession,
    *,
    days: int,
    include_user_id: str | None = None,
    now: datetime | None = None,
) -> dict:
    """The dashboard payload: people, jobs, modules, attendance over ``days``."""
    days = max(MIN_WINDOW_DAYS, min(MAX_WINDOW_DAYS, int(days)))
    now_utc = _as_utc(now) or _utcnow()
    online_after = now_utc - timedelta(seconds=ONLINE_WINDOW_SECONDS)
    today = date.today()
    window_start = (today - timedelta(days=days - 1)).isoformat()
    cutoff = datetime.combine(today - timedelta(days=days - 1), datetime.min.time(), UTC)
    today_iso = today.isoformat()

    people: dict[str, dict] = {}
    jobs: dict[str, dict] = {}
    fallback_names: dict[str, str] = {}

    def person(uid: str) -> dict:
        return people.setdefault(uid, _person_blank(uid, ""))

    def job(pid: str) -> dict:
        return jobs.setdefault(pid, _job_blank(pid))

    # ── Tasks ────────────────────────────────────────────────────────
    tasks = await session.scalars(select(StandupTask).where(StandupTask.deleted.is_(False)))
    for t in tasks:
        completed_at = _as_utc(t.completed_at)
        uid = (t.assignee_id or "").strip()
        pid = (t.project_id or "").strip()
        if uid and t.assignee_name:
            fallback_names.setdefault(uid, t.assignee_name)
        if completed_at is None:
            overdue = bool(t.due and t.due < today_iso)
            if uid:
                p = person(uid)
                p["tasks_open"] += 1
                p["tasks_overdue"] += overdue
            if pid:
                j = job(pid)
                j["open_tasks"] += 1
                j["overdue"] += overdue
        elif completed_at >= cutoff:
            created = _as_utc(t.created_at) or completed_at
            span_days = max(0.0, (completed_at - created).total_seconds() / 86400.0)
            if uid:
                p = person(uid)
                p["tasks_completed"] += 1
                p["_close_days"].append(span_days)
            if pid:
                job(pid)["completed"] += 1

    # ── Standups ─────────────────────────────────────────────────────
    entries = await session.scalars(select(StandupEntry).where(StandupEntry.day >= window_start))
    for e in entries:
        p = person(e.user_id)
        if e.author_name:
            fallback_names.setdefault(e.user_id, e.author_name)
        p["standups_posted"] += 1
        if (e.blockers or "").strip():
            p["blockers_raised"] += 1

    # ── Presence ─────────────────────────────────────────────────────
    modules: dict[str, int] = defaultdict(int)
    job_seconds_by_person: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    attendance: dict[tuple[str, str], dict] = {}

    def bucket(uid: str, day: str) -> dict:
        return attendance.setdefault((uid, day), _attendance_blank(uid, day))

    slots = await session.scalars(select(PresenceSlot).where(PresenceSlot.day >= window_start))
    for s in slots:
        secs = int(s.seconds or 0)
        if secs <= 0:
            continue
        p = person(s.user_id)
        by_mod = p["seconds_by_module"]
        by_mod[s.module_key] = by_mod.get(s.module_key, 0) + secs
        modules[s.module_key] += secs
        if s.project_id:
            job_seconds_by_person[s.project_id][s.user_id] += secs
        bucket(s.user_id, s.day)["active_seconds"] += secs

    # ── Session events -> attendance ─────────────────────────────────
    events = await session.scalars(
        select(SessionEvent).where(SessionEvent.day >= window_start).order_by(SessionEvent.at.asc())
    )
    for ev in events:
        b = bucket(ev.user_id, ev.day)
        person(ev.user_id)
        at = _as_utc(ev.at)
        _seen(b, at)
        if ev.event == "start":
            _seen(b, _parse_iso((ev.meta or {}).get("last_seen")))
        elif ev.event == "login":
            b["logins"].append(_iso(at))
        elif ev.event == "logout":
            b["logouts"].append(_iso(at))
        elif ev.event == "end":
            b["ends"].append(_iso(at))

    if include_user_id:
        person(str(include_user_id))

    # ── Names and job labels ─────────────────────────────────────────
    if people:
        users = await session.scalars(select(User).where(User.id.in_(list(people))))
        for u in users:
            people[str(u.id)]["name"] = u.full_name or u.email
    for uid, p in people.items():
        if not p["name"]:
            p["name"] = fallback_names.get(uid) or "Former member"

    for pid in job_seconds_by_person:
        job(pid)
    if jobs:
        projects = await session.scalars(select(Project).where(Project.id.in_(list(jobs))))
        for pr in projects:
            j = jobs[str(pr.id)]
            # Same rule as _job_blank: no project_code -> no code, never
            # a slice of the GUID dressed up as one.
            j["code"] = pr.project_code or ""
            j["name"] = pr.name or ""

    for pid, per_user in job_seconds_by_person.items():
        j = jobs[pid]
        j["seconds_total"] = sum(per_user.values())
        j["people"] = sorted(
            ({"user_id": uid, "name": people[uid]["name"], "seconds": secs} for uid, secs in per_user.items()),
            key=lambda r: -r["seconds"],
        )
        for uid, secs in per_user.items():
            people[uid]["seconds_by_job"].append(
                {"project_id": pid, "code": j["code"], "name": j["name"], "seconds": secs}
            )

    # ── Attendance rows (newest day first) + today on each person ───
    attendance_out = []
    for (uid, day), b in attendance.items():
        first, last = b.pop("_first"), b.pop("_last")
        b["name"] = people[uid]["name"]
        b["first_seen"] = _iso(first)
        b["last_seen"] = _iso(last)
        b["still_on"] = bool(day == today_iso and last is not None and last >= online_after)
        attendance_out.append(b)
    # Newest day first, names A-Z within a day (stable sort, name first).
    attendance_out.sort(key=lambda r: r["name"].lower())
    attendance_out.sort(key=lambda r: r["day"], reverse=True)

    people_out = []
    for p in people.values():
        closes = p.pop("_close_days")
        p["avg_days_to_close"] = round(sum(closes) / len(closes), 1) if closes else None
        p["seconds_by_job"].sort(key=lambda r: -r["seconds"])
        t = attendance.get((p["user_id"], today_iso))
        p["today"] = {
            "first_seen": t["first_seen"] if t else None,
            "last_seen": t["last_seen"] if t else None,
            "online": bool(t and t["still_on"]),
        }
        people_out.append(p)
    people_out.sort(key=lambda r: r["name"].lower())

    jobs_out = sorted(
        jobs.values(),
        # Coded jobs before uncoded ones at equal weight, so a job with no
        # code never leads the table on an empty sort key.
        key=lambda j: (-j["seconds_total"], -j["open_tasks"], not j["code"], j["code"].lower()),
    )
    modules_out = sorted(
        ({"module_key": k, "seconds": v} for k, v in modules.items()),
        key=lambda r: -r["seconds"],
    )
    return {
        "window_days": days,
        "people": people_out,
        "jobs": jobs_out,
        "modules": modules_out,
        "attendance": attendance_out,
    }

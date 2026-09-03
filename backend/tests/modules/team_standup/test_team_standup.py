# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Team Standup tests (PostgreSQL, py3.12).

Each rail is tested with the failure it exists to prevent:

1. One entry per person per day - re-saving updates in place, never
   duplicates, and a lost double-submit race falls back to update
   instead of 500ing (savepoint, not try/except - house rule).
2. Unreadable input tightens: junk days, impossible dates, far-future
   days, unknown statuses and oversize text are all refused.
3. The roster self-selects from recent posters (plus the caller) and
   drops inactive accounts, so a service account that never posts
   never appears as "not posted yet".
4. Comments: only the author deletes their own; an admin may moderate;
   anyone else is refused.
5. The blockers digest only surfaces entries that actually carry one.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.tasks.models import Task
from app.modules.team_standup import service
from app.modules.team_standup.models import StandupComment, StandupEntry
from app.modules.users.models import User
from tests._pg import transactional_session

TODAY = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _user(
    session: AsyncSession,
    *,
    name: str = "PM",
    role: str = "editor",
    is_active: bool = True,
) -> User:
    user = User(
        email=f"su-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name=name,
        role=role,
        is_active=is_active,
    )
    session.add(user)
    await session.flush()
    return user


# ── 1. Upsert semantics ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upsert_creates_then_updates_in_place(session: AsyncSession) -> None:
    user = await _user(session, name="Sam Rivera")
    first = await service.upsert_entry(session, user_id=str(user.id), day=TODAY, today="Site walk at Plant C")
    assert first.author_name == "Sam Rivera"
    assert first.today == "Site walk at Plant C"

    second = await service.upsert_entry(
        session,
        user_id=str(user.id),
        day=TODAY,
        status="site",
        today="Site walk, then RFQ review",
        blockers="Waiting on switchboard quote",
    )
    assert second.id == first.id, "re-saving the same day must update, not duplicate"
    count = await session.scalar(select(func.count()).select_from(StandupEntry).where(StandupEntry.day == TODAY))
    assert count == 1
    assert second.status == "site"
    assert second.blockers == "Waiting on switchboard quote"


@pytest.mark.asyncio
async def test_lost_insert_race_falls_back_to_update(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two saves race; the loser's INSERT hits the unique constraint and
    must recover onto the winner's row - a 500 here loses someone's
    standup on an ordinary double-click."""
    user = await _user(session)
    winner = await service.upsert_entry(session, user_id=str(user.id), day=TODAY, today="first")

    # Make the loser believe no row exists yet, exactly once.
    real_entry_for = service._entry_for
    calls = {"n": 0}

    async def racy_entry_for(s, uid, day):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return await real_entry_for(s, uid, day)

    monkeypatch.setattr(service, "_entry_for", racy_entry_for)
    loser = await service.upsert_entry(session, user_id=str(user.id), day=TODAY, today="second")
    assert loser.id == winner.id
    assert loser.today == "second"
    # The session must still be usable after the rolled-back INSERT.
    assert await session.scalar(select(func.count()).select_from(StandupEntry)) == 1


# ── 2. Refusals ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_day",
    [
        "junk",
        "2026-13-40",
        "2026-02-30",
        "20260901",  # ISO-compact parses, but the board keys on dashes
        "",
        (date.today() + timedelta(days=30)).isoformat(),  # a plan, not a standup
        (date.today() - timedelta(days=400)).isoformat(),  # too old to backfill
    ],
)
async def test_unwritable_days_are_refused(session: AsyncSession, bad_day: str) -> None:
    user = await _user(session)
    with pytest.raises(service.StandupError):
        await service.upsert_entry(session, user_id=str(user.id), day=bad_day)


@pytest.mark.asyncio
async def test_unknown_status_and_oversize_text_refused(session: AsyncSession) -> None:
    user = await _user(session)
    with pytest.raises(service.StandupError):
        await service.upsert_entry(session, user_id=str(user.id), day=TODAY, status="on the moon")
    with pytest.raises(service.StandupError):
        await service.upsert_entry(session, user_id=str(user.id), day=TODAY, today="x" * 4001)


@pytest.mark.asyncio
async def test_range_queries_refuse_junk_and_oversize_ranges(
    session: AsyncSession,
) -> None:
    with pytest.raises(service.StandupError):
        await service.history(session, from_day="junk", to_day=TODAY)
    with pytest.raises(service.StandupError):
        await service.history(session, from_day=TODAY, to_day=YESTERDAY)
    wide = (date.today() - timedelta(days=200)).isoformat()
    with pytest.raises(service.StandupError):
        await service.blockers(session, from_day=wide, to_day=TODAY)


# ── 3. Roster ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_roster_self_selects_recent_posters(session: AsyncSession) -> None:
    poster = await _user(session, name="Alex")
    lurker = await _user(session, name="Never Posts")
    ghost = await _user(session, name="Old Account", is_active=False)
    caller = await _user(session, name="Sam")

    await service.upsert_entry(session, user_id=str(poster.id), day=YESTERDAY, today="was here")
    # The inactive account posted too - it must STILL be excluded.
    session.add(StandupEntry(user_id=str(ghost.id), author_name="Old Account", day=YESTERDAY))
    await session.flush()

    roster = await service.roster(session, day=TODAY, include_user_id=str(caller.id))
    ids = {m["user_id"] for m in roster}
    assert str(poster.id) in ids, "recent poster is on the team"
    assert str(caller.id) in ids, "the caller always sees themselves"
    assert str(lurker.id) not in ids, "never-posted accounts stay off the roster"
    assert str(ghost.id) not in ids, "inactive accounts are dropped"

    by_id = {m["user_id"]: m for m in roster}
    assert by_id[str(poster.id)]["has_posted"] is False, "posted yesterday, not today"
    await service.upsert_entry(session, user_id=str(poster.id), day=TODAY, today="now")
    roster = await service.roster(session, day=TODAY, include_user_id=str(caller.id))
    by_id = {m["user_id"]: m for m in roster}
    assert by_id[str(poster.id)]["has_posted"] is True


# ── 4. Comments ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_comment_lifecycle_and_moderation(session: AsyncSession) -> None:
    author = await _user(session, name="Author")
    commenter = await _user(session, name="Commenter")
    other = await _user(session, name="Bystander")
    admin = await _user(session, name="Boss", role="admin")

    entry = await service.upsert_entry(session, user_id=str(author.id), day=TODAY, today="work")
    comment = await service.add_comment(session, entry_id=str(entry.id), user_id=str(commenter.id), body="Need a hand?")
    assert comment.author_name == "Commenter"

    with pytest.raises(PermissionError):
        await service.delete_comment(session, comment_id=str(comment.id), user_id=str(other.id), role="editor")

    await service.delete_comment(session, comment_id=str(comment.id), user_id=str(commenter.id), role="editor")
    assert await session.get(StandupComment, comment.id) is None

    second = await service.add_comment(session, entry_id=str(entry.id), user_id=str(commenter.id), body="ping")
    await service.delete_comment(session, comment_id=str(second.id), user_id=str(admin.id), role="admin")
    assert await session.get(StandupComment, second.id) is None

    with pytest.raises(service.StandupError):
        await service.add_comment(session, entry_id=str(entry.id), user_id=str(commenter.id), body="   ")


# ── 5. Job links ─────────────────────────────────────────────────────────


async def _project(session: AsyncSession, *, name: str, status: str = "active") -> Project:
    owner = await _user(session, name=f"owner-{name}")
    proj = Project(
        name=name,
        owner_id=owner.id,
        currency="AUD",
        status=status,
        project_code=f"J{uuid.uuid4().hex[:6].upper()}",
    )
    session.add(proj)
    await session.flush()
    return proj


@pytest.mark.asyncio
async def test_job_tags_validate_against_real_projects(session: AsyncSession) -> None:
    user = await _user(session)
    live = await _project(session, name="Plant C")
    dead = await _project(session, name="Old Job", status="archived")

    entry = await service.upsert_entry(session, user_id=str(user.id), day=TODAY, job_ids=[str(live.id)])
    assert entry.job_ids == [str(live.id)]

    with pytest.raises(service.StandupError):
        await service.upsert_entry(session, user_id=str(user.id), day=TODAY, job_ids=[str(uuid.uuid4())])
    with pytest.raises(service.StandupError):
        await service.upsert_entry(session, user_id=str(user.id), day=TODAY, job_ids=[str(dead.id)])
    # Duplicates collapse, order kept; too many refused.
    entry = await service.upsert_entry(
        session,
        user_id=str(user.id),
        day=TODAY,
        job_ids=[str(live.id), str(live.id)],
    )
    assert entry.job_ids == [str(live.id)]
    with pytest.raises(service.StandupError):
        await service.upsert_entry(
            session,
            user_id=str(user.id),
            day=TODAY,
            job_ids=[str(uuid.uuid4()) for _ in range(21)],
        )


@pytest.mark.asyncio
async def test_jobs_catalogue_hides_archived(session: AsyncSession) -> None:
    live = await _project(session, name="Live Job")
    await _project(session, name="Archived Job", status="archived")
    jobs = await service.jobs_catalogue(session)
    ids = {j["id"] for j in jobs}
    assert str(live.id) in ids
    assert all(j["name"] != "Archived Job" for j in jobs)


# ── 6. Native task surfacing ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_board_tasks_exclude_private_and_completed(session: AsyncSession) -> None:
    pm = await _user(session, name="PM One")
    proj = await _project(session, name="Task Job")

    def task(title: str, **kw) -> Task:
        return Task(
            project_id=proj.id,
            task_type="task",
            title=title,
            responsible_id=str(pm.id),
            **kw,
        )

    session.add_all(
        [
            task("visible open", status="open"),
            task("visible in progress", status="in_progress"),
            task("done, stays off the board", status="completed"),
            # Private means private - even the owner's card on a SHARED
            # board must not show it.
            task("private, never shown", status="open", is_private=True),
            task("overdue first", status="open", due_date="2026-01-01"),
        ]
    )
    await session.flush()

    by_user = await service.open_tasks_for(session, [str(pm.id)])
    bucket = by_user[str(pm.id)]
    titles = [t["title"] for t in bucket["tasks"]]
    assert bucket["total"] == 3
    assert titles[0] == "overdue first", "overdue tasks sort to the top"
    assert bucket["tasks"][0]["overdue"] is True
    assert "done, stays off the board" not in titles
    assert "private, never shown" not in titles


@pytest.mark.asyncio
async def test_last_entry_shown_for_members_who_have_not_posted(
    session: AsyncSession,
) -> None:
    pm = await _user(session, name="Quiet PM")
    await service.upsert_entry(session, user_id=str(pm.id), day=YESTERDAY, today="was on site")
    latest = await service.last_entries_before(session, [str(pm.id)], day=TODAY)
    assert latest[str(pm.id)].day == YESTERDAY
    assert latest[str(pm.id)].today == "was on site"


# ── 7. Blockers digest ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_blockers_digest_only_lists_real_blockers(session: AsyncSession) -> None:
    blocked = await _user(session, name="Blocked")
    fine = await _user(session, name="Fine")
    await service.upsert_entry(
        session,
        user_id=str(blocked.id),
        day=YESTERDAY,
        blockers="No access to level 3 riser",
    )
    await service.upsert_entry(session, user_id=str(fine.id), day=YESTERDAY, today="ok")

    rows = await service.blockers(session, from_day=YESTERDAY, to_day=TODAY)
    assert [r.user_id for r in rows] == [str(blocked.id)]
    assert rows[0].blockers == "No access to level 3 riser"

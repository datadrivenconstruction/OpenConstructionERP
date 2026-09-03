# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Delivery-board tests (PostgreSQL, py3.12).

Each rail is tested with the failure it exists to prevent:

1. move_task is the ONE stage-change path: entering a stage fires its
   template exactly once (an open task with the same title suppresses
   the duplicate), and closing a repeating task mints the next
   occurrence FROM THE SCHEDULED DATE - closing late must not slide the
   series.
2. Recurrence arithmetic: monthly means the same day of month (clamped),
   monthly-last means the last working day - never "+28 days".
3. move-undo only deletes what that exact move created - a forged or
   stale undo is refused.
4. Vocabulary tightens: unknown priorities, colours, stages, activities
   and archived jobs are refused, never coerced.
5. Config replaces are surgical: a renamed stage keeps its tasks, a
   deleted stage hands its tasks to the nearest earlier survivor, and a
   reset maps tasks across by stage NAME.
6. Every mutation writes a log row - the log is server-owned.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.team_standup import board_service, service
from app.modules.team_standup.models import StandupLog, StandupTask
from app.modules.team_standup.recurrence import next_occurrence
from app.modules.users.models import User
from tests._pg import transactional_session

TODAY = date.today().isoformat()


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _user(session: AsyncSession, *, name: str = "PM", role: str = "editor") -> User:
    user = User(
        email=f"db-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name=name,
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


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


async def _board(session: AsyncSession) -> tuple[User, Project, list]:
    """A seeded board, a user and a job - the common opening position."""
    await board_service.ensure_seeded(session)
    user = await _user(session, name="Sam Rivera")
    proj = await _project(session, name="Northbank - Plant upgrade")
    stages = await board_service.stages_ordered(session)
    return user, proj, stages


def _stage_named(stages: list, name: str):
    return next(s for s in stages if s.name == name)


# ── 1. Seeding ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_plants_the_electrical_run_once(session: AsyncSession) -> None:
    await board_service.ensure_seeded(session)
    await board_service.ensure_seeded(session)  # idempotent
    stages = await board_service.stages_ordered(session)
    acts = await board_service.activities_ordered(session)
    waits = await board_service.wait_reasons(session)
    assert [s.name for s in stages][:2] == ["To do", "Design & approvals"]
    assert len(stages) == 10
    assert stages[-1].is_done, "the run must end in a closing stage"
    assert _stage_named(stages, "Ordered").spawn == [
        "Confirm delivery date",
        "Book the unload",
    ]
    assert len(acts) == 6
    assert any(a.exclusive for a in acts), "leave must be exclusive"
    assert len(waits) == 6


# ── 2. Recurrence arithmetic ─────────────────────────────────────────────


def test_monthly_is_same_day_of_month_clamped() -> None:
    assert next_occurrence("2026-09-25", "monthly") == "2026-10-25"
    assert next_occurrence("2026-01-31", "monthly") == "2026-02-28"
    assert next_occurrence("2026-12-25", "monthly") == "2027-01-25"


def test_weekly_and_fortnightly_step_by_calendar() -> None:
    assert next_occurrence("2026-09-04", "weekly") == "2026-09-11"
    assert next_occurrence("2026-09-04", "fortnightly") == "2026-09-18"


def test_monthly_last_lands_on_a_working_day() -> None:
    # 31 Oct 2026 is a Saturday - the rule must give Friday 30 Oct.
    assert next_occurrence("2026-09-30", "monthly-last") == "2026-10-30"


def test_junk_recurrence_returns_none_not_a_guess() -> None:
    assert next_occurrence("not-a-date", "weekly") is None
    assert next_occurrence("2026-09-04", "hourly") is None


# ── 3. Task creation ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_create_defaults_and_validates(session: AsyncSession) -> None:
    user, proj, stages = await _board(session)
    made = await board_service.create_tasks(
        session,
        [
            {"title": "Price the riser package", "project_id": str(proj.id)},
            {"title": "Book the EWP", "project_id": str(proj.id), "priority": "high"},
        ],
        user_id=str(user.id),
    )
    assert len(made) == 2
    assert str(made[0].stage_id) == str(stages[0].id), "defaults to the first stage"
    assert made[0].assignee_name == "Sam Rivera", "defaults to the caller"
    assert made[1].priority == "high"

    with pytest.raises(service.StandupError, match="Priority"):
        await board_service.create_tasks(
            session,
            [{"title": "x", "project_id": str(proj.id), "priority": "asap"}],
            user_id=str(user.id),
        )

    archived = await _project(session, name="Old job", status="archived")
    with pytest.raises(service.StandupError, match="archived"):
        await board_service.create_tasks(
            session,
            [{"title": "x", "project_id": str(archived.id)}],
            user_id=str(user.id),
        )


# ── 4. The move rail ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_entering_a_stage_fires_its_template_once(session: AsyncSession) -> None:
    user, proj, stages = await _board(session)
    ordered = _stage_named(stages, "Ordered")
    [task] = await board_service.create_tasks(
        session,
        [{"title": "Main switchboard", "project_id": str(proj.id)}],
        user_id=str(user.id),
    )

    result = await board_service.move_task(
        session, task_id=str(task.id), stage_id=str(ordered.id), user_id=str(user.id)
    )
    titles = sorted(t.title for t in result["spawned"])
    assert titles == ["Book the unload", "Confirm delivery date"]
    assert all(t.is_sub for t in result["spawned"])
    assert all(t.origin == "spawn" for t in result["spawned"])

    # A second task arriving in Ordered on the same job must NOT
    # duplicate the still-open follow-ups.
    [task2] = await board_service.create_tasks(
        session,
        [{"title": "Cable tray order", "project_id": str(proj.id)}],
        user_id=str(user.id),
    )
    result2 = await board_service.move_task(
        session, task_id=str(task2.id), stage_id=str(ordered.id), user_id=str(user.id)
    )
    assert result2["spawned"] == []


@pytest.mark.asyncio
async def test_closing_a_repeating_task_mints_from_the_schedule(
    session: AsyncSession,
) -> None:
    user, proj, stages = await _board(session)
    done = stages[-1]
    [claim] = await board_service.create_tasks(
        session,
        [
            {
                "title": "Monthly progress claim",
                "project_id": str(proj.id),
                "due": "2026-09-25",
                "repeat_rule": "monthly",
            }
        ],
        user_id=str(user.id),
    )
    result = await board_service.move_task(session, task_id=str(claim.id), stage_id=str(done.id), user_id=str(user.id))
    assert result["task"].completed_at is not None
    repeated = result["repeated"]
    assert repeated is not None
    assert repeated.due == "2026-10-25", "next from the SCHEDULED date, closing late never slides"
    assert repeated.repeat_rule == "monthly"
    assert str(repeated.stage_id) == str(stages[0].id)
    assert repeated.origin == "repeat"


@pytest.mark.asyncio
async def test_move_undo_only_deletes_what_the_move_created(
    session: AsyncSession,
) -> None:
    user, proj, stages = await _board(session)
    ordered = _stage_named(stages, "Ordered")
    [task] = await board_service.create_tasks(
        session,
        [{"title": "Main switchboard", "project_id": str(proj.id)}],
        user_id=str(user.id),
    )
    [bystander] = await board_service.create_tasks(
        session,
        [{"title": "Innocent bystander", "project_id": str(proj.id)}],
        user_id=str(user.id),
    )
    result = await board_service.move_task(
        session, task_id=str(task.id), stage_id=str(ordered.id), user_id=str(user.id)
    )
    spawned_ids = [str(t.id) for t in result["spawned"]]

    # A forged undo naming an unrelated task must be refused whole.
    with pytest.raises(service.StandupError, match="expired"):
        await board_service.undo_move(
            session,
            task_id=str(task.id),
            to_stage_id=str(stages[0].id),
            spawned_ids=[str(bystander.id)],
            repeated_id=None,
            user_id=str(user.id),
        )
    assert await session.get(StandupTask, str(bystander.id)) is not None

    # The honest undo removes exactly the spawned pair and restores the stage.
    undone = await board_service.undo_move(
        session,
        task_id=str(task.id),
        to_stage_id=str(stages[0].id),
        spawned_ids=spawned_ids,
        repeated_id=None,
        user_id=str(user.id),
    )
    assert str(undone.stage_id) == str(stages[0].id)
    for sid in spawned_ids:
        assert await session.get(StandupTask, sid) is None


@pytest.mark.asyncio
async def test_stale_undo_is_refused(session: AsyncSession) -> None:
    user, proj, stages = await _board(session)
    ordered = _stage_named(stages, "Ordered")
    [task] = await board_service.create_tasks(
        session,
        [{"title": "Main switchboard", "project_id": str(proj.id)}],
        user_id=str(user.id),
    )
    result = await board_service.move_task(
        session, task_id=str(task.id), stage_id=str(ordered.id), user_id=str(user.id)
    )
    old = datetime.now(UTC) - timedelta(hours=2)
    for t in result["spawned"]:
        t.created_at = old
    await session.flush()
    with pytest.raises(service.StandupError, match="expired"):
        await board_service.undo_move(
            session,
            task_id=str(task.id),
            to_stage_id=str(stages[0].id),
            spawned_ids=[str(t.id) for t in result["spawned"]],
            repeated_id=None,
            user_id=str(user.id),
        )


# ── 5. Edits, delete, comments ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_validates_and_logs_changes(session: AsyncSession) -> None:
    user, proj, stages = await _board(session)
    [task] = await board_service.create_tasks(
        session,
        [{"title": "Price the riser package", "project_id": str(proj.id)}],
        user_id=str(user.id),
    )
    updated = await board_service.update_task(
        session,
        task_id=str(task.id),
        fields={"waiting_on": "Supplier price", "due": "2026-09-10", "priority": "urgent"},
        user_id=str(user.id),
    )
    assert updated.waiting_on == "Supplier price"
    assert updated.priority == "urgent"

    with pytest.raises(service.StandupError):
        await board_service.update_task(
            session, task_id=str(task.id), fields={"due": "next tuesday"}, user_id=str(user.id)
        )
    # A link with no reference collapses to no link at all.
    cleared = await board_service.update_task(
        session,
        task_id=str(task.id),
        fields={"link_kind": "rfi", "link_ref": ""},
        user_id=str(user.id),
    )
    assert cleared.link_kind == "" and cleared.link_ref == ""


@pytest.mark.asyncio
async def test_task_links_to_a_department_work_request(session: AsyncSession) -> None:
    """A task can point at a Work requests record (kind ``request``, the
    request's id as the target so the chip opens it) - and a kind the
    board has never heard of is still refused, not coerced."""
    user, proj, _ = await _board(session)
    request_id = str(uuid.uuid4())
    [task] = await board_service.create_tasks(
        session,
        [
            {
                "title": "Chase the switchboard drawings",
                "project_id": str(proj.id),
                "link_kind": "request",
                "link_ref": "WR-DRF-000012",
                "link_target_id": request_id,
            }
        ],
        user_id=str(user.id),
    )
    assert task.link_kind == "request"
    assert task.link_ref == "WR-DRF-000012"
    assert task.link_target_id == request_id

    # Re-pointing through update goes through the same validator.
    moved = await board_service.update_task(
        session,
        task_id=str(task.id),
        fields={"link_kind": "request", "link_ref": "WR-WKS-000003", "link_target_id": str(uuid.uuid4())},
        user_id=str(user.id),
    )
    assert moved.link_ref == "WR-WKS-000003"

    with pytest.raises(service.StandupError):
        await board_service.update_task(
            session,
            task_id=str(task.id),
            fields={"link_kind": "ticket", "link_ref": "T-1"},
            user_id=str(user.id),
        )


@pytest.mark.asyncio
async def test_soft_delete_hides_restore_returns(session: AsyncSession) -> None:
    user, proj, _ = await _board(session)
    [task] = await board_service.create_tasks(
        session,
        [{"title": "Doomed", "project_id": str(proj.id)}],
        user_id=str(user.id),
    )
    await board_service.delete_task(session, task_id=str(task.id), user_id=str(user.id))
    assert all(str(t.id) != str(task.id) for t in await board_service.board_tasks(session))
    with pytest.raises(service.StandupError):
        await board_service.get_task(session, str(task.id))

    restored = await board_service.restore_task(session, task_id=str(task.id), user_id=str(user.id))
    assert not restored.deleted
    assert any(str(t.id) == str(task.id) for t in await board_service.board_tasks(session))


@pytest.mark.asyncio
async def test_task_comment_delete_is_author_or_admin_only(
    session: AsyncSession,
) -> None:
    user, proj, _ = await _board(session)
    other = await _user(session, name="Alex", role="editor")
    admin = await _user(session, name="Boss", role="admin")
    [task] = await board_service.create_tasks(
        session,
        [{"title": "Talk about me", "project_id": str(proj.id)}],
        user_id=str(user.id),
    )
    comment = await board_service.add_task_comment(
        session, task_id=str(task.id), user_id=str(user.id), body="chasing the supplier"
    )
    with pytest.raises(PermissionError):
        await board_service.delete_task_comment(
            session, comment_id=str(comment.id), user_id=str(other.id), role="editor"
        )
    await board_service.delete_task_comment(session, comment_id=str(comment.id), user_id=str(admin.id), role="admin")
    assert (await board_service.get_task(session, str(task.id))).comments == []


# ── 6. Config replaces ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_replace_keeps_tasks_on_renamed_stage_and_rehomes_deleted(
    session: AsyncSession,
) -> None:
    user, proj, stages = await _board(session)
    pricing = _stage_named(stages, "Pricing")
    [task] = await board_service.create_tasks(
        session,
        [
            {
                "title": "Compare quotes",
                "project_id": str(proj.id),
                "stage_id": str(pricing.id),
            }
        ],
        user_id=str(user.id),
    )
    # Rename Pricing and drop "Design & approvals"; its neighbours survive.
    payload = []
    for s in stages:
        if s.name == "Design & approvals":
            continue
        payload.append(
            {
                "id": str(s.id),
                "name": "Quotes" if s.name == "Pricing" else s.name,
                "color": s.color,
                "wip_limit": s.wip_limit,
                "is_done": s.is_done,
                "spawn": list(s.spawn or []),
            }
        )
    replaced = await board_service.replace_stages(session, payload, user_id=str(user.id))
    assert "Design & approvals" not in [s.name for s in replaced]
    kept = await board_service.get_task(session, str(task.id))
    assert str(kept.stage_id) == str(pricing.id), "rename keeps the id, tasks stay"
    assert _stage_named(replaced, "Quotes").id == pricing.id

    with pytest.raises(service.StandupError, match="between 2"):
        await board_service.replace_stages(session, payload[:1], user_id=str(user.id))
    bad = [dict(p) for p in payload]
    bad[0]["color"] = "chartreuse"
    with pytest.raises(service.StandupError, match="colour"):
        await board_service.replace_stages(session, bad, user_id=str(user.id))


@pytest.mark.asyncio
async def test_deleting_a_stage_rehomes_its_tasks_to_the_earlier_survivor(
    session: AsyncSession,
) -> None:
    user, proj, stages = await _board(session)
    ordered = _stage_named(stages, "Ordered")
    pricing = _stage_named(stages, "Pricing")
    [task] = await board_service.create_tasks(
        session,
        [
            {
                "title": "Switchboard order",
                "project_id": str(proj.id),
                "stage_id": str(ordered.id),
            }
        ],
        user_id=str(user.id),
    )
    payload = [
        {
            "id": str(s.id),
            "name": s.name,
            "color": s.color,
            "wip_limit": s.wip_limit,
            "is_done": s.is_done,
            "spawn": list(s.spawn or []),
        }
        for s in stages
        if s.name != "Ordered"
    ]
    await board_service.replace_stages(session, payload, user_id=str(user.id))
    rehomed = await board_service.get_task(session, str(task.id))
    assert str(rehomed.stage_id) == str(pricing.id), "the row above inherits the tasks"


@pytest.mark.asyncio
async def test_reset_maps_tasks_across_by_stage_name(session: AsyncSession) -> None:
    user, proj, stages = await _board(session)
    onsite = _stage_named(stages, "On site")
    [task] = await board_service.create_tasks(
        session,
        [
            {
                "title": "Pull the risers",
                "project_id": str(proj.id),
                "stage_id": str(onsite.id),
            }
        ],
        user_id=str(user.id),
    )
    fresh = await board_service.reset_stages(session, user_id=str(user.id))
    assert len(fresh) == 10
    mapped = await board_service.get_task(session, str(task.id))
    assert str(mapped.stage_id) == str(_stage_named(fresh, "On site").id)


@pytest.mark.asyncio
async def test_waits_replace_dedupes_and_strips(session: AsyncSession) -> None:
    user, _, _ = await _board(session)
    labels = await board_service.replace_waits(
        session,
        ["Client approval", "  Client approval ", "", "Council inspection"],
        user_id=str(user.id),
    )
    assert labels == ["Client approval", "Council inspection"]


# ── 7. Entry activities rails ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_entry_activities_validate_and_exclusive_stands_alone(
    session: AsyncSession,
) -> None:
    user, _, _ = await _board(session)
    acts = await board_service.activities_ordered(session)
    office = next(a for a in acts if a.name == "In the office")
    travel = next(a for a in acts if a.name == "Travelling")
    leave = next(a for a in acts if a.exclusive)

    entry = await service.upsert_entry(
        session,
        user_id=str(user.id),
        day=TODAY,
        activities=[str(office.id), str(travel.id)],
        blocker_by="",
    )
    assert entry.activities == [str(office.id), str(travel.id)]

    with pytest.raises(service.StandupError, match="alone"):
        await service.upsert_entry(
            session,
            user_id=str(user.id),
            day=TODAY,
            activities=[str(leave.id), str(office.id)],
        )
    with pytest.raises(service.StandupError, match="exist"):
        await service.upsert_entry(
            session,
            user_id=str(user.id),
            day=TODAY,
            activities=[str(uuid.uuid4())],
        )
    with pytest.raises(service.StandupError):
        await service.upsert_entry(session, user_id=str(user.id), day=TODAY, blocker_by="whenever")


# ── 8. Fresh rows must serialise the way the router does ─────────────────


@pytest.mark.asyncio
async def test_fresh_tasks_serialise_without_lazy_loads(session: AsyncSession) -> None:
    """The router validates TaskRead straight off create/move results. A
    fresh StandupTask whose comments/files collections were never
    initialised would lazy-load inside sync pydantic validation - which
    asyncpg cannot do (MissingGreenlet) - so creation must hand every new
    row over with its collections already present. Hit live as a 500 on
    the very first composer save."""
    from app.modules.team_standup.schemas import TaskRead

    user, proj, stages = await _board(session)
    ordered = _stage_named(stages, "Ordered")
    made = await board_service.create_tasks(
        session,
        [{"title": "Serialise me", "project_id": str(proj.id), "due": "2026-09-25", "repeat_rule": "monthly"}],
        user_id=str(user.id),
    )
    for t in made:
        TaskRead.model_validate(t)

    result = await board_service.move_task(
        session, task_id=str(made[0].id), stage_id=str(ordered.id), user_id=str(user.id)
    )
    TaskRead.model_validate(result["task"])
    for t in result["spawned"]:
        TaskRead.model_validate(t)

    done = await board_service.move_task(
        session, task_id=str(made[0].id), stage_id=str(stages[-1].id), user_id=str(user.id)
    )
    assert done["repeated"] is not None
    TaskRead.model_validate(done["repeated"])


# ── 9. The log is server-owned ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_mutations_write_log_rows(session: AsyncSession) -> None:
    user, proj, stages = await _board(session)
    [task] = await board_service.create_tasks(
        session,
        [{"title": "Logged task", "project_id": str(proj.id)}],
        user_id=str(user.id),
    )
    await board_service.move_task(
        session,
        task_id=str(task.id),
        stage_id=str(stages[-1].id),
        user_id=str(user.id),
    )
    rows = list(await session.scalars(select(StandupLog)))
    whats = [r.what for r in rows]
    assert any(w.startswith('Created "Logged task"') for w in whats)
    assert any(w.startswith('Moved "Logged task"') for w in whats)
    assert all(r.author_name == "Sam Rivera" for r in rows)


# ── 10. Job client: contact link, then legacy text, then the name split ───


@pytest.mark.asyncio
async def test_job_client_prefers_contact_then_legacy_then_name_split(
    session: AsyncSession,
) -> None:
    """``client_id`` is a soft link to a ``client`` contact. The board's
    client column reads it in this order: a UUID naming a contact -> the
    contact's name (company, else person); a non-UUID value -> that text as
    typed; nothing usable -> the "Client - work" split of the project name,
    which is unchanged. The label is always the name's work part."""
    from app.modules.contacts.models import Contact

    company = Contact(contact_type="client", company_name="Example Client Pty Ltd")
    person = Contact(contact_type="client", first_name="Ada", last_name="Example")
    session.add_all([company, person])
    await session.flush()

    linked = await _project(session, name="Old Name Co - Plant upgrade")
    linked.client_id = str(company.id)
    by_person = await _project(session, name="Fitout")
    by_person.client_id = str(person.id).upper()  # case must not matter
    legacy = await _project(session, name="Acme Holdings - Switchroom")
    legacy.client_id = "Example Legacy Client"
    split_only = await _project(session, name="Northbank - Plant upgrade")
    dangling = await _project(session, name="Ghost Co - Lighting")
    dangling.client_id = str(uuid.uuid4())
    await session.flush()

    jobs = await board_service.job_payloads(session, [linked, by_person, legacy, split_only, dangling])
    by_id = {j["id"]: j for j in jobs}

    assert by_id[str(linked.id)]["client"] == "Example Client Pty Ltd"
    assert by_id[str(linked.id)]["label"] == "Plant upgrade", "label stays the work part"
    assert by_id[str(by_person.id)]["client"] == "Ada Example"
    assert by_id[str(by_person.id)]["label"] == "Fitout"
    assert by_id[str(legacy.id)]["client"] == "Example Legacy Client", "verbatim"
    assert by_id[str(split_only.id)]["client"] == "Northbank"
    assert by_id[str(split_only.id)]["label"] == "Plant upgrade"
    assert by_id[str(dangling.id)]["client"] == "Ghost Co", "a UUID no contact answers to falls back to the name split"


@pytest.mark.asyncio
async def test_job_clients_resolve_in_one_query(session: AsyncSession) -> None:
    """A board with N linked jobs must not cost N contact lookups."""
    from sqlalchemy import event

    from app.modules.contacts.models import Contact

    contacts = [Contact(contact_type="client", company_name=f"Client {i} Pty Ltd") for i in range(4)]
    session.add_all(contacts)
    await session.flush()
    projects = []
    for i, c in enumerate(contacts):
        p = await _project(session, name=f"Job {i}")
        p.client_id = str(c.id)
        projects.append(p)
    projects.append(await _project(session, name="Unlinked - Job"))
    await session.flush()

    sync_engine = (await session.connection()).sync_connection.engine
    selects: list[str] = []

    def _count(_conn, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    event.listen(sync_engine, "before_cursor_execute", _count)
    try:
        jobs = await board_service.job_payloads(session, projects)
    finally:
        event.remove(sync_engine, "before_cursor_execute", _count)

    assert [j["client"] for j in jobs] == [
        "Client 0 Pty Ltd",
        "Client 1 Pty Ltd",
        "Client 2 Pty Ltd",
        "Client 3 Pty Ltd",
        "Unlinked",
    ]
    assert len(selects) == 1, selects

    # No linked job at all -> no query at all.
    selects.clear()
    event.listen(sync_engine, "before_cursor_execute", _count)
    try:
        await board_service.job_payloads(session, [projects[-1]])
    finally:
        event.remove(sync_engine, "before_cursor_execute", _count)
    assert selects == []

"""PG: an assistant proposal reaches the project only when a person applies it.

The chat assistant used to write a BOQ line the moment the model asked for it.
It now stores a proposal and nothing else; the record is created or changed
when a person clicks Apply, under the same gates the record's REST route runs
for that person, with that person as the actor, and with an ``oe_activity_log``
row that says it came through the assistant and who asked for it.

Covered here, against real PostgreSQL:

* propose writes no domain row, for a task and for a BOQ line;
* apply writes through the domain service with the approver as the actor and
  logs ``via=ai_assistant`` with who asked and who approved;
* reject, edit (re-validated, the model's original kept), apply twice (409),
  a stranger (404), a person without the permission (403, and the card says
  why), a locked bill (409 ``locked``), a line changed since the proposal
  (409 ``target_changed``), undo and its guard (409 ``changed_since_apply``);
* apply-all where one proposal fails and the others still land;
* the router's structured refusals.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select, update

from app.core.audit_log import ActivityLog
from app.modules.boq.models import BOQ, BOQActivityLog, Position
from app.modules.erp_chat.actions.base import (
    ActionConflictError,
    ActionNotFoundError,
    ActionPermissionError,
    ActionValidationError,
)
from app.modules.erp_chat.actions.service import ChatActionService, propose_tool_result
from app.modules.erp_chat.models import ChatAction, ChatSession
from app.modules.projects.models import Project
from app.modules.tasks.models import Task
from app.modules.teams.models import Team, TeamMembership
from app.modules.users.models import User

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _permissions() -> None:
    """The registry the auth dependency reads; the app registers it on startup, tests do not boot the app."""
    from app.modules.boq.permissions import register_boq_permissions
    from app.modules.tasks.permissions import register_tasks_permissions

    register_boq_permissions()
    register_tasks_permissions()


@pytest.fixture(autouse=True)
def published(monkeypatch: pytest.MonkeyPatch, no_detached_subscribers: None) -> list[str]:
    """Record domain events instead of handing them to subscribers that open their own sessions."""
    import app.modules.boq.service as boq_service
    import app.modules.tasks.service as tasks_service

    names: list[str] = []

    async def _record(name: str, data: dict[str, Any], source_module: str = "", *, session: Any = None) -> None:
        names.append(name)

    monkeypatch.setattr(boq_service, "_safe_publish", _record)
    monkeypatch.setattr(tasks_service, "_safe_publish", _record)
    return names


async def _user(session, name: str, role: str) -> User:
    user = User(
        email=f"{name.lower().replace(' ', '.')}-{uuid.uuid4().hex[:6]}@site.test",
        hashed_password="x",
        full_name=name,
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def _member(session, project: Project, user: User) -> None:
    team = (await session.execute(select(Team).where(Team.project_id == project.id))).scalars().first()
    if team is None:
        team = Team(project_id=project.id, name="Site team")
        session.add(team)
        await session.flush()
    session.add(TeamMembership(team_id=team.id, user_id=user.id, role="member"))
    await session.flush()


async def _bill(session, project: Project, name: str = "Shell and core") -> BOQ:
    bill = BOQ(project_id=project.id, name=name)
    session.add(bill)
    await session.flush()
    return bill


async def _line(
    session,
    bill: BOQ,
    ordinal: str,
    description: str,
    *,
    unit: str = "m3",
    quantity: str = "0",
    unit_rate: str = "0",
    sort_order: int = 0,
    parent: Position | None = None,
) -> Position:
    total = str(Decimal(quantity) * Decimal(unit_rate))
    line = Position(
        boq_id=bill.id,
        parent_id=parent.id if parent is not None else None,
        ordinal=ordinal,
        description=description,
        unit=unit,
        quantity=quantity,
        unit_rate=unit_rate,
        total=total,
        sort_order=sort_order,
    )
    session.add(line)
    await session.flush()
    return line


@pytest.fixture
async def site(pg_session) -> dict[str, Any]:
    """A project owned by a manager, with an editor, a viewer and a stranger around it."""
    director = await _user(pg_session, "Dana Director", "manager")
    editor = await _user(pg_session, "Anna Schmidt", "editor")
    viewer = await _user(pg_session, "Victor Viewer", "viewer")
    stranger = await _user(pg_session, "Sam Stranger", "manager")
    project = Project(name="Residential House", owner_id=director.id, currency="EUR")
    pg_session.add(project)
    await pg_session.flush()
    await _member(pg_session, project, editor)
    await _member(pg_session, project, viewer)
    bill = await _bill(pg_session, project)
    section = await _line(pg_session, bill, "01", "Concrete works", unit="", sort_order=1)
    wall = await _line(
        pg_session,
        bill,
        "01.10",
        "Concrete wall C30/37",
        quantity="10",
        unit_rate="100",
        sort_order=2,
        parent=section,
    )
    return {
        "director": director,
        "editor": editor,
        "viewer": viewer,
        "stranger": stranger,
        "project": project,
        "bill": bill,
        "section": section,
        "wall": wall,
    }


async def _count(session, model, *where) -> int:
    return int((await session.execute(select(func.count()).select_from(model).where(*where))).scalar_one())


async def _stored_line(session, position_id: uuid.UUID) -> dict[str, Any]:
    row = (
        await session.execute(
            select(Position.quantity, Position.unit_rate, Position.description, Position.source).where(
                Position.id == position_id
            )
        )
    ).one()
    return {"quantity": Decimal(row[0]), "unit_rate": Decimal(row[1]), "description": row[2], "source": row[3]}


async def _propose_task(session, site: dict[str, Any], **args: Any) -> ChatAction:
    service = ChatActionService(session)
    return await service.propose(
        tool_name="propose_create_task",
        args={"title": "Check formwork on level 3", "due_date": "2026-09-25", **args},
        user_id=site["editor"].id,
        project_id=site["project"].id,
        batch_id="turn-1",
    )


# ── Propose writes nothing to the domain ────────────────────────────────────


@pytest.mark.asyncio
async def test_a_proposed_task_is_a_card_and_not_a_task(pg_session, site) -> None:
    action = await _propose_task(pg_session, site, priority="high", confidence=0.9, rationale="Asked for Friday")

    assert await _count(pg_session, Task, Task.project_id == site["project"].id) == 0
    assert action.status == "proposed"
    assert action.requested_by == site["editor"].id
    assert action.project_id == site["project"].id
    assert action.confidence == pytest.approx(0.9)
    assert action.payload == action.original_payload
    assert "confidence" not in action.payload and "rationale" not in action.payload

    service = ChatActionService(pg_session)
    [dto] = await service.to_dtos([action], await service.viewer(site["director"].id))
    assert dto.title_key == "erp_chat.action.type.task.create"
    assert dto.subtitle == "Check formwork on level 3"
    assert dto.project_name == "Residential House"
    assert dto.requested_by is not None and dto.requested_by.name == "Anna Schmidt"
    assert {f.key for f in dto.fields} >= {"title", "priority", "due_date", "assignee"}
    assert dto.can_apply and dto.can_edit and dto.can_reject and not dto.can_revert
    assert not dto.edited


@pytest.mark.asyncio
async def test_a_proposed_boq_line_is_numbered_like_the_editor_and_not_written(pg_session, site) -> None:
    service = ChatActionService(pg_session)
    first = await service.propose(
        tool_name="propose_add_boq_position",
        args={"description": "Slab formwork level 3", "unit": "m2", "quantity": 120, "unit_rate": "35.50"},
        user_id=site["editor"].id,
        project_id=site["project"].id,
    )
    second = await service.propose(
        tool_name="propose_add_boq_position",
        args={"description": "Slab concrete level 3", "unit": "m3", "quantity": "24", "unit_rate": 145},
        user_id=site["editor"].id,
        project_id=site["project"].id,
    )

    assert await _count(pg_session, Position, Position.boq_id == site["bill"].id) == 2
    # The bill has 01.10; two proposals of one turn do not claim the same number.
    assert first.payload["ordinal"] == "01.20"
    assert second.payload["ordinal"] == "01.30"
    assert first.payload["section_id"] == str(site["section"].id)
    fields = {f["key"]: f for f in first.preview["fields"]}
    assert fields["total"]["value"] == pytest.approx(4260)
    assert fields["unit_rate"]["currency"] == "EUR"
    assert first.preview["subtitle"] == "Shell and core"


# ── Apply ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_applying_a_task_writes_it_as_the_approver_and_logs_the_assistant(pg_session, site) -> None:
    action = await _propose_task(pg_session, site, assignee="anna schmidt", confidence=0.8)
    service = ChatActionService(pg_session)
    director = await service.viewer(site["director"].id)

    applied = await service.apply(action.id, director)

    assert applied.status == "applied"
    assert applied.decided_by == site["director"].id
    task = (await pg_session.execute(select(Task).where(Task.id == uuid.UUID(applied.applied_entity_id)))).scalar_one()
    assert task.created_by == str(site["director"].id)
    assert str(task.responsible_id) == str(site["editor"].id)
    assert task.metadata_["via"] == "ai_assistant"
    assert task.metadata_["ai_action_id"] == str(action.id)

    log = (
        (
            await pg_session.execute(
                select(ActivityLog).where(ActivityLog.module == "erp_chat", ActivityLog.entity_id == str(task.id))
            )
        )
        .scalars()
        .one()
    )
    assert log.action == "created"
    assert log.entity_type == "task"
    assert log.actor_id == site["director"].id
    assert log.parent_entity_type == "project"
    assert log.parent_entity_id == str(site["project"].id)
    assert log.metadata_["via"] == "ai_assistant"
    assert log.metadata_["requested_by"] == str(site["editor"].id)
    assert log.metadata_["approved_by"] == str(site["director"].id)
    assert log.metadata_["confidence"] == pytest.approx(0.8)
    assert log.metadata_["edited_by_human"] is False

    [dto] = await service.to_dtos([applied], director)
    assert dto.result is not None and dto.result.url == f"/projects/{site['project'].id}/tasks?id={task.id}"
    assert dto.decided_by is not None and dto.decided_by.name == "Dana Director"
    assert dto.can_revert
    # An assignee was notified; undo says it cannot take that back.
    assert dto.revert_hint_key == "erp_chat.action.revert_hint.task_notifications"


@pytest.mark.asyncio
async def test_applying_a_boq_line_goes_through_the_service_with_the_routes_activity_row(pg_session, site) -> None:
    service = ChatActionService(pg_session)
    action = await service.propose(
        tool_name="propose_add_boq_position",
        args={
            "description": "Slab formwork level 3",
            "unit": "m2",
            "quantity": 120,
            "unit_rate": 35.5,
            "confidence": 0.7,
        },
        user_id=site["editor"].id,
        project_id=site["project"].id,
    )
    applied = await service.apply(action.id, await service.viewer(site["director"].id))

    assert applied.status == "applied"
    line = (
        await pg_session.execute(select(Position).where(Position.id == uuid.UUID(applied.applied_entity_id)))
    ).scalar_one()
    assert line.ordinal == "01.20"
    assert line.parent_id == site["section"].id
    assert line.source == "ai_match"
    assert Decimal(line.confidence) == Decimal("0.7")
    assert Decimal(line.total) == Decimal("4260")
    assert line.metadata_["ai_action_id"] == str(action.id)
    assert line.metadata_["requested_by"] == str(site["editor"].id)

    route_row = (
        (
            await pg_session.execute(
                select(BOQActivityLog).where(
                    BOQActivityLog.target_id == line.id, BOQActivityLog.action == "position_added"
                )
            )
        )
        .scalars()
        .one()
    )
    assert route_row.user_id == site["director"].id
    assert (
        await _count(pg_session, ActivityLog, ActivityLog.module == "erp_chat", ActivityLog.entity_id == str(line.id))
        == 1
    )
    assert applied.result["url"] == f"/boq/{site['bill'].id}?highlight={line.id}"


@pytest.mark.asyncio
async def test_applying_twice_is_a_conflict_not_a_second_record(pg_session, site) -> None:
    action = await _propose_task(pg_session, site)
    service = ChatActionService(pg_session)
    director = await service.viewer(site["director"].id)
    await service.apply(action.id, director)

    with pytest.raises(ActionConflictError) as caught:
        await service.apply(action.id, director)
    assert caught.value.code == "not_pending"
    assert caught.value.status_code == 409
    assert await _count(pg_session, Task, Task.project_id == site["project"].id) == 1


@pytest.mark.asyncio
async def test_a_stranger_cannot_see_or_apply_a_proposal(pg_session, site) -> None:
    action = await _propose_task(pg_session, site)
    service = ChatActionService(pg_session)
    stranger = await service.viewer(site["stranger"].id)

    with pytest.raises(ActionNotFoundError):
        await service.get_visible(action.id, stranger)
    with pytest.raises(ActionNotFoundError):
        await service.apply(action.id, stranger)
    rows, total, counts = await service.list(stranger)
    assert rows == [] and total == 0 and counts.proposed == 0


@pytest.mark.asyncio
async def test_a_viewer_sees_why_they_cannot_apply_and_is_refused(pg_session, site) -> None:
    action = await _propose_task(pg_session, site)
    service = ChatActionService(pg_session)
    viewer = await service.viewer(site["viewer"].id)

    [dto] = await service.to_dtos([action], viewer)
    assert not dto.can_apply
    assert dto.blocked_reason_key == "erp_chat.action.blocked.permission"
    with pytest.raises(ActionPermissionError):
        await service.apply(action.id, viewer)
    assert (await service.get_visible(action.id, viewer)).status == "proposed"
    assert await _count(pg_session, Task, Task.project_id == site["project"].id) == 0


# ── Reject and edit ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rejecting_records_who_and_why_and_writes_nothing(pg_session, site) -> None:
    action = await _propose_task(pg_session, site)
    service = ChatActionService(pg_session)
    rejected = await service.reject(action.id, await service.viewer(site["editor"].id), "Wrong level")

    assert rejected.status == "rejected"
    assert rejected.decided_by == site["editor"].id
    assert rejected.decision_note == "Wrong level"
    assert await _count(pg_session, Task, Task.project_id == site["project"].id) == 0
    with pytest.raises(ActionConflictError):
        await service.apply(action.id, await service.viewer(site["director"].id))


@pytest.mark.asyncio
async def test_an_edit_is_revalidated_and_the_models_original_is_kept(pg_session, site) -> None:
    action = await _propose_task(pg_session, site)
    service = ChatActionService(pg_session)
    editor = await service.viewer(site["editor"].id)

    with pytest.raises(ActionValidationError) as bad_date:
        await service.patch(action.id, editor, {"due_date": "next Friday"})
    assert set(bad_date.value.field_errors) == {"due_date"}
    with pytest.raises(ActionValidationError) as not_editable:
        await service.patch(action.id, editor, {"project_id": str(uuid.uuid4())})
    assert set(not_editable.value.field_errors) == {"project_id"}

    edited = await service.patch(action.id, editor, {"title": "Check formwork on levels 3 and 4", "priority": "urgent"})
    assert edited.payload["title"] == "Check formwork on levels 3 and 4"
    assert edited.payload["priority"] == "urgent"
    assert edited.original_payload["title"] == "Check formwork on level 3"
    [dto] = await service.to_dtos([edited], editor)
    assert dto.edited
    assert dto.subtitle == "Check formwork on levels 3 and 4"

    applied = await service.apply(action.id, await service.viewer(site["director"].id))
    log = (
        (await pg_session.execute(select(ActivityLog).where(ActivityLog.entity_id == applied.applied_entity_id)))
        .scalars()
        .all()
    )
    assert [row.metadata_["edited_by_human"] for row in log if row.module == "erp_chat"] == [True]


@pytest.mark.asyncio
async def test_an_unknown_assignee_leaves_the_task_unassigned_and_the_card_offers_the_members(pg_session, site) -> None:
    action = await _propose_task(pg_session, site, assignee="Ivan")
    assert action.payload["responsible_id"] is None
    notes = action.preview["notes"]
    assert [n["key"] for n in notes] == ["erp_chat.action.note.assignee_unmatched"]
    assert notes[0]["params"] == {"name": "Ivan"}

    # The assignee is a pick list of the people on the project, not the stranger.
    assignee = next(f for f in action.preview["fields"] if f["key"] == "assignee")
    assert assignee["kind"] == "enum" and assignee["value"] is None and assignee["editable"]
    offered = {o["label"]: o["value"] for o in assignee["options"]}
    assert set(offered) == {"Anna Schmidt", "Dana Director", "Victor Viewer"}
    assert all(o["label_key"] is None for o in assignee["options"])

    service = ChatActionService(pg_session)
    editor = await service.viewer(site["editor"].id)
    picked = await service.patch(action.id, editor, {"assignee": offered["Anna Schmidt"]})
    assert picked.payload["responsible_id"] == str(site["editor"].id)
    assert picked.payload["assignee"] == "Anna Schmidt"
    assert picked.preview["notes"] == []
    [dto] = await service.to_dtos([picked], editor)
    assert dto.edited

    # A typed name is matched again; clearing the pick leaves the task unassigned without a warning.
    retyped = await service.patch(action.id, editor, {"assignee": "dana"})
    assert retyped.payload["responsible_id"] == str(site["director"].id)
    cleared = await service.patch(action.id, editor, {"assignee": ""})
    assert cleared.payload["responsible_id"] is None and cleared.preview["notes"] == []
    with pytest.raises(ActionValidationError) as outsider:
        await service.patch(action.id, editor, {"assignee": str(site["stranger"].id)})
    assert set(outsider.value.field_errors) == {"assignee"}


# ── State checks at apply time ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_bill_locked_after_the_proposal_is_refused_at_apply(pg_session, site) -> None:
    service = ChatActionService(pg_session)
    action = await service.propose(
        tool_name="propose_add_boq_position",
        args={"description": "Rebar B500", "unit": "t", "quantity": 2},
        user_id=site["editor"].id,
        project_id=site["project"].id,
    )
    await pg_session.execute(update(BOQ).where(BOQ.id == site["bill"].id).values(is_locked=True))

    with pytest.raises(ActionConflictError) as caught:
        await service.apply(action.id, await service.viewer(site["director"].id))
    assert caught.value.code == "locked"
    assert (await service.get_visible(action.id, await service.viewer(site["director"].id))).status == "proposed"
    assert await _count(pg_session, Position, Position.boq_id == site["bill"].id) == 2

    result = await propose_tool_result(
        pg_session,
        tool_name="propose_add_boq_position",
        args={"description": "Rebar B500", "unit": "t", "quantity": 2},
        user_id=site["editor"].id,
        project_id=site["project"].id,
    )
    assert result["renderer"] == "error"
    assert result["data"]["error"] == "locked"


@pytest.mark.asyncio
async def test_a_line_changed_since_the_proposal_is_not_overwritten(pg_session, site) -> None:
    service = ChatActionService(pg_session)
    action = await service.propose(
        tool_name="propose_update_boq_position",
        args={"ordinal": "01.10", "quantity": 20},
        user_id=site["editor"].id,
        project_id=site["project"].id,
    )
    fields = {f["key"]: f for f in action.preview["fields"]}
    assert fields["quantity"]["before"] == 10 and fields["quantity"]["value"] == 20
    assert fields["total"]["before"] == 1000 and fields["total"]["value"] == 2000
    assert action.before_state["quantity"] == "10"

    # Someone edits the line by hand before the director applies.
    await pg_session.execute(update(Position).where(Position.id == site["wall"].id).values(quantity="15"))

    with pytest.raises(ActionConflictError) as caught:
        await service.apply(action.id, await service.viewer(site["director"].id))
    assert caught.value.code == "target_changed"
    assert (await _stored_line(pg_session, site["wall"].id))["quantity"] == Decimal("15")


@pytest.mark.asyncio
async def test_an_applied_edit_can_be_undone_while_nobody_touched_the_line(pg_session, site) -> None:
    service = ChatActionService(pg_session)
    action = await service.propose(
        tool_name="propose_update_boq_position",
        args={"position_id": str(site["wall"].id), "quantity": "20", "unit_rate": "110"},
        user_id=site["editor"].id,
        project_id=site["project"].id,
    )
    director = await service.viewer(site["director"].id)
    applied = await service.apply(action.id, director)
    assert applied.status == "applied"
    stored = await _stored_line(pg_session, site["wall"].id)
    assert stored["quantity"] == Decimal("20") and stored["unit_rate"] == Decimal("110")
    assert stored["source"] == "manual"  # an edit does not relabel a hand-typed line as AI
    diff_rows = (
        (await pg_session.execute(select(BOQActivityLog).where(BOQActivityLog.target_id == site["wall"].id)))
        .scalars()
        .all()
    )
    assert diff_rows and all(row.user_id == site["director"].id for row in diff_rows)

    reverted = await service.revert(action.id, director, "Wrong drawing")
    assert reverted.status == "reverted"
    assert reverted.reverted_by == site["director"].id
    stored = await _stored_line(pg_session, site["wall"].id)
    assert stored["quantity"] == Decimal("10") and stored["unit_rate"] == Decimal("100")
    actions = (
        (
            await pg_session.execute(
                select(ActivityLog.action).where(
                    ActivityLog.module == "erp_chat", ActivityLog.entity_id == str(site["wall"].id)
                )
            )
        )
        .scalars()
        .all()
    )
    assert sorted(actions) == ["reverted", "updated"]


@pytest.mark.asyncio
async def test_undo_refuses_when_the_record_changed_after_apply(pg_session, site) -> None:
    service = ChatActionService(pg_session)
    action = await service.propose(
        tool_name="propose_add_boq_position",
        args={"description": "Slab formwork level 3", "unit": "m2", "quantity": 120},
        user_id=site["editor"].id,
        project_id=site["project"].id,
    )
    director = await service.viewer(site["director"].id)
    applied = await service.apply(action.id, director)
    line_id = uuid.UUID(applied.applied_entity_id)
    await pg_session.execute(update(Position).where(Position.id == line_id).values(quantity="130"))

    with pytest.raises(ActionConflictError) as caught:
        await service.revert(action.id, director)
    assert caught.value.code == "changed_since_apply"
    assert await _count(pg_session, Position, Position.id == line_id) == 1

    # Put it back as applied: undo now deletes the line.
    await pg_session.execute(update(Position).where(Position.id == line_id).values(quantity="120"))
    reverted = await service.revert(action.id, director)
    assert reverted.status == "reverted"
    assert await _count(pg_session, Position, Position.id == line_id) == 0


@pytest.mark.asyncio
async def test_undo_of_a_task_deleted_by_hand_says_it_is_gone(pg_session, site) -> None:
    action = await _propose_task(pg_session, site)
    service = ChatActionService(pg_session)
    director = await service.viewer(site["director"].id)
    applied = await service.apply(action.id, director)
    await pg_session.execute(delete(Task).where(Task.id == uuid.UUID(applied.applied_entity_id)))

    with pytest.raises(ActionConflictError) as caught:
        await service.revert(action.id, director)
    assert caught.value.code == "target_missing"
    assert (await service.get_visible(action.id, director)).status == "applied"


# ── Apply all ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_apply_all_keeps_what_applied_when_one_proposal_fails(pg_session, site, monkeypatch) -> None:
    from app.modules.tasks.service import TaskService

    service = ChatActionService(pg_session)
    line_a = await service.propose(
        tool_name="propose_add_boq_position",
        args={"description": "Slab formwork level 3", "unit": "m2", "quantity": 120},
        user_id=site["editor"].id,
        project_id=site["project"].id,
        batch_id="turn-7",
    )
    line_b = await service.propose(
        tool_name="propose_add_boq_position",
        args={"description": "Slab concrete level 3", "unit": "m3", "quantity": 24},
        user_id=site["editor"].id,
        project_id=site["project"].id,
        batch_id="turn-7",
    )
    doomed = await _propose_task(pg_session, site, title="Order crane")
    drifted = await service.propose(
        tool_name="propose_update_boq_position",
        args={"ordinal": "01.10", "quantity": 20},
        user_id=site["editor"].id,
        project_id=site["project"].id,
        batch_id="turn-7",
    )
    await pg_session.execute(update(Position).where(Position.id == site["wall"].id).values(quantity="11"))

    real_create = TaskService.create_task

    async def _refuse_crane(self: TaskService, data: Any, user_id: str | None = None) -> Task:
        if data.title == "Order crane":
            raise HTTPException(status_code=400, detail="Crane orders are closed")
        return await real_create(self, data, user_id=user_id)

    monkeypatch.setattr(TaskService, "create_task", _refuse_crane)

    items, errors = await service.apply_batch(
        [line_a.id, doomed.id, drifted.id, line_b.id],
        await service.viewer(site["director"].id),
    )

    by_id = {a.id: a for a in items}
    assert by_id[line_a.id].status == "applied"
    assert by_id[line_b.id].status == "applied"
    assert by_id[doomed.id].status == "failed"
    assert by_id[doomed.id].error == "Crane orders are closed"
    assert by_id[doomed.id].error_code == "domain_error"
    assert by_id[drifted.id].status == "proposed"
    assert [(e["id"], e["code"]) for e in errors] == [(drifted.id, "target_changed")]
    ordinals = (
        (await pg_session.execute(select(Position.ordinal).where(Position.boq_id == site["bill"].id))).scalars().all()
    )
    assert sorted(ordinals) == ["01", "01.10", "01.20", "01.30"]

    # The failed one can be retried once the cause is gone.
    monkeypatch.setattr(TaskService, "create_task", real_create)
    retried = await service.apply(doomed.id, await service.viewer(site["director"].id))
    assert retried.status == "applied" and retried.error is None


# ── What the model gets back, what the router says ──────────────────────────


@pytest.mark.asyncio
async def test_the_model_is_asked_to_pick_a_bill_when_there_are_several(pg_session, site) -> None:
    await _bill(pg_session, site["project"], name="External works")
    chat = ChatSession(user_id=site["editor"].id, project_id=site["project"].id, title="Level 3")
    pg_session.add(chat)
    await pg_session.flush()

    refused = await propose_tool_result(
        pg_session,
        tool_name="propose_add_boq_position",
        args={"description": "Kerb stones", "unit": "m", "quantity": 40},
        user_id=site["editor"].id,
        chat_session_id=chat.id,
        project_id=site["project"].id,
    )
    assert refused["renderer"] == "error"
    assert refused["data"]["error"] == "boq_ambiguous"
    assert {o["name"] for o in refused["data"]["options"]} == {"Shell and core", "External works"}

    accepted = await propose_tool_result(
        pg_session,
        tool_name="propose_add_boq_position",
        args={"description": "Kerb stones", "unit": "m", "quantity": 40, "boq": "external"},
        user_id=site["editor"].id,
        chat_session_id=chat.id,
        project_id=site["project"].id,
        batch_id="turn-2",
    )
    assert accepted["renderer"] == "action_proposal"
    assert accepted["data"]["status"] == "proposed"
    assert accepted["data"]["session_id"] == str(chat.id)
    assert accepted["data"]["subtitle"] == "External works"
    assert "NOT saved" in accepted["summary"]
    # External works has no sections: the line goes top level, numbered 0010, and the card says so.
    assert accepted["data"]["payload"]["ordinal"] == "0010"
    assert [n["key"] for n in accepted["data"]["notes"]] == ["erp_chat.action.note.top_level_position"]


@pytest.mark.asyncio
async def test_the_router_answers_with_structured_refusals_and_counts(pg_session, site) -> None:
    from app.modules.erp_chat.actions.router import apply_action, get_action, list_actions

    action = await _propose_task(pg_session, site)
    await _propose_task(pg_session, site, title="Second task")

    listed = await list_actions(
        user_id=str(site["director"].id),
        session=pg_session,
        project_id=site["project"].id,
        status="proposed",
        session_id=None,
        batch_id=None,
        limit=50,
        offset=0,
    )
    assert listed.total == 2 and listed.counts.proposed == 2 and len(listed.items) == 2

    applied = await apply_action(action.id, str(site["director"].id), pg_session)
    assert applied.status == "applied"
    with pytest.raises(HTTPException) as twice:
        await apply_action(action.id, str(site["director"].id), pg_session)
    assert twice.value.status_code == 409
    assert twice.value.detail["code"] == "not_pending"
    assert twice.value.detail["message"]
    with pytest.raises(HTTPException) as hidden:
        await get_action(action.id, str(site["stranger"].id), pg_session)
    assert hidden.value.status_code == 404

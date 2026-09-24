"""PG: the RFI, risk, punch item and schedule progress proposals, from card to record and back.

Each proposal is checked the way the BOQ line and the task are in
``test_erp_chat_action_lifecycle.py``, against real PostgreSQL:

* propose writes no domain row (or changes no progress);
* apply writes through the domain service for the person who clicks Apply,
  under the gates of the record's own REST route, and logs an
  ``oe_activity_log`` row with ``via=ai_assistant``, who asked, who approved,
  and the record's in-app link and label;
* a stranger to the project neither sees nor applies it (404);
* undo is refused once the record moved on (409) and works while it did not.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import delete, func, select, update

from app.core.audit_log import ActivityLog
from app.modules.erp_chat.actions.base import (
    ActionConflictError,
    ActionContext,
    ActionNotFoundError,
    ActionValidationError,
)
from app.modules.erp_chat.actions.service import ChatActionService
from app.modules.erp_chat.models import ChatAction
from app.modules.projects.models import Project
from app.modules.rfi.models import RFI
from app.modules.teams.models import Team, TeamMembership
from app.modules.users.models import User

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _permissions() -> None:
    """The registry the auth dependency reads; the app registers it on startup, tests do not boot the app."""
    from app.modules.punchlist.permissions import register_punchlist_permissions
    from app.modules.rfi.permissions import register_rfi_permissions
    from app.modules.risk.permissions import register_risk_permissions
    from app.modules.schedule.permissions import register_schedule_permissions

    register_rfi_permissions()
    register_risk_permissions()
    register_punchlist_permissions()
    register_schedule_permissions()


@pytest.fixture(autouse=True)
def published(monkeypatch: pytest.MonkeyPatch, no_detached_subscribers: None) -> list[str]:
    """Record domain events instead of handing them to subscribers that open their own sessions."""
    import app.modules.punchlist.service as punch_service
    import app.modules.rfi.service as rfi_service
    import app.modules.risk.escalation as risk_escalation
    import app.modules.risk.service as risk_service
    import app.modules.schedule.service as schedule_service

    names: list[str] = []

    async def _record(name: str, data: dict[str, Any], *args: Any, **kwargs: Any) -> None:
        names.append(name)

    async def _escalated(**kwargs: Any) -> None:
        names.append("risk.escalated")

    for module in (rfi_service, risk_service, punch_service, schedule_service):
        monkeypatch.setattr(module, "_safe_publish", _record)
    monkeypatch.setattr(risk_escalation, "_emit_escalated", _escalated)
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


@pytest.fixture
async def site(pg_session) -> dict[str, Any]:
    """A project owned by a manager, with an editor on its team and a stranger (a manager elsewhere)."""
    director = await _user(pg_session, "Dana Director", "manager")
    editor = await _user(pg_session, "Anna Schmidt", "editor")
    stranger = await _user(pg_session, "Sam Stranger", "manager")
    project = Project(name="Residential House", owner_id=director.id, currency="EUR")
    pg_session.add(project)
    await pg_session.flush()
    await _member(pg_session, project, editor)
    return {"director": director, "editor": editor, "stranger": stranger, "project": project}


async def _count(session, model, *where) -> int:
    return int((await session.execute(select(func.count()).select_from(model).where(*where))).scalar_one())


async def _propose(session, site: dict[str, Any], tool: str, args: dict[str, Any]) -> ChatAction:
    return await ChatActionService(session).propose(
        tool_name=tool,
        args=args,
        user_id=site["editor"].id,
        project_id=site["project"].id,
        batch_id="turn-1",
    )


async def _audit_row(session, entity_id: str, action: str) -> ActivityLog:
    stmt = select(ActivityLog).where(
        ActivityLog.module == "erp_chat",
        ActivityLog.entity_id == entity_id,
        ActivityLog.action == action,
    )
    return (await session.execute(stmt)).scalars().one()


def _assert_assistant_row(log: ActivityLog, site: dict[str, Any], action: ChatAction, entity_type: str) -> None:
    assert log.entity_type == entity_type
    assert log.actor_id == site["director"].id
    assert log.parent_entity_type == "project"
    assert log.parent_entity_id == str(site["project"].id)
    assert log.metadata_["via"] == "ai_assistant"
    assert log.metadata_["ai_action_id"] == str(action.id)
    assert log.metadata_["requested_by"] == str(site["editor"].id)
    assert log.metadata_["approved_by"] == str(site["director"].id)


# ── rfi.create ──────────────────────────────────────────────────────────────

_RFI_ARGS: dict[str, Any] = {
    "subject": "Rebar grade level 3 slab",
    "question": "Which rebar grade applies to the level 3 slab?",
    "priority": "high",
    "discipline": "structural",
    "response_due_date": "2026-10-02",
    "assignee": "anna schmidt",
    "cost_impact_value": 1500,
}


@pytest.mark.asyncio
async def test_a_proposed_rfi_is_a_card_and_not_an_rfi(pg_session, site) -> None:
    action = await _propose(pg_session, site, "propose_create_rfi", {**_RFI_ARGS, "confidence": 0.8})

    assert action.status == "proposed"
    assert await _count(pg_session, RFI, RFI.project_id == site["project"].id) == 0
    assert action.payload["assigned_to"] == str(site["editor"].id)
    assert action.payload["cost_impact"] == "yes" and action.payload["cost_impact_value"] == "1500"


@pytest.mark.asyncio
async def test_applying_an_rfi_raises_it_as_the_approver_and_logs_the_assistant(pg_session, site, published) -> None:
    action = await _propose(pg_session, site, "propose_create_rfi", {**_RFI_ARGS, "confidence": 0.8})
    service = ChatActionService(pg_session)
    director = await service.viewer(site["director"].id)

    applied = await service.apply(action.id, director)

    assert applied.status == "applied", applied.error
    rfi = (await pg_session.execute(select(RFI).where(RFI.id == uuid.UUID(applied.applied_entity_id)))).scalar_one()
    assert rfi.raised_by == site["director"].id
    assert rfi.created_by == str(site["director"].id)
    assert str(rfi.assigned_to) == str(site["editor"].id)
    assert str(rfi.ball_in_court) == str(site["editor"].id)
    assert rfi.status == "draft"
    assert (rfi.priority, rfi.discipline, rfi.response_due_date) == ("high", "structural", "2026-10-02")
    assert rfi.cost_impact is True and rfi.cost_impact_value == "1500"
    assert rfi.metadata_["via"] == "ai_assistant" and rfi.metadata_["approved_by"] == str(site["director"].id)
    assert "rfi.assigned" in published

    log = await _audit_row(pg_session, str(rfi.id), "created")
    _assert_assistant_row(log, site, action, "rfi")
    assert log.metadata_["url"] == f"/rfi/{rfi.id}"
    assert log.metadata_["label"] == f"{rfi.rfi_number} {rfi.subject}"

    [dto] = await service.to_dtos([applied], director)
    assert dto.result is not None and dto.result.url == f"/rfi/{rfi.id}"
    assert dto.can_revert
    assert dto.revert_hint_key == "erp_chat.action.revert_hint.rfi_notifications"


@pytest.mark.asyncio
async def test_a_stranger_can_neither_see_nor_apply_an_rfi(pg_session, site) -> None:
    action = await _propose(pg_session, site, "propose_create_rfi", _RFI_ARGS)
    service = ChatActionService(pg_session)
    stranger = await service.viewer(site["stranger"].id)

    with pytest.raises(ActionNotFoundError):
        await service.apply(action.id, stranger)
    ctx = await ActionContext.load(pg_session, site["stranger"].id)
    with pytest.raises(ActionNotFoundError):
        await service._spec(action).check_apply_gates(ctx, dict(action.payload))
    assert await _count(pg_session, RFI, RFI.project_id == site["project"].id) == 0


@pytest.mark.asyncio
async def test_undo_deletes_an_unanswered_rfi_and_logs_it(pg_session, site) -> None:
    action = await _propose(pg_session, site, "propose_create_rfi", _RFI_ARGS)
    service = ChatActionService(pg_session)
    director = await service.viewer(site["director"].id)
    applied = await service.apply(action.id, director)
    rfi_id = applied.applied_entity_id

    reverted = await service.revert(action.id, director, "Asked the wrong person")

    assert reverted.status == "reverted"
    assert reverted.reverted_by == site["director"].id
    assert await _count(pg_session, RFI, RFI.id == uuid.UUID(rfi_id)) == 0
    log = await _audit_row(pg_session, rfi_id, "reverted")
    assert log.after_state is None
    assert log.metadata_["reverted_by"] == str(site["director"].id)
    # The record is gone, so the undo row carries no link to it.
    assert "url" not in log.metadata_


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        {"status": "answered", "official_response": "B500B"},
        {"official_response": "B500B"},
        {"subject": "Rebar grade level 3 and 4 slabs"},
        {"status": "open"},
    ],
)
async def test_undo_refuses_an_rfi_that_was_answered_or_changed(pg_session, site, change) -> None:
    action = await _propose(pg_session, site, "propose_create_rfi", _RFI_ARGS)
    service = ChatActionService(pg_session)
    director = await service.viewer(site["director"].id)
    applied = await service.apply(action.id, director)
    rfi_id = uuid.UUID(applied.applied_entity_id)
    await pg_session.execute(update(RFI).where(RFI.id == rfi_id).values(**change))

    with pytest.raises(ActionConflictError) as caught:
        await service.revert(action.id, director)
    assert caught.value.code == "changed_since_apply"
    assert await _count(pg_session, RFI, RFI.id == rfi_id) == 1
    assert (await service.get_visible(action.id, director)).status == "applied"


@pytest.mark.asyncio
async def test_undo_of_an_rfi_deleted_by_hand_says_it_is_gone(pg_session, site) -> None:
    action = await _propose(pg_session, site, "propose_create_rfi", _RFI_ARGS)
    service = ChatActionService(pg_session)
    director = await service.viewer(site["director"].id)
    applied = await service.apply(action.id, director)
    await pg_session.execute(delete(RFI).where(RFI.id == uuid.UUID(applied.applied_entity_id)))

    with pytest.raises(ActionConflictError) as caught:
        await service.revert(action.id, director)
    assert caught.value.code == "target_missing"


@pytest.mark.asyncio
async def test_an_rfi_without_a_subject_goes_back_to_the_model(pg_session, site) -> None:
    with pytest.raises(ActionValidationError) as caught:
        await _propose(pg_session, site, "propose_create_rfi", {"question": "Which grade?"})
    assert set(caught.value.field_errors) == {"subject"}
    assert await _count(pg_session, ChatAction, ChatAction.project_id == site["project"].id) == 0


# ── risk.create ─────────────────────────────────────────────────────────────

_RISK_ARGS: dict[str, Any] = {
    "title": "Crane permit late",
    "description": "The city may not issue the tower crane permit before the slab pour.",
    "category": "regulatory",
    "probability": 30,
    "impact_severity": "high",
    "impact_cost": 12000,
    "impact_schedule_days": 20,
    "owner": "Anna Schmidt",
    "mitigation_strategy": "File the permit this week and book a mobile crane as a fallback.",
}


@pytest.mark.asyncio
async def test_applying_a_risk_logs_it_for_the_approver_with_the_projects_currency(pg_session, site, published) -> None:
    from app.modules.risk.models import RiskItem

    action = await _propose(pg_session, site, "propose_create_risk", {**_RISK_ARGS, "confidence": 0.6})
    assert await _count(pg_session, RiskItem, RiskItem.project_id == site["project"].id) == 0

    service = ChatActionService(pg_session)
    director = await service.viewer(site["director"].id)
    applied = await service.apply(action.id, director)

    assert applied.status == "applied", applied.error
    item = (
        await pg_session.execute(select(RiskItem).where(RiskItem.id == uuid.UUID(applied.applied_entity_id)))
    ).scalar_one()
    assert item.code == "R-001"
    assert (item.category, item.impact_severity, item.status) == ("regulatory", "high", "identified")
    assert float(item.probability) == pytest.approx(0.3)
    assert item.impact_cost == "12000" and item.impact_schedule_days == 20
    assert item.currency == "EUR"
    assert item.owner_user_id == site["editor"].id and item.owner_name == "Anna Schmidt"
    assert item.escalated is False
    # The risk table has no creator column: the approver is on the risk's metadata and the audit row.
    assert item.metadata_["via"] == "ai_assistant" and item.metadata_["approved_by"] == str(site["director"].id)
    assert "risk.assigned" in published

    log = await _audit_row(pg_session, str(item.id), "created")
    _assert_assistant_row(log, site, action, "risk")
    assert log.metadata_["url"] == f"/risks?id={item.id}"
    assert log.metadata_["label"] == "R-001 Crane permit late"
    [dto] = await service.to_dtos([applied], director)
    assert dto.revert_hint_key == "erp_chat.action.revert_hint.risk_notifications"


@pytest.mark.asyncio
async def test_a_risk_born_critical_is_escalated_and_undo_says_the_notice_stays(pg_session, site, published) -> None:
    from app.modules.risk.models import RiskItem

    args = {**_RISK_ARGS, "probability": 90, "impact_severity": "critical", "owner": None}
    action = await _propose(pg_session, site, "propose_create_risk", args)
    service = ChatActionService(pg_session)
    director = await service.viewer(site["director"].id)
    applied = await service.apply(action.id, director)

    assert applied.status == "applied", applied.error
    risk_id = uuid.UUID(applied.applied_entity_id)
    assert (await pg_session.execute(select(RiskItem.escalated).where(RiskItem.id == risk_id))).scalar_one()
    assert "risk.escalated" in published
    [dto] = await service.to_dtos([applied], director)
    assert dto.revert_hint_key == "erp_chat.action.revert_hint.risk_escalated"

    reverted = await service.revert(action.id, director)
    assert reverted.status == "reverted"
    assert await _count(pg_session, RiskItem, RiskItem.id == risk_id) == 0


@pytest.mark.asyncio
async def test_the_risk_gate_checks_project_access_that_the_rest_route_does_not(pg_session, site) -> None:
    action = await _propose(pg_session, site, "propose_create_risk", _RISK_ARGS)
    service = ChatActionService(pg_session)

    # A manager of another project holds ``risk.create``, which is all ``POST /risk/`` asks for.
    ctx = await ActionContext.load(pg_session, site["stranger"].id)
    assert ctx.has_permission("risk.create")
    with pytest.raises(ActionNotFoundError):
        await service._spec(action).check_apply_gates(ctx, dict(action.payload))
    with pytest.raises(ActionNotFoundError):
        await service.apply(action.id, await service.viewer(site["stranger"].id))

    # The person who asked still sees their proposal after leaving the team, and the gate refuses them.
    await pg_session.execute(delete(TeamMembership).where(TeamMembership.user_id == site["editor"].id))
    editor = await service.viewer(site["editor"].id)
    assert (await service.get_visible(action.id, editor)).status == "proposed"
    with pytest.raises(ActionNotFoundError):
        await service.apply(action.id, editor)


@pytest.mark.asyncio
async def test_undo_refuses_a_risk_that_moved_on_and_deletes_one_that_did_not(pg_session, site) -> None:
    from app.modules.risk.models import RiskItem

    service = ChatActionService(pg_session)
    director = await service.viewer(site["director"].id)
    moved = await _propose(pg_session, site, "propose_create_risk", _RISK_ARGS)
    moved_id = uuid.UUID((await service.apply(moved.id, director)).applied_entity_id)
    await pg_session.execute(update(RiskItem).where(RiskItem.id == moved_id).values(status="mitigating"))
    with pytest.raises(ActionConflictError) as caught:
        await service.revert(moved.id, director)
    assert caught.value.code == "changed_since_apply"

    kept = await _propose(pg_session, site, "propose_create_risk", {**_RISK_ARGS, "title": "Late steel delivery"})
    kept_id = (await service.apply(kept.id, director)).applied_entity_id
    reverted = await service.revert(kept.id, director)
    assert reverted.status == "reverted"
    assert await _count(pg_session, RiskItem, RiskItem.id == uuid.UUID(kept_id)) == 0
    assert await _count(pg_session, RiskItem, RiskItem.id == moved_id) == 1
    log = await _audit_row(pg_session, kept_id, "reverted")
    assert log.metadata_["label"] == "R-002 Late steel delivery" and "url" not in log.metadata_


# ── punch.create_item ───────────────────────────────────────────────────────

_PUNCH_ARGS: dict[str, Any] = {
    "title": "Cracked tile",
    "description": "Bathroom 2.04, floor tile by the door is cracked.",
    "priority": "high",
    "category": "finishing",
    "trade": "Tiler",
    "due_date": "2026-10-02",
    "assignee": "anna schmidt",
    "rework_cost": 85.5,
}


@pytest.mark.asyncio
async def test_applying_a_punch_item_opens_it_as_the_approver(pg_session, site) -> None:
    from app.modules.punchlist.models import PunchItem

    action = await _propose(pg_session, site, "propose_create_punch_item", _PUNCH_ARGS)
    assert await _count(pg_session, PunchItem, PunchItem.project_id == site["project"].id) == 0

    service = ChatActionService(pg_session)
    director = await service.viewer(site["director"].id)
    applied = await service.apply(action.id, director)

    assert applied.status == "applied", applied.error
    item = (
        await pg_session.execute(select(PunchItem).where(PunchItem.id == uuid.UUID(applied.applied_entity_id)))
    ).scalar_one()
    assert item.status == "open"
    assert item.created_by == str(site["director"].id)
    assert item.assigned_to == str(site["editor"].id)
    assert (item.priority, item.category, item.trade) == ("high", "finishing", "Tiler")
    # Sent as the punch list's own form sends it (``YYYY-MM-DD``), so it is stored the same way: midnight
    # in the database session's time zone, not in UTC.
    local_due = (
        await pg_session.execute(
            select(func.timezone(func.current_setting("TimeZone"), PunchItem.due_date)).where(PunchItem.id == item.id)
        )
    ).scalar_one()
    assert local_due.isoformat() == "2026-10-02T00:00:00"
    assert item.rework_cost == "85.5" and item.rework_cost_currency == "EUR"
    assert item.metadata_["via"] == "ai_assistant" and item.metadata_["approved_by"] == str(site["director"].id)

    log = await _audit_row(pg_session, str(item.id), "created")
    _assert_assistant_row(log, site, action, "punch_item")
    assert log.metadata_["url"] == f"/punchlist?highlight={item.id}"
    [dto] = await service.to_dtos([applied], director)
    assert dto.can_revert and dto.revert_hint_key is None


@pytest.mark.asyncio
async def test_a_stranger_can_neither_see_nor_apply_a_punch_item(pg_session, site) -> None:
    from app.modules.punchlist.models import PunchItem

    action = await _propose(pg_session, site, "propose_create_punch_item", _PUNCH_ARGS)
    service = ChatActionService(pg_session)
    with pytest.raises(ActionNotFoundError):
        await service.apply(action.id, await service.viewer(site["stranger"].id))
    ctx = await ActionContext.load(pg_session, site["stranger"].id)
    with pytest.raises(ActionNotFoundError):
        await service._spec(action).check_apply_gates(ctx, dict(action.payload))
    assert await _count(pg_session, PunchItem, PunchItem.project_id == site["project"].id) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"status": "in_progress"}, {"title": "Cracked tiles"}])
async def test_undo_refuses_a_punch_item_that_moved_on(pg_session, site, change) -> None:
    from app.modules.punchlist.models import PunchItem

    action = await _propose(pg_session, site, "propose_create_punch_item", _PUNCH_ARGS)
    service = ChatActionService(pg_session)
    director = await service.viewer(site["director"].id)
    item_id = uuid.UUID((await service.apply(action.id, director)).applied_entity_id)
    await pg_session.execute(update(PunchItem).where(PunchItem.id == item_id).values(**change))

    with pytest.raises(ActionConflictError) as caught:
        await service.revert(action.id, director)
    assert caught.value.code == "changed_since_apply"
    assert await _count(pg_session, PunchItem, PunchItem.id == item_id) == 1


@pytest.mark.asyncio
async def test_undo_deletes_a_punch_item_still_open_and_untouched(pg_session, site) -> None:
    from app.modules.punchlist.models import PunchItem

    action = await _propose(pg_session, site, "propose_create_punch_item", _PUNCH_ARGS)
    service = ChatActionService(pg_session)
    director = await service.viewer(site["director"].id)
    item_id = (await service.apply(action.id, director)).applied_entity_id

    reverted = await service.revert(action.id, director)
    assert reverted.status == "reverted"
    assert await _count(pg_session, PunchItem, PunchItem.id == uuid.UUID(item_id)) == 0
    assert (await _audit_row(pg_session, item_id, "reverted")).metadata_["via"] == "ai_assistant"


# ── schedule.update_progress ────────────────────────────────────────────────


@pytest.fixture
async def programme(pg_session, site) -> dict[str, Any]:
    """The project's master programme: foundations at 20 %, two wall activities."""
    from app.modules.schedule.models import Activity, Schedule

    schedule = Schedule(project_id=site["project"].id, name="Master programme")
    pg_session.add(schedule)
    await pg_session.flush()
    rows = {}
    for order, (name, wbs, progress, status) in enumerate(
        [
            ("Foundations", "1.1", "20", "in_progress"),
            ("Walls level 1", "1.2", "0", "not_started"),
            ("Walls level 2", "1.3", "0", "not_started"),
        ],
        start=1,
    ):
        activity = Activity(
            schedule_id=schedule.id,
            name=name,
            wbs_code=wbs,
            start_date="2026-09-01",
            end_date="2026-09-30",
            duration_days=21,
            progress_pct=progress,
            status=status,
            sort_order=order,
        )
        pg_session.add(activity)
        rows[name] = activity
    await pg_session.flush()
    return {"schedule": schedule, **rows}


async def _progress(session, activity_id: uuid.UUID) -> tuple[float, str]:
    from app.modules.schedule.models import Activity

    row = (
        await session.execute(select(Activity.progress_pct, Activity.status).where(Activity.id == activity_id))
    ).one()
    return float(row[0]), row[1]


@pytest.mark.asyncio
async def test_applying_progress_found_by_name_updates_the_activity_and_logs_before_and_after(
    pg_session, site, programme
) -> None:
    foundations = programme["Foundations"]
    action = await _propose(
        pg_session, site, "propose_update_schedule_progress", {"activity": "foundations", "progress": 60}
    )
    assert action.payload["activity_id"] == str(foundations.id)
    assert action.before_state["progress_pct"] == "20"
    assert await _progress(pg_session, foundations.id) == (20.0, "in_progress")

    service = ChatActionService(pg_session)
    director = await service.viewer(site["director"].id)
    applied = await service.apply(action.id, director)

    assert applied.status == "applied", applied.error
    assert await _progress(pg_session, foundations.id) == (60.0, "in_progress")
    log = await _audit_row(pg_session, str(foundations.id), "updated")
    _assert_assistant_row(log, site, action, "activity")
    assert float(log.before_state["progress_pct"]) == 20 and float(log.after_state["progress_pct"]) == 60
    assert log.metadata_["url"] == f"/schedule?project_id={site['project'].id}"
    assert log.metadata_["label"] == "1.1 Foundations"


@pytest.mark.asyncio
async def test_an_ambiguous_activity_goes_back_to_the_model_with_the_candidates(pg_session, site, programme) -> None:
    from app.modules.erp_chat.actions.service import propose_tool_result

    result = await propose_tool_result(
        pg_session,
        tool_name="propose_update_schedule_progress",
        args={"activity": "walls", "progress": 50},
        user_id=site["editor"].id,
        project_id=site["project"].id,
    )

    assert result["renderer"] == "error"
    assert result["data"]["error"] == "activity_ambiguous"
    assert {o["name"] for o in result["data"]["options"]} == {"Walls level 1", "Walls level 2"}
    assert {o["activity_id"] for o in result["data"]["options"]} == {
        str(programme["Walls level 1"].id),
        str(programme["Walls level 2"].id),
    }
    assert await _count(pg_session, ChatAction, ChatAction.project_id == site["project"].id) == 0


@pytest.mark.asyncio
async def test_progress_changed_since_the_proposal_is_not_overwritten(pg_session, site, programme) -> None:
    from app.modules.schedule.models import Activity

    foundations = programme["Foundations"]
    action = await _propose(
        pg_session, site, "propose_update_schedule_progress", {"activity_id": str(foundations.id), "progress": 60}
    )
    await pg_session.execute(update(Activity).where(Activity.id == foundations.id).values(progress_pct="35"))
    service = ChatActionService(pg_session)

    with pytest.raises(ActionConflictError) as caught:
        await service.apply(action.id, await service.viewer(site["director"].id))
    assert caught.value.code == "target_changed"
    assert await _progress(pg_session, foundations.id) == (35.0, "in_progress")
    assert (await service.get_visible(action.id, await service.viewer(site["editor"].id))).status == "proposed"


@pytest.mark.asyncio
async def test_a_stranger_can_neither_propose_nor_apply_progress(pg_session, site, programme) -> None:
    foundations = programme["Foundations"]
    service = ChatActionService(pg_session)
    with pytest.raises(ActionNotFoundError) as caught:
        await service.propose(
            tool_name="propose_update_schedule_progress",
            args={"activity_id": str(foundations.id), "progress": 90},
            user_id=site["stranger"].id,
        )
    assert caught.value.code == "activity_not_found"

    action = await _propose(
        pg_session, site, "propose_update_schedule_progress", {"activity_id": str(foundations.id), "progress": 60}
    )
    with pytest.raises(ActionNotFoundError):
        await service.apply(action.id, await service.viewer(site["stranger"].id))
    ctx = await ActionContext.load(pg_session, site["stranger"].id)
    with pytest.raises(ActionNotFoundError):
        await service._spec(action).check_apply_gates(ctx, dict(action.payload))
    assert await _progress(pg_session, foundations.id) == (20.0, "in_progress")


@pytest.mark.asyncio
async def test_undo_restores_the_previous_progress_only_while_it_holds_what_was_applied(
    pg_session, site, programme
) -> None:
    from app.modules.schedule.models import Activity

    service = ChatActionService(pg_session)
    director = await service.viewer(site["director"].id)
    foundations = programme["Foundations"]
    action = await _propose(
        pg_session, site, "propose_update_schedule_progress", {"activity_id": str(foundations.id), "progress": 60}
    )
    await service.apply(action.id, director)
    await pg_session.execute(update(Activity).where(Activity.id == foundations.id).values(progress_pct="70"))
    with pytest.raises(ActionConflictError) as caught:
        await service.revert(action.id, director)
    assert caught.value.code == "changed_since_apply"
    assert await _progress(pg_session, foundations.id) == (70.0, "in_progress")

    walls = programme["Walls level 1"]
    second = await _propose(
        pg_session, site, "propose_update_schedule_progress", {"activity_id": str(walls.id), "progress": 100}
    )
    await service.apply(second.id, director)
    assert await _progress(pg_session, walls.id) == (100.0, "completed")
    reverted = await service.revert(second.id, director)
    assert reverted.status == "reverted"
    assert await _progress(pg_session, walls.id) == (0.0, "not_started")
    log = await _audit_row(pg_session, str(walls.id), "reverted")
    assert float(log.after_state["progress_pct"]) == 0
    assert log.metadata_["url"] == f"/schedule?project_id={site['project'].id}"

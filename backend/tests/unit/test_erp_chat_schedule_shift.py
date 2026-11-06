# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""``schedule.shift_activity``: "move the slab pour by two days" becomes a card with old and new dates.

The activity reads are answered from a fixed list; the write through
``ScheduleService.update_activity`` is covered by the PostgreSQL lane.
"""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

import pytest

from app.modules.erp_chat.actions import labels, registry
from app.modules.erp_chat.actions._common import ProjectInfo
from app.modules.erp_chat.actions.base import ActionConflictError, ActionContext, ActionValidationError
from app.modules.erp_chat.actions.schedule_progress import ActivityRow
from app.modules.erp_chat.actions.schedule_shift import ScheduleShiftActivitySpec, shifted_dates
from app.modules.erp_chat.models import ChatAction

PROJECT = ProjectInfo(id=uuid.UUID("00000000-0000-0000-0000-00000000a001"), name="Residential House", currency="EUR")
SCHEDULE = uuid.UUID("00000000-0000-0000-0000-00000000c001")


def _activity(name: str, start: str, end: str, *, wbs: str = "", progress: str = "0", kind: str = "task"):
    return ActivityRow(
        id=uuid.uuid4(),
        schedule_id=SCHEDULE,
        schedule_name="Master programme",
        project_id=PROJECT.id,
        name=name,
        wbs_code=wbs,
        progress_pct=progress,
        status="not_started",
        activity_type=kind,
        start_date=start,
        end_date=end,
    )


@pytest.fixture
def ctx() -> ActionContext:
    return ActionContext(session=None, user_id=uuid.uuid4(), role="editor", project_id=PROJECT.id)


@pytest.fixture
def rows() -> list[ActivityRow]:
    return [
        _activity("Slab pour level 3", "2027-03-01", "2027-03-05", wbs="3.4"),
        _activity("Facade", "2027-04-01", "2027-04-30", wbs="5.1", progress="25"),
        _activity("Shell", "2027-01-10", "2027-05-01", wbs="3", kind="summary"),
        _activity("Handover", "", "", wbs="9.9"),
    ]


@pytest.fixture
def spec(monkeypatch: pytest.MonkeyPatch, ctx: ActionContext, rows: list[ActivityRow]) -> ScheduleShiftActivitySpec:
    from app.modules.erp_chat.actions import schedule_progress

    async def _project(ctx: ActionContext, args: dict[str, Any]) -> ProjectInfo:
        return PROJECT

    async def _get(ctx: ActionContext, activity_id: uuid.UUID | None):
        return next((a for a in rows if a.id == activity_id), None)

    async def _search(ctx: ActionContext, project_id: uuid.UUID, needle: str, *, schedule_id=None):
        return schedule_progress.match_activities(needle, rows)

    async def _access(project_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr(schedule_progress, "resolve_project", _project)
    monkeypatch.setattr(schedule_progress, "get_activity", _get)
    monkeypatch.setattr(schedule_progress, "search_activities", _search)
    monkeypatch.setattr(ctx, "require_project_access", _access)
    return ScheduleShiftActivitySpec()


def _fields(draft: Any) -> dict[str, Any]:
    return {f.key: f for f in draft.fields}


@pytest.mark.parametrize(
    ("days", "new_start", "expected"),
    [
        (2, None, ("2027-03-03", "2027-03-07")),
        (-3, None, ("2027-02-26", "2027-03-02")),
        (None, "2027-03-10", ("2027-03-10", "2027-03-14")),
        (28, None, ("2027-03-29", "2027-04-02")),
    ],
)
def test_a_shift_keeps_the_activity_length(days, new_start, expected) -> None:
    assert shifted_dates("2027-03-01", "2027-03-05", days=days, new_start=new_start) == expected


def test_the_tool_is_registered_with_the_gantt_routes_gates_and_an_english_title() -> None:
    spec = registry.get_spec("schedule.shift_activity")
    assert spec is not None
    assert registry.get_spec_for_tool("propose_shift_schedule_activity") is spec
    assert spec.modules == ("oe_schedule",)
    assert spec.apply_permissions == ("schedule.update",) and spec.revert_permissions == ("schedule.update",)
    assert spec.reversible
    assert labels.all_keys()[spec.title_key] == "Move schedule activity"
    props = spec.input_schema()["properties"]
    assert props["shift_days"]["type"] == "integer" and "confidence" in props


@pytest.mark.asyncio
async def test_move_the_slab_pour_by_two_days(spec, ctx, rows) -> None:
    slab = rows[0]
    draft = await spec.build(ctx, {"activity": "slab pour level 3", "shift_days": 2})

    assert draft.payload == {
        "project_id": str(PROJECT.id),
        "schedule_id": str(SCHEDULE),
        "activity_id": str(slab.id),
        "start_date": "2027-03-03",
        "end_date": "2027-03-07",
    }
    fields = _fields(draft)
    assert (fields["start_date"].kind, fields["start_date"].before, fields["start_date"].value) == (
        "date",
        "2027-03-01",
        "2027-03-03",
    )
    assert (fields["end_date"].before, fields["end_date"].value) == ("2027-03-05", "2027-03-07")
    assert all(f.editable for f in draft.fields)
    assert draft.target is not None and draft.target.label == "3.4 Slab pour level 3"
    assert draft.target.url == f"/schedule?project_id={PROJECT.id}"
    assert [n.key for n in draft.notes] == ["erp_chat.action.note.successors_not_moved"]
    # The stored payload builds again unchanged (edit and apply run build on it).
    again = await spec.build(ctx, dict(draft.payload))
    assert again.payload == draft.payload


@pytest.mark.asyncio
async def test_a_finish_typed_on_the_card_wins_and_cannot_fall_before_the_start(spec, ctx, rows) -> None:
    draft = await spec.build(
        ctx, {"activity_id": str(rows[0].id), "start_date": "2027-03-01", "end_date": "2027-03-09"}
    )
    assert (draft.payload["start_date"], draft.payload["end_date"]) == ("2027-03-01", "2027-03-09")

    with pytest.raises(ActionValidationError) as caught:
        await spec.build(ctx, {"activity_id": str(rows[0].id), "start_date": "2027-03-08", "end_date": "2027-03-02"})
    assert caught.value.field_errors["end_date"]["code"] == "end_before_start"


@pytest.mark.asyncio
async def test_a_request_without_days_or_a_date_asks_for_one(spec, ctx) -> None:
    with pytest.raises(ActionValidationError) as caught:
        await spec.build(ctx, {"activity": "3.4"})
    assert caught.value.field_errors["shift_days"]["code"] == "shift_required"

    with pytest.raises(ActionValidationError) as half:
        await spec.build(ctx, {"activity": "3.4", "shift_days": 1.5})
    assert half.value.field_errors["shift_days"]["code"] == "not_whole_number"

    with pytest.raises(ActionValidationError) as zero:
        await spec.build(ctx, {"activity": "3.4", "shift_days": 0})
    assert zero.value.code == "no_change"


@pytest.mark.asyncio
async def test_an_activity_without_dates_cannot_be_moved(spec, ctx) -> None:
    with pytest.raises(ActionValidationError) as caught:
        await spec.build(ctx, {"activity": "Handover", "shift_days": 2})
    assert caught.value.code == "activity_no_dates"
    assert labels.all_keys()["erp_chat.action.error.activity_no_dates"]


@pytest.mark.asyncio
async def test_a_started_or_summary_activity_carries_a_warning(spec, ctx) -> None:
    facade = await spec.build(ctx, {"activity": "Facade", "shift_days": 7})
    started = facade.notes[0]
    assert started.key == "erp_chat.action.note.activity_started" and started.tone == "warning"
    assert "25 %" in started.text

    shell = await spec.build(ctx, {"activity": "Shell", "new_start": "2027-01-17"})
    assert shell.notes[0].key == "erp_chat.action.note.summary_dates"


@pytest.mark.asyncio
async def test_dates_moved_by_someone_else_since_the_proposal_are_drift(spec, ctx, rows) -> None:
    draft = await spec.build(ctx, {"activity": "3.4", "shift_days": 2})
    prior = ChatAction(
        id=uuid.uuid4(),
        action_type=spec.action_type,
        status="proposed",
        title=spec.title,
        requested_by=uuid.uuid4(),
        payload=draft.payload,
        original_payload=draft.payload,
    )
    prior.before_state = draft.before_state
    rows[0] = dataclasses.replace(rows[0], start_date="2027-03-02", end_date="2027-03-06")

    with pytest.raises(ActionConflictError) as caught:
        await spec.build(ctx, dict(draft.payload), prior=prior)
    assert caught.value.code == "target_changed"


@pytest.mark.asyncio
async def test_undo_refuses_when_the_activity_moved_again_after_apply(spec, ctx, rows) -> None:
    applied = ChatAction(
        id=uuid.uuid4(),
        action_type=spec.action_type,
        status="applied",
        title=spec.title,
        requested_by=uuid.uuid4(),
        payload={},
        original_payload={},
        result={"after_state": {"start_date": "2027-03-03", "end_date": "2027-03-07"}},
    )
    applied.applied_entity_id = str(rows[0].id)
    applied.before_state = {"start_date": "2027-03-01", "end_date": "2027-03-05"}
    with pytest.raises(ActionConflictError) as caught:
        await spec.revert(ctx, applied)
    assert caught.value.code == "changed_since_apply"
    assert spec.revert_hint_key(applied) == "erp_chat.action.revert_hint.schedule_dates"

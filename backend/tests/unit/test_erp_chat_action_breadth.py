"""Field building and validation of the RFI, risk, punch item and schedule progress proposals.

Each spec turns the model's arguments (and a person's edits on the card) into
a checked payload and the fields the person reviews, and must accept its own
stored payload again unchanged, because the payload is built again at every
edit and at apply time. The database reads a build makes - the project and
its members - are replaced here with fixed values; the lifecycle against
PostgreSQL is covered in ``tests/pg/test_erp_chat_action_breadth_lifecycle.py``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

from app.modules.erp_chat.actions import labels, registry
from app.modules.erp_chat.actions._common import ProjectInfo
from app.modules.erp_chat.actions.base import (
    ActionContext,
    ActionValidationError,
    FieldErrors,
    parse_flag,
    parse_percent,
    parse_whole,
)
from app.modules.erp_chat.models import ChatAction

PROJECT = ProjectInfo(id=uuid.UUID("00000000-0000-0000-0000-00000000a001"), name="Residential House", currency="EUR")
ANNA = (uuid.UUID("00000000-0000-0000-0000-0000000000a1"), "Anna Schmidt", "anna@site.test")
ANNA_BERG = (uuid.UUID("00000000-0000-0000-0000-0000000000a2"), "Anna Berg", "berg@site.test")
DANA = (uuid.UUID("00000000-0000-0000-0000-0000000000d1"), "Dana Director", "dana@site.test")
MEMBERS = [ANNA_BERG, ANNA, DANA]


@pytest.fixture
def ctx() -> ActionContext:
    return ActionContext(session=None, user_id=uuid.uuid4(), role="editor", project_id=PROJECT.id)


@pytest.fixture
def fixed_project(monkeypatch: pytest.MonkeyPatch):
    """Answer a spec module's project and member reads without a database."""

    def _install(module: Any) -> None:
        async def _project(ctx: ActionContext, args: dict[str, Any]) -> ProjectInfo:
            return PROJECT

        async def _members(session: Any, project_id: uuid.UUID) -> list[tuple[uuid.UUID, str, str]]:
            return list(MEMBERS)

        monkeypatch.setattr(module, "resolve_project", _project)
        if hasattr(module, "project_members"):
            monkeypatch.setattr(module, "project_members", _members)

    return _install


def _fields(draft: Any) -> dict[str, Any]:
    return {f.key: f for f in draft.fields}


def _action(spec: Any, payload: dict[str, Any], after_state: dict[str, Any] | None = None) -> ChatAction:
    return ChatAction(
        id=uuid.uuid4(),
        action_type=spec.action_type,
        status="applied",
        title=spec.title,
        requested_by=uuid.uuid4(),
        payload=payload,
        original_payload=payload,
        result={"after_state": after_state or {}},
    )


# ── Value parsers the new specs share ───────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(True, True), (False, False), ("yes", True), ("No", False), ("true", True), ("0", False)],
)
def test_a_flag_is_read_from_a_boolean_or_the_cards_yes_no_option(raw: object, expected: bool) -> None:
    errors = FieldErrors()
    assert parse_flag({"flag": raw}, "flag", errors) is expected
    assert not errors


def test_an_unreadable_flag_is_a_field_error_and_an_absent_one_takes_the_default() -> None:
    errors = FieldErrors()
    parse_flag({"flag": "perhaps"}, "flag", errors)
    assert errors.errors["flag"]["code"] == "invalid_option"
    assert parse_flag({}, "flag", FieldErrors(), default=True) is True


def test_days_must_be_a_whole_number() -> None:
    errors = FieldErrors()
    assert parse_whole({"days": "5"}, "days", errors) == 5
    assert parse_whole({"days": 4.5}, "days", errors) is None
    assert errors.errors["days"]["code"] == "not_whole_number"


@pytest.mark.parametrize(
    ("raw", "expected"), [(60, Decimal("60")), ("60 %", Decimal("60")), ("12,5%", Decimal("12.5"))]
)
def test_a_percentage_is_read_in_the_spellings_people_type(raw: object, expected: Decimal) -> None:
    errors = FieldErrors()
    assert parse_percent({"pct": raw}, "pct", errors) == expected
    assert not errors


def test_a_percentage_above_a_hundred_or_below_zero_is_refused() -> None:
    errors = FieldErrors()
    assert parse_percent({"pct": 101}, "pct", errors) is None
    assert parse_percent({"low": -1}, "low", errors) is None
    assert errors.errors["pct"]["code"] == "percent_range"
    assert errors.errors["low"]["code"] == "negative"


def test_every_new_proposal_names_its_module_and_the_rest_routes_gates() -> None:
    expected = {
        "rfi.create": ("propose_create_rfi", ("oe_rfi",), ("rfi.create",), ("rfi.delete",)),
        "risk.create": ("propose_create_risk", ("oe_risk",), ("risk.create",), ("risk.delete",)),
        "punch.create_item": (
            "propose_create_punch_item",
            ("oe_punchlist",),
            ("punchlist.create",),
            ("punchlist.delete",),
        ),
        "schedule.update_progress": (
            "propose_update_schedule_progress",
            ("oe_schedule",),
            ("schedule.update",),
            ("schedule.update",),
        ),
    }
    for action_type, (tool, modules, apply_perms, revert_perms) in expected.items():
        spec = registry.get_spec(action_type)
        assert spec is not None, action_type
        assert registry.get_spec_for_tool(tool) is spec
        assert spec.modules == modules
        assert spec.apply_permissions == apply_perms
        assert spec.revert_permissions == revert_perms
        assert spec.reversible
        assert labels.all_keys()[spec.title_key] == spec.title


# ── rfi.create ──────────────────────────────────────────────────────────────


@pytest.fixture
def rfi(fixed_project):
    from app.modules.erp_chat.actions import rfi_create

    fixed_project(rfi_create)
    return rfi_create.RFICreateSpec()


def test_the_rfi_tool_asks_for_a_subject_and_a_question_in_the_registers_own_scales(rfi) -> None:
    schema = rfi.input_schema()
    assert schema["required"] == ["subject", "question"]
    props = schema["properties"]
    assert props["priority"]["enum"] == ["low", "normal", "high", "critical"]
    assert props["discipline"]["enum"] == list(labels.OPTIONS["rfi_discipline"])
    assert props["cost_impact"]["type"] == "boolean" and props["schedule_impact_days"]["type"] == "integer"


@pytest.mark.asyncio
async def test_an_rfi_is_drafted_with_its_addressee_and_no_impact_by_default(rfi, ctx) -> None:
    draft = await rfi.build(
        ctx,
        {"subject": "Rebar grade level 3 slab", "question": "Which grade applies?", "assignee": "dana"},
    )

    assert draft.payload["assigned_to"] == str(DANA[0])
    assert draft.payload["assignee"] == "Dana Director"
    assert draft.payload["priority"] == "normal"
    assert (draft.payload["cost_impact"], draft.payload["schedule_impact"]) == ("no", "no")
    fields = _fields(draft)
    assert list(fields) == [
        "subject",
        "question",
        "priority",
        "discipline",
        "response_due_date",
        "assignee",
        "cost_impact",
        "schedule_impact",
    ]
    assert {o.label_key for o in fields["priority"].options or []} == {
        f"erp_chat.action.option.rfi_priority.{value}" for value in ("low", "normal", "high", "critical")
    }
    assert fields["cost_impact"].value == "no" and fields["cost_impact"].kind == "enum"
    assert draft.notes == [] and draft.subtitle == "Rebar grade level 3 slab"


@pytest.mark.asyncio
async def test_an_amount_turns_its_flag_on_and_a_flag_turned_off_drops_the_amount(rfi, ctx) -> None:
    with_amount = await rfi.build(
        ctx,
        {"subject": "Door type", "question": "Which door?", "cost_impact_value": "1 500,50", "schedule_impact_days": 3},
    )
    assert with_amount.payload["cost_impact"] == "yes"
    assert with_amount.payload["cost_impact_value"] == "1500.5"
    assert with_amount.payload["schedule_impact"] == "yes"
    assert with_amount.payload["schedule_impact_days"] == 3
    fields = _fields(with_amount)
    assert fields["cost_impact_value"].kind == "money" and fields["cost_impact_value"].currency == "EUR"
    assert fields["cost_impact_value"].value == pytest.approx(1500.5)
    assert fields["schedule_impact_days"].value == 3

    # The person flips the flag off on the card: the amount goes with it, as on the RFI page.
    flipped = await rfi.build(ctx, rfi.merge_patch(with_amount.payload, {"cost_impact": "no"}))
    assert flipped.payload["cost_impact"] == "no" and flipped.payload["cost_impact_value"] is None
    assert "cost_impact_value" not in _fields(flipped)
    assert "cost_impact_value" in rfi.patch_aliases


@pytest.mark.asyncio
async def test_an_rfi_with_bad_values_reports_every_field_at_once(rfi, ctx) -> None:
    with pytest.raises(ActionValidationError) as caught:
        await rfi.build(
            ctx,
            {
                "subject": "x" * 501,
                "discipline": "hvac",
                "priority": "urgent",
                "response_due_date": "next week",
                "schedule_impact_days": 2.5,
                "cost_impact": "maybe",
            },
        )
    assert set(caught.value.field_errors) == {
        "subject",
        "question",
        "discipline",
        "priority",
        "response_due_date",
        "schedule_impact_days",
        "cost_impact",
    }


@pytest.mark.asyncio
async def test_an_rfi_takes_a_due_date_under_the_tasks_name_and_its_own_payload_back_unchanged(rfi, ctx) -> None:
    first = await rfi.build(
        ctx,
        {"subject": "Facade anchors", "question": "Spacing?", "due_date": "2026-10-02", "discipline": "Structural"},
    )
    assert first.payload["response_due_date"] == "2026-10-02"
    assert first.payload["discipline"] == "structural"
    again = await rfi.build(ctx, dict(first.payload))
    assert again.payload == first.payload


@pytest.mark.asyncio
async def test_an_ambiguous_addressee_leaves_the_rfi_unassigned_with_a_note_under_the_field(rfi, ctx) -> None:
    draft = await rfi.build(ctx, {"subject": "Screed", "question": "Thickness?", "assignee": "anna"})
    assert draft.payload["assigned_to"] is None
    [note] = draft.notes
    assert note.key == "erp_chat.action.note.member_ambiguous"
    assert note.field == "assignee" and note.params == {"name": "anna"}

    picked = await rfi.build(ctx, rfi.merge_patch(draft.payload, {"assignee": str(ANNA[0])}))
    assert picked.payload["assigned_to"] == str(ANNA[0]) and picked.notes == []
    with pytest.raises(ActionValidationError) as outsider:
        await rfi.build(ctx, rfi.merge_patch(draft.payload, {"assignee": str(uuid.uuid4())}))
    assert set(outsider.value.field_errors) == {"assignee"}


def test_undoing_an_rfi_warns_about_its_number_and_about_a_notification_only_when_one_went_out(rfi) -> None:
    assigned = _action(rfi, {}, {"assigned_to": str(ANNA[0])})
    unassigned = _action(rfi, {}, {"assigned_to": None})
    assert rfi.revert_hint_key(assigned) == "erp_chat.action.revert_hint.rfi_notifications"
    assert rfi.revert_hint_key(unassigned) == "erp_chat.action.revert_hint.rfi_number"


# ── risk.create ─────────────────────────────────────────────────────────────


@pytest.fixture
def risk(fixed_project):
    from app.modules.erp_chat.actions import risk_create

    fixed_project(risk_create)
    return risk_create.RiskCreateSpec()


def test_the_risk_tool_offers_the_registers_own_vocabularies(risk) -> None:
    from app.modules.risk.schemas import SEVERITY_CANONICAL

    props = risk.input_schema()["properties"]
    assert risk.input_schema()["required"] == ["title"]
    assert props["impact_severity"]["enum"] == list(SEVERITY_CANONICAL)
    assert props["category"]["enum"] == [
        "technical",
        "financial",
        "schedule",
        "regulatory",
        "environmental",
        "safety",
        "procurement",
    ]
    assert props["probability"]["maximum"] == 100


@pytest.mark.asyncio
async def test_a_risk_is_drafted_with_the_registers_defaults_and_its_owner(risk, ctx) -> None:
    draft = await risk.build(ctx, {"title": "Crane permit late", "owner": "Dana Director", "impact_cost": "12 000"})

    assert draft.payload["category"] == "technical"
    assert draft.payload["impact_severity"] == "medium"
    assert draft.payload["probability"] == "50"
    assert draft.payload["impact_cost"] == "12000"
    assert draft.payload["owner_user_id"] == str(DANA[0]) and draft.payload["owner"] == "Dana Director"
    fields = _fields(draft)
    assert list(fields) == [
        "title",
        "description",
        "category",
        "probability",
        "impact_severity",
        "impact_cost",
        "impact_schedule_days",
        "owner",
        "mitigation_strategy",
    ]
    assert fields["probability"].kind == "percent" and fields["probability"].value == 50
    assert fields["impact_cost"].kind == "money" and fields["impact_cost"].currency == "EUR"
    assert fields["owner"].kind == "enum" and fields["owner"].value == str(DANA[0])
    assert {o.label_key for o in fields["impact_severity"].options or []} == {
        f"erp_chat.action.option.risk_impact.{v}" for v in ("very_low", "low", "medium", "high", "critical")
    }
    assert draft.subtitle == "Crane permit late"
    again = await risk.build(ctx, dict(draft.payload))
    assert again.payload == draft.payload


@pytest.mark.asyncio
async def test_a_risk_with_bad_values_reports_every_field_at_once(risk, ctx) -> None:
    with pytest.raises(ActionValidationError) as caught:
        await risk.build(
            ctx,
            {
                "probability": 140,
                "impact_severity": "catastrophic",
                "category": "weather",
                "impact_schedule_days": 2.5,
                "impact_cost": -5,
            },
        )
    assert set(caught.value.field_errors) == {
        "title",
        "probability",
        "impact_severity",
        "category",
        "impact_schedule_days",
        "impact_cost",
    }


@pytest.mark.asyncio
async def test_an_ambiguous_risk_owner_leaves_the_field_empty_with_a_note(risk, ctx) -> None:
    draft = await risk.build(ctx, {"title": "Soil", "owner": "anna"})
    assert draft.payload["owner_user_id"] is None
    [note] = draft.notes
    assert note.key == "erp_chat.action.note.member_ambiguous" and note.field == "owner"
    picked = await risk.build(ctx, risk.merge_patch(draft.payload, {"owner_user_id": str(ANNA[0])}))
    assert picked.payload["owner_user_id"] == str(ANNA[0]) and picked.payload["owner"] == "Anna Schmidt"


def test_undoing_a_risk_names_the_side_effect_that_stays(risk) -> None:
    hint = labels.REVERT_HINT_PREFIX
    assert risk.revert_hint_key(_action(risk, {}, {"escalated": True})) == f"{hint}risk_escalated"
    assert risk.revert_hint_key(_action(risk, {}, {"owner_user_id": str(ANNA[0])})) == f"{hint}risk_notifications"
    assert risk.revert_hint_key(_action(risk, {}, {})) == f"{hint}risk_code"


# ── punch.create_item ───────────────────────────────────────────────────────


@pytest.fixture
def punch(fixed_project):
    from app.modules.erp_chat.actions import punch_create

    fixed_project(punch_create)
    return punch_create.PunchCreateItemSpec()


@pytest.mark.asyncio
async def test_a_punch_item_is_drafted_in_the_punch_lists_own_scales(punch, ctx) -> None:
    draft = await punch.build(
        ctx,
        {
            "title": "Cracked tile",
            "description": "Bathroom 2.04, floor by the door",
            "category": "Finishing",
            "trade": "Tiler",
            "due_date": "2026-10-02T00:00:00",
            "assignee": "anna schmidt",
            "rework_cost": "85,50",
        },
    )

    assert draft.payload["priority"] == "medium"
    assert draft.payload["category"] == "finishing"
    assert draft.payload["due_date"] == "2026-10-02"
    assert draft.payload["assigned_to"] == str(ANNA[0])
    assert draft.payload["rework_cost"] == "85.5"
    fields = _fields(draft)
    assert list(fields) == [
        "title",
        "description",
        "priority",
        "category",
        "trade",
        "due_date",
        "assignee",
        "rework_cost",
    ]
    assert [o.value for o in fields["priority"].options or []] == ["low", "medium", "high", "critical"]
    assert fields["rework_cost"].currency == "EUR"
    again = await punch.build(ctx, dict(draft.payload))
    assert again.payload == draft.payload
    assert punch.revert_hint_key(_action(punch, draft.payload)) is None


@pytest.mark.asyncio
async def test_a_punch_item_with_bad_values_reports_every_field_at_once(punch, ctx) -> None:
    with pytest.raises(ActionValidationError) as caught:
        await punch.build(ctx, {"priority": "normal", "category": "roofing", "due_date": "soon", "trade": "x" * 101})
    assert set(caught.value.field_errors) == {"title", "priority", "category", "due_date", "trade"}


@pytest.mark.asyncio
async def test_the_rework_cost_is_shown_in_the_currency_the_service_will_store(punch, ctx, monkeypatch) -> None:
    from app.modules.erp_chat.actions import punch_create

    async def _no_currency(ctx: ActionContext, args: dict[str, Any]) -> ProjectInfo:
        return ProjectInfo(id=PROJECT.id, name=PROJECT.name, currency="")

    monkeypatch.setattr(punch_create, "resolve_project", _no_currency)
    draft = await punch.build(ctx, {"title": "Scuffed door", "rework_cost": 20})
    assert _fields(draft)["rework_cost"].currency == "USD"


# ── schedule.update_progress ────────────────────────────────────────────────


def _activity(name: str, progress: str = "20", *, wbs: str = "", kind: str = "task", status: str = "in_progress"):
    from app.modules.erp_chat.actions.schedule_progress import ActivityRow

    return ActivityRow(
        id=uuid.uuid4(),
        schedule_id=uuid.UUID("00000000-0000-0000-0000-00000000c001"),
        schedule_name="Master programme",
        project_id=PROJECT.id,
        name=name,
        wbs_code=wbs,
        progress_pct=progress,
        status=status,
        activity_type=kind,
    )


@pytest.fixture
def activities() -> list[Any]:
    return [
        _activity("Foundations", wbs="1.1"),
        _activity("Walls level 1", wbs="1.2"),
        _activity("Walls level 2", wbs="1.3"),
        _activity("Shell", "40", wbs="1", kind="summary"),
    ]


@pytest.fixture
def schedule(fixed_project, monkeypatch, ctx, activities):
    """The spec with its activity reads answered from ``activities``."""
    from app.modules.erp_chat.actions import schedule_progress

    fixed_project(schedule_progress)

    async def _get(ctx: ActionContext, activity_id: uuid.UUID | None):
        return next((a for a in activities if a.id == activity_id), None)

    async def _search(ctx: ActionContext, project_id: uuid.UUID, needle: str, *, schedule_id=None):
        return schedule_progress.match_activities(needle, activities)

    async def _access(project_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr(schedule_progress, "get_activity", _get)
    monkeypatch.setattr(schedule_progress, "search_activities", _search)
    monkeypatch.setattr(ctx, "require_project_access", _access)
    return schedule_progress.ScheduleUpdateProgressSpec()


@pytest.mark.asyncio
async def test_progress_is_proposed_for_an_activity_found_by_name_with_before_and_after(
    schedule, ctx, activities
) -> None:
    foundations = activities[0]
    draft = await schedule.build(ctx, {"activity": "foundations", "progress": "60 %"})

    assert draft.payload == {
        "project_id": str(PROJECT.id),
        "schedule_id": str(foundations.schedule_id),
        "activity_id": str(foundations.id),
        "progress": "60",
    }
    [field] = draft.fields
    assert (field.key, field.kind, field.value, field.before) == ("progress", "percent", 60, 20)
    assert draft.before_state["progress_pct"] == "20" and draft.before_state["status"] == "in_progress"
    assert draft.target is not None and draft.target.label == "1.1 Foundations"
    assert draft.target.url == f"/schedule?project_id={PROJECT.id}"
    assert draft.subtitle == "Master programme"
    by_id = await schedule.build(ctx, dict(draft.payload))
    assert by_id.payload == draft.payload


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("фундамент", ["Фундамент"]),
        ("ÜBERGABE", ["Übergabe Ebene 1"]),
        ("übergabe ebene 1", ["Übergabe Ebene 1"]),
        ("2.1", ["Übergabe Ebene 1"]),
        ("ebene", ["Übergabe Ebene 1", "Rohbau Ebene 2"]),
        ("50%", []),
    ],
)
def test_an_activity_name_is_matched_ignoring_case_in_any_script(typed: str, expected: list[str]) -> None:
    from app.modules.erp_chat.actions.schedule_progress import match_activities

    rows = [
        _activity("Фундамент", wbs="1.1"),
        _activity("Übergabe Ebene 1", wbs="2.1"),
        _activity("Rohbau Ebene 2", wbs="2.2"),
    ]
    assert [r.name for r in match_activities(typed, rows)] == expected


@pytest.mark.asyncio
async def test_an_ambiguous_activity_name_returns_the_candidates_to_ask_about(schedule, ctx) -> None:
    with pytest.raises(ActionValidationError) as caught:
        await schedule.build(ctx, {"activity": "walls", "progress": 50})
    assert caught.value.code == "activity_ambiguous"
    assert [o["name"] for o in caught.value.options] == ["Walls level 1", "Walls level 2"]
    assert set(caught.value.options[0]) == {"activity_id", "name", "wbs_code", "schedule", "progress"}
    result = caught.value.to_tool_result()
    assert result["renderer"] == "error" and len(result["data"]["options"]) == 2

    with pytest.raises(ActionValidationError) as missing:
        await schedule.build(ctx, {"activity": "roof", "progress": 50})
    assert missing.value.code == "activity_not_found"


@pytest.mark.asyncio
async def test_progress_must_change_and_stay_within_a_hundred(schedule, ctx) -> None:
    with pytest.raises(ActionValidationError) as same:
        await schedule.build(ctx, {"activity": "1.1", "progress": 20})
    assert same.value.code == "no_change"
    with pytest.raises(ActionValidationError) as bad:
        await schedule.build(ctx, {"progress": 120})
    assert set(bad.value.field_errors) == {"progress", "activity"}


@pytest.mark.asyncio
async def test_progress_changed_since_the_proposal_is_drift(schedule, ctx, activities) -> None:
    import dataclasses

    from app.modules.erp_chat.actions.base import ActionConflictError

    draft = await schedule.build(ctx, {"activity": "foundations", "progress": 60})
    prior = _action(schedule, draft.payload)
    prior.before_state = draft.before_state
    activities[0] = dataclasses.replace(activities[0], progress_pct="35")

    with pytest.raises(ActionConflictError) as caught:
        await schedule.build(ctx, dict(draft.payload), prior=prior)
    assert caught.value.code == "target_changed"


@pytest.mark.asyncio
async def test_a_summary_activity_gets_a_warning_and_a_hand_set_status_an_undo_hint(schedule, ctx) -> None:
    draft = await schedule.build(ctx, {"activity": "Shell", "progress": 50})
    [note] = draft.notes
    assert note.key == "erp_chat.action.note.summary_activity" and note.tone == "warning"

    applied = _action(schedule, draft.payload)
    applied.before_state = {"progress_pct": "20", "status": "in_progress"}
    assert schedule.revert_hint_key(applied) is None
    applied.before_state = {"progress_pct": "20", "status": "delayed"}
    assert schedule.revert_hint_key(applied) == "erp_chat.action.revert_hint.schedule_status"

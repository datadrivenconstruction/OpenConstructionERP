"""Field building and validation of the RFI, risk, punch item and schedule progress proposals.

Each spec turns the model's arguments (and a person's edits on the card) into
a checked payload and the fields the person reviews, and must accept its own
stored payload again unchanged, because the payload is built again at every
edit and at apply time. The database reads a build makes - the project and
its members - are replaced here with fixed values; the lifecycle against
PostgreSQL is covered in ``tests/pg/test_erp_chat_action_breadth.py``.
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

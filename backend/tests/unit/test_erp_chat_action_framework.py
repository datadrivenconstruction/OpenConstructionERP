"""The erp_chat action framework, without a database.

What a proposal is made of before it touches PostgreSQL: how the model's
numbers and dates are read, how a new BOQ line is numbered, how a typed name
finds a project member, what the model is told when it gets something wrong,
and that every i18n key an action can send has English text.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.modules.erp_chat.actions import labels
from app.modules.erp_chat.actions._boq import LineRow, next_ordinal
from app.modules.erp_chat.actions.base import (
    ActionConflictError,
    ActionValidationError,
    FieldErrors,
    decimal_str,
    error_from_http,
    make_field,
    make_note,
    parse_date,
    parse_decimal,
    parse_enum,
    parse_text,
    same_value,
    to_number,
)
from app.modules.erp_chat.actions.registry import (
    all_specs,
    get_spec,
    get_spec_for_tool,
    openai_tool_definitions,
    tool_definitions,
)
from app.modules.erp_chat.actions.task_create import match_members, member_options


def _section(ordinal: str) -> LineRow:
    return LineRow(
        id=uuid.uuid4(),
        boq_id=uuid.uuid4(),
        parent_id=None,
        ordinal=ordinal,
        description="Concrete works",
        unit="",
        quantity="0",
        unit_rate="0",
        total="0",
        sort_order=1,
        link_role=None,
        link_group_id=None,
    )


# ── Reading the model's values ──────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (120, Decimal("120")),
        (12.5, Decimal("12.5")),
        ("120.50", Decimal("120.50")),
        ("1 200,5", Decimal("1200.5")),
        ("1,200.50", Decimal("1200.50")),
        ("0", Decimal("0")),
    ],
)
def test_a_number_is_read_in_the_spellings_people_type(raw: object, expected: Decimal) -> None:
    errors = FieldErrors()
    assert parse_decimal({"q": raw}, "q", errors) == expected
    assert not errors


@pytest.mark.parametrize(("raw", "code"), [("abc", "not_a_number"), (-1, "negative"), (True, "not_a_number")])
def test_a_bad_number_is_a_field_error_not_a_guess(raw: object, code: str) -> None:
    errors = FieldErrors()
    assert parse_decimal({"q": raw}, "q", errors) is None
    assert errors.errors["q"]["code"] == code
    assert errors.errors["q"]["message_key"] == f"erp_chat.action.field_error.{code}"


def test_a_missing_required_value_is_reported_and_every_problem_comes_back_at_once() -> None:
    errors = FieldErrors()
    parse_text({}, "title", errors, required=True)
    parse_decimal({"quantity": "x"}, "quantity", errors, required=True)
    with pytest.raises(ActionValidationError) as caught:
        errors.raise_if_any()
    assert caught.value.status_code == 422
    assert set(caught.value.field_errors) == {"title", "quantity"}


def test_too_long_text_is_refused_rather_than_cut() -> None:
    errors = FieldErrors()
    assert parse_text({"unit": "x" * 21}, "unit", errors, max_length=20) is None
    assert errors.errors["unit"]["code"] == "too_long"


def test_a_date_accepts_a_datetime_and_rejects_nonsense() -> None:
    errors = FieldErrors()
    assert parse_date({"d": "2026-09-25T17:00:00Z"}, "d", errors) == "2026-09-25"
    assert parse_date({"d": "Friday"}, "d", errors) is None
    assert errors.errors["d"]["code"] == "invalid_date"


def test_an_enum_is_case_insensitive_and_defaults_when_absent() -> None:
    errors = FieldErrors()
    allowed = ("low", "normal", "high", "urgent")
    assert parse_enum({"p": "High"}, "p", errors, allowed=allowed) == "high"
    assert parse_enum({}, "p", errors, allowed=allowed, default="normal") == "normal"
    assert parse_enum({"p": "asap"}, "p", errors, allowed=allowed) is None
    assert errors.errors["p"]["code"] == "invalid_option"


def test_numbers_compare_by_value_not_by_spelling() -> None:
    assert same_value("120.0000", 120)
    assert same_value("12.5", Decimal("12.50"))
    assert not same_value("12.5", "12.6")
    assert same_value(None, "")
    assert decimal_str(Decimal("120.0000")) == "120"
    assert to_number("12.50") == 12.5
    assert to_number("120.0000") == 120


# ── Numbering a new BOQ line like the editor does ───────────────────────────


def test_a_line_in_a_section_takes_the_next_step_of_ten() -> None:
    taken = {"01", "01.10", "01.20"}
    assert next_ordinal(_section("01"), taken) == "01.30"


def test_the_first_line_of_an_empty_section_is_ten() -> None:
    assert next_ordinal(_section("02"), {"01", "02", "01.10"}) == "02.10"


def test_a_number_claimed_by_a_pending_proposal_is_skipped() -> None:
    # 01.30 is held by another proposal of the same turn: the next one is 01.40.
    taken = {"01", "01.10", "01.20", "01.30"}
    assert next_ordinal(_section("01"), taken) == "01.40"


def test_a_bill_without_sections_gets_four_digit_top_level_numbers() -> None:
    assert next_ordinal(None, set()) == "0010"
    assert next_ordinal(None, {"0010", "0020"}) == "0030"


# ── Finding the person the model named ──────────────────────────────────────

_MEMBERS = [
    (uuid.uuid4(), "Anna Schmidt", "anna@site.test"),
    (uuid.uuid4(), "Anna Berg", "a.berg@site.test"),
    (uuid.uuid4(), "Piotr Nowak", "piotr@site.test"),
]


def test_a_unique_first_name_finds_the_member() -> None:
    assert [m[1] for m in match_members("piotr", _MEMBERS)] == ["Piotr Nowak"]


def test_an_exact_email_or_full_name_wins_over_a_partial_match() -> None:
    assert [m[1] for m in match_members("Anna Schmidt", _MEMBERS)] == ["Anna Schmidt"]
    assert [m[1] for m in match_members("a.berg", _MEMBERS)] == ["Anna Berg"]


def test_a_shared_first_name_is_ambiguous_and_an_unknown_one_matches_nobody() -> None:
    assert len(match_members("anna", _MEMBERS)) == 2
    assert match_members("ivan", _MEMBERS) == []


def test_the_assignee_list_tells_two_people_with_one_name_apart() -> None:
    twin = (uuid.uuid4(), "Anna Schmidt", "a.schmidt@other.test")
    options = member_options([*_MEMBERS, twin])
    labels_by_id = {o.value: o.label for o in options}
    assert labels_by_id[str(_MEMBERS[0][0])] == "Anna Schmidt (anna@site.test)"
    assert labels_by_id[str(twin[0])] == "Anna Schmidt (a.schmidt@other.test)"
    assert labels_by_id[str(_MEMBERS[2][0])] == "Piotr Nowak"
    assert all(o.label_key is None for o in options)


# ── What the model and the dock are told ────────────────────────────────────


def test_a_refusal_tells_the_model_what_to_ask_and_that_nothing_was_proposed() -> None:
    error = ActionValidationError(code="boq_ambiguous", options=[{"id": "b1", "name": "Shell"}])
    result = error.to_tool_result()
    assert result["renderer"] == "error"
    assert result["data"]["error"] == "boq_ambiguous"
    assert result["data"]["options"] == [{"id": "b1", "name": "Shell"}]
    assert "Nothing was proposed" in result["summary"]


def test_an_http_refusal_carries_code_message_and_key() -> None:
    detail = ActionConflictError(code="target_changed").to_detail()
    assert detail["code"] == "target_changed"
    assert detail["message_key"] == "erp_chat.action.error.target_changed"
    assert detail["message"] == labels.ERRORS["target_changed"]


def test_a_domain_refusal_keeps_its_status_and_gets_a_code_the_dock_can_explain() -> None:
    gone = error_from_http(HTTPException(status_code=404, detail="Task not found"))
    assert (gone.status_code, gone.code, gone.message) == (404, "target_missing", "Task not found")
    locked = error_from_http(
        HTTPException(
            status_code=409, detail="BOQ is locked and cannot be modified. Create a revision to make changes."
        )
    )
    assert (locked.status_code, locked.code) == (409, "locked")
    refused = error_from_http(HTTPException(status_code=400, detail={"message": "Crane orders are closed"}))
    assert (refused.status_code, refused.code, refused.message) == (422, "domain_error", "Crane orders are closed")


def test_a_note_renders_its_english_and_keeps_the_params_for_translation() -> None:
    note = make_note("assignee_unmatched", params={"name": "Ivan"}, field_key="assignee", tone="warning")
    assert note.key == "erp_chat.action.note.assignee_unmatched"
    assert '"Ivan"' in note.text and "{{" not in note.text
    assert note.params == {"name": "Ivan"}


def test_an_enum_field_lists_its_options_with_keys_and_english() -> None:
    field = make_field("priority", "enum", "high", editable=True)
    assert field.label_key == "erp_chat.action.field.priority"
    assert [o.value for o in field.options or []] == ["low", "normal", "high", "urgent"]
    assert all(o.label_key.startswith("erp_chat.action.option.priority.") for o in field.options or [])


# ── Registry ────────────────────────────────────────────────────────────────


def test_every_action_is_a_propose_tool_with_confidence_and_rationale() -> None:
    specs = all_specs()
    assert {s.action_type for s in specs} >= {"boq.add_position", "boq.update_position", "task.create"}
    names = [t["name"] for t in tool_definitions()]
    assert len(names) == len(set(names))
    for tool in tool_definitions():
        assert tool["name"].startswith("propose_")
        props = tool["input_schema"]["properties"]
        assert "confidence" in props and "rationale" in props
        assert tool["description"]
    assert {t["function"]["name"] for t in openai_tool_definitions()} == set(names)


def test_a_tool_name_and_an_action_type_lead_to_the_same_spec() -> None:
    assert get_spec_for_tool("propose_create_task") is get_spec("task.create")
    assert get_spec_for_tool("get_boq_items") is None


def test_every_title_label_and_option_an_action_can_send_has_english() -> None:
    keys = labels.all_keys()
    for spec in all_specs():
        assert keys[spec.title_key] == spec.title
    for field_key in labels.FIELDS:
        assert labels.field_key(field_key) in keys
    for field_key, options in labels.OPTIONS.items():
        for value in options:
            assert labels.option_key(field_key, value) in keys
    assert all(text.strip() for text in keys.values())
    assert all(key.startswith("erp_chat.action.") for key in keys)


def test_an_automatic_position_number_is_not_a_human_edit() -> None:
    spec = get_spec("boq.add_position")
    assert spec is not None
    original = {"ordinal": "01.20", "ordinal_auto": True, "quantity": "10"}
    renumbered = {"ordinal": "01.30", "ordinal_auto": True, "quantity": "10"}
    assert spec.edit_view(original) == spec.edit_view(renumbered)
    typed = spec.merge_patch(original, {"ordinal": "01.25"})
    assert typed["ordinal_auto"] is False
    assert spec.edit_view(typed) != spec.edit_view(original)

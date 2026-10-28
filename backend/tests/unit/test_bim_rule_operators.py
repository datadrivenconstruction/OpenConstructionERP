# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Quantity-rule property conditions beyond equality.

Matching itself is pinned by the shared parity table
(``test_rule_matching_parity.py``); this file pins what a rule may store:
an operator the engine knows, with the value that operator takes, and a
refusal in the caller's language for anything else.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.i18n import _current_locale
from app.modules.bim_hub.rule_operators import (
    ConditionError,
    Measure,
    check_property_filter,
    compare_measures,
    parse_measure,
)
from app.modules.bim_hub.schemas import (
    BIMQuantityMapCreate,
    BIMQuantityMapUpdate,
    QuantityRuleDraft,
)


def test_bare_values_pass_through_untouched() -> None:
    pf = {"Phase Created": "Progetto", "width": 300, "tags": ["a", "b"], "nested": {"x": "y"}}
    assert check_property_filter(pf) == pf


def test_operator_values_are_trimmed_and_numbers_kept_as_text() -> None:
    out = check_property_filter(
        {
            "Width": {"$op": "gt", "value": " 200 mm "},
            "Height": {"$op": "lte", "value": 3},
            "Phase Demolished": {"$op": "is_empty", "value": ""},
        }
    )
    assert out == {
        "Width": {"$op": "gt", "value": "200 mm"},
        "Height": {"$op": "lte", "value": "3"},
        "Phase Demolished": {"$op": "is_empty"},
    }


@pytest.mark.parametrize(
    ("pattern", "code"),
    [
        ({"$op": "between", "value": "1"}, "bim_rules.unknown_operator"),
        ({"$op": "gt", "value": "tall"}, "bim_rules.value_not_number"),
        ({"$op": "gt", "value": "3 furlongs"}, "bim_rules.value_not_number"),
        ({"$op": "lt", "value": "1,5"}, "bim_rules.value_not_number"),
        ({"$op": "gt", "value": True}, "bim_rules.value_not_number"),
        ({"$op": "contains"}, "bim_rules.value_required"),
        ({"$op": "not_equals", "value": "   "}, "bim_rules.value_required"),
        ({"$op": "contains", "value": ["a"]}, "bim_rules.value_required"),
        ({"$op": "contains", "value": "x" * 501}, "bim_rules.value_too_long"),
        ({"$op": "is_empty", "value": "x"}, "bim_rules.value_not_allowed"),
        ({"$op": "gt", "value": float("inf")}, "bim_rules.value_required"),
    ],
)
def test_invalid_conditions_are_refused(pattern: dict, code: str) -> None:
    with pytest.raises(ConditionError) as info:
        check_property_filter({"Width": pattern})
    assert info.value.code == code
    assert info.value.key == "Width"


def test_a_filter_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(ConditionError) as info:
        check_property_filter(["Width"])  # type: ignore[arg-type]
    assert info.value.code == "bim_rules.filter_not_object"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("3", Measure(3.0, "")),
        (" 2.5 m ", Measure(2.5, "m")),
        ("12 m²", Measure(12.0, "m2")),
        ("100 FT2", Measure(100.0, "ft2")),
        ("1e3mm", Measure(1000.0, "mm")),
        (4, Measure(4.0, "")),
        ("", None),
        ("m", None),
        ("nan", None),
        (True, None),
        ("1,5", None),
    ],
)
def test_parse_measure(raw: object, expected: Measure | None) -> None:
    assert parse_measure(raw) == expected


def test_compare_measures_converts_within_a_kind_only() -> None:
    assert compare_measures(Measure(3000, "mm"), Measure(3, "m")) == 0
    assert compare_measures(Measure(1, "m3"), Measure(999, "l")) == 1
    assert compare_measures(Measure(1, "t"), Measure(1001, "kg")) == -1
    assert compare_measures(Measure(1, "m"), Measure(1, "kg")) is None
    assert compare_measures(Measure(5, ""), Measure(4, "m")) == 1


@pytest.mark.parametrize("schema", [BIMQuantityMapCreate, BIMQuantityMapUpdate, QuantityRuleDraft])
def test_every_rule_schema_refuses_a_bad_condition(schema: type) -> None:
    payload = {"property_filter": {"Width": {"$op": "gt", "value": "wide"}}}
    if schema is BIMQuantityMapCreate:
        payload |= {"name": "r", "quantity_source": "count"}
    with pytest.raises(ValidationError) as info:
        schema(**payload)
    err = info.value.errors()[0]
    assert err["type"] == "bim_rule_condition"
    assert err["ctx"]["code"] == "bim_rules.value_not_number"
    assert '"Width"' in err["msg"] and '"wide"' in err["msg"]


def test_the_refusal_is_in_the_callers_language() -> None:
    token = _current_locale.set("de")
    try:
        with pytest.raises(ValidationError) as info:
            QuantityRuleDraft(property_filter={"Breite": {"$op": "lt", "value": "schmal"}})
    finally:
        _current_locale.reset(token)
    msg = info.value.errors()[0]["msg"]
    assert '"Breite"' in msg
    assert "is not a number" not in msg


def test_a_valid_condition_round_trips_through_the_schema() -> None:
    draft = QuantityRuleDraft(property_filter={"Phase Demolished": {"$op": "is_empty"}, "Category": "Walls"})
    assert draft.property_filter == {"Phase Demolished": {"$op": "is_empty"}, "Category": "Walls"}

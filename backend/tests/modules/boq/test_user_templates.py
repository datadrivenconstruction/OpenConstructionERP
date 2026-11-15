"""Editable estimate templates: shape, rules and the estimate-to-template conversion.

Pure functions only; no database. The worked examples are the ones an estimator
would try by hand: take a finished bill, keep or drop its numbers, check what
comes out.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.modules.boq.template_schemas import TemplateWrite
from app.modules.boq.templates import TEMPLATES
from app.modules.boq.user_templates import (
    RULE_DUPLICATE_ORDINAL,
    RULE_EMPTY_SECTION,
    RULE_MARKUP_BAND,
    RULE_NAME,
    RULE_NO_SECTIONS,
    RULE_POSITION_UNIT,
    RULE_UNCLASSIFIED,
    builtin_to_detail,
    expand_quantity,
    markups_from_rows,
    money_text,
    renumber,
    sections_from_positions,
    validate_template,
)


def _row(ordinal, description, unit="m2", qty="0", rate="0", parent=None, sort=0, classification=None, **extra):
    return SimpleNamespace(
        id=uuid.uuid4(),
        parent_id=parent,
        ordinal=ordinal,
        description=description,
        unit=unit,
        quantity=qty,
        unit_rate=rate,
        classification=classification or {},
        sort_order=sort,
        metadata_={"actual_cost": "99"},
        cad_element_ids=["e1"],
        wbs_id="w",
        cost_code_id="c",
        **extra,
    )


def _estimate():
    """Two real sections, one empty section, one loose line, one blank line."""
    s1 = _row("A", "Earthwork", unit="section", sort=0)
    s2 = _row("B", "Concrete", unit="section", sort=3)
    s3 = _row("C", "Nothing here", unit="section", sort=6)
    return [
        s1,
        _row("A.1", "Excavation", "m3", "120.50", "12.5", parent=s1.id, sort=1, classification={"din276": "311"}),
        _row("A.2", "Backfill", "m3", "40", "9", parent=s1.id, sort=2),
        s2,
        _row("B.1", "Slab", "m3", "30", "180", parent=s2.id, sort=4),
        _row("B.2", "", "", "0", "0", parent=s2.id, sort=5),
        s3,
        _row("Z.9", "Loose item", "pcs", "3", "10", parent=None, sort=7),
    ]


def test_from_estimate_keeps_structure_and_strips_project_data():
    sections = sections_from_positions(_estimate(), keep_quantities=True, keep_rates=True)
    # empty section C and blank line B.2 dropped; the loose line gets its own group
    assert [s["description"] for s in sections] == ["Earthwork", "Concrete", "General"]
    assert [len(s["positions"]) for s in sections] == [2, 1, 1]
    first = sections[0]["positions"][0]
    assert first == {
        "ordinal": "01.0010",
        "description": "Excavation",
        "unit": "m3",
        "quantity": "120.5",
        "qty_factor": None,
        "rate": "12.5",
        "classification": {"din276": "311"},
    }
    flat = str(sections)
    for leaked in ("actual_cost", "e1", "wbs", "cost_code"):
        assert leaked not in flat


def test_from_estimate_can_clear_quantities_and_rates():
    sections = sections_from_positions(_estimate(), keep_quantities=False, keep_rates=False)
    for sec in sections:
        for pos in sec["positions"]:
            assert pos["quantity"] is None
            assert pos["rate"] is None


def test_from_estimate_can_keep_original_ordinals():
    sections = sections_from_positions(_estimate(), keep_quantities=False, keep_rates=False, renumber_positions=False)
    assert [p["ordinal"] for p in sections[0]["positions"]] == ["A.1", "A.2"]


def test_renumber_is_stable_and_gap_free():
    out = renumber([{"ordinal": "x", "description": "S", "positions": [{"ordinal": "q"}, {"ordinal": "q"}]}])
    assert out[0]["ordinal"] == "01"
    assert [p["ordinal"] for p in out[0]["positions"]] == ["01.0010", "01.0020"]


def test_markups_drop_inactive_and_position_scoped_lines():
    rows = [
        SimpleNamespace(
            name="Overhead",
            markup_type="percentage",
            category="overhead",
            percentage="8",
            fixed_amount="0",
            apply_to="direct_cost",
            sort_order=0,
            is_active=True,
            scope_position_id=None,
            overrides_id=None,
        ),
        SimpleNamespace(
            name="Off",
            markup_type="percentage",
            category="profit",
            percentage="5",
            fixed_amount="0",
            apply_to="direct_cost",
            sort_order=1,
            is_active=False,
            scope_position_id=None,
            overrides_id=None,
        ),
        SimpleNamespace(
            name="Scoped",
            markup_type="percentage",
            category="profit",
            percentage="5",
            fixed_amount="0",
            apply_to="direct_cost",
            sort_order=2,
            is_active=True,
            scope_position_id=uuid.uuid4(),
            overrides_id=None,
        ),
    ]
    assert [m["name"] for m in markups_from_rows(rows)] == ["Overhead"]


def _rules(detail):
    return [i["rule_id"] for i in validate_template(detail)]


def test_validation_flags_empty_section_missing_unit_and_duplicate_numbers():
    detail = {
        "name": "T",
        "sections": [
            {"ordinal": "01", "description": "A", "positions": []},
            {
                "ordinal": "02",
                "description": "B",
                "positions": [
                    {"ordinal": "02.1", "description": "x", "unit": ""},
                    {"ordinal": "02.1", "description": "y", "unit": "m"},
                ],
            },
        ],
    }
    issues = validate_template(detail)
    rules = [i["rule_id"] for i in issues]
    assert rules.count(RULE_EMPTY_SECTION) == 1
    assert rules.count(RULE_POSITION_UNIT) == 1
    assert rules.count(RULE_DUPLICATE_ORDINAL) == 2  # both rows carrying the number are marked
    unit_issue = next(i for i in issues if i["rule_id"] == RULE_POSITION_UNIT)
    assert unit_issue["path"] == {"section": 1, "position": 0}
    assert all(i["severity"] == "warning" for i in issues)


def test_validation_name_sections_classification_and_markup_band():
    assert _rules({"name": " ", "sections": []}) == [RULE_NAME, RULE_NO_SECTIONS]
    detail = {
        "name": "T",
        "classification_standard": "din276",
        "sections": [
            {"ordinal": "1", "description": "S", "positions": [{"ordinal": "1.1", "description": "d", "unit": "m"}]}
        ],
        "markups": [{"name": "VAT", "percentage": "250"}],
    }
    assert sorted(_rules(detail)) == sorted([RULE_UNCLASSIFIED, RULE_MARKUP_BAND])


def test_clean_template_has_no_warnings():
    detail = {
        "name": "T",
        "sections": [
            {"ordinal": "1", "description": "S", "positions": [{"ordinal": "1.1", "description": "d", "unit": "m"}]}
        ],
    }
    assert validate_template(detail) == []


def test_every_built_in_template_passes_the_rules():
    for tid, tpl in TEMPLATES.items():
        detail = builtin_to_detail(tid, tpl)
        assert detail["builtin"] is True
        assert validate_template(detail) == [], tid


def test_expansion_prefers_factor_with_area_else_fixed_else_zero():
    assert expand_quantity({"qty_factor": "0.8", "quantity": "5"}, Decimal("100")) == Decimal("80.0")
    assert expand_quantity({"qty_factor": "0.8", "quantity": "5"}, None) == Decimal("5")
    assert expand_quantity({"quantity": "7.5"}, Decimal("100")) == Decimal("7.5")
    assert expand_quantity({}, Decimal("100")) == Decimal("0")


def test_amounts_are_canonical_strings_and_garbage_is_refused():
    assert money_text("12,50") == "12.5"
    assert money_text("") is None
    body = TemplateWrite.model_validate(
        {"name": "n", "sections": [{"positions": [{"description": "d", "unit": "m", "rate": "3.0", "quantity": " "}]}]}
    )
    pos = body.sections[0].positions[0]
    assert (pos.rate, pos.quantity, pos.qty_factor) == ("3", None, None)
    with pytest.raises(ValidationError):
        TemplateWrite.model_validate({"sections": [{"positions": [{"rate": "abc"}]}]})

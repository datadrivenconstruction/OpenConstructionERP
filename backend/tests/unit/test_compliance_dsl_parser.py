# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the compliance DSL parser (T08).

Covers:

* happy-path parses for forEach + assert and bare assert
* required-key, type-error and unknown-key rejections
* shorthand string expressions (``position.quantity > 0``)
* logical combinators and aggregation operators
* hostile inputs (Python-tag YAML, deep nesting, dunder field paths)
"""

from __future__ import annotations

import pytest

from app.core.validation.dsl.parser import (
    Aggregation,
    Comparison,
    DSLSyntaxError,
    DSLTypeError,
    FieldRef,
    ForEachAssert,
    Literal,
    Logical,
    SingleAssert,
    parse_definition,
    validate_definition,
)
from app.core.validation.engine import RuleCategory, Severity

# ── Fixtures ───────────────────────────────────────────────────────────────


_VALID_FOREACH_DOC = """
rule_id: custom.boq.no_zero_quantities
name: BOQ positions must have non-zero quantities
severity: error
scope: positions
expression:
  forEach: position
  assert: position.quantity > 0
"""

_VALID_SINGLE_ASSERT_DOC = """
rule_id: custom.boq.has_positions
name: BOQ must have at least one position
expression:
  assert:
    ">": [{ count: positions }, 0]
"""


# ── Tests ──────────────────────────────────────────────────────────────────


def test_parses_minimal_foreach_yaml() -> None:
    rule = parse_definition(_VALID_FOREACH_DOC)
    assert rule.rule_id == "custom.boq.no_zero_quantities"
    assert rule.severity is Severity.ERROR
    assert rule.category is RuleCategory.CUSTOM
    assert rule.scope == "positions"
    assert isinstance(rule.body, ForEachAssert)
    assert rule.body.iter_var == "position"
    assert isinstance(rule.body.predicate, Comparison)
    assert rule.body.predicate.op == ">"
    assert isinstance(rule.body.predicate.left, FieldRef)
    assert rule.body.predicate.left.path == ("position", "quantity")
    assert isinstance(rule.body.predicate.right, Literal)
    assert rule.body.predicate.right.value == 0


def test_parses_dict_input_directly() -> None:
    rule = parse_definition(
        {
            "rule_id": "custom.x",
            "name": "X",
            "expression": {"assert": True},
        }
    )
    assert rule.rule_id == "custom.x"
    assert isinstance(rule.body, SingleAssert)
    assert isinstance(rule.body.predicate, Literal)
    assert rule.body.predicate.value is True


def test_parses_aggregation_with_count() -> None:
    rule = parse_definition(_VALID_SINGLE_ASSERT_DOC)
    assert isinstance(rule.body, SingleAssert)
    assert isinstance(rule.body.predicate, Comparison)
    assert isinstance(rule.body.predicate.left, Aggregation)
    assert rule.body.predicate.left.kind == "count"
    assert rule.body.predicate.left.field == FieldRef(path=("positions",))


def test_parses_logical_and() -> None:
    rule = parse_definition(
        {
            "rule_id": "custom.x",
            "name": "X",
            "expression": {
                "forEach": "p",
                "assert": {
                    "and": [
                        "p.quantity > 0",
                        "p.unit_rate > 0",
                    ]
                },
            },
        }
    )
    assert isinstance(rule.body, ForEachAssert)
    assert isinstance(rule.body.predicate, Logical)
    assert rule.body.predicate.op == "and"
    assert len(rule.body.predicate.operands) == 2


def test_parses_in_membership() -> None:
    rule = parse_definition(
        {
            "rule_id": "custom.unit_in_set",
            "name": "Unit in set",
            "expression": {
                "forEach": "p",
                "assert": {
                    "in": {"value": "p.unit", "list": ["m", "m2", "m3"]},
                },
            },
        }
    )
    assert isinstance(rule.body, ForEachAssert)
    assert isinstance(rule.body.predicate, Comparison)
    assert rule.body.predicate.op == "in"
    assert isinstance(rule.body.predicate.right, Literal)
    assert rule.body.predicate.right.value == ("m", "m2", "m3")


def test_missing_required_key_raises_syntax_error() -> None:
    with pytest.raises(DSLSyntaxError) as exc_info:
        parse_definition(
            {
                "rule_id": "custom.x",
                # 'name' missing
                "expression": {"assert": True},
            }
        )
    assert "Missing required keys" in str(exc_info.value)


def test_unknown_top_level_key_raises_syntax_error() -> None:
    with pytest.raises(DSLSyntaxError):
        parse_definition(
            {
                "rule_id": "custom.x",
                "name": "X",
                "expression": {"assert": True},
                "haxxor": "rm -rf /",
            }
        )


def test_invalid_severity_raises_type_error() -> None:
    with pytest.raises(DSLTypeError):
        parse_definition(
            {
                "rule_id": "custom.x",
                "name": "X",
                "severity": "catastrophic",
                "expression": {"assert": True},
            }
        )


def test_invalid_category_raises_type_error() -> None:
    with pytest.raises(DSLTypeError):
        parse_definition(
            {
                "rule_id": "custom.x",
                "name": "X",
                "category": "bogus",
                "expression": {"assert": True},
            }
        )


def test_dunder_in_rule_id_rejected() -> None:
    with pytest.raises(DSLTypeError):
        parse_definition(
            {
                "rule_id": "custom.__class__.__init__",
                "name": "X",
                "expression": {"assert": True},
            }
        )


def test_dunder_in_field_path_rejected() -> None:
    with pytest.raises(DSLTypeError):
        parse_definition(
            {
                "rule_id": "custom.x",
                "name": "X",
                "expression": {"forEach": "p", "assert": "p.__class__"},
            }
        )


def test_yaml_python_tag_safe_load() -> None:
    """``!!python/object`` must NOT instantiate Python classes — yaml.safe_load
    rejects it and the parser surfaces a syntax error."""
    hostile = (
        "rule_id: custom.x\n"
        "name: X\n"
        "expression:\n"
        "  assert: !!python/object/new:os.system [echo pwned]\n"
    )
    with pytest.raises(DSLSyntaxError):
        parse_definition(hostile)


def test_empty_source_raises_syntax_error() -> None:
    with pytest.raises(DSLSyntaxError):
        parse_definition("")


def test_non_mapping_top_level_raises_syntax_error() -> None:
    with pytest.raises(DSLSyntaxError):
        parse_definition("[1, 2, 3]")


def test_for_each_without_assert_raises_syntax_error() -> None:
    with pytest.raises(DSLSyntaxError):
        parse_definition(
            {
                "rule_id": "custom.x",
                "name": "X",
                "expression": {"forEach": "p"},
            }
        )


def test_validate_definition_returns_false_on_bad_doc() -> None:
    ok, err = validate_definition(
        {
            "rule_id": "custom.x",
            "name": "X",
            "expression": {"forEach": "p"},
        }
    )
    assert ok is False
    assert err is not None
    assert "assert" in err


def test_validate_definition_returns_true_on_good_doc() -> None:
    ok, err = validate_definition(_VALID_FOREACH_DOC)
    assert ok is True
    assert err is None


def test_too_many_logical_operands_rejected() -> None:
    big_and = {"and": ["true"] * 64}
    with pytest.raises(DSLSyntaxError):
        parse_definition(
            {
                "rule_id": "custom.x",
                "name": "X",
                "expression": {"assert": big_and},
            }
        )


def test_rule_sets_must_be_list_of_strings() -> None:
    with pytest.raises(DSLTypeError):
        parse_definition(
            {
                "rule_id": "custom.x",
                "name": "X",
                "rule_sets": "not_a_list",
                "expression": {"assert": True},
            }
        )

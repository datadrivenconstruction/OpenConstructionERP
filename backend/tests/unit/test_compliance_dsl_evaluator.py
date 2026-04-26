# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the compliance DSL evaluator (T08).

Each test compiles a definition into a dynamic
:class:`~app.core.validation.engine.ValidationRule`, runs it against a
synthetic :class:`~app.core.validation.engine.ValidationContext`, and
asserts on the produced :class:`RuleResult` list.
"""

from __future__ import annotations

import textwrap

import pytest

from app.core.validation.dsl import compile_rule, parse_definition
from app.core.validation.engine import (
    Severity,
    ValidationContext,
)

# ── Helpers ────────────────────────────────────────────────────────────────


def _make_rule(yaml_text):
    """Compile an inline YAML/JSON string or dict into a ValidationRule.

    Dedents leading whitespace so test docstrings can be indented for
    readability without breaking YAML's significant indentation rules.
    """
    if isinstance(yaml_text, str):
        yaml_text = textwrap.dedent(yaml_text)
    return compile_rule(parse_definition(yaml_text))


def _ctx(data: object) -> ValidationContext:
    return ValidationContext(data=data)


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_for_each_passes_when_all_items_pass() -> None:
    rule = _make_rule(
        """
        rule_id: custom.qty_positive
        name: Quantity must be positive
        severity: error
        scope: positions
        expression:
          forEach: position
          assert: position.quantity > 0
        """
    )
    data = {"positions": [{"quantity": 1}, {"quantity": 5}]}
    results = await rule.validate(_ctx(data))
    assert len(results) == 1
    assert results[0].passed is True
    assert results[0].details.get("checked") == 2


@pytest.mark.asyncio
async def test_for_each_emits_one_result_per_failing_item() -> None:
    rule = _make_rule(
        """
        rule_id: custom.qty_positive
        name: Quantity must be positive
        severity: error
        scope: positions
        expression:
          forEach: position
          assert: position.quantity > 0
        """
    )
    data = {
        "positions": [
            {"id": "p1", "ordinal": "01.01", "quantity": 1},
            {"id": "p2", "ordinal": "01.02", "quantity": 0},
            {"id": "p3", "ordinal": "01.03", "quantity": -2},
        ]
    }
    results = await rule.validate(_ctx(data))
    failed = [r for r in results if not r.passed]
    assert len(failed) == 2
    assert {r.element_ref for r in failed} == {"p2", "p3"}
    # Severity propagates from the definition.
    assert all(r.severity is Severity.ERROR for r in failed)


@pytest.mark.asyncio
async def test_logical_and_combines_per_item_predicates() -> None:
    rule = _make_rule(
        """
        rule_id: custom.qty_and_rate
        name: Quantity and rate must be positive
        severity: warning
        scope: positions
        expression:
          forEach: p
          assert:
            and:
              - p.quantity > 0
              - p.unit_rate > 0
        """
    )
    data = {
        "positions": [
            {"id": "ok", "quantity": 1, "unit_rate": 100},
            {"id": "no_rate", "quantity": 1, "unit_rate": 0},
            {"id": "no_qty", "quantity": 0, "unit_rate": 50},
        ]
    }
    results = await rule.validate(_ctx(data))
    failed = [r for r in results if not r.passed]
    assert {r.element_ref for r in failed} == {"no_rate", "no_qty"}
    assert all(r.severity is Severity.WARNING for r in failed)


@pytest.mark.asyncio
async def test_in_membership_pass_and_fail() -> None:
    rule = _make_rule(
        {
            "rule_id": "custom.unit_whitelist",
            "name": "Unit must be metric",
            "severity": "info",
            "scope": "positions",
            "expression": {
                "forEach": "p",
                "assert": {
                    "in": {"value": "p.unit", "list": ["m", "m2", "m3"]},
                },
            },
        }
    )
    data = {
        "positions": [
            {"id": "ok", "unit": "m"},
            {"id": "imperial", "unit": "ft"},
        ]
    }
    results = await rule.validate(_ctx(data))
    failed = [r for r in results if not r.passed]
    assert len(failed) == 1
    assert failed[0].element_ref == "imperial"


@pytest.mark.asyncio
async def test_count_aggregation_in_single_assert() -> None:
    rule = _make_rule(
        {
            "rule_id": "custom.has_positions",
            "name": "BOQ must have at least one position",
            "severity": "error",
            "scope": "positions",
            "expression": {
                "assert": {
                    ">": [{"count": "positions"}, 0],
                }
            },
        }
    )
    # Pass — non-empty list.
    res_pass = await rule.validate(_ctx({"positions": [{"id": "x"}]}))
    assert len(res_pass) == 1
    assert res_pass[0].passed is True

    # Fail — empty list.
    res_fail = await rule.validate(_ctx({"positions": []}))
    assert res_fail[0].passed is False


@pytest.mark.asyncio
async def test_sum_aggregation() -> None:
    rule = _make_rule(
        {
            "rule_id": "custom.total_cap",
            "name": "Total must not exceed cap",
            "severity": "warning",
            "scope": "positions",
            "expression": {
                "assert": {
                    "<=": [{"sum": "p.amount"}, 1000],
                }
            },
        }
    )
    # Without forEach, ``sum`` operates on the resolved scope items
    # using the bare leaf segment of the field path.
    data = {
        "positions": [
            {"amount": 200},
            {"amount": 300},
            {"amount": 400},
        ]
    }
    res = await rule.validate(_ctx(data))
    assert res[0].passed is True

    data["positions"].append({"amount": 200})
    res2 = await rule.validate(_ctx(data))
    assert res2[0].passed is False


@pytest.mark.asyncio
async def test_missing_field_treated_as_failure_not_crash() -> None:
    rule = _make_rule(
        """
        rule_id: custom.has_unit
        name: Position must have unit
        severity: error
        scope: positions
        expression:
          forEach: p
          assert: p.unit != null
        """
    )
    data = {
        "positions": [
            {"id": "ok", "unit": "m"},
            {"id": "missing"},  # no unit
        ]
    }
    results = await rule.validate(_ctx(data))
    failed = [r for r in results if not r.passed]
    assert len(failed) == 1
    assert failed[0].element_ref == "missing"


@pytest.mark.asyncio
async def test_or_combinator_short_circuits() -> None:
    rule = _make_rule(
        {
            "rule_id": "custom.either_unit_or_lump",
            "name": "Either has unit or is lump sum",
            "severity": "warning",
            "scope": "positions",
            "expression": {
                "forEach": "p",
                "assert": {
                    "or": [
                        {"!=": ["p.unit", None]},
                        {"==": ["p.is_lump_sum", True]},
                    ]
                },
            },
        }
    )
    data = {
        "positions": [
            {"id": "with_unit", "unit": "m"},
            {"id": "lump", "is_lump_sum": True},
            {"id": "neither"},
        ]
    }
    results = await rule.validate(_ctx(data))
    failed = [r for r in results if not r.passed]
    assert {r.element_ref for r in failed} == {"neither"}


@pytest.mark.asyncio
async def test_not_combinator() -> None:
    rule = _make_rule(
        {
            "rule_id": "custom.no_negative_qty",
            "name": "No negative quantity",
            "severity": "error",
            "scope": "positions",
            "expression": {
                "forEach": "p",
                "assert": {"not": {"<": ["p.quantity", 0]}},
            },
        }
    )
    data = {
        "positions": [
            {"id": "ok", "quantity": 1},
            {"id": "neg", "quantity": -1},
        ]
    }
    results = await rule.validate(_ctx(data))
    failed = [r for r in results if not r.passed]
    assert len(failed) == 1
    assert failed[0].element_ref == "neg"


@pytest.mark.asyncio
async def test_severity_propagation_into_rule_result() -> None:
    rule = _make_rule(
        """
        rule_id: custom.always_fails
        name: Always fails
        severity: info
        expression:
          assert: false
        """
    )
    results = await rule.validate(_ctx({}))
    assert len(results) == 1
    assert results[0].severity is Severity.INFO
    assert results[0].passed is False


@pytest.mark.asyncio
async def test_for_each_against_missing_scope_passes_vacuously() -> None:
    """No data in scope → return a single passing result.

    This mirrors the engine's standard behaviour for empty inputs and
    avoids spurious failures when a rule references an optional sub-tree.
    """
    rule = _make_rule(
        """
        rule_id: custom.optional_section
        name: optional positions
        severity: warning
        scope: positions
        expression:
          forEach: p
          assert: p.quantity > 0
        """
    )
    results = await rule.validate(_ctx({"sections": []}))
    assert len(results) == 1
    assert results[0].passed is True


@pytest.mark.asyncio
async def test_for_each_against_non_list_scope_emits_eval_error_result() -> None:
    rule = _make_rule(
        """
        rule_id: custom.bogus_scope
        name: bogus
        severity: error
        scope: positions
        expression:
          forEach: p
          assert: p.x > 0
        """
    )
    # ``positions`` resolves to a dict — not a list.
    results = await rule.validate(_ctx({"positions": {"id": "x"}}))
    assert len(results) == 1
    assert results[0].passed is False
    assert results[0].details.get("error") == "dsl_evaluation_error"

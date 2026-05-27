"""Tests for the EAC constraint evaluator."""

import pytest

from app.modules.requirements.evaluator import OPERATORS, evaluate


@pytest.mark.parametrize(
    ("op", "expected", "actual", "passed"),
    [
        # equals / not_equals (string-insensitive)
        ("equals", "Concrete", "concrete", True),
        ("equals", "Concrete", "steel", False),
        ("not_equals", "Concrete", "Steel", True),
        ("not_equals", "Concrete", "concrete", False),
        # contains / not_contains
        ("contains", "fire", "Fire-rated wall", True),
        ("contains", "FIRE", "load-bearing", False),
        ("not_contains", "draft", "final spec", True),
        ("not_contains", "draft", "draft v2", False),
        # min / max (numeric)
        ("min", "0.24", "0.30", True),
        ("min", "0.24", "0.20", False),
        ("max", "5.0", "4.5", True),
        ("max", "5.0", "5.5", False),
        # range — accept all separator styles
        ("range", "200..400", "300", True),
        ("range", "200-400", "199", False),
        ("range", "200,400", "401", False),
        ("range", "200;400", "200", True),
        ("range", "400..200", "300", True),  # auto-swap when reversed
        # regex
        ("regex", r"^F\d{2,3}$", "F90", True),
        ("regex", r"^F\d{2,3}$", "F9", False),
        # exists / not_exists
        ("exists", "", "anything", True),
        ("exists", "", "", False),
        ("exists", "", None, False),
        ("not_exists", "", "", True),
        ("not_exists", "", None, True),
        ("not_exists", "", "value", False),
    ],
)
def test_evaluate_matrix(op: str, expected: str, actual: object, passed: bool) -> None:
    result = evaluate(op, expected, actual)
    assert result.passed is passed, f"{op}('{expected}', {actual!r}) -> {result.reason}"
    if passed:
        assert result.reason == ""
    else:
        assert result.reason  # non-empty explanation


def test_unknown_operator() -> None:
    result = evaluate("greater_than", "5", "6")
    assert result.passed is False
    assert "Unknown" in result.reason


def test_numeric_with_non_numeric_actual() -> None:
    result = evaluate("min", "5", "five")
    assert result.passed is False
    assert "non-numeric" in result.reason


def test_invalid_regex() -> None:
    result = evaluate("regex", "[unclosed", "anything")
    assert result.passed is False
    assert "invalid regex" in result.reason


def test_invalid_range_format() -> None:
    result = evaluate("range", "abc", "5")
    assert result.passed is False
    assert "must look like" in result.reason


def test_empty_constraint_value_for_value_required_op() -> None:
    result = evaluate("equals", "", "anything")
    assert result.passed is False
    assert "empty" in result.reason


def test_european_decimal_separator() -> None:
    # "5,5" should be coerced to 5.5 (common in DACH region)
    assert evaluate("min", "5", "5,5").passed is True
    assert evaluate("max", "5,0", "4,5").passed is True


def test_all_operators_covered_by_matrix() -> None:
    # Sanity: matrix must touch every supported operator
    matrix_ops = {
        "equals",
        "not_equals",
        "contains",
        "not_contains",
        "min",
        "max",
        "range",
        "regex",
        "exists",
        "not_exists",
    }
    assert matrix_ops == set(OPERATORS)

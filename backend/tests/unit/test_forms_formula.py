"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the Forms computed (formula) field engine.

The engine (``app.modules.forms.formula``) is pure - stdlib only, no ORM or app
imports - so it is loaded here directly from its file path, keeping the test
independent of the FastAPI dependency graph while exercising the real module,
identically here and in CI. Also loads ``validation`` to prove the formula rules
are wired into the real template / submission validation path.
"""

from __future__ import annotations

import importlib.util
import sys
from decimal import Decimal
from pathlib import Path

_FORMS_DIR = Path(__file__).resolve().parents[2] / "app" / "modules" / "forms"


def _load(module_name: str, filename: str):  # noqa: ANN202 - dynamic module handle
    path = _FORMS_DIR / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


formula = _load("forms_formula_under_test", "formula.py")
validation = _load("forms_validation_under_test", "validation.py")

evaluate_formula = formula.evaluate_formula
compute_formulas = formula.compute_formulas
list_formula_vars = formula.list_formula_vars
validate_formula = formula.validate_formula
FormulaSyntaxError = formula.FormulaSyntaxError
UnknownVariableError = formula.UnknownVariableError
FormulaMathError = formula.FormulaMathError


def _codes(issues) -> set[str]:  # noqa: ANN001
    return {i.code for i in issues}


# ── evaluate_formula: arithmetic ─────────────────────────────────────────────


def test_basic_arithmetic() -> None:
    assert evaluate_formula("length * width", {"length": 4, "width": 3}) == Decimal("12")


def test_precedence_and_parentheses() -> None:
    assert evaluate_formula("(a + b) * 2", {"a": 1, "b": 2}) == Decimal("6")


def test_decimal_is_exact() -> None:
    # Float 0.1 + 0.2 != 0.3; Decimal keeps it exact.
    assert evaluate_formula("a + b", {"a": "0.1", "b": "0.2"}) == Decimal("0.3")


def test_comma_decimal_operand() -> None:
    assert evaluate_formula("a * 2", {"a": "1,5"}) == Decimal("3.0")


def test_allowed_functions() -> None:
    assert evaluate_formula("round(a * 1.15, 2)", {"a": 10}) == Decimal("11.50")
    assert evaluate_formula("min(a, b)", {"a": 5, "b": 2}) == Decimal("2")
    assert evaluate_formula("max(a, b, c)", {"a": 5, "b": 2, "c": 9}) == Decimal("9")


def test_unknown_variable_raises() -> None:
    try:
        evaluate_formula("a + b", {"a": 1})
    except UnknownVariableError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected UnknownVariableError")


def test_division_by_zero_raises() -> None:
    try:
        evaluate_formula("a / b", {"a": 1, "b": 0})
    except FormulaMathError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected FormulaMathError")


# ── safety: never eval, banned grammar rejected ──────────────────────────────


def test_rejects_attribute_access() -> None:
    for expr in ("a.__class__", "().__class__", "a ** 2", "a % 2", "[a]", "a and b", "foo(a)"):
        try:
            validate_formula(expr)
        except FormulaSyntaxError:
            continue
        raise AssertionError(f"expected rejection of {expr!r}")  # pragma: no cover


def test_rejects_dunder_call_payload() -> None:
    # A classic sandbox-escape shape must be rejected at parse time.
    try:
        evaluate_formula("__import__('os')", {})
    except FormulaSyntaxError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected FormulaSyntaxError")


def test_list_vars_excludes_function_names() -> None:
    assert list_formula_vars("round(area * factor, 2)") == ["area", "factor"]


# ── compute_formulas ─────────────────────────────────────────────────────────


def _fields() -> list[dict]:
    return validation.normalize_fields(
        [
            {"type": "number", "label": "Length", "key": "length"},
            {"type": "number", "label": "Width", "key": "width"},
            {"type": "formula", "label": "Area", "key": "area", "formula": "length * width"},
        ]
    )


def test_compute_fills_formula_value() -> None:
    out = compute_formulas(_fields(), {"length": 4, "width": 3})
    assert out["area"] == 12


def test_compute_blank_operand_as_zero() -> None:
    # width unfilled -> treated as 0 so the running total still resolves.
    out = compute_formulas(_fields(), {"length": 4})
    assert out["area"] == 0


def test_compute_blank_operand_left_blank_when_not_zero_mode() -> None:
    out = compute_formulas(_fields(), {"length": 4}, blank_as_zero=False)
    assert out["area"] is None


def test_compute_chained_formulas_resolve_in_dependency_order() -> None:
    fields = validation.normalize_fields(
        [
            {"type": "number", "label": "Base", "key": "base"},
            {"type": "formula", "label": "Doubled", "key": "doubled", "formula": "base * 2"},
            {"type": "formula", "label": "Plus ten", "key": "plus_ten", "formula": "doubled + 10"},
        ]
    )
    out = compute_formulas(fields, {"base": 5})
    assert out["doubled"] == 10
    assert out["plus_ten"] == 20


def test_compute_division_by_zero_yields_none_not_raise() -> None:
    fields = validation.normalize_fields(
        [
            {"type": "number", "label": "A", "key": "a"},
            {"type": "number", "label": "B", "key": "b"},
            {"type": "formula", "label": "Ratio", "key": "ratio", "formula": "a / b"},
        ]
    )
    out = compute_formulas(fields, {"a": 1, "b": 0})
    assert out["ratio"] is None


# ── template validation wiring ───────────────────────────────────────────────


def test_template_formula_unknown_ref_flagged() -> None:
    fields = validation.normalize_fields(
        [
            {"type": "number", "label": "Length", "key": "length"},
            {"type": "formula", "label": "Area", "key": "area", "formula": "length * missing"},
        ]
    )
    assert "formula_unknown_ref" in _codes(validation.validate_template_fields(fields))


def test_template_formula_self_reference_flagged() -> None:
    fields = validation.normalize_fields(
        [
            {"type": "number", "label": "N", "key": "n"},
            {"type": "formula", "label": "Loop", "key": "loop", "formula": "loop + n"},
        ]
    )
    assert "formula_self_reference" in _codes(validation.validate_template_fields(fields))


def test_template_formula_cycle_flagged() -> None:
    fields = validation.normalize_fields(
        [
            {"type": "formula", "label": "A", "key": "a", "formula": "b + 1"},
            {"type": "formula", "label": "B", "key": "b", "formula": "a + 1"},
        ]
    )
    assert "formula_cycle" in _codes(validation.validate_template_fields(fields))


def test_template_formula_missing_expr_flagged() -> None:
    fields = validation.normalize_fields(
        [
            {"type": "number", "label": "N", "key": "n"},
            {"type": "formula", "label": "Empty", "key": "empty"},
        ]
    )
    assert "formula_missing" in _codes(validation.validate_template_fields(fields))


def test_template_with_only_formula_has_no_fillable_field() -> None:
    # A form of a section + a formula has nothing a user can enter.
    fields = validation.normalize_fields(
        [
            {"type": "section", "label": "Totals"},
            {"type": "formula", "label": "Total", "key": "total", "formula": "1 + 1"},
        ]
    )
    assert "no_fillable_field" in _codes(validation.validate_template_fields(fields))


def test_valid_formula_template_passes() -> None:
    assert validation.validate_template_fields(_fields()) == []

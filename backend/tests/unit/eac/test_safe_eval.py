# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the safe formula evaluator (EAC-1.3 §3 / §4).

Covers:

* AST parsing for every operator and function whitelisted in FR-1.7.
* Rejection of dunder access and ``eval()`` / ``exec()`` calls.
* Unit-conversion helpers (MM_TO_M, M_TO_FT, KG_TO_T, ...).
* Variable-name extraction (used by the validator to check that every
  ``${variable_name}`` resolves).
* Hard execution-time cap (FR-1.7 — runaway expressions abort).
"""

from __future__ import annotations

import math
import time

import pytest

from app.modules.eac.engine.safe_eval import (
    FormulaSyntaxError,
    FormulaUnsafeError,
    collect_variable_names,
    evaluate_formula,
    parse_formula,
)

# ── Parse: 30 expressions across operators/functions ─────────────────────


@pytest.mark.parametrize(
    "expr",
    [
        # Arithmetic operators
        "1 + 2",
        "Volume - 0.5",
        "Length * Width",
        "Volume / 2",
        "5 % 3",
        "2 ** 3",
        "-Volume",
        "+Volume",
        # Comparison + boolean
        "Volume > 10",
        "Volume >= 10",
        "Volume < 10",
        "Volume <= 10",
        "Volume == 10",
        "Volume != 10",
        "(Volume > 0) and (Length > 0)",
        "(Volume > 0) or (Length > 0)",
        "not (Volume > 0)",
        # Function calls (FR-1.7 whitelist)
        "ABS(-5)",
        "MIN(1, 2, 3)",
        "MAX(1, 2, 3)",
        "SUM(1, 2, 3)",
        "AVG(1, 2, 3)",
        "ROUND(3.14159, 2)",
        "CEIL(2.3)",
        "FLOOR(2.7)",
        "SQRT(16)",
        # Unit conversions
        "MM_TO_M(2500)",
        "M_TO_FT(1.0)",
        "KG_TO_T(2500)",
        # String / logical
        "IF(Volume > 0, Volume, 0)",
        "CONCAT('a', 'b')",
        "UPPER('abc')",
    ],
)
def test_parse_formula_accepts_expression(expr: str) -> None:
    """Every whitelisted expression parses without raising."""
    parsed = parse_formula(expr)
    assert parsed is not None


# ── Reject dunder access (sandbox escape attempt) ────────────────────────


def test_parse_rejects_dunder_class_access() -> None:
    """Dunder attribute access must be rejected at parse time."""
    with pytest.raises((FormulaUnsafeError, FormulaSyntaxError)):
        # Either parse-time AST scan catches it, or eval-time simpleeval does.
        evaluate_formula("(1).__class__.__bases__", {})


# ── Reject eval()/exec() ─────────────────────────────────────────────────


def test_evaluate_rejects_eval_call() -> None:
    """An ``eval()`` call must be rejected — it's not in the whitelist."""
    with pytest.raises((FormulaUnsafeError, FormulaSyntaxError)):
        evaluate_formula("eval('1+2')", {})


def test_evaluate_rejects_exec_call() -> None:
    """An ``exec()`` call must be rejected."""
    with pytest.raises((FormulaUnsafeError, FormulaSyntaxError)):
        evaluate_formula("exec('print(1)')", {})


# ── Unit conversions (3 known-good) ──────────────────────────────────────


def test_mm_to_m_conversion() -> None:
    """MM_TO_M(2500) must equal 2.5."""
    assert evaluate_formula("MM_TO_M(2500)", {}) == 2.5


def test_m_to_ft_conversion() -> None:
    """M_TO_FT(1) must equal ≈ 3.28084."""
    result = evaluate_formula("M_TO_FT(1)", {})
    assert math.isclose(result, 3.28084, rel_tol=1e-5)


def test_kg_to_t_conversion() -> None:
    """KG_TO_T(2500) must equal 2.5."""
    assert evaluate_formula("KG_TO_T(2500)", {}) == 2.5


# ── Timeout ─────────────────────────────────────────────────────────────


def test_evaluate_aborts_on_runaway_expression() -> None:
    """A runaway expression (e.g. catastrophic exponent) aborts within 200 ms.

    ``simpleeval`` already caps power-of-power explosions; we additionally
    wrap evaluation in a wall-clock guard. The combined effect must keep
    pathological inputs sub-200 ms even when the formula tries to allocate
    megabytes of intermediate state.
    """
    start = time.monotonic()
    with pytest.raises((FormulaUnsafeError, FormulaSyntaxError, Exception)):
        # 9**9**9 produces an integer with ~370M digits — simpleeval rejects.
        evaluate_formula("9 ** 9 ** 9", {}, timeout_ms=100)
    elapsed = time.monotonic() - start
    assert elapsed < 0.2, f"runaway expression took {elapsed:.3f}s (cap 0.2s)"


# ── collect_variable_names ──────────────────────────────────────────────


def test_collect_variable_names_simple() -> None:
    """Basic identifier extraction works."""
    parsed = parse_formula("Volume * Density")
    names = collect_variable_names(parsed)
    assert names == {"Volume", "Density"}


def test_collect_variable_names_complex() -> None:
    """Names are extracted from a complex nested expression.

    Constants (123, 'hello'), function names (ABS, IF), and Python
    builtins (True/False/None) must NOT be returned. Only free variables
    that the executor will need to bind from the element row.
    """
    formula = "IF(Volume > MIN_VOLUME, ROUND(Volume * Density, 2), 0)"
    parsed = parse_formula(formula)
    names = collect_variable_names(parsed)
    assert names == {"Volume", "MIN_VOLUME", "Density"}


def test_collect_variable_names_excludes_function_names() -> None:
    """Function call targets (e.g. ``ABS``) are not free variables."""
    parsed = parse_formula("ABS(-5)")
    names = collect_variable_names(parsed)
    assert names == set()

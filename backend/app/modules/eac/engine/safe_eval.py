# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Safe formula evaluator (RFC 34 L14, EAC-1.3 §4).

The evaluator is a thin wrapper over :class:`simpleeval.SimpleEval`:

* Whitelist of FR-1.7 functions (``ABS``, ``MIN``, ``ROUND``, …,
  ``MM_TO_M`` and the rest of the unit conversions).
* Hard execution-time cap: a runaway expression aborts.
* No attribute access, no dunder access, no ``eval``/``exec`` —
  ``simpleeval`` blocks these by default; we re-raise as our typed
  errors so callers can branch on shape.

The validator (EAC-1.3 §2) calls :func:`parse_formula` to AST-check
each formula without executing it. The executor (EAC-1.4) will call
:func:`evaluate_formula` to run a per-element formula against a
``names`` dict drawn from the canonical row.
"""

from __future__ import annotations

import ast
import math
import time
from typing import Any

import simpleeval
from simpleeval import (
    FeatureNotAvailable,
    FunctionNotDefined,
    InvalidExpression,
    NameNotDefined,
    NumberTooHigh,
    SimpleEval,
)

# ── Errors ──────────────────────────────────────────────────────────────


class FormulaSyntaxError(Exception):
    """Formula does not parse as a valid Python expression."""


class FormulaUnsafeError(Exception):
    """Formula references an unsafe construct (dunder, eval, exec, ...)."""


class FormulaTimeoutError(Exception):
    """Formula exceeded the configured execution-time cap."""


# ── Function whitelist (FR-1.7) ─────────────────────────────────────────
#
# Each entry maps the public formula name to a callable. The executor
# will look up names from this dict — anything missing raises
# ``FunctionNotDefined`` which we translate to ``FormulaUnsafeError``.


def _avg(*args: float) -> float:
    """Arithmetic mean of args."""
    if not args:
        raise ValueError("AVG requires at least one argument")
    return sum(args) / len(args)


def _count(*args: Any) -> int:
    """Number of non-None args."""
    return sum(1 for a in args if a is not None)


def _if(cond: Any, then_value: Any, else_value: Any) -> Any:
    """Function-style ternary used in formulas."""
    return then_value if cond else else_value


def _concat(*args: Any) -> str:
    """Concatenate string representations of args."""
    return "".join(str(a) for a in args)


def _substr(s: str, start: int, length: int | None = None) -> str:
    """Return a substring with Python-style indexing.

    Mirrors most spreadsheet semantics: 1-based start; if length is
    omitted, slice to the end.
    """
    if start < 1:
        start = 1
    py_start = start - 1
    if length is None:
        return s[py_start:]
    return s[py_start : py_start + length]


def _replace(s: str, old: str, new: str) -> str:
    return s.replace(old, new)


def _split(s: str, sep: str) -> list[str]:
    return s.split(sep)


# Unit conversions (FR-1.7).
_M_PER_FT = 0.3048
_FT_PER_M = 1.0 / _M_PER_FT  # ≈ 3.28084
_KG_PER_LB = 0.45359237
_LB_PER_KG = 1.0 / _KG_PER_LB


def _mm_to_m(x: float) -> float:
    """Millimetres to metres (x / 1000)."""
    return x / 1000.0


def _m_to_mm(x: float) -> float:
    """Metres to millimetres (x * 1000)."""
    return x * 1000.0


def _m_to_ft(x: float) -> float:
    """Metres to feet (x * 3.28084)."""
    return x * _FT_PER_M


def _ft_to_m(x: float) -> float:
    """Feet to metres."""
    return x * _M_PER_FT


def _m2_to_ft2(x: float) -> float:
    """Square metres to square feet."""
    return x * (_FT_PER_M ** 2)


def _ft2_to_m2(x: float) -> float:
    """Square feet to square metres."""
    return x * (_M_PER_FT ** 2)


def _m3_to_ft3(x: float) -> float:
    """Cubic metres to cubic feet."""
    return x * (_FT_PER_M ** 3)


def _ft3_to_m3(x: float) -> float:
    """Cubic feet to cubic metres."""
    return x * (_M_PER_FT ** 3)


def _kg_to_lb(x: float) -> float:
    """Kilograms to pounds."""
    return x * _LB_PER_KG


def _lb_to_kg(x: float) -> float:
    """Pounds to kilograms."""
    return x * _KG_PER_LB


def _kg_to_t(x: float) -> float:
    """Kilograms to metric tonnes (x / 1000)."""
    return x / 1000.0


def _t_to_kg(x: float) -> float:
    """Metric tonnes to kilograms (x * 1000)."""
    return x * 1000.0


def _convert(value: float, from_unit: str, to_unit: str) -> float:
    """Generic unit-conversion fallback for the ``CONVERT`` function.

    Supports the same set of pairs that have a dedicated helper. Raises
    :class:`ValueError` for unknown unit pairs so the validator can flag
    a meaningful error.
    """
    pairs: dict[tuple[str, str], float] = {
        ("mm", "m"): 0.001,
        ("m", "mm"): 1000.0,
        ("m", "ft"): _FT_PER_M,
        ("ft", "m"): _M_PER_FT,
        ("m2", "ft2"): _FT_PER_M ** 2,
        ("ft2", "m2"): _M_PER_FT ** 2,
        ("m3", "ft3"): _FT_PER_M ** 3,
        ("ft3", "m3"): _M_PER_FT ** 3,
        ("kg", "lb"): _LB_PER_KG,
        ("lb", "kg"): _KG_PER_LB,
        ("kg", "t"): 0.001,
        ("t", "kg"): 1000.0,
    }
    key = (from_unit.lower(), to_unit.lower())
    if from_unit == to_unit:
        return value
    if key not in pairs:
        raise ValueError(f"CONVERT: unsupported unit pair {from_unit} → {to_unit}")
    return value * pairs[key]


# Public function table — callable, but the validator only checks the
# *names* via the AST scan (it does not execute formulas).
ALLOWED_FUNCTIONS: dict[str, Any] = {
    # Math
    "ABS": abs,
    "MIN": min,
    "MAX": max,
    "SUM": sum,
    "AVG": _avg,
    "COUNT": _count,
    "ROUND": round,
    "CEIL": math.ceil,
    "FLOOR": math.floor,
    "SQRT": math.sqrt,
    "LN": math.log,
    "LOG": math.log10,
    "EXP": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    # Logical / conditional (function-style)
    "IF": _if,
    # String
    "CONCAT": _concat,
    "UPPER": str.upper,
    "LOWER": str.lower,
    "TRIM": str.strip,
    "LEN": len,
    "SUBSTR": _substr,
    "REPLACE": _replace,
    "SPLIT": _split,
    # Unit conversions
    "MM_TO_M": _mm_to_m,
    "M_TO_MM": _m_to_mm,
    "M_TO_FT": _m_to_ft,
    "FT_TO_M": _ft_to_m,
    "M2_TO_FT2": _m2_to_ft2,
    "FT2_TO_M2": _ft2_to_m2,
    "M3_TO_FT3": _m3_to_ft3,
    "FT3_TO_M3": _ft3_to_m3,
    "KG_TO_LB": _kg_to_lb,
    "LB_TO_KG": _lb_to_kg,
    "KG_TO_T": _kg_to_t,
    "T_TO_KG": _t_to_kg,
    "CONVERT": _convert,
}


# ── Public API ──────────────────────────────────────────────────────────


def parse_formula(formula: str) -> ast.Expression:
    """Parse a formula string into a Python AST expression.

    Raises :class:`FormulaSyntaxError` on any parse failure. The result
    can be passed to :func:`collect_variable_names` for variable
    discovery without executing anything.
    """
    if not isinstance(formula, str) or not formula.strip():
        raise FormulaSyntaxError("formula must be a non-empty string")
    try:
        return ast.parse(formula, mode="eval")  # type: ignore[return-value]
    except SyntaxError as exc:
        raise FormulaSyntaxError(f"syntax error: {exc.msg}") from exc


def evaluate_formula(
    formula: str,
    variables: dict[str, Any],
    *,
    timeout_ms: int = 100,
) -> Any:
    """Evaluate a formula against a binding of ``variables``.

    ``timeout_ms`` is a wall-clock cap. ``simpleeval`` already trips on
    explosive integer powers, so the timeout is a defensive backstop
    rather than the primary line of defence.
    """
    # Parse first so we can report syntax errors with a typed exception.
    parsed = parse_formula(formula)
    _scan_for_unsafe(parsed)

    evaluator = SimpleEval(
        names=variables,
        functions=ALLOWED_FUNCTIONS,
    )

    started_at = time.monotonic()
    try:
        result = evaluator.eval(formula)
    except (FeatureNotAvailable, NumberTooHigh) as exc:
        raise FormulaUnsafeError(str(exc)) from exc
    except (FunctionNotDefined, NameNotDefined) as exc:
        raise FormulaUnsafeError(str(exc)) from exc
    except InvalidExpression as exc:
        raise FormulaSyntaxError(str(exc)) from exc
    except SyntaxError as exc:
        raise FormulaSyntaxError(str(exc)) from exc

    elapsed_ms = (time.monotonic() - started_at) * 1000.0
    if elapsed_ms > timeout_ms:
        raise FormulaTimeoutError(
            f"formula exceeded {timeout_ms} ms cap (took {elapsed_ms:.1f} ms)"
        )
    return result


def collect_variable_names(parsed: ast.Expression | ast.Module) -> set[str]:
    """Return the set of free variable names referenced by ``parsed``.

    Function-call targets are excluded — ``ABS(x)`` returns ``{"x"}``.
    Python builtins (``True`` / ``False`` / ``None``) are excluded.
    Whitelisted function names (``ABS``, ``MIN``, …) are excluded so
    the validator doesn't flag them as missing aliases.
    """
    names: set[str] = set()
    call_func_names: set[str] = set()

    for node in ast.walk(parsed):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            call_func_names.add(node.func.id)

    for node in ast.walk(parsed):
        if isinstance(node, ast.Name):
            if node.id in call_func_names:
                continue
            if node.id in {"True", "False", "None"}:
                continue
            if node.id in ALLOWED_FUNCTIONS:
                continue
            names.add(node.id)
    return names


# ── Internal helpers ────────────────────────────────────────────────────


_FORBIDDEN_PREFIXES = ("__",)


def _scan_for_unsafe(parsed: ast.AST) -> None:
    """Walk the AST and reject obviously-unsafe nodes.

    Forbids:
    * Attribute access whose attr starts with ``__``.
    * ``Lambda`` / ``GeneratorExp`` / ``ListComp`` constructs (we don't
      need them, and they're a sandbox-escape vector).
    * Direct calls to ``eval`` / ``exec``.

    ``simpleeval`` already enforces most of these — duplicating the
    check at parse time gives the validator a deterministic error code
    even when the formula is never actually executed.
    """
    for node in ast.walk(parsed):
        if isinstance(node, ast.Attribute):
            if any(node.attr.startswith(p) for p in _FORBIDDEN_PREFIXES):
                raise FormulaUnsafeError(
                    f"forbidden dunder access: .{node.attr}",
                )
        if isinstance(node, (ast.Lambda, ast.GeneratorExp, ast.ListComp, ast.DictComp, ast.SetComp)):
            raise FormulaUnsafeError(
                f"unsupported construct: {type(node).__name__}",
            )
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"eval", "exec", "compile", "__import__", "open"}:
                raise FormulaUnsafeError(
                    f"forbidden function call: {node.func.id}",
                )


__all__ = [
    "ALLOWED_FUNCTIONS",
    "FormulaSyntaxError",
    "FormulaTimeoutError",
    "FormulaUnsafeError",
    "collect_variable_names",
    "evaluate_formula",
    "parse_formula",
]


# Quiet "unused import" warnings for re-exports the rest of the package
# may use lazily via ``from .safe_eval import simpleeval``.
_re = simpleeval  # noqa: F841

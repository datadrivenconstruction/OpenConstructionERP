"""‌⁠‍Pure constraint evaluator for EAC requirements.

A single function that decides whether an actual value satisfies a
requirement's ``constraint_type`` + ``constraint_value`` pair. Used by
the validate-against-BIM-model endpoint and by the consistency gate.

The evaluator is deliberately string-first: ``constraint_value`` is
stored as text (Excel- and CSV-friendly), and the operator decides how
to coerce. ``range`` accepts ``"a..b" | "a-b" | "a,b" | "a;b"``.

Also exposes :func:`compute_deliverable_coverage` — a pure-function
roll-up of ISO 19650 EIR deliverable rows used by the matrix view.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Final

# Operators considered in the unified contract.
OPERATORS: Final[tuple[str, ...]] = (
    "equals",
    "not_equals",
    "min",
    "max",
    "range",
    "contains",
    "not_contains",
    "regex",
    "exists",
    "not_exists",
)

NUMERIC_OPERATORS: Final[frozenset[str]] = frozenset({"min", "max", "range"})
VALUE_OPTIONAL: Final[frozenset[str]] = frozenset({"exists", "not_exists"})

_RANGE_SPLIT_RE: Final = re.compile(r"\s*(?:\.\.|;|,|-)\s*")


@dataclass(frozen=True)
class EvalResult:
    """‌⁠‍Outcome of a single constraint check."""

    passed: bool
    reason: str  # human-readable; empty when passed cleanly


def _coerce_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_range(spec: str) -> tuple[float, float] | None:
    parts = [p for p in _RANGE_SPLIT_RE.split(spec.strip()) if p]
    if len(parts) != 2:
        return None
    lo = _coerce_float(parts[0])
    hi = _coerce_float(parts[1])
    if lo is None or hi is None:
        return None
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


def _norm(text: object) -> str:
    return "" if text is None else str(text).strip()


def evaluate(
    constraint_type: str,
    constraint_value: str,
    actual: object,
) -> EvalResult:
    """‌⁠‍Run one EAC constraint against an actual value.

    Returns ``EvalResult(passed, reason)``. A pass always has empty
    reason; a fail explains why so the caller can store it verbatim
    in ``RuleResult.message`` / SARIF.
    """

    op = (constraint_type or "equals").strip().lower()

    if op not in OPERATORS:
        return EvalResult(False, f"Unknown constraint type '{op}'")

    actual_str = _norm(actual)
    actual_present = actual is not None and actual_str != ""

    # Presence-only operators
    if op == "exists":
        if actual_present:
            return EvalResult(True, "")
        return EvalResult(False, "value is missing")
    if op == "not_exists":
        if actual_present:
            return EvalResult(False, f"value '{actual_str}' should not exist")
        return EvalResult(True, "")

    # All remaining operators need a constraint_value
    expected = (constraint_value or "").strip()
    if not expected:
        return EvalResult(False, "constraint_value is empty")

    if op == "equals":
        if actual_str.lower() == expected.lower():
            return EvalResult(True, "")
        return EvalResult(False, f"got '{actual_str}', expected '{expected}'")

    if op == "not_equals":
        if actual_str.lower() != expected.lower():
            return EvalResult(True, "")
        return EvalResult(False, f"value '{actual_str}' equals forbidden '{expected}'")

    if op == "contains":
        if expected.lower() in actual_str.lower():
            return EvalResult(True, "")
        return EvalResult(False, f"'{actual_str}' does not contain '{expected}'")

    if op == "not_contains":
        if expected.lower() not in actual_str.lower():
            return EvalResult(True, "")
        return EvalResult(False, f"'{actual_str}' contains forbidden '{expected}'")

    if op == "regex":
        try:
            pattern = re.compile(expected)
        except re.error as exc:
            return EvalResult(False, f"invalid regex: {exc}")
        if pattern.search(actual_str):
            return EvalResult(True, "")
        return EvalResult(False, f"'{actual_str}' does not match /{expected}/")

    # Numeric operators
    if op in NUMERIC_OPERATORS:
        actual_num = _coerce_float(actual)
        if actual_num is None:
            return EvalResult(
                False,
                f"non-numeric value '{actual_str}' for numeric constraint",
            )

        if op == "min":
            threshold = _coerce_float(expected)
            if threshold is None:
                return EvalResult(False, f"non-numeric threshold '{expected}'")
            if actual_num >= threshold:
                return EvalResult(True, "")
            return EvalResult(False, f"{actual_num} < min {threshold}")

        if op == "max":
            threshold = _coerce_float(expected)
            if threshold is None:
                return EvalResult(False, f"non-numeric threshold '{expected}'")
            if actual_num <= threshold:
                return EvalResult(True, "")
            return EvalResult(False, f"{actual_num} > max {threshold}")

        # op == "range"
        bounds = _parse_range(expected)
        if bounds is None:
            return EvalResult(
                False,
                f"range '{expected}' must look like 'min..max', 'min-max', or 'min,max'",
            )
        lo, hi = bounds
        if lo <= actual_num <= hi:
            return EvalResult(True, "")
        return EvalResult(False, f"{actual_num} outside [{lo}, {hi}]")

    # Should be unreachable thanks to the OPERATORS membership check.
    return EvalResult(False, f"Operator '{op}' not implemented")


# ── ISO 19650 EIR deliverable coverage ──────────────────────────────────────


def _deliverable_status(deliverable: Any) -> str:
    """Return the derived status of a deliverable row.

    Mirrors :pyattr:`RequirementDeliverable.status` but stays pure so
    plain dicts (e.g. test fixtures) and ORM rows can be mixed.
    """
    accepted = (
        deliverable.get("accepted_at") if isinstance(deliverable, dict) else getattr(deliverable, "accepted_at", None)
    )
    submitted = (
        deliverable.get("submitted_at") if isinstance(deliverable, dict) else getattr(deliverable, "submitted_at", None)
    )
    if accepted is not None:
        return "accepted"
    if submitted is not None:
        return "submitted"
    return "missing"


def _deliverable_type(deliverable: Any) -> str:
    if isinstance(deliverable, dict):
        return str(deliverable.get("deliverable_type") or "other")
    return str(getattr(deliverable, "deliverable_type", "other") or "other")


def compute_deliverable_coverage(
    deliverables: Iterable[Any],
    *,
    requirement_id: Any | None = None,
) -> dict[str, Any]:
    """Roll up a requirement's deliverable rows into a coverage summary.

    The ``coverage_pct`` is ``accepted / total * 100`` — i.e. how much
    of the EIR has been *signed off*. Submitted-but-not-accepted rows
    surface separately so the UI can flag "in review" tiles.

    Returns a plain ``dict`` (not a Pydantic model) so the evaluator
    stays pure and dependency-free; the router maps it to
    :class:`DeliverableCoverage` for the HTTP layer.
    """
    rows = list(deliverables)
    total = len(rows)

    if total == 0:
        return {
            "requirement_id": requirement_id,
            "total": 0,
            "submitted": 0,
            "accepted": 0,
            "missing": 0,
            "coverage_pct": 0.0,
            "by_type": {},
        }

    submitted = 0
    accepted = 0
    missing = 0
    by_type: dict[str, dict[str, int]] = {}

    for row in rows:
        dtype = _deliverable_type(row)
        status = _deliverable_status(row)

        bucket = by_type.setdefault(
            dtype,
            {"total": 0, "submitted": 0, "accepted": 0, "missing": 0},
        )
        bucket["total"] += 1

        if status == "accepted":
            accepted += 1
            bucket["accepted"] += 1
        elif status == "submitted":
            submitted += 1
            bucket["submitted"] += 1
        else:
            missing += 1
            bucket["missing"] += 1

    coverage_pct = round((accepted / total) * 100.0, 2) if total else 0.0

    return {
        "requirement_id": requirement_id,
        "total": total,
        "submitted": submitted,
        "accepted": accepted,
        "missing": missing,
        "coverage_pct": coverage_pct,
        "by_type": by_type,
    }

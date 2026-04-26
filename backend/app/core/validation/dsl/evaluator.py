# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""DSL evaluator — AST → :class:`ValidationRule` instance.

Given a :class:`~app.core.validation.dsl.parser.RuleDefinition` produced
by :func:`~app.core.validation.dsl.parser.parse_definition`, this module
synthesises a dynamic :class:`~app.core.validation.engine.ValidationRule`
subclass that the engine can dispatch over a
:class:`~app.core.validation.engine.ValidationContext`.

The evaluator is **explicitly not** a Python interpreter. It only knows
how to:

* dereference dotted paths against dicts (and the iteration variable
  introduced by ``forEach``);
* compare scalars with the operators the parser allowed
  (``==``, ``!=``, ``<``, ``<=``, ``>``, ``>=``, ``in``);
* combine booleans with ``and`` / ``or`` / ``not``;
* compute aggregates (``count``, ``sum``, ``avg``, ``min``, ``max``) over
  a homogeneous list scope.

There is no ``eval``, no attribute access, no name lookup outside the
explicit ``forEach`` variable, and no implicit type coercion beyond
treating ``int``/``float`` together for numeric ops.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.validation.dsl.parser import (
    Aggregation,
    Comparison,
    Expression,
    FieldRef,
    ForEachAssert,
    Literal,
    Logical,
    RuleDefinition,
    SingleAssert,
)
from app.core.validation.engine import (
    RuleResult,
    ValidationContext,
    ValidationRule,
)

logger = logging.getLogger(__name__)


# ── Errors ─────────────────────────────────────────────────────────────────


class DSLEvaluationError(Exception):
    """Raised when an AST cannot be evaluated against the given context.

    The dynamic rule wraps these into a single failing
    :class:`RuleResult` so a single bad definition cannot break the
    whole report.
    """

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


# ── Sentinel for "no value found" ──────────────────────────────────────────

_MISSING: Any = object()


# ── Core evaluation primitives ─────────────────────────────────────────────


def _resolve_path(
    bindings: dict[str, Any], path: tuple[str, ...],
) -> Any:
    """Walk a dotted path through ``bindings`` (dicts only — no attrs)."""
    if not path:
        return _MISSING
    head, *rest = path
    if head not in bindings:
        return _MISSING
    current: Any = bindings[head]
    for segment in rest:
        if isinstance(current, dict):
            if segment not in current:
                return _MISSING
            current = current[segment]
        else:
            # Refuse to traverse non-dict values — no attr access.
            return _MISSING
    return current


def _evaluate(expr: Expression, bindings: dict[str, Any]) -> Any:
    """Recursive AST walker."""
    if isinstance(expr, Literal):
        return expr.value
    if isinstance(expr, FieldRef):
        return _resolve_path(bindings, expr.path)
    if isinstance(expr, Comparison):
        return _evaluate_comparison(expr, bindings)
    if isinstance(expr, Logical):
        return _evaluate_logical(expr, bindings)
    if isinstance(expr, Aggregation):
        return _evaluate_aggregation(expr, bindings)
    raise DSLEvaluationError(
        f"Unknown AST node type: {type(expr).__name__}",
    )


def _coerce_for_compare(value: Any) -> Any:
    """Treat ``None``/``MISSING`` uniformly so missing fields don't crash."""
    if value is _MISSING:
        return None
    return value


def _evaluate_comparison(expr: Comparison, bindings: dict[str, Any]) -> bool:
    left = _coerce_for_compare(_evaluate(expr.left, bindings))
    right = _coerce_for_compare(_evaluate(expr.right, bindings))

    if expr.op == "in":
        if not isinstance(right, (list, tuple)):
            return False
        return left in right

    # Equality is total — works on any pair of scalars.
    if expr.op == "==":
        return left == right
    if expr.op == "!=":
        return left != right

    # Ordering — both sides must be numeric or both strings; missing
    # field on either side counts as "comparison fails".
    if left is None or right is None:
        return False

    try:
        if expr.op == "<":
            return left < right
        if expr.op == "<=":
            return left <= right
        if expr.op == ">":
            return left > right
        if expr.op == ">=":
            return left >= right
    except TypeError:
        # Mixed string/number — treat as failed comparison rather than
        # raising; the engine logs the calling rule for diagnostics.
        return False

    raise DSLEvaluationError(f"Unsupported comparison operator: {expr.op}")


def _evaluate_logical(expr: Logical, bindings: dict[str, Any]) -> bool:
    if expr.op == "not":
        return not bool(_evaluate(expr.operands[0], bindings))
    if expr.op == "and":
        return all(bool(_evaluate(operand, bindings)) for operand in expr.operands)
    if expr.op == "or":
        return any(bool(_evaluate(operand, bindings)) for operand in expr.operands)
    raise DSLEvaluationError(f"Unsupported logical operator: {expr.op}")


def _evaluate_aggregation(expr: Aggregation, bindings: dict[str, Any]) -> Any:
    items = bindings.get("__scope_items__")
    if not isinstance(items, list):
        raise DSLEvaluationError(
            "Aggregations require a list scope. Use forEach or set scope to a list.",
        )

    iter_var = bindings.get("__iter_var__")
    scope_leaf = bindings.get("__scope_leaf__")

    def _per_item(item: Any) -> tuple[Any, bool]:
        """Resolve ``expr.field`` against a single iteration item.

        Recognised field-reference shapes:

        * ``position.quantity`` — first segment is the iteration variable
          (e.g. ``forEach: position``); strip it and walk the remainder
          off ``item``.
        * ``positions`` (matching the scope leaf) — degenerate case;
          treat as "the item itself" so users can write ``count: positions``
          for "count of all positions in scope".
        * ``quantity`` — bare leaf; walk straight off ``item``.
        * In single-assert mode (no explicit ``forEach``), the first
          path segment is treated as a placeholder iterator and
          stripped — so ``sum: p.amount`` works without requiring the
          author to introduce a forEach block just for the aggregator.

        Returns ``(value, refers_to_whole_item)`` so callers can branch
        without re-checking the path shape.
        """
        assert expr.field is not None
        path = expr.field.path
        if iter_var and path and path[0] == iter_var:
            path = path[1:]
        elif scope_leaf and path == (scope_leaf,):
            return item, True
        elif iter_var is None and len(path) >= 2:
            # Single-assert mode: strip the placeholder iterator so the
            # user can write ``sum: p.amount`` against a list scope.
            path = path[1:]
        if not path:
            return item, True
        return _resolve_path({"__item__": item}, ("__item__", *path)), False

    if expr.kind == "count":
        if expr.field is None:
            return len(items)
        # If the field path resolves to the whole item (degenerate case
        # explained above), behave like ``count`` with no field — i.e.
        # count every item in scope. Otherwise count items where the
        # resolved value is truthy.
        if expr.field.path == (scope_leaf,) and scope_leaf is not None:
            return len(items)
        return sum(1 for item in items if _truthy_value(_per_item(item)[0]))

    if expr.field is None:
        raise DSLEvaluationError(f"'{expr.kind}' requires a field reference.")

    values = [_per_item(item)[0] for item in items]
    numeric: list[float] = []
    for v in values:
        if v is _MISSING or v is None:
            continue
        try:
            numeric.append(float(v))
        except (TypeError, ValueError):
            continue

    if expr.kind == "sum":
        return sum(numeric)
    if expr.kind == "avg":
        return (sum(numeric) / len(numeric)) if numeric else 0.0
    if expr.kind == "min":
        return min(numeric) if numeric else None
    if expr.kind == "max":
        return max(numeric) if numeric else None
    raise DSLEvaluationError(f"Unsupported aggregation: {expr.kind}")


def _truthy_value(value: Any) -> bool:
    if value is _MISSING or value is None:
        return False
    return bool(value)


# ── Scope resolution ───────────────────────────────────────────────────────


def _resolve_scope(scope: str, data: Any) -> Any:
    """Walk ``scope`` through the validation context's data.

    ``"data"`` (the default) returns the raw ``data`` object. Any other
    dotted path walks dicts. Returns :data:`_MISSING` if the path does
    not resolve.
    """
    if scope in ("", "data"):
        return data

    if not isinstance(data, dict):
        return _MISSING

    parts = scope.split(".")
    current: Any = data
    for segment in parts:
        if segment == "data":
            continue
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            return _MISSING
    return current


# ── Compilation ────────────────────────────────────────────────────────────


def compile_rule(definition: RuleDefinition) -> ValidationRule:
    """Build a runtime :class:`ValidationRule` instance from a definition.

    The returned object is a fresh class per call so each compiled rule
    has its own ``rule_id`` / ``name`` class attributes (the engine reads
    them off ``self``, but keeping them on the class mirrors the
    hand-coded rules in :mod:`app.core.validation.rules`).
    """

    body = definition.body

    class CompiledDSLRule(ValidationRule):
        rule_id = definition.rule_id
        name = definition.name
        standard = definition.standard
        severity = definition.severity
        category = definition.category
        description = definition.description

        async def validate(self, context: ValidationContext) -> list[RuleResult]:
            try:
                return _run(definition, body, context, self)
            except DSLEvaluationError as exc:
                logger.warning(
                    "Compliance DSL rule %s failed during evaluation: %s",
                    self.rule_id,
                    exc,
                )
                return [
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=self.severity,
                        category=self.category,
                        passed=False,
                        message=f"Rule could not be evaluated: {exc}",
                        details={"error": "dsl_evaluation_error", **exc.details},
                    )
                ]

    return CompiledDSLRule()


def _run(
    definition: RuleDefinition,
    body: ForEachAssert | SingleAssert,
    context: ValidationContext,
    rule: ValidationRule,
) -> list[RuleResult]:
    scope_value = _resolve_scope(definition.scope, context.data)

    if isinstance(body, ForEachAssert):
        if scope_value is _MISSING:
            return [
                RuleResult(
                    rule_id=rule.rule_id,
                    rule_name=rule.name,
                    severity=rule.severity,
                    category=rule.category,
                    passed=True,
                    message="No data in scope to validate.",
                )
            ]
        if not isinstance(scope_value, list):
            raise DSLEvaluationError(
                f"forEach requires the scope '{definition.scope}' to resolve to a list, "
                f"got {type(scope_value).__name__}.",
            )

        results: list[RuleResult] = []
        any_failure = False
        scope_leaf = definition.scope.split(".")[-1] if definition.scope else None
        for index, item in enumerate(scope_value):
            bindings = {
                body.iter_var: item,
                "__scope_items__": scope_value,
                "__iter_var__": body.iter_var,
                "__scope_leaf__": scope_leaf,
            }
            try:
                outcome = bool(_evaluate(body.predicate, bindings))
            except DSLEvaluationError:
                raise
            if not outcome:
                any_failure = True
                element_ref = (
                    item.get("id") if isinstance(item, dict) else None
                )
                results.append(
                    RuleResult(
                        rule_id=rule.rule_id,
                        rule_name=rule.name,
                        severity=rule.severity,
                        category=rule.category,
                        passed=False,
                        message=_failure_message(definition, item, index),
                        element_ref=element_ref,
                        details={"index": index},
                    )
                )

        if not any_failure:
            results.append(
                RuleResult(
                    rule_id=rule.rule_id,
                    rule_name=rule.name,
                    severity=rule.severity,
                    category=rule.category,
                    passed=True,
                    message="All items in scope passed.",
                    details={"checked": len(scope_value)},
                )
            )
        return results

    # Single assert — evaluate once over the resolved scope.
    scope_leaf = definition.scope.split(".")[-1] if definition.scope else None
    bindings: dict[str, Any] = {
        "data": context.data,
        "__scope_leaf__": scope_leaf,
    }
    if isinstance(scope_value, dict):
        bindings.update(scope_value)
        # Also expose the scope under its leaf-name so the user can
        # write ``boq.total > 0`` against ``scope: boq``.
        if scope_leaf:
            bindings[scope_leaf] = scope_value
    elif isinstance(scope_value, list):
        bindings["__scope_items__"] = scope_value
        if scope_leaf:
            bindings[scope_leaf] = scope_value
    elif scope_value is not _MISSING and scope_leaf:
        bindings[scope_leaf] = scope_value

    outcome = bool(_evaluate(body.predicate, bindings))
    return [
        RuleResult(
            rule_id=rule.rule_id,
            rule_name=rule.name,
            severity=rule.severity,
            category=rule.category,
            passed=outcome,
            message=(
                "Assertion passed."
                if outcome
                else f"Assertion failed for rule '{rule.rule_id}'."
            ),
        )
    ]


def _failure_message(
    definition: RuleDefinition, item: Any, index: int,
) -> str:
    """Compose a per-item failure message.

    Tries to lift a stable identifier (``ordinal``, ``id``) off the item
    so the user can locate it in the source data; falls back to the
    iteration index.
    """
    if isinstance(item, dict):
        for key in ("ordinal", "id", "code", "name"):
            value = item.get(key)
            if value:
                return (
                    f"Rule '{definition.rule_id}' failed for "
                    f"{key}={value}"
                )
    return f"Rule '{definition.rule_id}' failed at index {index}"


__all__ = [
    "DSLEvaluationError",
    "compile_rule",
]

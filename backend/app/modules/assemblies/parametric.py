# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Parametric assembly evaluation (Issue #365).

An assembly can carry named PARAMETERS and give each child line a quantity
FORMULA over those parameters, so one template drives many priced positions
(``rebar_kg = wall_area * rebar_ratio``). Three parameter kinds:

* ``input``     - a value the estimator enters (with a default).
* ``constant``  - a fixed value baked into the template.
* ``calculated``- a formula over other parameters (``area = length * height``).

This module is the pure, database-free brain: it validates the parameter
graph (unique names, resolvable references, no cycles), resolves parameter
values in dependency order, and expands each component's quantity formula.
It REUSES the shared #347 allow-listed-AST + Decimal engine
(:mod:`app.modules.boq.quantity_formula`) - there is no second evaluator -
so ``+ - * / ( )`` and ``round`` / ``min`` / ``max`` behave identically to a
per-element BOQ formula and every quantity stays exact.

Nothing here touches SQLAlchemy or FastAPI; the service layer maps ORM rows
to the plain dicts these functions consume and turns :class:`ParamError`
into the API response.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.modules.boq.quantity_formula import (
    FormulaMathError,
    FormulaSyntaxError,
    UnknownVariableError,
    evaluate_formula,
    list_formula_vars,
    normalize_var_name,
    validate_formula,
)

PARAM_KINDS = ("input", "calculated", "constant")


@dataclass(frozen=True)
class ParamError:
    """A single structured problem with a parameter or a component formula."""

    scope: str  # "parameter" | "component"
    name: str  # offending parameter name / component ref
    code: str  # empty_name | duplicate | invalid_value | missing_formula
    #            | syntax | invalid_ref | cycle | div_by_zero
    message: str

    def as_dict(self) -> dict[str, str]:
        """Return the JSON-friendly form the API surfaces."""
        return {"scope": self.scope, "name": self.name, "code": self.code, "message": self.message}


@dataclass(frozen=True)
class ComputedLine:
    """One expanded child line: its formula-computed and static quantities."""

    component_id: str | None
    description: str
    computed_quantity: Decimal
    static_quantity: Decimal
    has_formula: bool


@dataclass(frozen=True)
class ExpansionResult:
    """The outcome of expanding an assembly at a set of parameter values."""

    resolved_parameters: dict[str, Decimal]
    lines: list[ComputedLine]
    errors: list[ParamError]


def _norm(raw: Any) -> str:
    """Normalise a parameter name to a formula identifier (may be empty)."""
    return normalize_var_name(raw)


def _to_decimal(value: Any) -> Decimal | None:
    """Best-effort Decimal coercion; ``None`` when the value is not numeric."""
    if value is None or isinstance(value, bool):
        return None
    try:
        dec = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    return dec if dec.is_finite() else None


def _kind(param: dict[str, Any]) -> str:
    return str(param.get("kind") or "input")


def _analyse(
    parameters: list[dict[str, Any]],
) -> tuple[list[ParamError], list[str], dict[str, dict[str, Any]]]:
    """Static-check the parameter set.

    Returns ``(errors, eval_order, by_name)`` where ``eval_order`` is the
    dependency-first order of the ``calculated`` parameters (empty when a
    structural error such as a cycle makes ordering impossible) and
    ``by_name`` maps each normalised name to its (name-augmented) definition.
    """
    errors: list[ParamError] = []
    by_name: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()

    for param in parameters:
        raw_name = param.get("name", "")
        name = _norm(raw_name)
        kind = _kind(param)
        if not name:
            errors.append(ParamError("parameter", str(raw_name), "empty_name", "Parameter name is empty or invalid."))
            continue
        if kind not in PARAM_KINDS:
            errors.append(ParamError("parameter", name, "invalid_value", f"Unknown parameter kind: {kind!r}."))
            continue
        if name in seen:
            errors.append(ParamError("parameter", name, "duplicate", f"Duplicate parameter name: {name!r}."))
            continue
        seen.add(name)
        by_name[name] = {**param, "_name": name, "_kind": kind}

    declared = set(by_name)
    calc_names = {n for n, p in by_name.items() if p["_kind"] == "calculated"}

    # Per-parameter formula/value checks.
    for name in list(by_name):
        param = by_name[name]
        kind = param["_kind"]
        if kind == "calculated":
            formula = param.get("formula") or ""
            if not str(formula).strip():
                errors.append(
                    ParamError("parameter", name, "missing_formula", "A calculated parameter needs a formula.")
                )
                continue
            try:
                validate_formula(formula)
            except FormulaSyntaxError as exc:
                errors.append(ParamError("parameter", name, "syntax", str(exc)))
                continue
            for ref in list_formula_vars(formula):
                if ref not in declared:
                    errors.append(
                        ParamError(
                            "parameter",
                            name,
                            "invalid_ref",
                            f"Formula references undeclared parameter {ref!r}.",
                        )
                    )
        else:  # input / constant must hold a finite number
            if _to_decimal(param.get("value")) is None:
                errors.append(
                    ParamError("parameter", name, "invalid_value", f"Parameter {name!r} needs a numeric value.")
                )

    # Cycle detection over the calculated sub-graph (Kahn's algorithm).
    deps: dict[str, set[str]] = {}
    for name in calc_names:
        formula = by_name[name].get("formula") or ""
        try:
            refs = set(list_formula_vars(formula))
        except FormulaSyntaxError:
            refs = set()
        deps[name] = {r for r in refs if r in calc_names}

    dependents: dict[str, set[str]] = defaultdict(set)
    for node, node_deps in deps.items():
        for dep in node_deps:
            dependents[dep].add(node)

    remaining = {n: set(d) for n, d in deps.items()}
    queue = deque(sorted(n for n, d in remaining.items() if not d))
    order: list[str] = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for dependent in sorted(dependents[node]):
            remaining[dependent].discard(node)
            if not remaining[dependent]:
                queue.append(dependent)

    cyclic = sorted(calc_names - set(order))
    if cyclic:
        joined = ", ".join(cyclic)
        for name in cyclic:
            errors.append(ParamError("parameter", name, "cycle", f"Calculated parameters form a cycle: {joined}."))
        order = []

    return errors, order, by_name


def validate_parameter_graph(parameters: list[dict[str, Any]]) -> list[ParamError]:
    """Return every structural problem in the parameter set (empty when clean)."""
    errors, _order, _by_name = _analyse(parameters)
    return errors


def resolve_parameters(
    parameters: list[dict[str, Any]],
    overrides: dict[str, Any] | None = None,
) -> tuple[dict[str, Decimal], list[ParamError]]:
    """Resolve every parameter to a Decimal at the given input overrides.

    Inputs take their override (by normalised name) else their stored default;
    constants take their stored value; calculated parameters are evaluated in
    dependency order. On any structural error the resolved map is returned as
    far as it got, alongside the errors.
    """
    errors, order, by_name = _analyse(parameters)
    scope: dict[str, Decimal] = {}
    override_map = {_norm(k): v for k, v in (overrides or {}).items()}

    # Seed inputs and constants.
    for name, param in by_name.items():
        kind = param["_kind"]
        if kind == "input":
            raw = override_map.get(name, param.get("value"))
            value = _to_decimal(raw)
            if value is None:
                value = _to_decimal(param.get("value")) or Decimal(0)
            scope[name] = value
        elif kind == "constant":
            value = _to_decimal(param.get("value"))
            if value is not None:
                scope[name] = value

    if any(e.code in ("cycle", "syntax", "missing_formula") for e in errors):
        return scope, errors

    # Evaluate calculated parameters in dependency-first order.
    for name in order:
        formula = by_name[name].get("formula") or ""
        try:
            scope[name] = evaluate_formula(formula, scope)
        except FormulaMathError as exc:
            errors.append(ParamError("parameter", name, "div_by_zero", str(exc)))
        except UnknownVariableError as exc:
            errors.append(ParamError("parameter", name, "invalid_ref", str(exc)))
        except FormulaSyntaxError as exc:
            errors.append(ParamError("parameter", name, "syntax", str(exc)))

    return scope, errors


def expand_assembly(
    parameters: list[dict[str, Any]],
    components: list[dict[str, Any]],
    overrides: dict[str, Any] | None = None,
) -> ExpansionResult:
    """Resolve parameters then compute every component's quantity.

    A component with a ``quantity_formula`` has its quantity computed against
    the resolved parameters; without one it keeps its static ``quantity``.
    Component-level formula errors are collected (scope ``component``) and that
    line falls back to its static quantity so a preview still renders.
    """
    scope, errors = resolve_parameters(parameters, overrides)
    lines: list[ComputedLine] = []

    for comp in components:
        comp_id = comp.get("id")
        ref = str(comp_id) if comp_id is not None else str(comp.get("description") or "")
        static_qty = _to_decimal(comp.get("quantity")) or Decimal(0)
        formula = comp.get("quantity_formula")
        has_formula = bool(formula and str(formula).strip())
        computed = static_qty
        if has_formula:
            try:
                computed = evaluate_formula(str(formula), scope)
            except FormulaSyntaxError as exc:
                errors.append(ParamError("component", ref, "syntax", str(exc)))
                computed = static_qty
            except UnknownVariableError as exc:
                errors.append(ParamError("component", ref, "invalid_ref", str(exc)))
                computed = static_qty
            except FormulaMathError as exc:
                errors.append(ParamError("component", ref, "div_by_zero", str(exc)))
                computed = static_qty
        lines.append(
            ComputedLine(
                component_id=str(comp_id) if comp_id is not None else None,
                description=str(comp.get("description") or ""),
                computed_quantity=computed,
                static_quantity=static_qty,
                has_formula=has_formula,
            )
        )

    return ExpansionResult(resolved_parameters=scope, lines=lines, errors=errors)

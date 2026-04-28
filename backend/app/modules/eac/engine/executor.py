# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rule executor for EAC v2 (RFC 35 §1.6 EAC-1.4).

Runs a parsed :class:`EacRuleDefinition` against a sequence of canonical
element rows (dicts that mirror the canonical Parquet schema produced
by the DDC cad2data pipeline — never IFC bytes).

This is the MVP execution engine that powers the ``/runs:dry-run`` and
``/runs`` endpoints. It is intentionally Python-only and does not yet
delegate to DuckDB: the planner already emits a SQL plan for the future
columnar path, but for the volumes the UI cares about (≤10k elements
per ruleset) walking the rule tree in Python is fast enough and removes
DuckDB from the test surface.

Output modes covered (FR-1.6):

* ``boolean``  — per-element pass/fail; ``passed`` count drives the run.
* ``issue``    — every selected element with a failing predicate emits
  an :class:`IssueResult` rendered from ``issue_template``.
* ``aggregate`` — single numeric scalar produced by ``formula`` over
  the matched element set (``SUM``/``AVG``/``COUNT``/``MIN``/``MAX``).

``clash`` mode is intentionally deferred; it requires a geometry kernel
and is tracked as a separate ticket. Callers receive a clear
:class:`UnsupportedOutputModeError` rather than a silent miss.

The executor never persists. Persistence (``EacRun``, ``EacRunResultItem``)
is the responsibility of the service layer that wraps this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.modules.eac.engine.safe_eval import (
    FormulaSyntaxError,
    FormulaTimeoutError,
    FormulaUnsafeError,
    evaluate_formula,
)
from app.modules.eac.schemas import (
    AliasAttributeRef,
    AndPredicate,
    AndSelector,
    AttributeRef,
    BetweenConstraint,
    CategorySelector,
    ClassificationCodeSelector,
    Constraint,
    ContainsConstraint,
    DisciplineSelector,
    EacRuleDefinition,
    EndsWithConstraint,
    EntitySelector,
    EqConstraint,
    ExactAttributeRef,
    ExistsConstraint,
    FamilySelector,
    GeometryFilterSelector,
    GtConstraint,
    GteConstraint,
    IfcClassSelector,
    InConstraint,
    IsBooleanConstraint,
    IsDateConstraint,
    IsEmptyConstraint,
    IsNotEmptyConstraint,
    IsNotNullConstraint,
    IsNullConstraint,
    IsNumericConstraint,
    LevelSelector,
    LtConstraint,
    LteConstraint,
    MatchesConstraint,
    NamedGroupSelector,
    NeqConstraint,
    NotBetweenConstraint,
    NotContainsConstraint,
    NotExistsConstraint,
    NotInConstraint,
    NotMatchesConstraint,
    NotPredicate,
    NotSelector,
    OrPredicate,
    OrSelector,
    Predicate,
    PsetsPresentSelector,
    RegexAttributeRef,
    StartsWithConstraint,
    TripletPredicate,
    TypeSelector,
)

# ── Errors ──────────────────────────────────────────────────────────────


class UnsupportedOutputModeError(Exception):
    """Raised when a rule's ``output_mode`` is not yet implemented (e.g. clash)."""


class ExecutionError(Exception):
    """Raised on a fatal failure inside the executor (formula crash, etc.)."""


# ── Sentinel for "attribute not present on element" ────────────────────


class _Missing:
    """Sentinel class. Distinguishes ``None`` (an explicit value) from absence."""

    _instance: _Missing | None = None

    def __new__(cls) -> _Missing:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<MISSING>"

    def __bool__(self) -> bool:
        return False


MISSING = _Missing()


# ── Public dataclasses ──────────────────────────────────────────────────


@dataclass(frozen=True)
class ElementResult:
    """Per-element verdict for ``boolean`` mode.

    ``attribute_snapshot`` holds the resolved values of every attribute
    referenced by the predicate tree at evaluation time, for audit /
    later inspection in the run-detail UI.
    """

    element_id: str
    passed: bool
    attribute_snapshot: dict[str, Any]
    error: str | None = None


@dataclass(frozen=True)
class IssueResult:
    """Per-element issue for ``issue`` mode."""

    element_id: str
    title: str
    description: str | None
    topic_type: str
    priority: str
    stage: str | None
    labels: list[str]
    attribute_snapshot: dict[str, Any]


@dataclass(frozen=True)
class AggregateResult:
    """Single scalar for ``aggregate`` mode."""

    value: Any
    result_unit: str | None
    elements_evaluated: int


@dataclass(frozen=True)
class ExecutionResult:
    """Top-level executor output. Exactly one of ``boolean_results`` /
    ``issue_results`` / ``aggregate_result`` is populated."""

    output_mode: str
    elements_evaluated: int
    elements_matched: int
    elements_passed: int
    boolean_results: list[ElementResult] = field(default_factory=list)
    issue_results: list[IssueResult] = field(default_factory=list)
    aggregate_result: AggregateResult | None = None
    errors: list[str] = field(default_factory=list)


# ── Public entry point ─────────────────────────────────────────────────


def execute_rule(
    rule: EacRuleDefinition,
    elements: list[dict[str, Any]],
    *,
    formula_timeout_ms: int = 100,
) -> ExecutionResult:
    """Run ``rule`` against ``elements`` and return an :class:`ExecutionResult`.

    Each element in ``elements`` should be a dict shaped like the
    canonical row produced by ``BIMElement.to_canonical_dict()``:

    .. code-block:: python

        {
            "stable_id": "wall_001",
            "element_type": "Wall",          # used for category / ifc_class
            "ifc_class": "IfcWall",          # optional override of element_type
            "name": "Exterior wall",
            "level": "Level 1",              # storey alias
            "discipline": "ARC",
            "properties": {...},             # flat or nested by Pset
            "quantities": {                   # area / volume / length in metric
                "area_m2": 37.5,
                "volume_m3": 9.0,
                "length_m": 12.5,
            },
        }

    The function never raises for per-element failures (timeout, missing
    attribute) — those are surfaced via :class:`ElementResult.error` so a
    single bad element doesn't poison the whole run. It *does* raise
    :class:`UnsupportedOutputModeError` for ``clash`` mode and
    :class:`ExecutionError` for malformed input.
    """
    if rule.output_mode == "clash":
        raise UnsupportedOutputModeError(
            "clash output mode requires the geometry kernel — see RFC 35 §1.6.4"
        )

    # 1. Selector pass — filter to candidate elements.
    matched = [e for e in elements if _matches_selector(e, rule.selector)]

    # 2. Predicate pass (if any) — for boolean / issue modes we need
    #    a per-element verdict. For aggregate mode the predicate is
    #    optional and acts as an additional filter.
    if rule.output_mode == "aggregate":
        return _run_aggregate(rule, elements, matched, timeout_ms=formula_timeout_ms)

    if rule.output_mode == "issue":
        return _run_issue(rule, elements, matched)

    # boolean
    return _run_boolean(rule, elements, matched)


# ── Mode runners ────────────────────────────────────────────────────────


def _run_boolean(
    rule: EacRuleDefinition,
    all_elements: list[dict[str, Any]],
    matched: list[dict[str, Any]],
) -> ExecutionResult:
    """Evaluate predicate per matched element; produce ElementResult list."""
    results: list[ElementResult] = []
    passed = 0
    for elem in matched:
        snapshot: dict[str, Any] = {}
        verdict = True
        if rule.predicate is not None:
            try:
                verdict = _eval_predicate(elem, rule.predicate, snapshot)
            except Exception as exc:  # pragma: no cover - defensive
                results.append(
                    ElementResult(
                        element_id=str(elem.get("stable_id") or elem.get("id") or ""),
                        passed=False,
                        attribute_snapshot=snapshot,
                        error=str(exc),
                    )
                )
                continue
        if verdict:
            passed += 1
        results.append(
            ElementResult(
                element_id=str(elem.get("stable_id") or elem.get("id") or ""),
                passed=verdict,
                attribute_snapshot=snapshot,
            )
        )

    return ExecutionResult(
        output_mode="boolean",
        elements_evaluated=len(all_elements),
        elements_matched=len(matched),
        elements_passed=passed,
        boolean_results=results,
    )


def _run_issue(
    rule: EacRuleDefinition,
    all_elements: list[dict[str, Any]],
    matched: list[dict[str, Any]],
) -> ExecutionResult:
    """Render an IssueResult for every matched element that fails the predicate."""
    if rule.issue_template is None:
        raise ExecutionError(
            "rule.output_mode='issue' requires issue_template to be set"
        )
    template = rule.issue_template

    issues: list[IssueResult] = []
    passed = 0
    errors: list[str] = []
    for elem in matched:
        snapshot: dict[str, Any] = {}
        verdict = True
        if rule.predicate is not None:
            try:
                verdict = _eval_predicate(elem, rule.predicate, snapshot)
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(f"{elem.get('stable_id')}: {exc}")
                continue
        if verdict:
            passed += 1
            continue
        issues.append(
            IssueResult(
                element_id=str(elem.get("stable_id") or elem.get("id") or ""),
                title=_render_template(template.title, elem, snapshot),
                description=(
                    _render_template(template.description, elem, snapshot)
                    if template.description
                    else None
                ),
                topic_type=template.topic_type,
                priority=template.priority,
                stage=template.stage,
                labels=list(template.labels),
                attribute_snapshot=snapshot,
            )
        )

    return ExecutionResult(
        output_mode="issue",
        elements_evaluated=len(all_elements),
        elements_matched=len(matched),
        elements_passed=passed,
        issue_results=issues,
        errors=errors,
    )


def _run_aggregate(
    rule: EacRuleDefinition,
    all_elements: list[dict[str, Any]],
    matched: list[dict[str, Any]],
    *,
    timeout_ms: int,
) -> ExecutionResult:
    """Run formula across the matched set. Predicate, if present, narrows the set."""
    if rule.formula is None:
        raise ExecutionError(
            "rule.output_mode='aggregate' requires formula to be set"
        )

    qualifying = matched
    if rule.predicate is not None:
        qualifying = [
            e for e in matched if _eval_predicate(e, rule.predicate, {})
        ]

    # Aggregate-mode formulas operate on numeric arrays. Bind common
    # canonical quantity names to lists; the formula whitelist exposes
    # SUM/AVG/COUNT/MIN/MAX so an expression like ``SUM(volume_m3)``
    # collapses the list to a scalar.
    bindings: dict[str, list[Any]] = _build_aggregate_bindings(
        qualifying, formula=rule.formula
    )

    try:
        value = evaluate_formula(
            rule.formula,
            variables=bindings,
            timeout_ms=timeout_ms,
        )
    except (FormulaSyntaxError, FormulaUnsafeError) as exc:
        raise ExecutionError(f"formula error: {exc}") from exc
    except FormulaTimeoutError as exc:
        raise ExecutionError(f"formula timed out: {exc}") from exc

    return ExecutionResult(
        output_mode="aggregate",
        elements_evaluated=len(all_elements),
        elements_matched=len(matched),
        elements_passed=len(qualifying),
        aggregate_result=AggregateResult(
            value=value,
            result_unit=rule.result_unit,
            elements_evaluated=len(qualifying),
        ),
    )


# ── Selector evaluation ────────────────────────────────────────────────


def _matches_selector(elem: dict[str, Any], sel: EntitySelector) -> bool:
    """Walk the selector tree; return True iff ``elem`` matches."""
    # Combinators first.
    if isinstance(sel, AndSelector):
        return all(_matches_selector(elem, child) for child in sel.children)
    if isinstance(sel, OrSelector):
        return any(_matches_selector(elem, child) for child in sel.children)
    if isinstance(sel, NotSelector):
        return not _matches_selector(elem, sel.child)

    # Leaves.
    if isinstance(sel, CategorySelector):
        return _ci_in(elem.get("element_type") or elem.get("category"), sel.values)
    if isinstance(sel, IfcClassSelector):
        return _ci_in(elem.get("ifc_class") or elem.get("element_type"), sel.values)
    if isinstance(sel, FamilySelector):
        return _ci_in(_family_of(elem), sel.values)
    if isinstance(sel, TypeSelector):
        return _ci_in(_type_of(elem), sel.values)
    if isinstance(sel, LevelSelector):
        return _ci_in(elem.get("level") or elem.get("storey"), sel.values)
    if isinstance(sel, DisciplineSelector):
        return _ci_in(elem.get("discipline"), sel.values)
    if isinstance(sel, ClassificationCodeSelector):
        codes = _classification_codes(elem, system=sel.system)
        return any(v in codes for v in sel.values)
    if isinstance(sel, PsetsPresentSelector):
        psets = _present_psets(elem)
        return all(v in psets for v in sel.values)
    if isinstance(sel, NamedGroupSelector):
        groups = _named_groups(elem)
        return any(v in groups for v in sel.values)
    if isinstance(sel, GeometryFilterSelector):
        return _passes_geometry_filter(elem, sel)

    raise ExecutionError(f"unknown selector kind: {type(sel).__name__}")


def _ci_in(value: Any, candidates: list[str]) -> bool:
    """Case-insensitive membership."""
    if value is None:
        return False
    target = str(value).strip().lower()
    return any(target == c.strip().lower() for c in candidates)


def _family_of(elem: dict[str, Any]) -> str | None:
    """Resolve Revit-style family from canonical properties."""
    props = elem.get("properties") or {}
    return (
        props.get("family")
        or props.get("Family")
        or props.get("revit_family")
    )


def _type_of(elem: dict[str, Any]) -> str | None:
    props = elem.get("properties") or {}
    return (
        props.get("type")
        or props.get("Type")
        or props.get("type_name")
        or props.get("revit_type")
    )


def _classification_codes(
    elem: dict[str, Any],
    *,
    system: str | None,
) -> list[str]:
    """Return classification codes attached to ``elem``.

    Canonical layout: ``classification: {din276: "330", nrm: "2.6.1", ...}``
    or a list of ``{system, code}`` records under ``classifications``.
    """
    out: list[str] = []
    classification = elem.get("classification") or {}
    if isinstance(classification, dict):
        if system is None:
            out.extend(str(v) for v in classification.values() if v is not None)
        else:
            v = classification.get(system) or classification.get(system.lower())
            if v is not None:
                out.append(str(v))
    classifications = elem.get("classifications") or []
    if isinstance(classifications, list):
        for entry in classifications:
            if not isinstance(entry, dict):
                continue
            entry_system = entry.get("system") or entry.get("standard")
            entry_code = entry.get("code") or entry.get("value")
            if entry_code is None:
                continue
            if system is None or (
                entry_system and str(entry_system).lower() == system.lower()
            ):
                out.append(str(entry_code))
    return out


def _present_psets(elem: dict[str, Any]) -> set[str]:
    """Return the set of property-set names present on ``elem``."""
    props = elem.get("properties") or {}
    out: set[str] = set()
    for key, value in props.items():
        # A nested dict at top level is a Pset.
        if isinstance(value, dict):
            out.add(key)
        # Flat keys named ``Pset_X.Field`` also count.
        if "." in key:
            out.add(key.split(".", 1)[0])
    return out


def _named_groups(elem: dict[str, Any]) -> set[str]:
    """Return named groups assigned to the element (canonical: list of strings)."""
    groups = elem.get("groups") or elem.get("named_groups") or []
    if isinstance(groups, list):
        return {str(g) for g in groups}
    if isinstance(groups, str):
        return {groups}
    return set()


def _passes_geometry_filter(
    elem: dict[str, Any], sel: GeometryFilterSelector
) -> bool:
    quantities = elem.get("quantities") or {}
    vol = _as_float(quantities.get("volume_m3") or quantities.get("volume"))
    area = _as_float(quantities.get("area_m2") or quantities.get("area"))
    length = _as_float(quantities.get("length_m") or quantities.get("length"))

    if sel.min_volume_m3 is not None and (vol is None or vol < sel.min_volume_m3):
        return False
    if sel.max_volume_m3 is not None and (vol is not None and vol > sel.max_volume_m3):
        return False
    if sel.min_area_m2 is not None and (area is None or area < sel.min_area_m2):
        return False
    if sel.max_area_m2 is not None and (area is not None and area > sel.max_area_m2):
        return False
    if sel.min_length_m is not None and (length is None or length < sel.min_length_m):
        return False
    return not (
        sel.max_length_m is not None
        and length is not None
        and length > sel.max_length_m
    )


# ── Predicate evaluation ───────────────────────────────────────────────


def _eval_predicate(
    elem: dict[str, Any],
    pred: Predicate,
    snapshot: dict[str, Any],
) -> bool:
    if isinstance(pred, AndPredicate):
        return all(_eval_predicate(elem, child, snapshot) for child in pred.children)
    if isinstance(pred, OrPredicate):
        return any(_eval_predicate(elem, child, snapshot) for child in pred.children)
    if isinstance(pred, NotPredicate):
        return not _eval_predicate(elem, pred.child, snapshot)
    if isinstance(pred, TripletPredicate):
        attr_value = _resolve_attribute(elem, pred.attribute)
        snapshot[_attr_label(pred.attribute)] = (
            None if attr_value is MISSING else attr_value
        )
        if attr_value is MISSING:
            # treat_missing_as_fail=True (default): missing attribute fails
            # the predicate. False: missing => predicate passes (vacuous).
            return not pred.treat_missing_as_fail
        return _eval_constraint(attr_value, pred.constraint)
    raise ExecutionError(f"unknown predicate kind: {type(pred).__name__}")


def _resolve_attribute(elem: dict[str, Any], ref: AttributeRef) -> Any:
    """Look up the value referenced by ``ref`` in ``elem``.

    Returns :data:`MISSING` if the attribute is not present — callers
    distinguish absence from an explicit ``None`` value.
    """
    props = elem.get("properties") or {}
    quantities = elem.get("quantities") or {}

    if isinstance(ref, ExactAttributeRef):
        # 1) Pset-qualified path: properties[pset][name] or "pset.name".
        if ref.pset_name:
            nested = props.get(ref.pset_name)
            if isinstance(nested, dict):
                value = _dict_lookup(nested, ref.name, ref.case_sensitive)
                if value is not MISSING:
                    return value
            flat_key = f"{ref.pset_name}.{ref.name}"
            value = _dict_lookup(props, flat_key, ref.case_sensitive)
            if value is not MISSING:
                return value
        # 2) Bare name in properties / quantities / top-level row.
        for source in (props, quantities, elem):
            value = _dict_lookup(source, ref.name, ref.case_sensitive)
            if value is not MISSING:
                return value
        return MISSING

    if isinstance(ref, RegexAttributeRef):
        flags = 0 if ref.case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(ref.pattern, flags)
        except re.error as exc:
            raise ExecutionError(f"invalid regex {ref.pattern!r}: {exc}") from exc
        sources: list[dict[str, Any]] = []
        if ref.pset_name and isinstance(props.get(ref.pset_name), dict):
            sources.append(props[ref.pset_name])
        else:
            sources.extend([props, quantities])
        for source in sources:
            for key, value in source.items():
                if pattern.search(str(key)):
                    return value
        return MISSING

    if isinstance(ref, AliasAttributeRef):
        # Alias resolution requires the alias catalog from EAC-2.
        # The MVP executor does not reach into the catalog yet; the
        # caller is expected to expand aliases before invoking us, or
        # mirror the alias as ``properties[alias_id]``.
        for source in (props, elem):
            value = _dict_lookup(source, ref.alias_id, case_sensitive=True)
            if value is not MISSING:
                return value
        return MISSING

    raise ExecutionError(f"unknown attribute ref kind: {type(ref).__name__}")


def _dict_lookup(d: dict[str, Any], key: str, case_sensitive: bool) -> Any:
    if case_sensitive:
        if key in d:
            return d[key]
        return MISSING
    target = key.lower()
    for k, v in d.items():
        if str(k).lower() == target:
            return v
    return MISSING


def _attr_label(ref: AttributeRef) -> str:
    if isinstance(ref, ExactAttributeRef):
        return f"{ref.pset_name}.{ref.name}" if ref.pset_name else ref.name
    if isinstance(ref, RegexAttributeRef):
        return f"~{ref.pattern}"
    if isinstance(ref, AliasAttributeRef):
        return f"alias:{ref.alias_id}"
    return repr(ref)


# ── Constraint evaluation ─────────────────────────────────────────────


def _eval_constraint(value: Any, constraint: Constraint) -> bool:
    if isinstance(constraint, EqConstraint):
        return _eq(value, constraint.value)
    if isinstance(constraint, NeqConstraint):
        return not _eq(value, constraint.value)
    if isinstance(constraint, LtConstraint):
        return _cmp(value, constraint.value) < 0
    if isinstance(constraint, LteConstraint):
        return _cmp(value, constraint.value) <= 0
    if isinstance(constraint, GtConstraint):
        return _cmp(value, constraint.value) > 0
    if isinstance(constraint, GteConstraint):
        return _cmp(value, constraint.value) >= 0
    if isinstance(constraint, BetweenConstraint):
        lo, hi = _cmp(value, constraint.min), _cmp(value, constraint.max)
        if constraint.inclusive:
            return lo >= 0 and hi <= 0
        return lo > 0 and hi < 0
    if isinstance(constraint, NotBetweenConstraint):
        lo, hi = _cmp(value, constraint.min), _cmp(value, constraint.max)
        if constraint.inclusive:
            return lo < 0 or hi > 0
        return lo <= 0 or hi >= 0
    if isinstance(constraint, InConstraint):
        return any(_eq(value, v) for v in constraint.values)
    if isinstance(constraint, NotInConstraint):
        return not any(_eq(value, v) for v in constraint.values)
    if isinstance(constraint, ContainsConstraint):
        return _str_contains(value, constraint.value, constraint.case_sensitive)
    if isinstance(constraint, NotContainsConstraint):
        return not _str_contains(value, constraint.value, constraint.case_sensitive)
    if isinstance(constraint, StartsWithConstraint):
        return _str_op(value, constraint.value, constraint.case_sensitive, "startswith")
    if isinstance(constraint, EndsWithConstraint):
        return _str_op(value, constraint.value, constraint.case_sensitive, "endswith")
    if isinstance(constraint, MatchesConstraint):
        return _regex_match(value, constraint.pattern, constraint.case_sensitive)
    if isinstance(constraint, NotMatchesConstraint):
        return not _regex_match(value, constraint.pattern, constraint.case_sensitive)
    if isinstance(constraint, ExistsConstraint):
        return value is not None
    if isinstance(constraint, NotExistsConstraint):
        return value is None
    if isinstance(constraint, IsNullConstraint):
        return value is None
    if isinstance(constraint, IsNotNullConstraint):
        return value is not None
    if isinstance(constraint, IsEmptyConstraint):
        return value is None or (isinstance(value, (str, list, dict)) and len(value) == 0)
    if isinstance(constraint, IsNotEmptyConstraint):
        return not (
            value is None or (isinstance(value, (str, list, dict)) and len(value) == 0)
        )
    if isinstance(constraint, IsNumericConstraint):
        return _as_float(value) is not None
    if isinstance(constraint, IsBooleanConstraint):
        return isinstance(value, bool)
    if isinstance(constraint, IsDateConstraint):
        return _looks_like_date(value)
    raise ExecutionError(
        f"unknown constraint operator: {type(constraint).__name__}"
    )


# ── Comparison helpers ────────────────────────────────────────────────


def _eq(a: Any, b: Any) -> bool:
    """Equality with numeric coercion (``"3"`` == ``3``) and case-insensitive strings."""
    if a is None or b is None:
        return a is None and b is None
    af, bf = _as_float(a), _as_float(b)
    if af is not None and bf is not None:
        return af == bf
    return str(a).strip().lower() == str(b).strip().lower()


def _cmp(a: Any, b: Any) -> int:
    """Three-way numeric comparison; falls back to string comparison."""
    af, bf = _as_float(a), _as_float(b)
    if af is not None and bf is not None:
        if af < bf:
            return -1
        if af > bf:
            return 1
        return 0
    sa, sb = str(a), str(b)
    if sa < sb:
        return -1
    if sa > sb:
        return 1
    return 0


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _str_contains(value: Any, needle: str, case_sensitive: bool) -> bool:
    if value is None:
        return False
    haystack = str(value) if case_sensitive else str(value).lower()
    target = needle if case_sensitive else needle.lower()
    return target in haystack


def _str_op(value: Any, needle: str, case_sensitive: bool, op: str) -> bool:
    if value is None:
        return False
    haystack = str(value) if case_sensitive else str(value).lower()
    target = needle if case_sensitive else needle.lower()
    if op == "startswith":
        return haystack.startswith(target)
    return haystack.endswith(target)


def _regex_match(value: Any, pattern: str, case_sensitive: bool) -> bool:
    if value is None:
        return False
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        return re.search(pattern, str(value), flags) is not None
    except re.error as exc:
        raise ExecutionError(f"invalid regex {pattern!r}: {exc}") from exc


def _looks_like_date(value: Any) -> bool:
    """Cheap date detector — accept ISO-8601 dates / datetimes."""
    if value is None or not isinstance(value, str):
        return False
    return bool(
        re.match(
            r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?$",
            value.strip(),
        )
    )


# ── Aggregate-mode bindings ───────────────────────────────────────────


def _build_aggregate_bindings(
    elements: list[dict[str, Any]],
    *,
    formula: str | None = None,
) -> dict[str, list[Any]]:
    """Project canonical numeric fields into named lists for formula access.

    The formula sees every quantity / numeric property as a list
    (``volume_m3``, ``area_m2``, etc.) and collapses it via
    ``SUM`` / ``AVG`` / ``COUNT`` / ``MIN`` / ``MAX``.

    When ``elements`` is empty (selector matched nothing) we still bind
    every name that appears in ``formula`` to an empty list so functions
    like ``SUM([])=0`` / ``COUNT([])=0`` succeed instead of raising
    ``NameNotDefined``. ``AVG([])`` / ``MIN([])`` / ``MAX([])`` will
    still raise — there is no sensible scalar for "average of nothing"
    and the safe-eval surface lets that bubble up as a typed error.
    """
    bindings: dict[str, list[Any]] = {}

    # Quantities are the most common aggregation source — flatten them.
    quantity_keys: set[str] = set()
    for elem in elements:
        quantity_keys.update((elem.get("quantities") or {}).keys())
    for key in quantity_keys:
        bindings[key] = [
            (elem.get("quantities") or {}).get(key) for elem in elements
        ]

    # Top-level numeric properties (flat ``properties`` dict).
    property_keys: set[str] = set()
    for elem in elements:
        for k, v in (elem.get("properties") or {}).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                property_keys.add(k)
    for key in property_keys:
        if key in bindings:
            continue
        bindings[key] = [
            (elem.get("properties") or {}).get(key) for elem in elements
        ]

    # Element count is always available as ``elements`` (non-None list).
    bindings.setdefault("elements", [1 for _ in elements])

    # Empty-set safety: bind every free variable referenced by the
    # formula to an empty list so SUM/COUNT-style aggregates collapse
    # to 0 instead of NameError. Only matters when ``elements`` is empty.
    if not elements and formula is not None:
        try:
            from app.modules.eac.engine.safe_eval import (
                collect_variable_names,
                parse_formula,
            )

            for name in collect_variable_names(parse_formula(formula)):
                bindings.setdefault(name, [])
        except Exception:  # noqa: BLE001 — caller will surface formula errors
            pass

    return bindings


# ── Issue templating ──────────────────────────────────────────────────


_TEMPLATE_TOKEN_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_.]*)\}")


def _render_template(
    template: str | None,
    elem: dict[str, Any],
    snapshot: dict[str, Any],
) -> str:
    """Replace ``{token}`` placeholders with element values.

    Tokens resolved in this order: snapshot, top-level row, properties,
    ``properties.<pset>.<field>`` paths. Missing tokens are left as the
    literal placeholder so users can spot misspellings.
    """
    if template is None:
        return ""

    def repl(match: re.Match[str]) -> str:
        token = match.group(1)
        if token in snapshot and snapshot[token] is not None:
            return str(snapshot[token])
        if token in elem and elem[token] is not None:
            return str(elem[token])
        props = elem.get("properties") or {}
        if token in props:
            return str(props[token])
        if "." in token:
            head, tail = token.split(".", 1)
            nested = props.get(head)
            if isinstance(nested, dict) and tail in nested:
                return str(nested[tail])
        return match.group(0)

    return _TEMPLATE_TOKEN_RE.sub(repl, template)


__all__ = [
    "AggregateResult",
    "ElementResult",
    "ExecutionError",
    "ExecutionResult",
    "IssueResult",
    "UnsupportedOutputModeError",
    "execute_rule",
]

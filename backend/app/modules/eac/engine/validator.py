# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Semantic validator for EAC v2 rule definitions (RFC 35 §5 EAC-1.3, FR-1.10).

Adds the semantic checks the JSON Schema cannot express:

* Reference existence (``alias_id``, ``${global_var}``, classifier_id).
* Standard-variable allowlist (``${Volume}``, ``${Length}``, …).
* ``between`` / ``not_between``: ``min <= max``.
* Regex patterns: compile + ReDoS heuristic.
* Local variable dependency graph: reject cycles.

The schema-level check (Pydantic shape) is performed earlier by
``EacRuleDefinition.model_validate`` in the router. The validator
operates on an already-parsed :class:`EacRuleDefinition` instance.

Public surface:

* :class:`ValidatorIssue`  — one diagnostic
* :class:`ValidatorResult` — pass/fail + list of issues
* :func:`validate_rule`    — async entry point
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.eac.engine.safe_eval import (
    FormulaSyntaxError,
    FormulaUnsafeError,
    collect_variable_names,
    parse_formula,
)
from app.modules.eac.engine.standard_vars import is_standard_variable
from app.modules.eac.models import EacGlobalVariable, EacParameterAlias
from app.modules.eac.schemas import (
    AliasAttributeRef,
    AndPredicate,
    AndSelector,
    BetweenConstraint,
    EacRuleDefinition,
    EntitySelector,
    NotBetweenConstraint,
    NotPredicate,
    NotSelector,
    OrPredicate,
    OrSelector,
    Predicate,
    RegexAttributeRef,
    TripletPredicate,
)

logger = logging.getLogger(__name__)


Severity = Literal["error", "warning"]


# ── Public dataclasses ──────────────────────────────────────────────────


@dataclass(frozen=True)
class ValidatorIssue:
    """Single diagnostic produced by :func:`validate_rule`.

    ``code`` is a short machine-readable identifier (e.g.
    ``alias_not_found``, ``redos_regex``, ``cyclic_local_var``).
    ``path`` is a JSON-pointer-like cursor into the rule body so the UI
    can highlight the exact field. ``message_i18n_key`` is a stable key
    the frontend resolves through its translation catalog.
    ``context`` carries extra structured data (alternatives, the bad
    alias_id, etc.) the UI can render as needed.
    """

    code: str
    severity: Severity
    path: str
    message_i18n_key: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidatorResult:
    """Outcome of a validation pass."""

    valid: bool
    issues: list[ValidatorIssue]


# ── Public entry point ──────────────────────────────────────────────────


async def validate_rule(
    definition: EacRuleDefinition,
    *,
    session: AsyncSession,
    tenant_id: uuid.UUID | None = None,
) -> ValidatorResult:
    """Run every semantic check on a parsed rule definition.

    Issues are accumulated rather than raising — the validator never
    fail-fast so the UI can render every blocker in one round-trip.

    :param definition: a Pydantic-parsed rule body (shape already valid).
    :param session: async DB session for alias / global-variable lookups.
    :param tenant_id: optional tenant scope; ``None`` matches global
        built-ins. (RLS is added in W0.4 and is out of scope here.)
    """
    ctx = _ValidationContext()

    # 1. Selector — walk and collect classifier_id refs (deferred to EAC-5).
    _walk_selector(definition.selector, "$.selector", ctx)

    # 2. Predicate — collect alias_id refs and run regex / between checks.
    if definition.predicate is not None:
        _walk_predicate(definition.predicate, "$.predicate", ctx)

    # 3. Resolve alias references against the DB.
    await _check_alias_refs(session, ctx, tenant_id)

    # 4. Local variable cycle detection.
    _check_local_variable_cycles(definition, ctx)

    # 5. Formula syntax + variable existence (formula-only checks).
    _check_formula(definition, ctx, session=session, tenant_id=tenant_id)

    # 6. Global variable resolution (anything collected during step 5).
    await _check_global_var_refs(session, ctx, tenant_id)

    issues = ctx.issues
    valid = not any(i.severity == "error" for i in issues)
    return ValidatorResult(valid=valid, issues=issues)


# ── Internal: validation context ────────────────────────────────────────


@dataclass
class _ValidationContext:
    """Mutable accumulator shared across the walk."""

    issues: list[ValidatorIssue] = field(default_factory=list)
    # alias_id refs: list of (alias_id, json_path)
    alias_refs: list[tuple[str, str]] = field(default_factory=list)
    # global var refs: list of (scope, name, json_path)
    global_var_refs: list[tuple[str, str, str]] = field(default_factory=list)

    def add(
        self,
        *,
        code: str,
        path: str,
        i18n_key: str,
        ctx: dict[str, Any] | None = None,
        severity: Severity = "error",
    ) -> None:
        self.issues.append(
            ValidatorIssue(
                code=code,
                severity=severity,
                path=path,
                message_i18n_key=i18n_key,
                context=ctx or {},
            )
        )


# ── Internal: selector walk ─────────────────────────────────────────────


def _walk_selector(
    selector: EntitySelector,
    path: str,
    ctx: _ValidationContext,
) -> None:
    """Walk a selector tree.

    The validator only flags semantic issues. Structural validity (every
    leaf has a recognised ``kind``, ``children`` non-empty, etc.) is
    already enforced by Pydantic.
    """
    if isinstance(selector, (AndSelector, OrSelector)):
        for i, child in enumerate(selector.children):
            _walk_selector(child, f"{path}.children[{i}]", ctx)
    elif isinstance(selector, NotSelector):
        _walk_selector(selector.child, f"{path}.child", ctx)
    # Other leaves (category / ifc_class / classification_code / ...)
    # carry no references the validator must resolve at this stage.
    # classifier_id resolution is deferred to EAC-5.


# ── Internal: predicate walk ────────────────────────────────────────────


def _walk_predicate(
    predicate: Predicate,
    path: str,
    ctx: _ValidationContext,
) -> None:
    """Walk a predicate tree, collecting alias refs and checking constraints."""
    if isinstance(predicate, AndPredicate):
        for i, child in enumerate(predicate.children):
            _walk_predicate(child, f"{path}.children[{i}]", ctx)
        return
    if isinstance(predicate, OrPredicate):
        for i, child in enumerate(predicate.children):
            _walk_predicate(child, f"{path}.children[{i}]", ctx)
        return
    if isinstance(predicate, NotPredicate):
        _walk_predicate(predicate.child, f"{path}.child", ctx)
        return
    if isinstance(predicate, TripletPredicate):
        _check_attribute(predicate, path, ctx)
        _check_constraint(predicate, path, ctx)


def _check_attribute(
    predicate: TripletPredicate,
    path: str,
    ctx: _ValidationContext,
) -> None:
    """Inspect an attribute reference for alias lookups and regex safety."""
    attr = predicate.attribute
    if isinstance(attr, AliasAttributeRef):
        ctx.alias_refs.append((attr.alias_id, f"{path}.attribute.alias_id"))
        return
    if isinstance(attr, RegexAttributeRef):
        _check_regex_pattern(attr.pattern, f"{path}.attribute.pattern", ctx)


def _check_constraint(
    predicate: TripletPredicate,
    path: str,
    ctx: _ValidationContext,
) -> None:
    """Inspect a constraint for between min/max ordering and regex safety."""
    constraint = predicate.constraint
    if isinstance(constraint, (BetweenConstraint, NotBetweenConstraint)):
        try:
            if float(constraint.min) > float(constraint.max):  # type: ignore[arg-type]
                ctx.add(
                    code="between_min_greater_than_max",
                    path=f"{path}.constraint",
                    i18n_key="eac.validator.between_min_greater_than_max",
                    ctx={
                        "min": constraint.min,
                        "max": constraint.max,
                        "operator": constraint.operator,
                    },
                )
        except (TypeError, ValueError):
            # Non-numeric min/max for between: schema permits string
            # values; we only flag the ordering issue when both sides
            # cast cleanly to float. String-typed bounds are accepted.
            pass
        return
    # MatchesConstraint / NotMatchesConstraint: walk pattern.
    pattern = getattr(constraint, "pattern", None)
    if isinstance(pattern, str):
        _check_regex_pattern(pattern, f"{path}.constraint.pattern", ctx)


# ── Internal: regex ReDoS heuristic ─────────────────────────────────────

# Heuristic for catastrophic backtracking patterns. Two well-known
# canonical shapes:
#   (X+)+   nested + quantifier on group
#   (X*)*   nested * quantifier on group
#   (X+)*   mixed quantifier
# We deliberately keep the heuristic tight (no false positives on
# `^[A-Z]{2}-\d+$` or similar). This is a syntactic guard only; the
# executor still applies a wall-clock timeout per match.

_REDOS_PATTERN = re.compile(
    r"\([^)]*[*+][^)]*\)[*+]"
)


def _check_regex_pattern(
    pattern: str, path: str, ctx: _ValidationContext
) -> None:
    """Compile the pattern and reject obvious ReDoS shapes."""
    try:
        re.compile(pattern)
    except re.error as exc:
        ctx.add(
            code="invalid_regex",
            path=path,
            i18n_key="eac.validator.invalid_regex",
            ctx={"pattern": pattern, "error": str(exc)},
        )
        return

    if _REDOS_PATTERN.search(pattern):
        ctx.add(
            code="redos_regex",
            path=path,
            i18n_key="eac.validator.redos_regex",
            ctx={"pattern": pattern},
        )


# ── Internal: alias resolution ──────────────────────────────────────────


async def _check_alias_refs(
    session: AsyncSession,
    ctx: _ValidationContext,
    tenant_id: uuid.UUID | None,
) -> None:
    """Verify every collected ``alias_id`` resolves to a real row."""
    if not ctx.alias_refs:
        return

    # Distinct list of alias_id strings to look up.
    distinct_ids = {alias_id for alias_id, _ in ctx.alias_refs}

    found: set[str] = set()
    for alias_id_str in distinct_ids:
        # alias_id may be a UUID string or a name-style id like
        # "alias_thickness". The schema doesn't constrain it. Try as a
        # UUID first; if that fails, fall back to a name match.
        alias_uuid: uuid.UUID | None = None
        try:
            alias_uuid = uuid.UUID(alias_id_str)
        except (ValueError, TypeError):
            alias_uuid = None

        match = None
        if alias_uuid is not None:
            match = await session.get(EacParameterAlias, alias_uuid)
        if match is None:
            stmt = select(EacParameterAlias).where(
                EacParameterAlias.name == alias_id_str
            )
            res = await session.execute(stmt)
            match = res.scalar_one_or_none()
        if match is not None:
            found.add(alias_id_str)

    for alias_id_str, path in ctx.alias_refs:
        if alias_id_str not in found:
            ctx.add(
                code="alias_not_found",
                path=path,
                i18n_key="eac.validator.alias_not_found",
                ctx={"alias_id": alias_id_str},
            )


# ── Internal: global variable resolution ────────────────────────────────


async def _check_global_var_refs(
    session: AsyncSession,
    ctx: _ValidationContext,
    tenant_id: uuid.UUID | None,
) -> None:
    """Verify every ``project.X`` / ``org.X`` reference resolves."""
    if not ctx.global_var_refs:
        return

    distinct = {(scope, name) for scope, name, _ in ctx.global_var_refs}
    found: set[tuple[str, str]] = set()
    for scope, name in distinct:
        stmt = select(EacGlobalVariable).where(
            EacGlobalVariable.scope == scope,
            EacGlobalVariable.name == name,
        )
        res = await session.execute(stmt)
        if res.scalar_one_or_none() is not None:
            found.add((scope, name))

    for scope, name, path in ctx.global_var_refs:
        if (scope, name) not in found:
            ctx.add(
                code="global_var_not_found",
                path=path,
                i18n_key="eac.validator.global_var_not_found",
                ctx={"scope": scope, "name": name},
            )


# ── Internal: formula checks ────────────────────────────────────────────


def _check_formula(
    definition: EacRuleDefinition,
    ctx: _ValidationContext,
    *,
    session: AsyncSession,  # noqa: ARG001 — async lookups happen later
    tenant_id: uuid.UUID | None,  # noqa: ARG001 — reserved for tenant-scoped checks
) -> None:
    """Parse the formula (if any) and surface name-resolution problems.

    Local variables are listed in :class:`LocalVariableDefinition`;
    references to ``project.X`` / ``org.X`` go on
    ``ctx.global_var_refs`` for resolution by :func:`_check_global_var_refs`.
    """
    formulas: list[tuple[str, str]] = []  # (path, formula)
    if definition.formula:
        formulas.append(("$.formula", definition.formula))
    for i, lv in enumerate(definition.local_variables):
        formulas.append((f"$.local_variables[{i}].expression", lv.expression))

    if not formulas:
        return

    local_var_names = {lv.name for lv in definition.local_variables}

    for path, formula in formulas:
        try:
            parsed = parse_formula(formula)
        except FormulaSyntaxError as exc:
            ctx.add(
                code="formula_syntax",
                path=path,
                i18n_key="eac.validator.formula_syntax",
                ctx={"formula": formula, "error": str(exc)},
            )
            continue
        except FormulaUnsafeError as exc:
            ctx.add(
                code="formula_unsafe",
                path=path,
                i18n_key="eac.validator.formula_unsafe",
                ctx={"formula": formula, "error": str(exc)},
            )
            continue

        # Variable-existence scan.
        names = collect_variable_names(parsed)

        # Detect "scope.name" attribute-style refs the AST scanner can't see.
        # Walk the formula's AST manually for ``project.X`` / ``org.X``.
        import ast as _ast

        for node in _ast.walk(parsed):
            if isinstance(node, _ast.Attribute) and isinstance(node.value, _ast.Name):
                scope = node.value.id
                if scope in {"project", "org"}:
                    ctx.global_var_refs.append((scope, node.attr, path))

        for name in names:
            # Names like ``project`` / ``org`` are scope handles, not
            # free variables — they're consumed by the attribute scan
            # above. Skip them here.
            if name in {"project", "org"}:
                continue
            if name in local_var_names:
                continue
            if is_standard_variable(name):
                continue
            # Otherwise the name must be either a known alias by name,
            # or it'll fall through to ``unknown_variable``. We don't
            # hit the DB here — the alias-by-name probe already runs in
            # ``_check_alias_refs`` for explicit ``alias_id`` refs. For
            # bare names we register them as unknown unless they look
            # like upper-snake constants the user is likely to define
            # at org level later.
            ctx.add(
                code="unknown_variable",
                path=path,
                i18n_key="eac.validator.unknown_variable",
                ctx={"name": name},
                severity="warning",
            )


# ── Internal: local variable cycle detection ────────────────────────────


def _check_local_variable_cycles(
    definition: EacRuleDefinition,
    ctx: _ValidationContext,
) -> None:
    """Build the dependency graph of local variables and detect cycles.

    Each local variable's expression is parsed; the names it references
    that match other local-variable names form the edges. A standard
    DFS with a visiting set finds back-edges → cycles.
    """
    locals_by_name = {lv.name: lv for lv in definition.local_variables}
    if not locals_by_name:
        return

    graph: dict[str, set[str]] = {}
    for name, lv in locals_by_name.items():
        try:
            parsed = parse_formula(lv.expression)
        except (FormulaSyntaxError, FormulaUnsafeError):
            # Syntax / safety problems are reported by ``_check_formula``;
            # we just skip the cycle check for that node.
            graph[name] = set()
            continue
        refs = collect_variable_names(parsed)
        graph[name] = {r for r in refs if r in locals_by_name}

    visited: set[str] = set()
    on_stack: set[str] = set()
    cycles: list[list[str]] = []

    def _dfs(node: str, path: list[str]) -> None:
        if node in on_stack:
            # Found a back-edge — record the cycle.
            cycle_start = path.index(node)
            cycles.append(path[cycle_start:] + [node])
            return
        if node in visited:
            return
        visited.add(node)
        on_stack.add(node)
        for nxt in graph.get(node, set()):
            _dfs(nxt, path + [node])
        on_stack.discard(node)

    for name in graph:
        if name not in visited:
            _dfs(name, [])

    if cycles:
        # Report each unique cycle once. Different DFS roots can yield
        # rotations of the same cycle, so canonicalise on the sorted
        # frozenset of nodes.
        seen: set[frozenset[str]] = set()
        for cycle in cycles:
            key = frozenset(cycle)
            if key in seen:
                continue
            seen.add(key)
            ctx.add(
                code="cyclic_local_var",
                path="$.local_variables",
                i18n_key="eac.validator.cyclic_local_var",
                ctx={"cycle": cycle},
            )


__all__ = ["ValidatorIssue", "ValidatorResult", "validate_rule"]

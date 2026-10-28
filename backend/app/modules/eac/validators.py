# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Validation rules for the EAC visual block graph.

A block graph is the estimator's own drawing of a rule: blocks at canvas
coordinates, wired together through typed slots. It is saved constantly and
half-finished most of the time, so these rules never block a save. They run on
every write and their findings are persisted on the row, which is what turns
"is this methodology actually sound?" from a question the estimator has to hold
in their head into a traffic light they can see in a list.

Four rules, all in the ``eac_graph`` rule set:

* ``eac_graph.block_reference_exists`` - ERROR. A wire must land on a block that
  is on the canvas, and on a slot that exists on *that* block. This is the rule a
  foreign key cannot express, and the reason connections are stored by client id
  rather than by FK.
* ``eac_graph.no_cycles``              - ERROR. The wiring must be acyclic. A
  cyclic graph cannot be evaluated: every block waits on itself. A self-wired
  block is the degenerate case and is caught here too, matching the canvas store,
  which refuses to draw one.
* ``eac_graph.slot_type_compatible``   - ERROR. A wire runs output to input, and
  the two data types must be compatible. Mirrors ``canConnectSlots`` in
  ``features/eac/canvas/dnd.ts``, so the server cannot accept a graph the editor
  would have refused to draw, nor refuse one it drew.
* ``eac_graph.parameter_domain``       - ERROR. A block parameter must sit inside
  the domain the block kind declares: a constraint operator must be one of the 25
  the spec defines, a range operator needs exactly two bounds, and an operator
  that takes no operand must not carry one.

Every rule reads the same plain-dict shape the service hands it, so none of them
needs a database session and all of them are unit-testable in isolation.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)

logger = logging.getLogger(__name__)

#: The rule set every block-graph rule registers under.
EAC_GRAPH_RULE_SET = "eac_graph"


# ── Vocabulary mirrored from the editor ──────────────────────────────────────
#
# These are copies of TypeScript unions, not new invention. Keeping them here
# rather than deriving them means a change on either side shows up as a test
# failure instead of as a silently permissive server.

#: ``SLOT_TYPE_COMPATIBILITY`` from ``features/eac/canvas/dnd.ts``.
SLOT_TYPE_COMPATIBILITY: dict[str, frozenset[str]] = {
    "selector": frozenset({"selector", "any"}),
    "predicate": frozenset({"predicate", "any"}),
    "attribute": frozenset({"attribute", "any"}),
    "constraint": frozenset({"constraint", "any"}),
    "variable": frozenset({"variable", "number", "any"}),
    "number": frozenset({"number", "variable", "any"}),
    "string": frozenset({"string", "any"}),
    "boolean": frozenset({"boolean", "any"}),
    "any": frozenset(
        {
            "selector",
            "predicate",
            "attribute",
            "constraint",
            "variable",
            "number",
            "string",
            "boolean",
            "any",
        }
    ),
}

#: The 25 ``ConstraintOperator`` values from ``features/eac/types.ts``.
CONSTRAINT_OPERATORS: frozenset[str] = frozenset(
    {
        "eq",
        "ne",
        "gt",
        "gte",
        "lt",
        "lte",
        "between",
        "not_between",
        "in",
        "not_in",
        "starts_with",
        "ends_with",
        "contains",
        "not_contains",
        "matches",
        "not_matches",
        "exists",
        "not_exists",
        "is_null",
        "is_not_null",
        "is_numeric",
        "is_string",
        "is_boolean",
        "eq_unit_aware",
        "gte_unit_aware",
        "lte_unit_aware",
    }
)

#: Operators taking exactly two bounds in ``values``.
RANGE_OPERATORS: frozenset[str] = frozenset({"between", "not_between"})

#: Operators taking no right-hand operand at all.
UNARY_OPERATORS: frozenset[str] = frozenset(
    {
        "exists",
        "not_exists",
        "is_null",
        "is_not_null",
        "is_numeric",
        "is_string",
        "is_boolean",
    }
)

#: Operators taking a list of candidate values.
SET_OPERATORS: frozenset[str] = frozenset({"in", "not_in"})

#: ``AggregateFunction`` from ``features/eac/types.ts``.
AGGREGATE_FUNCTIONS: frozenset[str] = frozenset(
    {"sum", "avg", "min", "max", "count", "count_distinct", "first", "last"}
)

#: Block kinds whose ``params`` carry a constraint operator.
_CONSTRAINT_KINDS: frozenset[str] = frozenset({"constraint", *CONSTRAINT_OPERATORS})


# ── Context helpers ──────────────────────────────────────────────────────────


def _graph(context: ValidationContext) -> dict[str, Any]:
    """The graph payload carried on the context (or an empty dict)."""
    data = context.data
    return data if isinstance(data, dict) else {}


def _blocks(context: ValidationContext) -> list[dict[str, Any]]:
    """Every block dict on the graph."""
    blocks = _graph(context).get("blocks")
    if not isinstance(blocks, list):
        return []
    return [b for b in blocks if isinstance(b, dict)]


def _connections(context: ValidationContext) -> list[dict[str, Any]]:
    """Every connection dict on the graph."""
    connections = _graph(context).get("connections")
    if not isinstance(connections, list):
        return []
    return [c for c in connections if isinstance(c, dict)]


def _slots(block: dict[str, Any]) -> list[dict[str, Any]]:
    """Slot definitions declared on a block."""
    slots = block.get("slots")
    if not isinstance(slots, list):
        return []
    return [s for s in slots if isinstance(s, dict)]


def _block_index(blocks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map block client id to the block dict."""
    return {str(b.get("client_id") or ""): b for b in blocks if b.get("client_id")}


def _find_slot(block: dict[str, Any] | None, slot_id: str) -> dict[str, Any] | None:
    """Locate a slot by id on a block, or return None."""
    if block is None:
        return None
    for slot in _slots(block):
        if str(slot.get("id") or "") == slot_id:
            return slot
    return None


def _label(block: dict[str, Any] | None, fallback: str) -> str:
    """A human-facing name for a block: its title, else its kind, else its id."""
    if block is None:
        return fallback
    title = str(block.get("title") or "").strip()
    if title:
        return title
    kind = str(block.get("kind") or "").strip()
    return kind or fallback


def _result(
    rule: ValidationRule,
    passed: bool,
    message: str,
    *,
    element_ref: str | None = None,
    suggestion: str | None = None,
    details: dict[str, Any] | None = None,
) -> RuleResult:
    """Build a RuleResult carrying the rule's own id / name / severity / category."""
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=element_ref,
        suggestion=suggestion,
        details=details or {},
    )


# ── Rule 1: every wire endpoint must exist ───────────────────────────────────


class EacGraphBlockReferenceExists(ValidationRule):
    """A wire must land on a block that is present, and on a slot it declares."""

    rule_id = "eac_graph.block_reference_exists"
    name = "Block Graph References Resolve"
    standard = "eac_graph"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Every connection must reference a block on the canvas and a slot that block declares."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        connections = _connections(context)
        if not connections:
            # No result at all, rather than a passing one. A canvas with no
            # wires has no reference to check, and reporting that as a pass
            # would let a blank methodology accumulate a perfect score out of
            # checks that never examined anything.
            return []
        index = _block_index(_blocks(context))
        results: list[RuleResult] = []
        for conn in connections:
            ref = str(conn.get("client_id") or "")
            problems: list[str] = []
            for side in ("source", "target"):
                block_id = str(conn.get(f"{side}_block_client_id") or "")
                slot_id = str(conn.get(f"{side}_slot_id") or "")
                block = index.get(block_id)
                if block is None:
                    problems.append(
                        f"its {side} block '{block_id}' is not on the canvas",
                    )
                    continue
                if _find_slot(block, slot_id) is None:
                    problems.append(
                        f"block '{_label(block, block_id)}' has no {side} slot '{slot_id}'",
                    )
            if not problems:
                results.append(_result(self, True, "OK", element_ref=ref))
                continue
            results.append(
                _result(
                    self,
                    False,
                    f"Connection '{ref}' cannot be resolved: {'; '.join(problems)}.",
                    element_ref=ref,
                    suggestion="Delete the dangling wire, or restore the block it points at.",
                    details={"connection_id": ref, "problems": problems},
                )
            )
        return results


# ── Rule 2: the wiring must be acyclic ───────────────────────────────────────


class EacGraphNoCycles(ValidationRule):
    """The directed block graph must be acyclic."""

    rule_id = "eac_graph.no_cycles"
    name = "Block Graph Is Acyclic"
    standard = "eac_graph"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "A cycle in the wiring cannot be evaluated: every block on the loop waits on itself."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        blocks = _blocks(context)
        index = _block_index(blocks)
        # Only edges whose endpoints both exist can form a cycle; a dangling
        # edge is rule 1's finding, not this one's.
        edges: dict[str, list[str]] = {block_id: [] for block_id in index}
        for conn in _connections(context):
            source = str(conn.get("source_block_client_id") or "")
            target = str(conn.get("target_block_client_id") or "")
            if source in index and target in index:
                edges[source].append(target)
        if not any(edges.values()):
            # Nothing is wired, so "acyclic" is vacuously true and carries no
            # information. Stay silent instead of banking a free pass.
            return []

        cycle = _first_cycle(edges)
        if cycle is None:
            return [_result(self, True, "OK")]
        names = [_label(index.get(node), node) for node in cycle]
        return [
            _result(
                self,
                False,
                (f"The blocks are wired in a loop ({' -> '.join(names)}), so the methodology cannot be evaluated."),
                element_ref=cycle[0],
                suggestion="Remove one wire on the loop so the blocks form a one-way chain.",
                details={"cycle": cycle, "cycle_labels": names, "length": len(cycle) - 1},
            )
        ]


def _first_cycle(edges: dict[str, list[str]]) -> list[str] | None:
    """Return one cycle as a node path (first node repeated at the end), or None.

    Iterative depth-first search with an explicit stack: a deeply nested graph
    from a real canvas must not be able to blow the Python recursion limit and
    turn a validation finding into a 500.
    """
    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[str, int] = dict.fromkeys(edges, WHITE)

    for root in edges:
        if color[root] != WHITE:
            continue
        # Each frame is (node, iterator over its remaining successors).
        path: list[str] = [root]
        color[root] = GREY
        stack: list[tuple[str, list[str], int]] = [(root, edges[root], 0)]
        while stack:
            node, successors, cursor = stack.pop()
            if cursor >= len(successors):
                color[node] = BLACK
                path.pop()
                continue
            stack.append((node, successors, cursor + 1))
            nxt = successors[cursor]
            if color.get(nxt) == GREY:
                # Found a back edge: the cycle is the tail of the current path.
                start = path.index(nxt)
                return [*path[start:], nxt]
            if color.get(nxt, BLACK) == WHITE:
                color[nxt] = GREY
                path.append(nxt)
                stack.append((nxt, edges[nxt], 0))
    return None


# ── Rule 3: wires must respect slot direction and data type ──────────────────


class EacGraphSlotTypeCompatible(ValidationRule):
    """A wire runs output to input, between compatible data types."""

    rule_id = "eac_graph.slot_type_compatible"
    name = "Block Graph Slot Types Compatible"
    standard = "eac_graph"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "A connection must run from an output slot to an input slot carrying a compatible data type."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        connections = _connections(context)
        if not connections:
            return []
        index = _block_index(_blocks(context))
        results: list[RuleResult] = []
        for conn in connections:
            ref = str(conn.get("client_id") or "")
            source_block = index.get(str(conn.get("source_block_client_id") or ""))
            target_block = index.get(str(conn.get("target_block_client_id") or ""))
            source = _find_slot(source_block, str(conn.get("source_slot_id") or ""))
            target = _find_slot(target_block, str(conn.get("target_slot_id") or ""))
            # An unresolvable endpoint is rule 1's finding. Staying silent here
            # keeps a single mistake from being reported twice, and keeps each
            # rule's rejecting fixture provably its own.
            if source is None or target is None:
                continue

            source_dir = str(source.get("direction") or "")
            target_dir = str(target.get("direction") or "")
            source_type = str(source.get("dataType") or "")
            target_type = str(target.get("dataType") or "")

            if source_dir != "output" or target_dir != "input":
                results.append(
                    _result(
                        self,
                        False,
                        (
                            f"Connection '{ref}' runs {source_dir or 'an unknown slot'} to "
                            f"{target_dir or 'an unknown slot'}; a wire must leave an output "
                            "and arrive at an input."
                        ),
                        element_ref=ref,
                        suggestion="Redraw the wire from the block's output handle to the other block's input handle.",
                        details={
                            "connection_id": ref,
                            "source_direction": source_dir,
                            "target_direction": target_dir,
                        },
                    )
                )
                continue

            allowed = SLOT_TYPE_COMPATIBILITY.get(source_type, frozenset())
            if target_type in allowed:
                results.append(_result(self, True, "OK", element_ref=ref))
                continue
            results.append(
                _result(
                    self,
                    False,
                    (
                        f"Connection '{ref}' feeds a {source_type or 'unknown'} output into a "
                        f"{target_type or 'unknown'} input, which cannot carry it."
                    ),
                    element_ref=ref,
                    suggestion=(
                        f"A {source_type or 'unknown'} output accepts {', '.join(sorted(allowed)) or 'no'} inputs."
                    ),
                    details={
                        "connection_id": ref,
                        "source_type": source_type,
                        "target_type": target_type,
                        "allowed": sorted(allowed),
                    },
                )
            )
        # An empty list here means every wire was unresolvable, which rule 1 is
        # already reporting. Substituting a pass would have this rule vouch for
        # wiring it could not read.
        return results


# ── Rule 4: block parameters must sit inside their declared domain ───────────


class EacGraphParameterDomain(ValidationRule):
    """A block parameter must sit inside the domain its kind declares."""

    rule_id = "eac_graph.parameter_domain"
    name = "Block Parameters Within Domain"
    standard = "eac_graph"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "Block parameters must hold values their block kind allows, e.g. a range needs exactly two bounds."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        blocks = _blocks(context)
        if not blocks:
            return []
        results: list[RuleResult] = []
        for block in blocks:
            ref = str(block.get("client_id") or "")
            params = block.get("params")
            params = params if isinstance(params, dict) else {}
            problems = _constraint_problems(block, params) + _variable_problems(block, params)
            if not problems:
                results.append(_result(self, True, "OK", element_ref=ref))
                continue
            name = _label(block, ref)
            results.append(
                _result(
                    self,
                    False,
                    f"Block '{name}' has a parameter outside its allowed values: {'; '.join(problems)}.",
                    element_ref=ref,
                    suggestion="Correct the block's parameters in the editor panel.",
                    details={"block_id": ref, "kind": block.get("kind"), "problems": problems},
                )
            )
        return results


def _constraint_problems(block: dict[str, Any], params: dict[str, Any]) -> list[str]:
    """Domain problems on a constraint block's operator and operands."""
    kind = str(block.get("kind") or "")
    operator = params.get("operator")
    # A block is a constraint block if its kind says so, or if it carries an
    # operator at all - the palette drops some operators as their own kind.
    if kind not in _CONSTRAINT_KINDS and operator is None:
        return []
    if operator is None:
        return ["no comparison operator is set"]
    if not isinstance(operator, str) or operator not in CONSTRAINT_OPERATORS:
        return [f"'{operator}' is not one of the {len(CONSTRAINT_OPERATORS)} supported operators"]

    problems: list[str] = []
    values = params.get("values")
    has_value = params.get("value") is not None

    if operator in RANGE_OPERATORS:
        if not isinstance(values, list) or len(values) != 2:
            count = len(values) if isinstance(values, list) else 0
            problems.append(f"'{operator}' needs exactly two bounds, got {count}")
        elif _numeric_pair(values) and _as_float(values[0]) > _as_float(values[1]):
            problems.append(f"'{operator}' has a lower bound above its upper bound")
    elif operator in SET_OPERATORS:
        if not isinstance(values, list) or not values:
            problems.append(f"'{operator}' needs at least one value to match against")
    elif operator in UNARY_OPERATORS:
        if has_value or (isinstance(values, list) and values):
            problems.append(f"'{operator}' takes no value, but one is set")
    elif not has_value:
        problems.append(f"'{operator}' needs a value to compare against")

    tolerance = params.get("tolerance")
    if tolerance is not None and not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool):
        problems.append("tolerance must be a number")

    treat_missing = params.get("treat_missing_as")
    if treat_missing is not None and treat_missing not in {"fail", "pass", "skip"}:
        problems.append(f"treat_missing_as '{treat_missing}' must be fail, pass or skip")

    return problems


def _variable_problems(block: dict[str, Any], params: dict[str, Any]) -> list[str]:
    """Domain problems on a variable block's aggregate function."""
    if str(block.get("kind") or "") != "variable":
        return []
    aggregate = params.get("aggregate")
    if aggregate is None:
        return []
    if not isinstance(aggregate, str) or aggregate not in AGGREGATE_FUNCTIONS:
        return [f"'{aggregate}' is not a supported aggregate function"]
    return []


def _numeric_pair(values: list[Any]) -> bool:
    """True when both bounds are real numbers (bool is not a number here)."""
    return all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values)


def _as_float(value: Any) -> float:
    """Coerce an already-numeric bound to float."""
    return float(value)


# ── Registration ─────────────────────────────────────────────────────────────

_EAC_GRAPH_RULES: tuple[ValidationRule, ...] = (
    EacGraphBlockReferenceExists(),
    EacGraphNoCycles(),
    EacGraphSlotTypeCompatible(),
    EacGraphParameterDomain(),
)


def register_eac_graph_rules() -> None:
    """Register the block-graph rules with the core rule registry.

    Idempotent - the registry overwrites a rule by id, so a re-import or hot
    reload re-registers cleanly. Called from the module ``on_startup`` hook,
    which is what makes ``eac_graph`` a reachable rule set rather than a name
    nothing answers to.
    """
    for rule in _EAC_GRAPH_RULES:
        rule_registry.register(rule, [EAC_GRAPH_RULE_SET])
    logger.debug("Registered %d eac_graph validation rules", len(_EAC_GRAPH_RULES))

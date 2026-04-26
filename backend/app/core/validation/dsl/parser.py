# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""DSL parser — YAML/JSON document → typed AST.

The parser is the *only* entry point that touches user-supplied text
(see ``compile_rule`` in :mod:`.evaluator`). It is responsible for:

1. Safely loading YAML — :func:`yaml.safe_load` so ``!!python/object``
   tags raise ``ConstructorError`` instead of importing arbitrary
   modules.
2. Validating the document shape — every top-level key has a fixed
   type, every expression node is one of a handful of known kinds, and
   anything else is rejected.
3. Producing a typed :class:`RuleDefinition` AST that the evaluator can
   walk without re-parsing.

The grammar is deliberately tiny — see the module docstring of
:mod:`app.core.validation.dsl` for the rationale.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import yaml

from app.core.validation.engine import RuleCategory, Severity

# ── Public errors ──────────────────────────────────────────────────────────


class DSLError(Exception):
    """Base class for DSL parse / type / evaluation failures.

    Each subclass carries a stable ``message_key`` so the router layer
    can translate the error string consistently.
    """

    message_key: str = "compliance.dsl.error"

    def __init__(
        self,
        message: str,
        *,
        path: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.path = path
        self.details = details or {}


class DSLSyntaxError(DSLError):
    """Document could not be parsed as YAML/JSON, or required keys are missing."""

    message_key = "compliance.dsl.syntax_error"


class DSLTypeError(DSLError):
    """Document parsed but a value has the wrong type (e.g. severity not a string)."""

    message_key = "compliance.dsl.type_error"


# ── AST nodes ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FieldRef:
    """A dotted path expression — ``position.quantity``, ``boq.total``."""

    path: tuple[str, ...]


@dataclass(frozen=True)
class Literal:
    """A primitive constant (number / bool / string / None)."""

    value: int | float | str | bool | None


@dataclass(frozen=True)
class Comparison:
    """Binary comparison: left ``op`` right.

    ``op`` is one of: ``==`` ``!=`` ``<`` ``<=`` ``>`` ``>=``.
    Also includes ``in`` for membership checks against a literal list.

    ``left`` / ``right`` are :class:`Expression` values — quoted because
    :class:`Expression` is a forward-referenced type alias declared
    further down.
    """

    op: str
    left: Any  # Expression — see comment above.
    right: Any  # Expression


@dataclass(frozen=True)
class Logical:
    """Logical combinator — ``and`` / ``or`` / ``not``.

    For ``not``, ``operands`` has length 1; otherwise length >= 2.
    ``operands`` holds :class:`Expression` values (forward-referenced).
    """

    op: str
    operands: tuple[Any, ...]  # tuple[Expression, ...]


@dataclass(frozen=True)
class Aggregation:
    """``count`` / ``sum`` / ``avg`` / ``min`` / ``max`` over the active scope."""

    kind: str  # "count" | "sum" | "avg" | "min" | "max"
    field: FieldRef | None  # None for ``count`` of all items.


# An ``Expression`` is any of the following — modelled as a union via
# ``isinstance`` checks rather than a sum type for evaluator simplicity.
Expression = Comparison | Logical | Aggregation | FieldRef | Literal


@dataclass(frozen=True)
class ForEachAssert:
    """Iterate ``scope`` items and assert ``predicate`` on each.

    Failed iterations produce one :class:`RuleResult` each; the success
    path produces a single passing result so the report stays compact.
    """

    iter_var: str
    predicate: Expression


@dataclass(frozen=True)
class SingleAssert:
    """Single boolean check over the whole scope (no iteration)."""

    predicate: Expression


# Body union — what ``expression`` resolves to.
RuleBody = ForEachAssert | SingleAssert


@dataclass(frozen=True)
class RuleDefinition:
    """Top-level parsed rule — the AST root.

    All fields are validated by :func:`parse_definition`; constructing
    one directly bypasses those checks (don't).
    """

    rule_id: str
    name: str
    severity: Severity
    category: RuleCategory
    standard: str
    description: str
    scope: str
    body: RuleBody
    rule_sets: tuple[str, ...] = field(default_factory=tuple)


# ── Constants ──────────────────────────────────────────────────────────────

_VALID_COMPARE_OPS = frozenset({"==", "!=", "<", "<=", ">", ">=", "in"})
_VALID_LOGICAL_OPS = frozenset({"and", "or", "not"})
_VALID_AGG_KINDS = frozenset({"count", "sum", "avg", "min", "max"})

_REQUIRED_TOP_KEYS: frozenset[str] = frozenset({"rule_id", "name", "expression"})
_OPTIONAL_TOP_KEYS: frozenset[str] = frozenset(
    {
        "severity",
        "category",
        "standard",
        "description",
        "scope",
        "rule_sets",
    }
)
_ALLOWED_TOP_KEYS: frozenset[str] = _REQUIRED_TOP_KEYS | _OPTIONAL_TOP_KEYS

_DEFAULT_SEVERITY = Severity.WARNING
_DEFAULT_CATEGORY = RuleCategory.CUSTOM
_DEFAULT_STANDARD = "custom"
_DEFAULT_SCOPE = "data"

# Hard caps to keep evaluator runtime bounded on hostile rules.
_MAX_AST_DEPTH = 16
_MAX_LOGICAL_OPERANDS = 32
_MAX_LITERAL_LIST_LEN = 256
_MAX_FIELD_PATH_DEPTH = 8

# Identifier-name policy: lowercase letters, digits, underscore. Keeps
# evaluator field-access defenses simple — no dunders, no ``__class__``.
_IDENT_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_")


# ── Public API ─────────────────────────────────────────────────────────────


def parse_definition(source: str | dict[str, Any]) -> RuleDefinition:
    """Parse a YAML/JSON document or dict into a :class:`RuleDefinition`.

    Args:
        source: Raw YAML/JSON text or an already-decoded mapping.

    Returns:
        Validated :class:`RuleDefinition`.

    Raises:
        DSLSyntaxError: malformed YAML/JSON or missing required key.
        DSLTypeError: a key has the wrong type.
    """
    raw = _load_document(source)
    if not isinstance(raw, dict):
        raise DSLSyntaxError(
            "Compliance DSL document must be a mapping at the top level.",
            path="$",
        )

    _check_top_level_keys(raw)

    rule_id = _require_str(raw, "rule_id")
    if not _is_safe_identifier(rule_id, allow_dots=True):
        raise DSLTypeError(
            "rule_id must contain only [a-z0-9_.] characters.",
            path="$.rule_id",
            details={"value": rule_id},
        )

    name = _require_str(raw, "name")
    if not name.strip():
        raise DSLTypeError("rule name must not be empty.", path="$.name")

    severity = _parse_severity(raw.get("severity", _DEFAULT_SEVERITY.value))
    category = _parse_category(raw.get("category", _DEFAULT_CATEGORY.value))
    standard = _optional_str(raw, "standard", _DEFAULT_STANDARD)
    description = _optional_str(raw, "description", "")
    scope = _optional_str(raw, "scope", _DEFAULT_SCOPE)
    if not _is_safe_path(scope):
        raise DSLTypeError(
            "scope must be a dotted path like 'boq.positions'.",
            path="$.scope",
            details={"value": scope},
        )

    rule_sets_raw = raw.get("rule_sets")
    rule_sets: tuple[str, ...] = ()
    if rule_sets_raw is not None:
        if not isinstance(rule_sets_raw, list) or not all(
            isinstance(s, str) for s in rule_sets_raw
        ):
            raise DSLTypeError(
                "rule_sets must be a list of strings.",
                path="$.rule_sets",
            )
        rule_sets = tuple(s.strip() for s in rule_sets_raw if s and s.strip())

    body = _parse_body(raw["expression"], path="$.expression")

    return RuleDefinition(
        rule_id=rule_id,
        name=name,
        severity=severity,
        category=category,
        standard=standard,
        description=description,
        scope=scope,
        body=body,
        rule_sets=rule_sets,
    )


def validate_definition(source: str | dict[str, Any]) -> tuple[bool, str | None]:
    """Lint a definition without raising.

    Returns:
        ``(True, None)`` on success, ``(False, "<error message>")``
        otherwise. Used by the ``/validate-syntax`` endpoint to give
        users live feedback before they hit save.
    """
    try:
        parse_definition(source)
        return True, None
    except DSLError as exc:
        return False, str(exc)


# ── Internals ──────────────────────────────────────────────────────────────


def _load_document(source: str | dict[str, Any]) -> Any:
    """Decode user-supplied source (string-or-dict) into a Python value."""
    if isinstance(source, dict):
        return source
    if not isinstance(source, str):
        raise DSLSyntaxError(
            "DSL source must be a YAML/JSON string or a dict.",
            path="$",
        )
    text = source.strip()
    if not text:
        raise DSLSyntaxError("DSL source is empty.", path="$")

    # Try JSON first — strict, fast, and unambiguous. Fall back to YAML
    # (safe_load only) for the user-friendly path.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise DSLSyntaxError(
            f"Invalid YAML/JSON: {exc}",
            path="$",
        ) from exc


def _check_top_level_keys(doc: dict[str, Any]) -> None:
    keys = set(doc.keys())
    missing = _REQUIRED_TOP_KEYS - keys
    if missing:
        raise DSLSyntaxError(
            f"Missing required keys: {sorted(missing)}",
            path="$",
            details={"missing": sorted(missing)},
        )
    unknown = keys - _ALLOWED_TOP_KEYS
    if unknown:
        raise DSLSyntaxError(
            f"Unknown top-level keys: {sorted(unknown)}",
            path="$",
            details={"unknown": sorted(unknown)},
        )


def _require_str(doc: dict[str, Any], key: str) -> str:
    value = doc.get(key)
    if not isinstance(value, str):
        raise DSLTypeError(
            f"'{key}' must be a string.",
            path=f"$.{key}",
            details={"got_type": type(value).__name__},
        )
    return value


def _optional_str(doc: dict[str, Any], key: str, default: str) -> str:
    value = doc.get(key, default)
    if not isinstance(value, str):
        raise DSLTypeError(
            f"'{key}' must be a string.",
            path=f"$.{key}",
            details={"got_type": type(value).__name__},
        )
    return value


def _parse_severity(value: Any) -> Severity:
    if isinstance(value, Severity):
        return value
    if not isinstance(value, str):
        raise DSLTypeError(
            "severity must be one of: error, warning, info.",
            path="$.severity",
        )
    try:
        return Severity(value.strip().lower())
    except ValueError as exc:
        raise DSLTypeError(
            "severity must be one of: error, warning, info.",
            path="$.severity",
            details={"value": value},
        ) from exc


def _parse_category(value: Any) -> RuleCategory:
    if isinstance(value, RuleCategory):
        return value
    if not isinstance(value, str):
        raise DSLTypeError(
            "category must be a string.",
            path="$.category",
        )
    try:
        return RuleCategory(value.strip().lower())
    except ValueError as exc:
        raise DSLTypeError(
            "category must be one of: structure, completeness, "
            "consistency, compliance, quality, custom.",
            path="$.category",
            details={"value": value},
        ) from exc


def _parse_body(node: Any, *, path: str) -> RuleBody:
    if not isinstance(node, dict):
        raise DSLTypeError(
            "expression must be a mapping.",
            path=path,
        )
    if "forEach" in node:
        iter_var = node["forEach"]
        if not isinstance(iter_var, str) or not _is_safe_identifier(iter_var):
            raise DSLTypeError(
                "forEach must be a simple identifier (letters, digits, underscore).",
                path=f"{path}.forEach",
                details={"value": iter_var},
            )
        if "assert" not in node:
            raise DSLSyntaxError(
                "forEach block requires a sibling 'assert' clause.",
                path=path,
            )
        unknown = set(node.keys()) - {"forEach", "assert"}
        if unknown:
            raise DSLSyntaxError(
                f"Unknown keys in forEach block: {sorted(unknown)}",
                path=path,
            )
        predicate = _parse_expression(
            node["assert"], path=f"{path}.assert", depth=0,
        )
        return ForEachAssert(iter_var=iter_var, predicate=predicate)

    if "assert" in node:
        unknown = set(node.keys()) - {"assert"}
        if unknown:
            raise DSLSyntaxError(
                f"Unknown keys in assert block: {sorted(unknown)}",
                path=path,
            )
        predicate = _parse_expression(
            node["assert"], path=f"{path}.assert", depth=0,
        )
        return SingleAssert(predicate=predicate)

    raise DSLSyntaxError(
        "expression must contain either 'forEach' + 'assert' or just 'assert'.",
        path=path,
    )


def _parse_expression(node: Any, *, path: str, depth: int) -> Expression:
    if depth > _MAX_AST_DEPTH:
        raise DSLSyntaxError(
            f"Expression nested deeper than {_MAX_AST_DEPTH} levels.",
            path=path,
        )

    # Literal scalars — numbers, bools, None.
    if isinstance(node, bool) or node is None:
        return Literal(value=node)
    if isinstance(node, (int, float)):
        return Literal(value=node)

    # Strings can be either a quoted literal or a dotted field-ref. We
    # distinguish syntactically: if the string starts with a single quote
    # we treat it as a literal, otherwise we attempt to parse it as a
    # field-ref or a comparison operator embedded into a longer string.
    if isinstance(node, str):
        return _parse_string_expression(node, path=path)

    if isinstance(node, list):
        # Lists at expression position are only legal as the right-hand
        # side of an ``in`` comparison — but at this point we don't know
        # the parent. Reject here; ``_parse_compare`` will accept lists
        # via ``_parse_literal_list``.
        raise DSLTypeError(
            "Bare list is not a valid expression — wrap with 'in: <field>: [...]'.",
            path=path,
        )

    if isinstance(node, dict):
        if len(node) != 1:
            raise DSLSyntaxError(
                "Expression mapping must have exactly one operator key.",
                path=path,
                details={"keys": sorted(node.keys())},
            )
        ((op, inner),) = node.items()

        if op in _VALID_LOGICAL_OPS:
            return _parse_logical(op, inner, path=path, depth=depth)

        if op in _VALID_COMPARE_OPS:
            return _parse_compare(op, inner, path=path, depth=depth)

        if op in _VALID_AGG_KINDS:
            return _parse_aggregation(op, inner, path=path)

        raise DSLSyntaxError(
            f"Unknown operator '{op}'.",
            path=path,
            details={"operator": op},
        )

    raise DSLTypeError(
        f"Unsupported expression node type: {type(node).__name__}",
        path=path,
    )


def _parse_string_expression(node: str, *, path: str) -> Expression:
    """Parse a string at expression position — literal, ref, or shorthand."""
    text = node.strip()
    if not text:
        raise DSLTypeError("Empty string is not a valid expression.", path=path)

    # Shorthand for "the whole identifier in single-quotes" → string literal.
    if (text.startswith("'") and text.endswith("'") and len(text) >= 2) or (
        text.startswith('"') and text.endswith('"') and len(text) >= 2
    ):
        return Literal(value=text[1:-1])

    # Inline binary comparison — ``position.quantity > 0``. Allows users
    # to write naturally: ``assert: position.quantity > 0``.
    for op in ("<=", ">=", "==", "!=", "<", ">"):
        if f" {op} " in text:
            left, right = text.split(f" {op} ", 1)
            left_node = _parse_atom(left.strip(), path=f"{path}.lhs")
            right_node = _parse_atom(right.strip(), path=f"{path}.rhs")
            return Comparison(op=op, left=left_node, right=right_node)

    # Plain field-ref / boolean coercion.
    return _parse_atom(text, path=path)


def _parse_atom(text: str, *, path: str) -> Expression:
    """Parse a single token — number / bool / null / string / field-ref."""
    if text in {"true", "false"}:
        return Literal(value=(text == "true"))
    if text in {"null", "none", "None"}:
        return Literal(value=None)

    # Try integer / float.
    try:
        return Literal(value=int(text))
    except ValueError:
        pass
    try:
        return Literal(value=float(text))
    except ValueError:
        pass

    if (text.startswith("'") and text.endswith("'") and len(text) >= 2) or (
        text.startswith('"') and text.endswith('"') and len(text) >= 2
    ):
        return Literal(value=text[1:-1])

    if not _is_safe_path(text):
        raise DSLTypeError(
            "Atom must be a literal, boolean, null, or dotted field reference.",
            path=path,
            details={"value": text},
        )
    return FieldRef(path=tuple(text.split(".")))


def _parse_logical(
    op: str, operands: Any, *, path: str, depth: int,
) -> Logical:
    if op == "not":
        # Single operand — accept either a list-of-1 or a bare expression.
        if isinstance(operands, list):
            if len(operands) != 1:
                raise DSLSyntaxError(
                    "'not' takes exactly one operand.",
                    path=f"{path}.not",
                )
            inner = operands[0]
        else:
            inner = operands
        parsed = _parse_expression(inner, path=f"{path}.not", depth=depth + 1)
        return Logical(op=op, operands=(parsed,))

    # ``and`` / ``or`` — list of operands.
    if not isinstance(operands, list) or len(operands) < 2:
        raise DSLSyntaxError(
            f"'{op}' requires a list of at least two operands.",
            path=f"{path}.{op}",
        )
    if len(operands) > _MAX_LOGICAL_OPERANDS:
        raise DSLSyntaxError(
            f"'{op}' may not have more than {_MAX_LOGICAL_OPERANDS} operands.",
            path=f"{path}.{op}",
        )
    parsed_ops = tuple(
        _parse_expression(op_node, path=f"{path}.{op}[{i}]", depth=depth + 1)
        for i, op_node in enumerate(operands)
    )
    return Logical(op=op, operands=parsed_ops)


def _parse_compare(
    op: str, inner: Any, *, path: str, depth: int,
) -> Comparison:
    """Parse a structured comparison node — ``{">=": [a, b]}`` or
    ``{"in": {"value": x, "list": [...]}}``."""
    if op == "in":
        if not isinstance(inner, dict):
            raise DSLSyntaxError(
                "'in' must be a mapping with 'value' and 'list' keys.",
                path=f"{path}.in",
            )
        unknown = set(inner.keys()) - {"value", "list"}
        if unknown or "value" not in inner or "list" not in inner:
            raise DSLSyntaxError(
                "'in' requires exactly two keys: 'value' and 'list'.",
                path=f"{path}.in",
            )
        value_node = _parse_expression(
            inner["value"], path=f"{path}.in.value", depth=depth + 1,
        )
        list_node = _parse_literal_list(
            inner["list"], path=f"{path}.in.list",
        )
        return Comparison(op=op, left=value_node, right=list_node)

    # Standard binary comparison — list of two.
    if not isinstance(inner, list) or len(inner) != 2:
        raise DSLSyntaxError(
            f"'{op}' requires a list of exactly two operands.",
            path=f"{path}.{op}",
        )
    left = _parse_expression(inner[0], path=f"{path}.{op}[0]", depth=depth + 1)
    right = _parse_expression(inner[1], path=f"{path}.{op}[1]", depth=depth + 1)
    return Comparison(op=op, left=left, right=right)


def _parse_literal_list(node: Any, *, path: str) -> Literal:
    if not isinstance(node, list):
        raise DSLTypeError("'in' rhs must be a list literal.", path=path)
    if len(node) > _MAX_LITERAL_LIST_LEN:
        raise DSLTypeError(
            f"List literal exceeds {_MAX_LITERAL_LIST_LEN} entries.",
            path=path,
        )
    out: list[Any] = []
    for i, item in enumerate(node):
        if isinstance(item, (int, float, str, bool)) or item is None:
            out.append(item)
        else:
            raise DSLTypeError(
                "List literal may only contain primitives.",
                path=f"{path}[{i}]",
            )
    return Literal(value=tuple(out))  # type: ignore[arg-type]


def _parse_aggregation(op: str, inner: Any, *, path: str) -> Aggregation:
    if op == "count":
        # ``count`` may target the iterating scope (no field) or a
        # boolean-yielding sub-clause. We currently support only the
        # ``count of items`` form — a future iteration can extend.
        if inner in (None, "", "*"):
            return Aggregation(kind=op, field=None)
        if isinstance(inner, str) and _is_safe_path(inner):
            return Aggregation(kind=op, field=FieldRef(path=tuple(inner.split("."))))
        raise DSLTypeError(
            "'count' takes either no argument or a field reference.",
            path=f"{path}.count",
        )

    # sum / avg / min / max — require a field reference.
    if not isinstance(inner, str) or not _is_safe_path(inner):
        raise DSLTypeError(
            f"'{op}' requires a field reference (e.g. 'position.quantity').",
            path=f"{path}.{op}",
        )
    return Aggregation(kind=op, field=FieldRef(path=tuple(inner.split("."))))


def _is_safe_identifier(name: str, *, allow_dots: bool = False) -> bool:
    if not name:
        return False
    chars = _IDENT_CHARS | ({"."} if allow_dots else set())
    if any(c not in chars for c in name.lower()):
        return False
    if name.startswith(".") or name.endswith("."):
        return False
    return "__" not in name


def _is_safe_path(text: str) -> bool:
    if not text:
        return False
    parts = text.split(".")
    if len(parts) > _MAX_FIELD_PATH_DEPTH:
        return False
    return all(_is_safe_identifier(p) for p in parts)


__all__ = [
    "Aggregation",
    "Comparison",
    "DSLError",
    "DSLSyntaxError",
    "DSLTypeError",
    "Expression",
    "FieldRef",
    "ForEachAssert",
    "Literal",
    "Logical",
    "RuleBody",
    "RuleDefinition",
    "SingleAssert",
    "parse_definition",
    "validate_definition",
]

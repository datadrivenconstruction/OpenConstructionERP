# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Canonical-format-aware Smart View rule engine for the BIM module.

Smart Views replace the legacy IFC-biased "filter_criteria" predicate
(which only supported ``element_type`` / ``category`` / ``storey`` and
``property_filter`` key=value exact matches) with a typed, nestable
rule tree that works for **any** CAD source the converter emits:

    - IFC      (IfcWall, IfcSlab, properties.* from PropertySets)
    - RVT/Revit  (Walls / Doors / Floors, properties.family / .type_name)
    - DWG      (properties.layer / .block / .object_class)
    - DGN      (properties.level / .cell)
    - Photos   (CV-extracted properties.material / .confidence)

The evaluator does not care which source produced an element: every
predicate operates on the canonical fields exposed by ``BIMElement``:

    id, name, element_type, category (via properties.category),
    discipline, storey, properties.{*}, quantities.{*},
    geometry.{area_m2, volume_m3, length_m, height_m, thickness_m}

A *rule tree* is a JSON object of the form::

    {
      "op": "AND" | "OR",
      "rules": [
        { "field": "element_type", "op": "in",
          "value": ["IfcWall", "Walls"] },
        { "field": "geometry.area_m2", "op": "between",
          "value": [5, 20] },
        {
          "op": "OR",
          "rules": [
            { "field": "properties.material", "op": "contains",
              "value": "concrete" },
            { "field": "properties.fire_rating", "op": "=",
              "value": "F90" }
          ]
        }
      ]
    }

Safety guards (enforced at validation time):

    - max depth: 6 nested groups
    - max leaves: 100 leaf rules
    - regex max length: 200 chars (and compile-time check)
    - string field max length: 80 chars
    - value list max length: 200 items
    - field whitelist by prefix: ``identity.``, ``geometry.``,
      ``properties.``, ``quantities.``, or one of the canonical
      top-level columns.

The engine evaluates rules **in Python** against pre-fetched
``BIMElement`` rows.  We deliberately avoid translating to SQL: SQLite
in dev can't handle the JSONB containment we need, the rule trees are
small (< 100 leaves), and the candidate set is already capped at
``DYNAMIC_GROUP_CAP`` = 50 000.  A bounded-element-count loop in pure
Python is well under 50 ms for realistic models.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from fastapi import HTTPException, status

# ── Constants ──────────────────────────────────────────────────────────────

MAX_DEPTH = 6
MAX_LEAVES = 200
MAX_REGEX_LEN = 200
MAX_STRING_LEN = 80
MAX_VALUE_LIST = 200

# Canonical top-level columns on BIMElement that are queryable.  Anything
# else MUST be prefixed (``properties.``, ``quantities.``, ``geometry.``,
# ``identity.``) so the field whitelist stays explicit.
_TOP_LEVEL_FIELDS: set[str] = {
    "id",
    "name",
    "element_type",
    "discipline",
    "storey",
    "category",  # alias for properties.category
}

# Geometry keys recognised inside ``geometry.<key>`` paths.  We accept
# both canonical-format names (area_m2, volume_m3, length_m) and the
# common Revit / IFC quantity-name aliases so a user picking from the
# Property Catalog can use the displayed key verbatim.
_GEOMETRY_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "area_m2": ("area_m2", "Area", "area", "Gross Area", "Surface Area"),
    "volume_m3": ("volume_m3", "Volume", "volume", "Gross Volume"),
    "length_m": ("length_m", "Length", "length"),
    "height_m": ("height_m", "Height", "height"),
    "thickness_m": ("thickness_m", "Thickness", "thickness", "Width", "width"),
    "weight_kg": ("weight_kg", "Weight", "weight", "Mass", "mass"),
    "count": ("count", "Count"),
}


# ── Operators ──────────────────────────────────────────────────────────────


OP_EQ = "="
OP_NE = "!="
OP_CONTAINS = "contains"
OP_STARTS_WITH = "starts_with"
OP_ENDS_WITH = "ends_with"
OP_REGEX = "regex"
OP_GT = ">"
OP_LT = "<"
OP_GTE = ">="
OP_LTE = "<="
OP_BETWEEN = "between"
OP_IN = "in"
OP_NOT_IN = "not_in"
OP_EMPTY = "is_empty"
OP_NOT_EMPTY = "is_not_empty"

_STRING_OPS = {
    OP_EQ,
    OP_NE,
    OP_CONTAINS,
    OP_STARTS_WITH,
    OP_ENDS_WITH,
    OP_REGEX,
    OP_IN,
    OP_NOT_IN,
    OP_EMPTY,
    OP_NOT_EMPTY,
}
_NUMERIC_OPS = {OP_EQ, OP_NE, OP_GT, OP_LT, OP_GTE, OP_LTE, OP_BETWEEN, OP_IN, OP_NOT_IN, OP_EMPTY, OP_NOT_EMPTY}
_ALL_OPS = _STRING_OPS | _NUMERIC_OPS


# ── Exceptions ─────────────────────────────────────────────────────────────


class SmartViewRuleError(HTTPException):
    """Raised on a structurally invalid rule tree.  400 by default."""

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


# ── Validation ─────────────────────────────────────────────────────────────


def _ensure_dict(node: Any, where: str) -> dict[str, Any]:
    if not isinstance(node, dict):
        raise SmartViewRuleError(f"{where}: expected object, got {type(node).__name__}")
    return node


def _validate_field(field: Any) -> str:
    if not isinstance(field, str):
        raise SmartViewRuleError(f"field must be string, got {type(field).__name__}")
    if len(field) > MAX_STRING_LEN:
        raise SmartViewRuleError(f"field too long (>{MAX_STRING_LEN} chars)")
    if not field:
        raise SmartViewRuleError("field cannot be empty")
    # Whitelist: top-level or known prefix.
    if field in _TOP_LEVEL_FIELDS:
        return field
    for prefix in ("properties.", "quantities.", "geometry.", "identity."):
        if field.startswith(prefix) and len(field) > len(prefix):
            return field
    raise SmartViewRuleError(
        f"field '{field}' is not in the allowed set (top-level or properties./quantities./geometry./identity. prefix)"
    )


def _coerce_number(value: Any, where: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise SmartViewRuleError(f"{where}: expected numeric value") from exc


def _validate_leaf(node: dict[str, Any]) -> None:
    field = _validate_field(node.get("field"))
    op = node.get("op")
    if op not in _ALL_OPS:
        raise SmartViewRuleError(f"unknown operator '{op}'")
    value = node.get("value")

    # Operator-specific value validation.
    if op in (OP_EMPTY, OP_NOT_EMPTY):
        return  # No value needed.

    if op == OP_BETWEEN:
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise SmartViewRuleError(f"{field} {op}: value must be [min, max]")
        _coerce_number(value[0], f"{field} between[0]")
        _coerce_number(value[1], f"{field} between[1]")
        return

    if op in (OP_IN, OP_NOT_IN):
        if not isinstance(value, list):
            raise SmartViewRuleError(f"{field} {op}: value must be array")
        if len(value) > MAX_VALUE_LIST:
            raise SmartViewRuleError(f"{field} {op}: value array too long (>{MAX_VALUE_LIST} items)")
        return

    if op == OP_REGEX:
        if not isinstance(value, str):
            raise SmartViewRuleError(f"{field} regex: value must be string")
        if len(value) > MAX_REGEX_LEN:
            raise SmartViewRuleError(f"{field} regex: pattern too long (>{MAX_REGEX_LEN} chars)")
        try:
            re.compile(value)
        except re.error as exc:
            raise SmartViewRuleError(f"{field} regex: invalid pattern: {exc}") from exc
        return

    if op in _NUMERIC_OPS - _STRING_OPS:  # gt/lt/gte/lte
        _coerce_number(value, f"{field} {op}")
        return

    # Generic string/scalar value - must be string or number, length-bounded.
    if isinstance(value, str) and len(value) > MAX_STRING_LEN * 4:
        raise SmartViewRuleError(f"{field} {op}: value string too long")


def _validate_tree(node: Any, depth: int, leaf_count: list[int]) -> None:
    n = _ensure_dict(node, f"node at depth {depth}")
    if depth > MAX_DEPTH:
        raise SmartViewRuleError(f"rule tree too deep (>{MAX_DEPTH})")

    # Group node?
    if "op" in n and n["op"] in ("AND", "OR"):
        rules = n.get("rules")
        if not isinstance(rules, list):
            raise SmartViewRuleError(f"group at depth {depth}: 'rules' must be array")
        if not rules:
            # Empty groups are allowed (match-all for AND, match-none for OR
            # - see _eval_node).  Don't raise.
            return
        for child in rules:
            _validate_tree(child, depth + 1, leaf_count)
        return

    # Leaf node.
    leaf_count[0] += 1
    if leaf_count[0] > MAX_LEAVES:
        raise SmartViewRuleError(f"rule tree has too many leaves (>{MAX_LEAVES})")
    _validate_leaf(n)


def validate_rule_tree(tree: Any) -> dict[str, Any]:
    """Validate and return the rule tree.  Raises SmartViewRuleError on failure.

    A None / empty tree is treated as "match everything" (returned as
    ``{"op": "AND", "rules": []}``) so callers can save smart views with
    a draft / pending predicate.
    """
    if tree is None or tree == {} or tree == []:
        return {"op": "AND", "rules": []}
    if not isinstance(tree, dict):
        raise SmartViewRuleError("rule tree must be an object")
    # If a caller hands us a single leaf at the root, wrap it in an AND
    # group so the evaluator only has one structural case to handle.
    if "op" in tree and tree["op"] in ("AND", "OR"):
        _validate_tree(tree, 0, [0])
        return tree
    if "field" in tree:
        wrapped = {"op": "AND", "rules": [tree]}
        _validate_tree(wrapped, 0, [0])
        return wrapped
    raise SmartViewRuleError("rule tree root must be a group (AND/OR) or a leaf")


# ── Field resolution ───────────────────────────────────────────────────────


def _resolve_field(element: Any, field: str) -> Any:
    """Extract the value of *field* from a BIMElement-like object/dict.

    Accepts both ORM rows (attribute access) and dicts (key access) so the
    evaluator can run against fully-loaded rows OR against client-side
    canonical-format payloads in tests.
    """

    def _get(obj: Any, key: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    # Top-level columns.
    if field == "category":
        # Canonical alias - resolves to properties.category for IFC/RVT and
        # to element_type for DGN / DWG (where "category" really is the layer).
        props = _get(element, "properties") or {}
        cat = props.get("category") if isinstance(props, dict) else None
        if cat:
            return cat
        return _get(element, "element_type")

    if field in _TOP_LEVEL_FIELDS:
        return _get(element, field)

    if field.startswith("identity."):
        sub = field[len("identity.") :]
        # identity.din276 / identity.nrm / identity.masterformat live inside
        # properties.classification (canonical format spec).
        props = _get(element, "properties") or {}
        if not isinstance(props, dict):
            return None
        classif = props.get("classification") if isinstance(props.get("classification"), dict) else {}
        if sub in classif:
            return classif[sub]
        return props.get(sub)

    if field.startswith("properties."):
        key = field[len("properties.") :]
        props = _get(element, "properties") or {}
        if not isinstance(props, dict):
            return None
        if key in props:
            return props[key]
        # Case-insensitive fallback so IFC PropertySet keys (often
        # MixedCase) match the catalog-displayed key.
        lower = key.lower()
        for k, v in props.items():
            if isinstance(k, str) and k.lower() == lower:
                return v
        return None

    if field.startswith("quantities."):
        key = field[len("quantities.") :]
        qty = _get(element, "quantities") or {}
        if not isinstance(qty, dict):
            return None
        if key in qty:
            return qty[key]
        lower = key.lower()
        for k, v in qty.items():
            if isinstance(k, str) and k.lower() == lower:
                return v
        return None

    if field.startswith("geometry."):
        key = field[len("geometry.") :]
        # Geometry values live in quantities for backend-converted models
        # (canonical format) - check the alias map then fall through to
        # the raw quantities map.
        qty = _get(element, "quantities") or {}
        if not isinstance(qty, dict):
            qty = {}
        aliases = _GEOMETRY_KEY_ALIASES.get(key, (key,))
        for alias in aliases:
            if alias in qty and qty[alias] is not None:
                return qty[alias]
        return None

    return None


# ── Evaluation ─────────────────────────────────────────────────────────────


def _to_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v)


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _eval_leaf(element: Any, leaf: dict[str, Any]) -> bool:
    field = leaf["field"]
    op = leaf["op"]
    val = leaf.get("value")
    actual = _resolve_field(element, field)

    # Empty checks first - they don't care about value type.
    if op == OP_EMPTY:
        return actual is None or actual == "" or actual == [] or actual == {}
    if op == OP_NOT_EMPTY:
        return not (actual is None or actual == "" or actual == [] or actual == {})

    # String operators normalise both sides to lowercase string.
    if op in (OP_CONTAINS, OP_STARTS_WITH, OP_ENDS_WITH, OP_REGEX):
        s = _to_str(actual).lower()
        target = _to_str(val).lower()
        if op == OP_CONTAINS:
            return target in s
        if op == OP_STARTS_WITH:
            return s.startswith(target)
        if op == OP_ENDS_WITH:
            return s.endswith(target)
        if op == OP_REGEX:
            try:
                return bool(re.search(val, _to_str(actual), flags=re.IGNORECASE))
            except re.error:
                return False

    if op == OP_IN:
        if not isinstance(val, list):
            return False
        # Match by stringified equality so "330" matches 330.
        s_actual = _to_str(actual)
        return any(_to_str(v) == s_actual for v in val) or actual in val

    if op == OP_NOT_IN:
        if not isinstance(val, list):
            return True
        s_actual = _to_str(actual)
        return not (any(_to_str(v) == s_actual for v in val) or actual in val)

    # Equality / inequality - try numeric first when both sides look
    # numeric, fall back to string compare.  ``=`` is case-insensitive
    # for strings so users typing "concrete" match "Concrete".
    if op in (OP_EQ, OP_NE):
        a_num = _to_float(actual)
        v_num = _to_float(val)
        if a_num is not None and v_num is not None:
            eq = abs(a_num - v_num) < 1e-9
        else:
            eq = _to_str(actual).lower() == _to_str(val).lower()
        return eq if op == OP_EQ else not eq

    # Numeric-only operators.
    a_num = _to_float(actual)
    if a_num is None:
        return False
    if op == OP_BETWEEN:
        lo = _to_float(val[0]) if isinstance(val, (list, tuple)) else None
        hi = _to_float(val[1]) if isinstance(val, (list, tuple)) else None
        if lo is None or hi is None:
            return False
        if lo > hi:
            lo, hi = hi, lo
        return lo <= a_num <= hi
    v_num = _to_float(val)
    if v_num is None:
        return False
    if op == OP_GT:
        return a_num > v_num
    if op == OP_LT:
        return a_num < v_num
    if op == OP_GTE:
        return a_num >= v_num
    if op == OP_LTE:
        return a_num <= v_num
    return False


def _eval_node(element: Any, node: dict[str, Any]) -> bool:
    """Recursively evaluate a (validated) rule tree against one element."""
    if "op" in node and node["op"] in ("AND", "OR"):
        rules = node.get("rules", [])
        if not rules:
            # Empty AND matches everything; empty OR matches nothing.
            return node["op"] == "AND"
        if node["op"] == "AND":
            return all(_eval_node(element, child) for child in rules)
        return any(_eval_node(element, child) for child in rules)
    return _eval_leaf(element, node)


def evaluate(tree: dict[str, Any], elements: Iterable[Any]) -> list[Any]:
    """Return the subset of *elements* matching *tree*.

    The tree is assumed to have already been passed through
    :func:`validate_rule_tree`.
    """
    return [el for el in elements if _eval_node(element=el, node=tree)]


# ── Property catalog (Phase 2.A: Identity / Geometry / Properties) ─────────


@dataclass
class PropertyEntry:
    """One row in the Property Catalog returned to the UI."""

    field: str
    label: str
    group: Literal["identity", "geometry", "properties", "quantities"]
    data_type: Literal["string", "number", "enum", "boolean"]
    source_formats: list[str]
    sample_values: list[str]
    distinct_count: int
    truncated: bool


def _source_format_of(model_format: str | None) -> str:
    if not model_format:
        return "other"
    fmt = model_format.lower()
    if "rvt" in fmt or "revit" in fmt:
        return "RVT"
    if "ifc" in fmt:
        return "IFC"
    if "dwg" in fmt:
        return "DWG"
    if "dgn" in fmt:
        return "DGN"
    if "pdf" in fmt:
        return "PDF"
    return fmt.upper()


def build_property_catalog(
    elements: list[Any],
    model_format: str | None = None,
    sample_cap: int = 25,
) -> list[PropertyEntry]:
    """Build the canonical-format property catalog for a model.

    Walks the in-memory element rows once and produces a deduplicated
    list of every queryable field grouped by Identity / Geometry /
    Properties / Quantities, with sample distinct values.  Source-format
    badge is supplied by the caller (``model_format``) and stamped onto
    every row; mixed-format federations should call this once per model
    and merge.
    """
    src = _source_format_of(model_format)
    entries: dict[str, dict[str, Any]] = {}

    def _record(field: str, group: str, value: Any) -> None:
        bucket = entries.setdefault(
            field,
            {"group": group, "values": set(), "numeric_count": 0, "total": 0},
        )
        bucket["total"] += 1
        if value is None or value == "":
            return
        # Track distinct values (string-cast for storage).
        s_val = str(value)
        if len(bucket["values"]) < sample_cap * 8:  # Cap memory while sampling.
            bucket["values"].add(s_val)
        if _to_float(value) is not None:
            bucket["numeric_count"] += 1

    # Identity - every element always has these.
    for el in elements:
        _record("name", "identity", getattr(el, "name", None) or (el.get("name") if isinstance(el, dict) else None))
        _record(
            "element_type",
            "identity",
            getattr(el, "element_type", None) or (el.get("element_type") if isinstance(el, dict) else None),
        )
        _record(
            "discipline",
            "identity",
            getattr(el, "discipline", None) or (el.get("discipline") if isinstance(el, dict) else None),
        )
        _record(
            "storey", "identity", getattr(el, "storey", None) or (el.get("storey") if isinstance(el, dict) else None)
        )

        props = getattr(el, "properties", None)
        if props is None and isinstance(el, dict):
            props = el.get("properties")
        if not isinstance(props, dict):
            props = {}
        # Identity from classification.
        classif = props.get("classification") if isinstance(props.get("classification"), dict) else {}
        for k, v in classif.items():
            _record(f"identity.{k}", "identity", v)
        # Plain properties.
        for k, v in props.items():
            if k == "classification":
                continue
            if isinstance(v, (dict, list)):
                # Don't enumerate nested structures - flag as present only.
                _record(f"properties.{k}", "properties", "<complex>")
                continue
            _record(f"properties.{k}", "properties", v)

        # Geometry - surface canonical geometry keys derived from quantities.
        qty = getattr(el, "quantities", None)
        if qty is None and isinstance(el, dict):
            qty = el.get("quantities")
        if not isinstance(qty, dict):
            qty = {}
        for canon, aliases in _GEOMETRY_KEY_ALIASES.items():
            for alias in aliases:
                if alias in qty and qty[alias] is not None:
                    _record(f"geometry.{canon}", "geometry", qty[alias])
                    break
        # Raw quantities - anything not picked up by the geometry aliases.
        for k, v in qty.items():
            if isinstance(v, (dict, list)):
                continue
            _record(f"quantities.{k}", "quantities", v)

    catalog: list[PropertyEntry] = []
    for field, bucket in entries.items():
        # Skip identity fields with zero non-null values (annotation-only
        # elements that have e.g. no storey).
        if not bucket["values"]:
            continue
        values_sorted = sorted(bucket["values"])
        truncated = len(values_sorted) > sample_cap
        sampled = values_sorted[:sample_cap]
        # Type inference: enum if ≤ 20 distinct values and not all numeric;
        # number if ≥ 70% numeric; string otherwise.
        n_distinct = len(values_sorted)
        n_total = max(1, bucket["total"])
        numeric_ratio = bucket["numeric_count"] / n_total
        if numeric_ratio >= 0.7:
            data_type: Literal["string", "number", "enum", "boolean"] = "number"
        elif n_distinct <= 20:
            data_type = "enum"
        else:
            data_type = "string"

        label = field.split(".")[-1].replace("_", " ")
        catalog.append(
            PropertyEntry(
                field=field,
                label=label,
                group=bucket["group"],  # type: ignore[arg-type]
                data_type=data_type,
                source_formats=[src] if src != "other" else [],
                sample_values=sampled,
                distinct_count=n_distinct,
                truncated=truncated,
            )
        )

    # Stable sort: group then field name.
    group_order = {"identity": 0, "geometry": 1, "quantities": 2, "properties": 3}
    catalog.sort(key=lambda e: (group_order.get(e.group, 99), e.field))
    return catalog


def catalog_to_dict(entry: PropertyEntry) -> dict[str, Any]:
    return {
        "field": entry.field,
        "label": entry.label,
        "group": entry.group,
        "data_type": entry.data_type,
        "source_formats": entry.source_formats,
        "sample_values": entry.sample_values,
        "distinct_count": entry.distinct_count,
        "truncated": entry.truncated,
    }


# ── Legacy adapter - convert old filter_criteria into a rule tree ──────────


def legacy_criteria_to_tree(criteria: dict[str, Any] | None) -> dict[str, Any]:
    """Translate the pre-Smart-View ``filter_criteria`` shape into a rule tree.

    The old shape only supported AND-joined equality / IN predicates and
    a single ``property_filter`` dict.  Every existing saved group can be
    converted to a rule tree with no semantic change.
    """
    if not criteria or not isinstance(criteria, dict):
        return {"op": "AND", "rules": []}
    leaves: list[dict[str, Any]] = []

    for legacy_field in ("element_type", "discipline", "storey"):
        v = criteria.get(legacy_field)
        if not v:
            continue
        if isinstance(v, list):
            leaves.append({"field": legacy_field, "op": OP_IN, "value": [str(x) for x in v]})
        else:
            leaves.append({"field": legacy_field, "op": OP_EQ, "value": str(v)})

    category = criteria.get("category")
    if category:
        if isinstance(category, list):
            leaves.append({"field": "category", "op": OP_IN, "value": [str(x) for x in category]})
        else:
            leaves.append({"field": "category", "op": OP_EQ, "value": str(category)})

    name = criteria.get("name_contains")
    if isinstance(name, str) and name:
        leaves.append({"field": "name", "op": OP_CONTAINS, "value": name})

    pf = criteria.get("property_filter")
    if isinstance(pf, dict):
        for k, v in pf.items():
            if v is None:
                continue
            leaves.append({"field": f"properties.{k}", "op": OP_EQ, "value": v})

    # If the original criteria already used the new tree shape (forward-
    # compatibility), pass it through verbatim.
    if "op" in criteria and criteria["op"] in ("AND", "OR"):
        return validate_rule_tree(criteria)
    if "rule_tree" in criteria and isinstance(criteria["rule_tree"], dict):
        return validate_rule_tree(criteria["rule_tree"])

    return {"op": "AND", "rules": leaves}


__all__ = [
    "MAX_DEPTH",
    "MAX_LEAVES",
    "MAX_REGEX_LEN",
    "MAX_VALUE_LIST",
    "PropertyEntry",
    "SmartViewRuleError",
    "build_property_catalog",
    "catalog_to_dict",
    "evaluate",
    "legacy_criteria_to_tree",
    "validate_rule_tree",
    # Operator literals re-exported for tests + UI.
    "OP_EQ",
    "OP_NE",
    "OP_CONTAINS",
    "OP_STARTS_WITH",
    "OP_ENDS_WITH",
    "OP_REGEX",
    "OP_GT",
    "OP_LT",
    "OP_GTE",
    "OP_LTE",
    "OP_BETWEEN",
    "OP_IN",
    "OP_NOT_IN",
    "OP_EMPTY",
    "OP_NOT_EMPTY",
]

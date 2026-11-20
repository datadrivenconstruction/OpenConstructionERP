"""Estimate rules (``ddc-rules/1``): validation, element selection, aggregates.

A rule is data. ``model`` rules select elements of a revision and read one quantity; ``derived`` rules
evaluate a formula over named aggregates (and over inputs that carry their own source); ``manual`` rules only
reserve a position that people fill in. Every number a rule needs from outside the model has a source, or is
null and the position says so.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent / "data" / "rules"
KINDS = ("model", "derived", "manual")
AGGREGATIONS = ("sum", "max", "min", "count", "first")
# Quantity columns a model rule may read (ERP canonical keys plus the gross values of the contract).
QUANTITY_FIELDS = ("length_m", "area_m2", "volume_m3", "weight_kg", "count", "area_gross_m2", "volume_gross_m3")
SELECT_KEYS = (
    "ifc_class",
    "type_key_prefix",
    "type_key_not_prefix",
    "key_matches",
    "material_contains",
    "storey",
    "where",
    "any_of",
)
WHERE_OPS = ("eq", "ne", "gt", "ge", "lt", "le", "in", "contains")
_CODE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_DIN = re.compile(r"^\d{3}$")


class RulesError(ValueError):
    pass


def _fail(where: str, msg: str) -> RulesError:
    return RulesError(f"{where}: {msg}")


def _check_select(sel: Any, where: str) -> None:
    if not isinstance(sel, dict) or not sel:
        raise _fail(where, "select must be a non-empty object")
    for k, v in sel.items():
        if k not in SELECT_KEYS:
            raise _fail(where, f"unknown selector '{k}'")
        if k == "key_matches":
            try:
                re.compile(v)
            except (re.error, TypeError) as exc:
                raise _fail(where, f"key_matches is not a regular expression: {exc}") from exc
        elif k == "any_of":  # the element must match at least one of the nested selectors (OR of AND-groups)
            if not (isinstance(v, list) and v):
                raise _fail(where, "any_of must be a non-empty list of selectors")
            for i, nested in enumerate(v):
                _check_select(nested, f"{where}.any_of[{i}]")
        elif k == "storey":
            if not isinstance(v, str):
                raise _fail(where, "storey must be a string")
        elif k == "where":
            if not isinstance(v, list):
                raise _fail(where, "where must be a list")
            for p in v:
                if not (
                    isinstance(p, dict)
                    and p.get("op") in WHERE_OPS
                    and isinstance(p.get("field"), str)
                    and "value" in p
                ):
                    raise _fail(where, f"bad predicate {p!r}; need field, op in {WHERE_OPS}, value")
        elif not (isinstance(v, list) and v and all(isinstance(s, str) and s for s in v)):
            raise _fail(where, f"{k} must be a non-empty list of strings")


def validate_rule(rule: Any, aggregates: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.modules.boq.quantity_formula import FormulaError, list_formula_vars, validate_formula

    if not isinstance(rule, dict):
        raise RulesError("rule must be an object")
    code, kind = rule.get("id"), rule.get("kind")
    where = f"rule {code!r}"
    if not isinstance(code, str) or not _CODE.match(code):
        raise _fail(where, "id must match ^[a-z][a-z0-9_]{0,62}$")
    if kind not in KINDS:
        raise _fail(where, f"kind must be one of {KINDS}")
    if not _DIN.match(str(rule.get("cost_group", ""))):
        raise _fail(where, "cost_group must be a three-digit cost group code")
    if not str(rule.get("label", "")).strip() or not str(rule.get("unit", "")).strip():
        raise _fail(where, "label and unit are required")
    cq = rule.get("cost_query")
    if (
        cq is not None
        and not (isinstance(cq, str) and cq.strip())
        and not (
            isinstance(cq, dict)
            and cq
            and all(isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in cq.items())
        )
    ):
        raise _fail(where, "cost_query must be a search text or a {language: text} object")
    if kind == "model":
        _check_select(rule.get("select"), where)
        q = rule.get("quantity")
        if not isinstance(q, dict) or q.get("aggregation", "sum") not in AGGREGATIONS:
            raise _fail(where, f"quantity needs aggregation in {AGGREGATIONS}")
        if bool(q.get("field")) == bool(q.get("formula")):
            raise _fail(where, "quantity needs exactly one of field and formula")
        if q.get("field") and q["field"] not in QUANTITY_FIELDS:
            raise _fail(where, f"quantity.field must be one of {QUANTITY_FIELDS}")
        if q.get("formula"):
            try:
                validate_formula(q["formula"])
            except FormulaError as exc:
                raise _fail(where, f"invalid formula: {exc}") from exc
    elif kind == "derived":
        try:
            validate_formula(rule.get("formula") or "")
            names = set(list_formula_vars(rule["formula"]))
        except FormulaError as exc:
            raise _fail(where, f"invalid formula: {exc}") from exc
        inputs = rule.get("inputs") or {}
        known = set(aggregates or {}) | set(inputs)
        unknown = sorted(names - known) if aggregates is not None else []
        if unknown:
            raise _fail(where, f"formula uses unknown names: {', '.join(unknown)}")
        for name, inp in inputs.items():
            if not isinstance(inp, dict) or "value" not in inp:
                raise _fail(where, f"input {name} needs value (null when no source exists)")
            if inp["value"] is not None and not (
                isinstance(inp.get("source"), dict) and inp["source"].get("url") and inp["source"].get("date")
            ):
                raise _fail(where, f"input {name} has a value without source url and date")
        rate = rule.get("rate")
        if rate is None:
            if not str(rule.get("missing", "")).strip():
                raise _fail(where, "a derived rule without a rate must say why in 'missing'")
        elif "benchmark" in rate:
            b = rate["benchmark"]
            if not (isinstance(b, dict) and b.get("cost_group") and b.get("basis")):
                raise _fail(where, "rate.benchmark needs cost_group and basis")
        else:
            src = rate.get("source")
            if rate.get("value") is None or not (isinstance(src, dict) and src.get("url") and src.get("date")):
                raise _fail(where, "a literal rate needs value, source.url and source.date")
    return rule


def validate_document(doc: Any) -> dict[str, Any]:
    if not isinstance(doc, dict) or doc.get("schema") != "ddc-rules/1":
        raise RulesError("schema must be ddc-rules/1")
    aggs = doc.get("aggregates") or {}
    for name, a in aggs.items():
        if not _CODE.match(name):
            raise _fail(f"aggregate {name!r}", "name must match ^[a-z][a-z0-9_]{0,62}$")
        _check_select(a.get("select"), f"aggregate {name!r}")
        if a.get("field") not in QUANTITY_FIELDS or a.get("aggregation") not in AGGREGATIONS:
            raise _fail(f"aggregate {name!r}", "needs field and aggregation")
        if not str(a.get("assumption", "")).strip():
            raise _fail(f"aggregate {name!r}", "an aggregate states its assumption")
    rules = doc.get("rules")
    if not isinstance(rules, list) or not rules:
        raise RulesError("rules must be a non-empty list")
    seen: set[str] = set()
    for r in rules:
        validate_rule(r, aggs)
        if r["id"] in seen:
            raise _fail(f"rule {r['id']!r}", "duplicate id")
        seen.add(r["id"])
    return doc


@lru_cache(maxsize=8)
def starter_set(country: str) -> dict[str, Any] | None:
    """The shipped rule set of a country, validated; ``None`` when none exists (nothing is invented)."""
    for f in sorted(DATA.glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        if doc.get("country") == country:
            return validate_document(doc)
    return None


# ── selection ───────────────────────────────────────────────────────────────


_IFC = re.compile(r"Ifc[A-Za-z]+")


def _prop(properties: dict, name: str) -> Any:
    """First value of property ``name`` (any case), flat or inside a nested ``Pset_*`` dict; None when absent."""
    want = name.casefold()
    for k, v in properties.items():
        if isinstance(k, str) and k.casefold() == want and not isinstance(v, dict):
            return v
    for v in properties.values():
        if isinstance(v, dict):
            for k, x in v.items():
                if isinstance(k, str) and k.casefold() == want and not isinstance(x, dict):
                    return x
    return None


def _flag(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    t = str(v).strip().casefold() if v is not None else ""
    return True if t in ("true", "1", "yes", ".t.") else False if t in ("false", "0", "no", ".f.") else None


def derive_type_key(ifc_class: str, properties: dict) -> str:
    """Type key of an imported IFC element from what the file states; "" when it states nothing usable."""
    if ifc_class in ("IfcWall", "IfcWallStandardCase"):
        ext = _flag(_prop(properties, "IsExternal"))
        return "" if ext is None else "wall/ext" if ext else "wall/int"
    if ifc_class == "IfcSlab":
        predefined = str(_prop(properties, "PredefinedType") or "").strip().upper().strip(".")
        return {"BASESLAB": "slab/foundation", "ROOF": "slab/roof"}.get(predefined, "")
    return ""


class Element:
    """The few fields of an element the selectors read (an ERP ``BIMElement`` or a plain mapping)."""

    __slots__ = ("key", "ifc_class", "type_key", "material", "storey", "quantities", "fields")

    def __init__(self, key: str, element_type: str | None, storey: str | None, properties: dict, quantities: dict):
        self.key = key
        # Converter imports (R16) carry the IFC entity in element_type or category, not in ifc_class.
        self.ifc_class = str(
            properties.get("ifc_class")
            or next(
                (v for v in (element_type, properties.get("category")) if isinstance(v, str) and _IFC.fullmatch(v)), ""
            )
        )
        self.type_key = str(properties.get("type_key") or "") or derive_type_key(self.ifc_class, properties)
        self.material = str(properties.get("material") or "")
        self.storey = storey or ""
        self.quantities = quantities or {}
        self.fields = {**properties, "element_type": element_type, "storey": storey, "element_key": key}

    @classmethod
    def of(cls, e) -> Element:
        props = e.properties if isinstance(e.properties, dict) else {}
        qty = e.quantities if isinstance(e.quantities, dict) else {}
        return cls(e.stable_id, e.element_type, e.storey, props, qty)


def _num(v: Any) -> Decimal | None:
    try:
        return Decimal(str(v))
    except Exception:  # noqa: BLE001
        return None


def _predicate(e: Element, p: dict[str, Any]) -> bool:
    field = p["field"]
    got = e.quantities.get(field, e.fields.get(field))
    want, op = p["value"], p["op"]
    if got is None:
        return False
    if op == "eq":
        return str(got) == str(want)
    if op == "ne":
        return str(got) != str(want)
    if op == "in":
        return str(got) in {str(w) for w in want}
    if op == "contains":
        return str(want).casefold() in str(got).casefold()
    a, b = _num(got), _num(want)
    if a is None or b is None:
        return False
    return {"gt": a > b, "ge": a >= b, "lt": a < b, "le": a <= b}[op]


def matches(e: Element, sel: dict[str, Any]) -> bool:
    if "any_of" in sel and not any(matches(e, s) for s in sel["any_of"]):
        return False
    if "ifc_class" in sel and e.ifc_class not in sel["ifc_class"]:
        return False
    if "type_key_prefix" in sel and not any(e.type_key.startswith(p) for p in sel["type_key_prefix"]):
        return False
    if "type_key_not_prefix" in sel and any(e.type_key.startswith(p) for p in sel["type_key_not_prefix"]):
        return False
    if "key_matches" in sel and not re.search(sel["key_matches"], e.key):
        return False
    if "material_contains" in sel and not any(m.casefold() in e.material.casefold() for m in sel["material_contains"]):
        return False
    if "storey" in sel and e.storey != sel["storey"]:
        return False
    return all(_predicate(e, p) for p in sel.get("where", []))


def select(elements: list[Element], sel: dict[str, Any]) -> list[Element]:
    return [e for e in elements if matches(e, sel)]


def aggregate(values: list[Decimal], how: str) -> Decimal:
    if how == "count":
        return Decimal(len(values))
    if not values:
        return Decimal(0)
    return {"sum": sum(values, Decimal(0)), "max": max(values), "min": min(values), "first": values[0]}[how]


def read_field(e: Element, field: str) -> Decimal | None:
    v = e.quantities.get(field)
    return None if v is None else _num(v)

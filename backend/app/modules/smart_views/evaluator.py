# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Smart Views rule engine.

The evaluator is **pure** — no DB, no IO, no globals. Callers pass in a
:class:`SmartView` (or its rules + defaults) and a list of element-like
mappings; the function returns a ``{stable_id: ElementState}`` dict and
optional colour legend. That purity is what makes the engine cheap to
unit-test (no fixtures) and safe to call on every model load.

Counter-intuitive design choices
--------------------------------
* No ``eval``, no ``exec``, no ``getattr`` chains. Every operator is a
  hard-coded predicate. ``regex`` is the only place user input reaches a
  language interpreter at all and it is hard length-capped (see
  ``MAX_REGEX_LENGTH``) plus restricted to ``re.search`` (no
  catastrophic-backtracking ``re.fullmatch`` over a long input).
* Rule order is **explicit** (``rule.order``) and ties resolve by
  stable id, so two saves of the same rule list always produce the same
  evaluation — important for visual diff in the UI.
* ``isolate`` is implemented as "hide the complement", not "show the
  match + hide everything else", because the latter would clobber any
  ``color`` / ``transparent`` an earlier rule already applied to the
  match. The complement-hide leaves matched elements with their
  previously-painted state intact.
* ``color_by_property`` uses an **HCL** ring (not RGB) so the auto-
  palette stays perceptually-distinct across 50+ buckets without the
  green-mud-clusters RGB hashing gives.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

from app.modules.smart_views.schemas import (
    MAX_REGEX_LENGTH,
    ElementState,
    SmartViewRule,
    SmartViewSelector,
)

# ── Element view ─────────────────────────────────────────────────────────


def _props_of(element: Any) -> dict[str, Any]:
    """Return the element's ``properties`` dict (never ``None``)."""
    if isinstance(element, Mapping):
        props = element.get("properties")
    else:
        props = getattr(element, "properties", None)
    return props if isinstance(props, dict) else {}


def _stable_id_of(element: Any) -> str:
    """Return the element's stable id, falling back to its UUID id."""
    if isinstance(element, Mapping):
        sid = element.get("stable_id") or element.get("id")
    else:
        sid = getattr(element, "stable_id", None) or getattr(element, "id", None)
    return str(sid) if sid is not None else ""


def _element_type_of(element: Any) -> str:
    """Return the element's source-native type (``element_type`` column)."""
    if isinstance(element, Mapping):
        et = element.get("element_type")
    else:
        et = getattr(element, "element_type", None)
    return str(et).strip() if et else ""


def _ifc_class_of(element: Any) -> str:
    """Return the element's IFC class.

    DDC-converted Revit elements expose it under
    ``properties.ifc_class`` (or ``properties.IfcEntity``); native IFC
    elements typically reuse the indexed ``element_type`` column. We
    accept *either* source so a rule written against ``IfcWall``
    matches both flavours of model.
    """
    props = _props_of(element)
    for key in ("ifc_class", "IfcEntity", "ifc_type", "ifc_entity"):
        v = props.get(key)
        if v:
            return str(v).strip()
    return _element_type_of(element)


def _prop_value(element: Any, name: str) -> Any:
    """Look up a single property — case-insensitive on miss.

    Source converters are inconsistent on casing (``FireRating`` vs
    ``fireRating`` vs ``fire_rating``); we try the literal first
    (fast path) and only fall back to a case-insensitive lookup if
    that misses. ``None`` is returned to mean "absent".
    """
    props = _props_of(element)
    if name in props:
        return props[name]
    # Case-insensitive fallback — bounded by len(props), no regex.
    lname = name.lower()
    for k, v in props.items():
        if isinstance(k, str) and k.lower() == lname:
            return v
    return None


# ── Operator predicates ──────────────────────────────────────────────────


def _to_float(v: Any) -> float | None:
    """Coerce a value to ``float`` for numeric ops; ``None`` on failure.

    Rejects non-finite floats so a property carrying ``"inf"`` cannot
    derail a ``gt`` comparison (Python ``float('inf') > x`` is True for
    every finite x, which is rarely what the user wants).
    """
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def _safe_str(v: Any) -> str:
    """Stringify for ``eq`` / ``neq`` / ``contains``.

    ``bool`` is special-cased *before* the int branch (Python's
    ``isinstance(True, int)`` is True), so the literal ``"True"`` /
    ``"False"`` round-trips cleanly. Non-string scalars fall through
    to ``str(v)``.
    """
    if v is None:
        return ""
    if isinstance(v, bool):
        return "True" if v else "False"
    return str(v)


def _eval_operator(operator: str, lhs: Any, rhs: Any) -> bool:
    """Apply a single operator. Returns False on any coercion failure.

    *Important semantic*: every comparison operator (``eq`` / ``neq`` /
    ``contains`` / ``regex`` / ``gt`` / ``lt`` / ``between`` / ``in``)
    returns False when ``lhs is None`` — i.e. the property is absent
    from the element. That mirrors SQL three-valued logic where
    ``NULL != 'x'`` is NULL (not TRUE) and stops a ``neq`` rule from
    accidentally hiding every element that simply doesn't carry the
    property. ``exists`` is the only operator that *probes* absence.
    """
    if operator == "exists":
        return lhs is not None
    # Treat a missing property as "no match" for every comparison op.
    # Without this gate a ``neq Material 'Wood'`` rule hides every
    # element that has no Material property at all — counterintuitive
    # and useless.
    if lhs is None:
        return False
    if operator == "eq":
        return _safe_str(lhs) == _safe_str(rhs)
    if operator == "neq":
        return _safe_str(lhs) != _safe_str(rhs)
    if operator == "contains":
        return _safe_str(rhs) in _safe_str(lhs)
    if operator == "regex":
        if not isinstance(rhs, str) or len(rhs) > MAX_REGEX_LENGTH:
            return False
        try:
            # Pre-compile is required so that an invalid pattern is a
            # *match miss*, not a 500. We do not use re.fullmatch over a
            # bounded re.search to keep behaviour predictable on
            # property values that contain delimiters.
            pat = re.compile(rhs)
        except re.error:
            return False
        return bool(pat.search(_safe_str(lhs)))
    if operator == "gt":
        lf, rf = _to_float(lhs), _to_float(rhs)
        return lf is not None and rf is not None and lf > rf
    if operator == "lt":
        lf, rf = _to_float(lhs), _to_float(rhs)
        return lf is not None and rf is not None and lf < rf
    if operator == "between":
        if not isinstance(rhs, (list, tuple)) or len(rhs) != 2:
            return False
        lf = _to_float(lhs)
        if lf is None:
            return False
        low, high = _to_float(rhs[0]), _to_float(rhs[1])
        if low is None or high is None:
            return False
        if low > high:
            low, high = high, low
        return low <= lf <= high
    if operator == "in":
        if not isinstance(rhs, list):
            return False
        lhs_s = _safe_str(lhs)
        return any(_safe_str(x) == lhs_s for x in rhs)
    # Unknown operator — match miss, not a crash. Validation should
    # already have caught this upstream.
    return False


def _matches(selector: SmartViewSelector, element: Any) -> bool:
    """True iff ``element`` satisfies *every* clause of ``selector``."""
    # ifc_class clause — case-insensitive exact match. The user often
    # types ``IfcWall`` but Revit-derived elements surface ``Wall`` or
    # ``ifcwall``; an ``IfcClass`` rule is meant to be a coarse "kind
    # of thing" filter so we are permissive with casing.
    if selector.ifc_class:
        want = selector.ifc_class.strip().lower()
        got = _ifc_class_of(element).lower()
        if not got or got != want:
            return False

    if selector.property is not None:
        if selector.operator is None:
            # Bare ``property`` selector with no operator = ``exists``.
            if _prop_value(element, selector.property) is None:
                return False
        else:
            lhs = _prop_value(element, selector.property)
            if not _eval_operator(selector.operator, lhs, selector.value):
                return False

    return True


# ── Auto-colour (color_by_property) ──────────────────────────────────────


def _hash_to_hcl(label: str) -> str:
    """Deterministic, perceptually-distinct colour for an arbitrary label.

    Hashing through SHA-1 to spread similar inputs uniformly (a plain
    ``hash()`` is salt-randomised in CPython by default — explicit hash
    keeps colours stable across processes). The first 32 bits seed a
    hue in [0, 360); we fix chroma + lightness so every bucket is
    legible against a neutral viewer background. Returns ``#RRGGBB``.
    """
    digest = hashlib.sha1(label.encode("utf-8"), usedforsecurity=False).digest()
    hue_units = int.from_bytes(digest[:4], "big") / 0xFFFFFFFF  # [0,1)
    h = hue_units * 360.0
    return _hcl_to_hex(h, chroma=0.55, lightness=0.62)


def _hcl_to_hex(h: float, chroma: float, lightness: float) -> str:
    """Convert HCL (≈HSL with absolute chroma) to a ``#RRGGBB`` hex.

    Cheap HSL implementation good enough for legend-style swatches;
    we don't need full CIELCH precision here.
    """
    c = chroma * (1.0 - abs(2.0 * lightness - 1.0))
    h_prime = (h % 360.0) / 60.0
    x = c * (1.0 - abs(h_prime % 2.0 - 1.0))
    if 0 <= h_prime < 1:
        r, g, b = c, x, 0.0
    elif 1 <= h_prime < 2:
        r, g, b = x, c, 0.0
    elif 2 <= h_prime < 3:
        r, g, b = 0.0, c, x
    elif 3 <= h_prime < 4:
        r, g, b = 0.0, x, c
    elif 4 <= h_prime < 5:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    m = lightness - c / 2.0
    rgb = (
        max(0, min(255, round((r + m) * 255))),
        max(0, min(255, round((g + m) * 255))),
        max(0, min(255, round((b + m) * 255))),
    )
    return "#{:02X}{:02X}{:02X}".format(*rgb)


# ── Public evaluator ─────────────────────────────────────────────────────


def evaluate_rules(
    rules: Iterable[SmartViewRule | dict],
    elements: Iterable[Any],
    *,
    default_action: str = "show_all",
) -> tuple[dict[str, ElementState], dict[str, str]]:
    """Run the rules over the elements and return per-element states.

    The signature is independent of the ORM SmartView row so the
    evaluator stays trivially testable: the service layer just unpacks
    the row and forwards the JSON rules. Returns
    ``(states_by_stable_id, color_legend)`` — ``color_legend`` is
    populated only when at least one rule used
    ``color_by_property``.
    """
    # Materialise once — we iterate multiple times (one pass per rule).
    elem_list = list(elements)

    # 1. Seed every element with the default action.
    states: dict[str, ElementState] = {}
    start_visible = default_action != "hide_all"
    for el in elem_list:
        sid = _stable_id_of(el)
        if not sid:
            continue
        states[sid] = ElementState(visible=start_visible, color=None, opacity=1.0)

    # 2. Normalise rules — accept either Pydantic objects or raw dicts
    #    (so the evaluator works in service code without re-validating).
    norm_rules: list[SmartViewRule] = []
    for r in rules:
        if isinstance(r, SmartViewRule):
            norm_rules.append(r)
        elif isinstance(r, dict):
            norm_rules.append(SmartViewRule.model_validate(r))
        # silently skip anything else — defensive

    # 3. Sort by (order, id) — deterministic across rebuilds.
    norm_rules.sort(key=lambda r: (r.order, r.id))

    # 4. Apply rules in order. Later rules override earlier ones.
    legend: dict[str, str] = {}
    for rule in norm_rules:
        matched: list[tuple[str, Any]] = []
        for el in elem_list:
            sid = _stable_id_of(el)
            if not sid or sid not in states:
                continue
            if _matches(rule.selector, el):
                matched.append((sid, el))

        if rule.action == "show":
            for sid, _ in matched:
                states[sid].visible = True

        elif rule.action == "hide":
            for sid, _ in matched:
                states[sid].visible = False

        elif rule.action == "isolate":
            # Hide the *complement* — see module docstring.
            matched_ids = {sid for sid, _ in matched}
            for sid in list(states.keys()):
                if sid not in matched_ids:
                    states[sid].visible = False

        elif rule.action == "transparent":
            opacity = rule.action_args.opacity
            if opacity is None:
                opacity = 0.5
            opacity = max(0.0, min(1.0, float(opacity)))
            for sid, _ in matched:
                states[sid].opacity = opacity

        elif rule.action == "color":
            prop = rule.action_args.color_by_property
            if prop:
                # Auto-colour by bucket: hash the property value to a
                # stable HCL colour and stamp it on every matched
                # element. Builds the legend incrementally.
                for sid, el in matched:
                    val = _prop_value(el, prop)
                    label = _safe_str(val) if val is not None else "(unset)"
                    color = legend.get(label)
                    if color is None:
                        color = _hash_to_hcl(label)
                        legend[label] = color
                    states[sid].color = color
            else:
                # Fixed colour.
                color = rule.action_args.color or "#888888"
                for sid, _ in matched:
                    states[sid].color = color

    return states, legend


def evaluate_smart_view(
    view: Any,
    elements: Iterable[Any],
) -> tuple[dict[str, ElementState], dict[str, str]]:
    """Convenience wrapper that unpacks a :class:`SmartView` ORM row.

    Accepts either the ORM model (``view.rules`` is a list of dicts
    stored in JSON) or any object exposing ``rules`` /
    ``default_action`` attributes — keeps the test surface friendly
    while letting routers pass the row straight through.
    """
    rules = getattr(view, "rules", None) or []
    default_action = getattr(view, "default_action", "show_all") or "show_all"
    return evaluate_rules(rules, elements, default_action=default_action)

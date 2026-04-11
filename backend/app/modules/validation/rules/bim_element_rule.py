"""BIMElementRule — per-element validation rule for BIM models.

A :class:`BIMElementRule` is a plain Python class (not a database row) that
describes a single validation check to run against every
``BIMElement`` in a model. The rule consists of three pieces:

* ``element_filter`` — cheap dict-based filter that decides whether an
  element is in scope for this rule (by element_type prefix, discipline,
  storey, category, ...).
* ``property_checks`` — list of checks against ``BIMElement.properties``
  (the free-form JSON blob of IFC/Revit attributes).
* ``quantity_checks`` — list of checks against ``BIMElement.quantities``
  (area_m2, volume_m3, thickness_m, ...).

The rule is stateless and deterministic. Running it against an element
returns a list of per-element :class:`BIMElementRuleResult` entries — one
per failing check (passing checks contribute to the pass count but do not
emit result rows, so large clean models stay cheap).

This module intentionally does NOT touch the engine's global
``rule_registry`` — BIM element rules are a separate rule shape (operate
over individual ORM rows rather than a flat data dict) and are driven by
:class:`app.modules.validation.bim_validation_service.BIMValidationService`
directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["error", "warning", "info"]


# ── Result shape ─────────────────────────────────────────────────────────────


@dataclass
class BIMElementRuleResult:
    """Single per-element result emitted by a :class:`BIMElementRule`."""

    rule_id: str
    rule_name: str
    severity: Severity
    passed: bool
    message: str
    element_id: str
    element_name: str | None = None
    element_type: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


# ── Rule class ───────────────────────────────────────────────────────────────


@dataclass
class BIMElementRule:
    """Declarative per-element validation rule.

    Attributes:
        rule_id: Unique rule identifier (e.g. ``"bim.wall.has_thickness"``).
        name: Human-readable rule name.
        severity: ``"error"`` | ``"warning"`` | ``"info"``.
        description: Optional long-form rationale shown in rule catalogues.
        element_filter: Dict describing which elements this rule applies to.
            Supported keys (all optional, all ANDed together):

            * ``element_type`` — exact match (case-insensitive)
            * ``element_type_startswith`` — prefix match (case-insensitive),
              may be a single string or list of prefixes
            * ``element_type_in`` — list of exact matches (case-insensitive)
            * ``discipline`` — exact match (case-insensitive)
            * ``storey`` — exact match
            * ``category`` — match against ``properties["category"]``

        property_checks: List of property-level checks. Each entry is a dict
            with at least ``property``. Supported keys:

            * ``property`` — dotted path inside ``element.properties``
            * ``must_exist`` — property must be present and non-empty
            * ``must_equal`` — property must equal this value
            * ``must_be_in`` — property must be in this list
            * ``must_match`` — property must match this regex (str)

        quantity_checks: List of quantity-level checks. Each entry is a dict
            with at least ``quantity``. Supported keys:

            * ``quantity`` — dotted path inside ``element.quantities``
            * ``must_exist`` — quantity key must be present and non-null
            * ``must_be_gt`` — numeric value must be > threshold
            * ``must_be_gte`` — numeric value must be >= threshold
            * ``must_be_lt`` — numeric value must be < threshold
            * ``must_be_lte`` — numeric value must be <= threshold

        require_any_of_properties: Optional list of property paths where at
            least ONE must exist (e.g. door width may live in either
            ``properties`` or ``quantities``).
        require_any_of_quantities: Same, but for quantities.
        require_storey: If True, the element must have a non-empty ``storey``.
        require_name: If True, the element must have a real ``name`` (not
            ``None``, ``""``, or the literal string ``"None"``).
    """

    rule_id: str
    name: str
    severity: Severity
    description: str = ""
    element_filter: dict[str, Any] = field(default_factory=dict)
    property_checks: list[dict[str, Any]] = field(default_factory=list)
    quantity_checks: list[dict[str, Any]] = field(default_factory=list)
    require_any_of_properties: list[str] = field(default_factory=list)
    require_any_of_quantities: list[str] = field(default_factory=list)
    require_storey: bool = False
    require_name: bool = False
    enabled: bool = True

    # ── Matching ────────────────────────────────────────────────────────

    def matches(self, element: Any) -> bool:
        """Return True if ``element`` is in scope for this rule."""
        f = self.element_filter
        if not f:
            return True

        etype = (getattr(element, "element_type", None) or "").strip()
        etype_lc = etype.lower()

        if "element_type" in f:
            if etype_lc != str(f["element_type"]).lower():
                return False

        if "element_type_startswith" in f:
            raw = f["element_type_startswith"]
            prefixes = [raw] if isinstance(raw, str) else list(raw or [])
            if not any(etype_lc.startswith(str(p).lower()) for p in prefixes):
                return False

        if "element_type_in" in f:
            allowed = {str(x).lower() for x in f["element_type_in"] or []}
            if etype_lc not in allowed:
                return False

        if "discipline" in f:
            disc = (getattr(element, "discipline", None) or "").lower()
            if disc != str(f["discipline"]).lower():
                return False

        if "storey" in f:
            if (getattr(element, "storey", None) or "") != f["storey"]:
                return False

        if "category" in f:
            props = getattr(element, "properties", None) or {}
            if str(props.get("category", "")).lower() != str(f["category"]).lower():
                return False

        return True

    # ── Evaluation ──────────────────────────────────────────────────────

    def evaluate(self, element: Any) -> list[BIMElementRuleResult]:
        """Run all checks against ``element`` and return failing results.

        Only failing checks emit result rows. A fully passing element
        produces zero entries — callers track the pass count externally.
        """
        results: list[BIMElementRuleResult] = []
        props: dict[str, Any] = getattr(element, "properties", None) or {}
        quants: dict[str, Any] = getattr(element, "quantities", None) or {}

        def _emit(message: str, details: dict[str, Any] | None = None) -> None:
            results.append(
                BIMElementRuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    passed=False,
                    message=message,
                    element_id=str(getattr(element, "id", "")),
                    element_name=getattr(element, "name", None),
                    element_type=getattr(element, "element_type", None),
                    details=details or {},
                )
            )

        # Storey requirement
        if self.require_storey:
            storey = getattr(element, "storey", None)
            if not storey or not str(storey).strip():
                _emit(
                    f"Element has no storey assigned (rule {self.rule_id})",
                    {"field": "storey"},
                )

        # Name requirement
        if self.require_name:
            nm = getattr(element, "name", None)
            if nm is None or str(nm).strip() in {"", "None"}:
                _emit(
                    f"Element has empty or placeholder name (rule {self.rule_id})",
                    {"field": "name", "value": nm},
                )

        # Property checks
        for check in self.property_checks:
            path = check.get("property")
            if not path:
                continue
            value = _lookup_path(props, path)
            failure = _check_value(value, check)
            if failure is not None:
                _emit(
                    f"Property '{path}' {failure} (rule {self.rule_id})",
                    {"property": path, "value": value, "check": check},
                )

        # Quantity checks
        for check in self.quantity_checks:
            path = check.get("quantity")
            if not path:
                continue
            value = _lookup_path(quants, path)
            failure = _check_value(value, check)
            if failure is not None:
                _emit(
                    f"Quantity '{path}' {failure} (rule {self.rule_id})",
                    {"quantity": path, "value": value, "check": check},
                )

        # any-of-properties
        if self.require_any_of_properties:
            if not any(_has_value(_lookup_path(props, p)) for p in self.require_any_of_properties):
                _emit(
                    "Element missing all of: " + ", ".join(self.require_any_of_properties),
                    {"any_of": self.require_any_of_properties, "scope": "properties"},
                )

        # any-of-quantities
        if self.require_any_of_quantities:
            if not any(_has_value(_lookup_path(quants, p)) for p in self.require_any_of_quantities):
                _emit(
                    "Element missing all of: " + ", ".join(self.require_any_of_quantities),
                    {"any_of": self.require_any_of_quantities, "scope": "quantities"},
                )

        return results


# ── Helpers ──────────────────────────────────────────────────────────────────


def _lookup_path(blob: dict[str, Any], path: str) -> Any:
    """Resolve a dotted path inside ``blob``. Missing keys return ``None``."""
    if not isinstance(blob, dict) or not path:
        return None
    cur: Any = blob
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def _has_value(value: Any) -> bool:
    """Return True if ``value`` is a meaningful (non-empty) value."""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() not in {"", "None"}
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) > 0
    return True


def _coerce_number(value: Any) -> float | None:
    """Coerce a value into a float. Returns ``None`` if not possible."""
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


def _check_value(value: Any, check: dict[str, Any]) -> str | None:
    """Run a single check spec against ``value``. Return a failure message
    fragment, or ``None`` if the check passed.
    """
    if check.get("must_exist") and not _has_value(value):
        return "is missing or empty"

    if "must_equal" in check:
        if value != check["must_equal"]:
            return f"expected {check['must_equal']!r}, got {value!r}"

    if "must_be_in" in check:
        allowed = check["must_be_in"] or []
        if value not in allowed:
            return f"value {value!r} not in {allowed!r}"

    if "must_match" in check:
        import re

        pattern = str(check["must_match"])
        if not isinstance(value, str) or re.search(pattern, value) is None:
            return f"does not match /{pattern}/"

    numeric_keys = ("must_be_gt", "must_be_gte", "must_be_lt", "must_be_lte")
    if any(k in check for k in numeric_keys):
        num = _coerce_number(value)
        if num is None:
            return "is not a number"
        if "must_be_gt" in check and not num > float(check["must_be_gt"]):
            return f"must be > {check['must_be_gt']} (got {num})"
        if "must_be_gte" in check and not num >= float(check["must_be_gte"]):
            return f"must be >= {check['must_be_gte']} (got {num})"
        if "must_be_lt" in check and not num < float(check["must_be_lt"]):
            return f"must be < {check['must_be_lt']} (got {num})"
        if "must_be_lte" in check and not num <= float(check["must_be_lte"]):
            return f"must be <= {check['must_be_lte']} (got {num})"

    return None

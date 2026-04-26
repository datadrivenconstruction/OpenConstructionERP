"""IDS importer — buildingSMART Information Delivery Specification → ValidationRule.

Parses an IDS v1.0 XML file (one ``<specification>`` per business rule) and
generates one :class:`ValidationRule` per specification.  The rules check
canonical-format BIM elements (see ``data/bim_canonical/*.json``) for the
predicates declared in each spec's ``<applicability>`` and ``<requirements>``.

Design notes:
    * NO IfcOpenShell — ban from CLAUDE.md §"Важные ограничения".  We treat
      IDS as plain XML and walk the DOM via :mod:`defusedxml` (XXE-safe).
    * Each spec becomes one rule.  ``rule_id`` is derived from the spec's
      ``identifier`` attribute when present, otherwise from the spec name +
      a hash so re-imports stay idempotent.
    * Rules are NOT auto-registered with the global ``rule_registry`` —
      callers decide whether to plug them in (the API endpoint does so).

Public API:
    * :func:`parse_ids` — parse an IDS file/bytes/string into a list of
      ``ValidationRule`` instances.
    * :class:`IDSImportError` — raised for malformed input.

Spec reference: https://github.com/buildingSMART/IDS
"""

from __future__ import annotations

import hashlib
import logging
import re
import xml.etree.ElementTree as ET  # noqa: S405 — types + traversal only
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import defusedxml.ElementTree as safe_ET

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
)

logger = logging.getLogger(__name__)

# ── Namespaces ──────────────────────────────────────────────────────────────

_IDS_NS = "http://standards.buildingsmart.org/IDS"
_XS_NS = "http://www.w3.org/2001/XMLSchema"
_NS = {"ids": _IDS_NS, "xs": _XS_NS}


class IDSImportError(ValueError):
    """Raised when an IDS file cannot be parsed (malformed XML, missing root, etc.)."""


# ── Predicate dataclasses ───────────────────────────────────────────────────


@dataclass(frozen=True)
class _ValueRestriction:
    """Compiled value restriction extracted from an ``<ids:value>`` block."""

    simple_value: str | None = None
    enum: tuple[str, ...] | None = None
    pattern: str | None = None
    min_inclusive: float | None = None
    max_inclusive: float | None = None

    def matches(self, value: Any) -> bool:
        """Check whether ``value`` satisfies this restriction.

        ``None`` always fails (the property is missing).  Empty restriction
        passes anything (used for ``cardinality=required`` with no value
        constraint — only presence matters).
        """
        if value is None:
            return False
        if self.simple_value is not None and str(value) != self.simple_value:
            return False
        if self.enum is not None and str(value) not in self.enum:
            return False
        if self.pattern is not None:
            try:
                if re.fullmatch(self.pattern, str(value)) is None:
                    return False
            except re.error:
                return False
        if self.min_inclusive is not None or self.max_inclusive is not None:
            try:
                num = float(value)
            except (TypeError, ValueError):
                return False
            if self.min_inclusive is not None and num < self.min_inclusive:
                return False
            if self.max_inclusive is not None and num > self.max_inclusive:
                return False
        return True

    @property
    def is_empty(self) -> bool:
        """True if no constraint is set (presence-only check)."""
        return all(
            x is None
            for x in (
                self.simple_value,
                self.enum,
                self.pattern,
                self.min_inclusive,
                self.max_inclusive,
            )
        )


@dataclass
class _Applicability:
    """The set of selectors that decide whether an element is in scope."""

    ifc_class: str | None = None  # e.g. "IFCWALL"
    predefined_type: str | None = None
    classification_system: str | None = None
    classification_value: str | None = None

    def matches(self, element: dict[str, Any]) -> bool:
        """Return True if ``element`` falls within this applicability."""
        if self.ifc_class is not None:
            ifc = (element.get("ifc_class") or "").upper()
            cat = (element.get("category") or "").upper()
            target = self.ifc_class.upper()
            # Allow either ifc_class or category to match.  Canonical-format
            # files sometimes carry "Walls" in ``category`` and "IfcWall" in
            # ``ifc_class`` — both should satisfy IFCWALL.
            if ifc != target and cat != target and not cat.startswith(target):
                # Try the "IfcWall" → "WALL" / "Walls" relaxation.
                short = target.removeprefix("IFC")
                if cat != short and not cat.startswith(short):
                    return False
        if self.predefined_type is not None:
            actual = (element.get("predefined_type") or "").upper()
            if actual != self.predefined_type.upper():
                return False
        if self.classification_system is not None or self.classification_value is not None:
            classif = element.get("classification") or {}
            if self.classification_system is not None:
                # canonical-format stores e.g. {"din276": "330"} — use the
                # system as the dict KEY (lowercased) for an exact lookup.
                key = self.classification_system.lower().replace(" ", "_")
                if key not in {k.lower() for k in classif}:
                    # Fallback: also accept system==value style maps.
                    if self.classification_system not in classif.values():
                        return False
            if self.classification_value is not None:
                if self.classification_value not in {str(v) for v in classif.values()}:
                    return False
        return True


@dataclass
class _Requirement:
    """A single requirement predicate (property OR attribute)."""

    kind: str  # "property" or "attribute"
    cardinality: str = "required"  # required | optional | prohibited
    property_set: str | None = None  # only for kind="property"
    name: str | None = None  # property name OR attribute name
    restriction: _ValueRestriction = field(default_factory=_ValueRestriction)

    def evaluate(self, element: dict[str, Any]) -> tuple[bool, str]:
        """Evaluate this requirement against an element.

        Returns:
            (passed, message) — message describes the failure when ``passed`` is False.
        """
        actual = self._extract_value(element)
        present = actual is not None

        if self.cardinality == "prohibited":
            if present:
                return (
                    False,
                    f"{self._target()} must NOT be set, but found '{actual}'",
                )
            return (True, "OK (prohibited)")

        if self.cardinality == "optional":
            if not present:
                return (True, "OK (optional, absent)")
            if self.restriction.is_empty:
                return (True, "OK (optional, present)")
            ok = self.restriction.matches(actual)
            return (
                ok,
                "OK"
                if ok
                else f"{self._target()} value '{actual}' violates restriction",
            )

        # cardinality == required (default)
        if not present:
            return (False, f"{self._target()} is required but missing")
        if self.restriction.is_empty:
            return (True, "OK")
        ok = self.restriction.matches(actual)
        return (
            ok,
            "OK"
            if ok
            else f"{self._target()} value '{actual}' violates restriction",
        )

    def _target(self) -> str:
        if self.kind == "property":
            return f"property {self.property_set}.{self.name}"
        return f"attribute {self.name}"

    def _extract_value(self, element: dict[str, Any]) -> Any:
        """Pull the value targeted by this requirement out of the element dict."""
        if self.kind == "attribute":
            # IFC attributes (Name, Description, GlobalId, …) live on the top
            # level of the canonical element OR inside a nested "attributes"
            # dict.  Try both, case-insensitively.
            if self.name is None:
                return None
            if self.name in element:
                return element[self.name]
            attrs = element.get("attributes") or {}
            for k, v in attrs.items():
                if k.lower() == self.name.lower():
                    return v
            # Special: some element dicts nest IFC attrs in "ifc_attributes".
            for k, v in (element.get("ifc_attributes") or {}).items():
                if k.lower() == self.name.lower():
                    return v
            # Common synonyms in canonical format
            if self.name.lower() == "name" and "name" in element:
                return element["name"]
            return None

        # kind == "property"
        if self.name is None:
            return None
        props = element.get("properties") or {}
        # Properties may be flat ({"IsExternal": True}) OR grouped by pset
        # ({"Pset_WallCommon": {"IsExternal": True}}).  Try grouped first.
        if self.property_set and self.property_set in props:
            group = props[self.property_set] or {}
            if isinstance(group, dict) and self.name in group:
                return group[self.name]
        # Flat lookup
        if self.name in props:
            return props[self.name]
        # Case-insensitive flat lookup as a last resort
        for k, v in props.items():
            if isinstance(v, dict):
                continue
            if k.lower() == self.name.lower():
                return v
        return None


# ── XML helpers ─────────────────────────────────────────────────────────────


def _find(el: ET.Element, path: str) -> ET.Element | None:
    return el.find(path, _NS)


def _findall(el: ET.Element, path: str) -> list[ET.Element]:
    return el.findall(path, _NS)


def _find_any(el: ET.Element, local_name: str) -> ET.Element | None:
    """Find first child by local name, namespace-agnostic."""
    found = _find(el, f"ids:{local_name}")
    if found is not None:
        return found
    return el.find(local_name)


def _findall_any(el: ET.Element, local_name: str) -> list[ET.Element]:
    found = _findall(el, f"ids:{local_name}")
    if found:
        return found
    return el.findall(local_name)


def _simple_value(el: ET.Element | None) -> str | None:
    if el is None:
        return None
    sv = _find_any(el, "simpleValue")
    if sv is not None and sv.text:
        return sv.text.strip()
    if el.text and el.text.strip():
        return el.text.strip()
    return None


def _parse_restriction(value_el: ET.Element | None) -> _ValueRestriction:
    """Translate an ``<ids:value>`` block into a :class:`_ValueRestriction`."""
    if value_el is None:
        return _ValueRestriction()

    simple = _simple_value(value_el)

    # xs:restriction lookups — try ids namespace, then xs namespace, then bare.
    restriction = (
        _find(value_el, "xs:restriction")
        or value_el.find(f"{{{_XS_NS}}}restriction")
        or value_el.find("restriction")
    )
    enums: list[str] = []
    pattern: str | None = None
    min_inc: float | None = None
    max_inc: float | None = None

    if restriction is not None:
        for child in list(restriction):
            tag = child.tag.split("}", 1)[-1]  # strip namespace
            v = child.get("value")
            if tag == "enumeration" and v is not None:
                enums.append(v)
            elif tag == "pattern" and v is not None:
                pattern = v
            elif tag == "minInclusive" and v is not None:
                try:
                    min_inc = float(v)
                except ValueError:
                    pass
            elif tag == "maxInclusive" and v is not None:
                try:
                    max_inc = float(v)
                except ValueError:
                    pass

    # If the value was just a simpleValue and there's no restriction, treat it
    # as an exact match.
    return _ValueRestriction(
        simple_value=simple if not enums and pattern is None else None,
        enum=tuple(enums) if enums else None,
        pattern=pattern,
        min_inclusive=min_inc,
        max_inclusive=max_inc,
    )


def _parse_applicability(spec: ET.Element) -> _Applicability:
    appl = _find_any(spec, "applicability")
    if appl is None:
        return _Applicability()

    out = _Applicability()

    entity = _find_any(appl, "entity")
    if entity is not None:
        name = _simple_value(_find_any(entity, "name"))
        if name:
            out.ifc_class = name.upper()
        pred = _simple_value(_find_any(entity, "predefinedType"))
        if pred:
            out.predefined_type = pred.upper()

    classif = _find_any(appl, "classification")
    if classif is not None:
        sys_val = _simple_value(_find_any(classif, "system"))
        val_val = _simple_value(_find_any(classif, "value"))
        if sys_val:
            out.classification_system = sys_val
        if val_val:
            out.classification_value = val_val

    return out


def _parse_requirements(spec: ET.Element) -> list[_Requirement]:
    reqs_container = _find_any(spec, "requirements")
    if reqs_container is None:
        return []

    out: list[_Requirement] = []

    for prop_el in _findall_any(reqs_container, "property"):
        pset = _simple_value(_find_any(prop_el, "propertySet"))
        name = _simple_value(_find_any(prop_el, "baseName"))
        cardinality = (prop_el.get("cardinality") or "required").lower()
        restriction = _parse_restriction(_find_any(prop_el, "value"))
        if name:
            out.append(
                _Requirement(
                    kind="property",
                    cardinality=cardinality,
                    property_set=pset,
                    name=name,
                    restriction=restriction,
                )
            )

    for attr_el in _findall_any(reqs_container, "attribute"):
        name = _simple_value(_find_any(attr_el, "name"))
        cardinality = (attr_el.get("cardinality") or "required").lower()
        restriction = _parse_restriction(_find_any(attr_el, "value"))
        if name:
            out.append(
                _Requirement(
                    kind="attribute",
                    cardinality=cardinality,
                    name=name,
                    restriction=restriction,
                )
            )

    return out


# ── Concrete ValidationRule ─────────────────────────────────────────────────


class IDSValidationRule(ValidationRule):
    """A :class:`ValidationRule` synthesised from one IDS ``<specification>``.

    The ``validate()`` walks ``context.data`` (expected to be a dict with
    ``elements: list[dict]`` — i.e. canonical-format BIM data) and emits one
    :class:`RuleResult` per applicable element.
    """

    standard = "IDS"
    category = RuleCategory.COMPLIANCE
    severity = Severity.ERROR  # IDS spec failures are blocking by default

    def __init__(
        self,
        rule_id: str,
        name: str,
        applicability: _Applicability,
        requirements: list[_Requirement],
        *,
        description: str = "",
        ifc_version: str | None = None,
    ) -> None:
        self.rule_id = rule_id
        self.name = name
        self.description = description
        self.ifc_version = ifc_version
        self._applicability = applicability
        self._requirements = requirements
        self.enabled = True

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        """Apply this IDS spec to all applicable canonical-format elements."""
        data = context.data
        elements: list[dict[str, Any]]
        if isinstance(data, dict):
            elements = list(data.get("elements") or [])
        elif isinstance(data, list):
            elements = list(data)
        else:
            elements = []

        applicable = [e for e in elements if self._applicability.matches(e)]
        results: list[RuleResult] = []

        # No applicable elements → emit a single passed result so the rule shows
        # up in the report (instead of vanishing silently).
        if not applicable:
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message="No applicable elements (vacuously satisfied)",
                )
            )
            return results

        for el in applicable:
            element_id = str(el.get("id") or el.get("guid") or "")
            failures: list[str] = []
            for req in self._requirements:
                ok, msg = req.evaluate(el)
                if not ok:
                    failures.append(msg)
            passed = not failures
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK" if passed else "; ".join(failures),
                    element_ref=element_id or None,
                    details=(
                        {"failures": failures, "ifc_version": self.ifc_version}
                        if not passed
                        else None
                    )
                    or {},
                )
            )

        return results


# ── Public API ──────────────────────────────────────────────────────────────


def _read_source(source: Path | str | bytes) -> str:
    if isinstance(source, bytes):
        return source.decode("utf-8")
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8")
    # str: heuristic — looks like an existing path?
    if isinstance(source, str):
        if "\n" not in source and "<" not in source and Path(source).exists():
            return Path(source).read_text(encoding="utf-8")
        return source
    msg = f"Unsupported source type: {type(source)!r}"
    raise IDSImportError(msg)


def _stable_rule_id(spec_idx: int, identifier: str | None, name: str) -> str:
    if identifier:
        slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", identifier).strip("_")
        if slug:
            return f"ids.{slug}"
    base = name or f"spec_{spec_idx}"
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]  # noqa: S324 — short id, not crypto
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", base).strip("_").lower()[:40] or "spec"
    return f"ids.{slug}.{digest}"


def parse_ids(source: Path | str | bytes) -> list[ValidationRule]:
    """Parse an IDS file/string/bytes and return one :class:`ValidationRule` per spec.

    Args:
        source: Path to an ``.ids`` file, or the raw XML as ``str`` / ``bytes``.

    Returns:
        List of synthesised :class:`IDSValidationRule` instances.

    Raises:
        IDSImportError: If the input cannot be parsed as IDS XML.
    """
    try:
        xml_text = _read_source(source)
    except IDSImportError:
        raise
    except OSError as exc:
        msg = f"Cannot read IDS source: {exc}"
        raise IDSImportError(msg) from exc

    try:
        root = safe_ET.fromstring(xml_text)
    except ET.ParseError as exc:
        msg = f"Invalid IDS XML: {exc}"
        raise IDSImportError(msg) from exc
    except Exception as exc:  # noqa: BLE001 — defusedxml may raise its own subclasses
        msg = f"Failed to parse IDS XML: {exc}"
        raise IDSImportError(msg) from exc

    # Accept both <ids:ids> and bare <ids> roots.
    root_local = root.tag.split("}", 1)[-1]
    if root_local.lower() != "ids":
        msg = f"Expected <ids> root element, got <{root_local}>"
        raise IDSImportError(msg)

    specs_container = _find_any(root, "specifications")
    if specs_container is None:
        msg = "No <specifications> element found in IDS file"
        raise IDSImportError(msg)

    specs = _findall_any(specs_container, "specification")

    rules: list[ValidationRule] = []
    for idx, spec in enumerate(specs):
        spec_name = spec.get("name", f"IDS spec {idx + 1}")
        identifier = spec.get("identifier")
        ifc_version = spec.get("ifcVersion")
        description = spec.get("description", "") or ""

        applicability = _parse_applicability(spec)
        requirements = _parse_requirements(spec)

        if not requirements:
            logger.debug("IDS spec %s has no requirements — skipping", spec_name)
            continue

        rule_id = _stable_rule_id(idx, identifier, spec_name)
        rule = IDSValidationRule(
            rule_id=rule_id,
            name=spec_name,
            applicability=applicability,
            requirements=requirements,
            description=description,
            ifc_version=ifc_version,
        )
        rules.append(rule)

    logger.info("Parsed IDS: %d rules from %d specifications", len(rules), len(specs))
    return rules

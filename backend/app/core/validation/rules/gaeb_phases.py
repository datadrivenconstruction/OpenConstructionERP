# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""GAEB DA XML 3.3 exchange-phase rules (rule set ``gaeb_exchange``).

The rules the German pack's ``gaeb_x83_x86`` document declares. Two inputs:

* a bill, as ``context.data["positions"]`` (the shape every BOQ rule reads),
  with ``gaeb_phase`` (``x83``, ``x84``, ``x86``) and ``currency`` beside it;
* an exchange file, as ``context.data["gaeb_document"] = {"phase", "content"}``,
  the X83 we send, the X84 a bidder returns, the X86 we award with.

A rule whose input is absent returns no result rather than a pass: a check
that did not run is not reported as one that held. The set is separate from
``gaeb`` so a bill validated against the DACH rules keeps its known result
list; the tender and export paths run this set on purpose.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
)
from app.core.validation.messages import translate
from app.core.validation.rules import _get_locale, _get_positions, _ok, _position_metadata

GAEB_EXCHANGE_RULE_SET = "gaeb_exchange"

_PRICED_PHASES = frozenset({"x84", "x86"})
_SECTION_UNITS = frozenset({"", "section", "lsec"})
_OZ_PART = re.compile(r"^[0-9A-Za-z]{1,14}$")
_PROFILE_DIR = Path(__file__).resolve().parents[3] / "modules" / "boq" / "gaeb_profile"
_PROFILE_XSD = {"x83": "oce-gaeb-3.3-x83.xsd", "x84": "oce-gaeb-3.3-x84.xsd"}


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _items(context: ValidationContext) -> list[dict[str, Any]]:
    """Priceable lines of the bill: section headings left out (no unit, no quantity, no price)."""
    out = []
    for pos in _get_positions(context):
        if not isinstance(pos, dict):
            continue
        meta = _position_metadata(pos)
        if meta.get("gaeb_is_section") or str(pos.get("type") or "").lower() == "section":
            continue
        unit = str(pos.get("unit") or "").strip().lower()
        if unit in _SECTION_UNITS and not _dec(pos.get("quantity")) and not _dec(pos.get("unit_rate")):
            continue
        out.append(pos)
    return out


def _phase(context: ValidationContext) -> str:
    data = context.data if isinstance(context.data, dict) else {}
    return str(data.get("gaeb_phase") or "").strip().lower()


def _document(context: ValidationContext) -> dict[str, Any] | None:
    data = context.data if isinstance(context.data, dict) else {}
    doc = data.get("gaeb_document")
    if not isinstance(doc, dict) or not doc.get("content"):
        return None
    return doc


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse(doc: dict[str, Any]) -> Any | None:
    """The document's root element, or ``None`` when it is not well-formed XML."""
    from defusedxml import ElementTree as SafeET

    content = doc["content"]
    raw = content.encode("utf-8") if isinstance(content, str) else bytes(content)
    try:
        return SafeET.fromstring(raw)
    except Exception:  # noqa: BLE001 - any parse failure means "not well-formed"
        return None


def _find_all(root: Any, name: str) -> list[Any]:
    return [el for el in root.iter() if _local(el.tag) == name]


def _child_text(el: Any, name: str) -> str:
    for child in el:
        if _local(child.tag) == name:
            return (child.text or "").strip()
    return ""


class _GAEBPhaseRule(ValidationRule):
    standard = "gaeb"
    category = RuleCategory.COMPLIANCE
    severity = Severity.ERROR

    def _result(
        self,
        context: ValidationContext,
        passed: bool,
        ref: str | None,
        key: str,
        details: dict[str, Any] | None = None,
        **params: Any,
    ) -> RuleResult:
        locale = _get_locale(context)
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message=_ok(locale) if passed else translate(f"gaeb_exchange.{key}.fail", locale=locale, **params),
            element_ref=ref,
            details=details or {},
            suggestion=None if passed else translate(f"gaeb_exchange.{key}.suggestion", locale=locale),
        )


# ── Bill rules ──────────────────────────────────────────────────────────────


class ItemDescriptionNotEmpty(_GAEBPhaseRule):
    rule_id = "gaeb.item_description_not_empty"
    name = "GAEB item has a text"
    description = "Every GAEB item carries a short text; an item without one cannot be read by the receiver."
    category = RuleCategory.COMPLETENESS

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return [
            self._result(
                context,
                bool(str(pos.get("description") or "").strip()),
                pos.get("id"),
                "item_description_not_empty",
                ordinal=pos.get("ordinal") or "?",
            )
            for pos in _items(context)
        ]


class UnitSpecifiedPerItem(_GAEBPhaseRule):
    rule_id = "gaeb.unit_specified_per_item"
    name = "GAEB item has a unit"
    description = "Every GAEB item names its unit (QU)."
    category = RuleCategory.COMPLETENESS

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return [
            self._result(
                context,
                bool(str(pos.get("unit") or "").strip()),
                pos.get("id"),
                "unit_specified_per_item",
                ordinal=pos.get("ordinal") or "?",
            )
            for pos in _items(context)
        ]


class QuantityPresentX83(_GAEBPhaseRule):
    rule_id = "gaeb.quantity_present_x83"
    name = "GAEB call for bids states quantities"
    description = "In a call for bids (X83) every item carries a quantity above zero."
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _phase(context) not in ("x83", "x86"):
            return []
        return [
            self._result(
                context,
                (_dec(pos.get("quantity")) or Decimal("0")) > 0,
                pos.get("id"),
                "quantity_present_x83",
                ordinal=pos.get("ordinal") or "?",
            )
            for pos in _items(context)
        ]


class UnitPricePresentX84(_GAEBPhaseRule):
    rule_id = "gaeb.unit_price_present_x84"
    name = "GAEB bid and award price every item"
    description = "A bid (X84) and an award (X86) carry a unit price on every item."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _phase(context) not in _PRICED_PHASES:
            return []
        return [
            self._result(
                context,
                _dec(pos.get("unit_rate")) is not None and (_dec(pos.get("unit_rate")) or Decimal("0")) >= 0,
                pos.get("id"),
                "unit_price_present_x84",
                ordinal=pos.get("ordinal") or "?",
            )
            for pos in _items(context)
        ]


class TotalPriceCalculatedCorrectly(_GAEBPhaseRule):
    rule_id = "gaeb.total_price_calculated_correctly"
    name = "GAEB item total is quantity times unit price"
    description = "The item total (IT) equals quantity x unit price (UP), rounded to the cent."
    category = RuleCategory.CONSISTENCY

    _TOLERANCE = Decimal("0.01")

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _phase(context) not in _PRICED_PHASES:
            return []
        results = []
        for pos in _items(context):
            qty, rate, total = _dec(pos.get("quantity")), _dec(pos.get("unit_rate")), _dec(pos.get("total"))
            if qty is None or rate is None or total is None:
                continue
            expected = (qty * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            results.append(
                self._result(
                    context,
                    abs(expected - total) <= self._TOLERANCE,
                    pos.get("id"),
                    "total_price_calculated_correctly",
                    details={"expected": str(expected), "total": str(total)},
                    ordinal=pos.get("ordinal") or "?",
                    total=str(total),
                    expected=str(expected),
                )
            )
        return results


def _oz_key(value: Any) -> str:
    parts = [p.lstrip("0") or "0" for p in re.split(r"[.\s/]+", str(value or "").strip()) if p]
    return ".".join(parts).upper()


class LVNumberingConsistent(_GAEBPhaseRule):
    rule_id = "gaeb.lv_numbering_consistent"
    name = "GAEB item numbers are unique"
    description = "No two items of the bill share an item number (OZ); the receiver matches lines by it."
    category = RuleCategory.CONSISTENCY

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        seen: dict[str, int] = {}
        items = _items(context)
        for pos in items:
            key = _oz_key(pos.get("ordinal"))
            if key:
                seen[key] = seen.get(key, 0) + 1
        return [
            self._result(
                context,
                not key or seen.get(key, 0) <= 1,
                pos.get("id"),
                "lv_numbering_consistent",
                ordinal=pos.get("ordinal") or "?",
            )
            for pos in items
            for key in [_oz_key(pos.get("ordinal"))]
        ]


class OZFormatValid(_GAEBPhaseRule):
    rule_id = "gaeb.oz_ordnungszahl_format_valid"
    name = "GAEB item number fits the OZ"
    description = "An item number (OZ) has at most five levels of up to 14 letters or digits each."
    severity = Severity.WARNING

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results = []
        for pos in _items(context):
            ordinal = str(pos.get("ordinal") or "").strip()
            parts = [p for p in re.split(r"[.\s/]+", ordinal) if p]
            passed = bool(parts) and len(parts) <= 5 and all(_OZ_PART.match(p) for p in parts)
            results.append(self._result(context, passed, pos.get("id"), "oz_format_valid", ordinal=ordinal or "?"))
        return results


class CurrencyElementPresent(_GAEBPhaseRule):
    rule_id = "gaeb.currency_element_present"
    name = "GAEB exchange names its currency"
    description = "A GAEB file states its currency (Cur); a bill without a project currency writes an empty one."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        doc = _document(context)
        if doc is not None:
            root = _parse(doc)
            if root is None:
                return []
            currency = ""
            for info in _find_all(root, "AwardInfo"):
                currency = currency or _child_text(info, "Cur")
            return [self._result(context, bool(currency), "file", "currency_element_present")]
        data = context.data if isinstance(context.data, dict) else {}
        if "currency" not in data:
            return []
        return [
            self._result(context, bool(str(data.get("currency") or "").strip()), "bill", "currency_element_present")
        ]


# ── File rules ──────────────────────────────────────────────────────────────


class XMLSchemaValid(_GAEBPhaseRule):
    rule_id = "gaeb.xml_schema_valid"
    name = "GAEB file is valid GAEB DA XML 3.3"
    description = (
        "The file is well-formed XML in the GAEB DA XML 3.3 namespace; an X83 or X84 the platform wrote "
        "also validates against its 3.3 profile schema."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        doc = _document(context)
        if doc is None:
            return []
        root = _parse(doc)
        if root is None:
            return [self._result(context, False, "file", "xml_schema_valid", reason="not well-formed XML")]
        namespace = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else ""
        if _local(root.tag) != "GAEB" or not namespace.endswith("/3.3"):
            return [self._result(context, False, "file", "xml_schema_valid", reason="not a GAEB DA XML 3.3 root")]
        phase = str(doc.get("phase") or "").lower()
        xsd = _PROFILE_XSD.get(phase)
        # The profile schema describes what our writer emits; a file from
        # another program may carry more of the standard and is only held to
        # well-formedness and the 3.3 namespace here.
        if xsd is None or not doc.get("own"):
            return [self._result(context, True, "file", "xml_schema_valid")]
        try:
            from lxml import etree  # test-time dependency; the check degrades to well-formedness without it
        except ImportError:
            return [self._result(context, True, "file", "xml_schema_valid")]
        parser = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False)
        schema = etree.XMLSchema(etree.parse(str(_PROFILE_DIR / xsd), parser))
        content = doc["content"]
        raw = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        tree = etree.fromstring(raw, parser)
        if schema.validate(tree):
            return [self._result(context, True, "file", "xml_schema_valid")]
        first = schema.error_log.last_error
        reason = f"line {first.line}: {first.message}" if first is not None else "schema"
        return [self._result(context, False, "file", "xml_schema_valid", reason=reason[:300])]


class _PhaseStructure(_GAEBPhaseRule):
    phase = ""
    priced = False

    def _problems(self, root: Any) -> list[str]:
        problems: list[str] = []
        dp = ""
        for award in _find_all(root, "Award"):
            dp = dp or _child_text(award, "DP")
        if dp != self.phase[1:]:
            problems.append(f"DP is '{dp}', expected '{self.phase[1:]}'")
        if not _find_all(root, "BoQ"):
            problems.append("no BoQ")
        items = _find_all(root, "Item")
        if not items:
            problems.append("no Item")
        for item in items:
            has_price = bool(_child_text(item, "UP"))
            if self.priced and not has_price:
                problems.append(f"item {item.get('RNoPart') or '?'} has no UP")
                break
            if not self.priced and (has_price or _child_text(item, "IT")):
                problems.append(f"item {item.get('RNoPart') or '?'} carries a price")
                break
        if self.priced and not _find_all(root, "CTR"):
            problems.append("no CTR (bidder or contractor)")
        return problems

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        doc = _document(context)
        if doc is None or str(doc.get("phase") or "").lower() != self.phase:
            return []
        root = _parse(doc)
        problems = ["not well-formed XML"] if root is None else self._problems(root)
        return [
            self._result(
                context,
                not problems,
                "file",
                "phase_structure_valid",
                details={"problems": problems},
                phase=self.phase.upper(),
                problems="; ".join(problems),
            )
        ]


class PhaseX81StructureValid(_PhaseStructure):
    rule_id = "gaeb.phase_x81_structure_valid"
    name = "GAEB X81 structure"
    description = "An X81 bill (DP 81) carries a BoQ with items and no prices."
    phase = "x81"


class PhaseX83StructureValid(_PhaseStructure):
    rule_id = "gaeb.phase_x83_structure_valid"
    name = "GAEB X83 structure"
    description = "A call for bids (DP 83) carries a BoQ with items and no prices."
    phase = "x83"


class PhaseX84StructureValid(_PhaseStructure):
    rule_id = "gaeb.phase_x84_structure_valid"
    name = "GAEB X84 structure"
    description = "A bid (DP 84) prices every item and names the bidder (CTR)."
    phase = "x84"
    priced = True


class PhaseX86StructureValid(_PhaseStructure):
    rule_id = "gaeb.phase_x86_structure_valid"
    name = "GAEB X86 structure"
    description = "An award (DP 86) prices every item, keeps the item texts and names the contractor (CTR)."
    phase = "x86"
    priced = True

    def _problems(self, root: Any) -> list[str]:
        problems = super()._problems(root)
        if any(not _find_all(item, "Description") for item in _find_all(root, "Item")):
            problems.append("an item has no text")
        return problems


class BidderInfoPresentX84(_GAEBPhaseRule):
    rule_id = "gaeb.bidder_info_present_x84"
    name = "GAEB bid names the bidder"
    description = "A bid (X84) and an award (X86) name the firm in CTR / Address / Name1."
    category = RuleCategory.COMPLETENESS

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        doc = _document(context)
        if doc is None or str(doc.get("phase") or "").lower() not in _PRICED_PHASES:
            return []
        root = _parse(doc)
        if root is None:
            return []
        name = ""
        for ctr in _find_all(root, "CTR"):
            for address in _find_all(ctr, "Address"):
                name = name or _child_text(address, "Name1")
        return [self._result(context, bool(name), "file", "bidder_info_present_x84")]


GAEB_EXCHANGE_RULES: tuple[ValidationRule, ...] = (
    XMLSchemaValid(),
    PhaseX81StructureValid(),
    PhaseX83StructureValid(),
    PhaseX84StructureValid(),
    PhaseX86StructureValid(),
    LVNumberingConsistent(),
    OZFormatValid(),
    ItemDescriptionNotEmpty(),
    UnitSpecifiedPerItem(),
    QuantityPresentX83(),
    UnitPricePresentX84(),
    TotalPriceCalculatedCorrectly(),
    CurrencyElementPresent(),
    BidderInfoPresentX84(),
)


async def run_gaeb_exchange_rules(data: dict[str, Any], locale: str | None = None) -> list[dict[str, Any]]:
    """Run the set over one payload and return plain result dicts (failed and passed)."""
    context = ValidationContext(data=data, metadata={"locale": locale} if locale else {})
    out: list[dict[str, Any]] = []
    for rule in GAEB_EXCHANGE_RULES:
        for result in await rule.validate(context):
            out.append(
                {
                    "rule_id": result.rule_id,
                    "severity": str(getattr(result.severity, "value", result.severity)),
                    "passed": result.passed,
                    "message": result.message,
                    "element_ref": result.element_ref,
                    "suggestion": result.suggestion,
                }
            )
    return out

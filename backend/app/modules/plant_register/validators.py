# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Validation rule set ``plant_register`` (SPEC section 7).

The rules read one payload, built by ``PlantService.validation_payload``::

    {
      "today": "YYYY-MM-DD",
      "gate_date": "YYYY-MM-DD" | null,      # planned date of the gate to execution
      "items": [PlantService.view_payload(...)],
      "route_findings": {item_code: [error codes]},
      "slots": [{"item", "status", "terms_blockers", "convert_by_date"}],
      "it_services": [{"id", "kind", "needed_from", "cde_container_id", "status"}],
    }

Several rules are enforced at write time too. They exist as rules because the
register also moves without a write here: a date passes, a quote ages, a
package plan changes under an item.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.plant_register.calc import at_least, is_ordered
from app.modules.plant_register.errors import finding_keys
from app.modules.plant_register.messages import translate

PLANT_RULE_SET = "plant_register"


def _locale(context: ValidationContext) -> str:
    meta = getattr(context, "metadata", None) or {}
    return str(meta.get("locale") or "en")


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _rows(context: ValidationContext, key: str) -> list[dict[str, Any]]:
    raw = _data(context).get(key) or []
    return [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []


def _reasons(findings: list[str], locale: str) -> str:
    """The findings as a sentence part in ``locale``: the sub-reason where a finding has one, else the finding."""
    texts = []
    for finding in findings:
        _, key, reason_key = finding_keys(finding)
        texts.append(translate(reason_key or key, locale=locale))
    return "; ".join(texts)


class _PlantRule(ValidationRule):
    standard = "plant"
    category = RuleCategory.COMPLETENESS
    severity = Severity.ERROR
    key = ""

    def _result(
        self, locale: str, passed: bool, ref: str, severity: Severity | None = None, **params: Any
    ) -> RuleResult:
        base = f"plant.rules.{self.key}"
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=severity or self.severity,
            category=self.category,
            passed=passed,
            message=translate("plant.common.ok", locale=locale)
            if passed
            else translate(f"{base}.fail", locale=locale, **params),
            element_ref=ref,
            suggestion=None if passed else translate(f"{base}.suggestion", locale=locale),
        )

    def _items(self, context: ValidationContext) -> list[dict[str, Any]]:
        return _rows(context, "items")

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        return [r for i in self._items(context) if (r := self.check(loc, i, context)) is not None]

    def check(self, loc: str, item: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        raise NotImplementedError


class LeadTimeHasEnquiryDate(_PlantRule):
    """Rule 2: a long-lead item's lead time comes from a dated enquiry, not from the catalogue."""

    key = "lead_time_has_enquiry_date"
    rule_id = "plant_register.lead_time_has_enquiry_date"
    name = "Lead Time Has Enquiry Date"
    description = "Every long-lead item needs a lead time quote with the date it was asked."

    def check(self, loc: str, item: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        if not item["long_lead"]:
            return None
        return self._result(loc, item["quote_count"] > 0, item["code"], item=item["code"])


class LeadTimeFresh(_PlantRule):
    """Rule 3: warning when the basis quote is older than the class allows."""

    key = "lead_time_fresh"
    rule_id = "plant_register.lead_time_fresh"
    name = "Lead Time Fresh"
    severity = Severity.WARNING
    description = "The basis quote is not older than the class quote_max_age_days."

    def check(self, loc: str, item: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        if item["basis_count"] == 0 or is_ordered(item["status"]):
            return None
        return self._result(loc, not item["quote_stale"], item["code"], item=item["code"])


class SingleBasisQuote(_PlantRule):
    """Rule 4: from ``enquired`` on, exactly one basis quote."""

    key = "single_basis_quote"
    rule_id = "plant_register.single_basis_quote"
    name = "Single Basis Quote"
    description = "An enquired item has exactly one basis quote."

    def check(self, loc: str, item: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        if not at_least(item["status"], "enquired"):
            return None
        return self._result(loc, item["basis_count"] == 1, item["code"], item=item["code"])


class CriticalHasMarketEvidence(_PlantRule):
    """Rule 6."""

    key = "critical_has_market_evidence"
    rule_id = "plant_register.critical_has_market_evidence"
    name = "Critical Has Market Evidence"
    description = "A critical item's lead time is not a catalogue default or an expert estimate."

    def check(self, loc: str, item: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        if not item["critical"] or not at_least(item["status"], "specified"):
            return None
        sev = Severity.ERROR if at_least(item["status"], "route_set") else Severity.WARNING
        return self._result(loc, item["market_evidence"], item["code"], severity=sev, item=item["code"])


class OrderNotOverdue(_PlantRule):
    """Rule 7: past the latest order date and not ordered is an error; within warn days a warning."""

    key = "order_not_overdue"
    rule_id = "plant_register.order_not_overdue"
    name = "Order Not Overdue"
    category = RuleCategory.CONSISTENCY
    description = "The item is ordered before its latest order date."

    def check(self, loc: str, item: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        if item["latest_order_date"] is None or is_ordered(item["status"]):
            return None
        status = item["order_status"]
        sev = Severity.WARNING if status == "due_soon" else Severity.ERROR
        return self._result(
            loc, status == "ok", item["code"], severity=sev, item=item["code"], date=item["latest_order_date"]
        )


class VendorBoundHasReason(_PlantRule):
    """Rule 8."""

    key = "vendor_bound_has_reason"
    rule_id = "plant_register.vendor_bound_has_reason"
    name = "Vendor Bound Has Reason"
    description = "A vendor-bound specification states why; a neutral one names no vendor."

    def check(self, loc: str, item: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        findings = item["vendor_findings"]
        if "neutral_spec_names_vendor" in findings:
            return self._result(loc, False, item["code"], severity=Severity.WARNING, item=item["code"])
        return self._result(loc, "vendor_bound_needs_reason" not in findings, item["code"], item=item["code"])


class CriticalHasDecisionPaper(_PlantRule):
    """Rule 9."""

    key = "critical_has_decision_paper"
    rule_id = "plant_register.critical_has_decision_paper"
    name = "Critical Has Decision Paper"
    description = "A critical item has an approved decision paper before its route is set."

    def check(self, loc: str, item: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        if not item["critical"] or not at_least(item["status"], "specified"):
            return None
        sev = Severity.ERROR if at_least(item["status"], "route_set") else Severity.WARNING
        return self._result(loc, item["paper_status"] == "approved", item["code"], severity=sev, item=item["code"])


class RouteConsistentWithPackagePlan(_PlantRule):
    """Rule 10."""

    key = "route_consistent_with_package_plan"
    rule_id = "plant_register.route_consistent_with_package_plan"
    name = "Route Consistent With Package Plan"
    category = RuleCategory.CONSISTENCY
    description = "The procurement route matches the project's package plan and owner-furnished items."

    def check(self, loc: str, item: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        if item["procurement_route"] is None:
            return None
        findings = (_data(context).get("route_findings") or {}).get(item["code"]) or []
        return self._result(loc, not findings, item["code"], item=item["code"], reason=_reasons(findings, loc))


class SlotTermsComplete(_PlantRule):
    """Rule 13: a held slot carries fee, refund terms, deadline and (fee > 0) its commitment link."""

    key = "slot_terms_complete"
    rule_id = "plant_register.slot_terms_complete"
    name = "Slot Terms Complete"
    description = "A held capacity reservation has complete terms."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        out = []
        for s in _rows(context, "slots"):
            if s["status"] != "held":
                continue
            out.append(self._result(loc, not s["terms_blockers"], s["item"], item=s["item"]))
        for i in self._items(context):
            if i["slot_after_order_date"]:
                # The deadline to sign falls after the latest order date (warning, slot_after_order_date).
                out.append(
                    RuleResult(
                        rule_id=self.rule_id,
                        rule_name=self.name,
                        severity=Severity.WARNING,
                        category=self.category,
                        passed=False,
                        message=translate("plant.rules.slot_after_order_date.fail", locale=loc, item=i["code"]),
                        element_ref=i["code"],
                        suggestion=translate("plant.rules.slot_after_order_date.suggestion", locale=loc),
                    )
                )
        return out


class SlotNotExpired(_PlantRule):
    """Rule 13: a held slot whose conversion deadline passed must be converted or released."""

    key = "slot_not_expired"
    rule_id = "plant_register.slot_not_expired"
    name = "Slot Not Expired"
    category = RuleCategory.CONSISTENCY
    description = "No held reservation is past its conversion deadline."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        today = _data(context).get("today") or date.today().isoformat()
        return [
            self._result(loc, not s["convert_by_date"] or s["convert_by_date"] >= today, s["item"], item=s["item"])
            for s in _rows(context, "slots")
            if s["status"] == "held"
        ]


class DeliveryLimitsComplete(_PlantRule):
    """Rule 14."""

    key = "delivery_limits_complete"
    rule_id = "plant_register.delivery_limits_complete"
    name = "Delivery Limits Complete"
    description = "Every delivery step of a main component or user equipment has a party."

    def check(self, loc: str, item: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        if item["item_class"] not in ("main_component", "user_equipment") or not at_least(item["status"], "enquired"):
            return None
        sev = Severity.ERROR if at_least(item["status"], "route_set") else Severity.WARNING
        gaps = item["delivery_limit_gaps"]
        return self._result(loc, not gaps, item["code"], severity=sev, item=item["code"], steps=", ".join(gaps))


class CriticalHasStrategicSpares(_PlantRule):
    """Rule 15."""

    key = "critical_has_strategic_spares"
    rule_id = "plant_register.critical_has_strategic_spares"
    name = "Critical Has Strategic Spares"
    description = "A critical item has a strategic spare or a stated reason why not."

    def check(self, loc: str, item: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        if not item["critical"] or not at_least(item["status"], "route_set"):
            return None
        return self._result(loc, item["strategic_spares_ok"], item["code"], item=item["code"])


class RedundancyQuantity(_PlantRule):
    """Rule 17 (warning)."""

    key = "redundancy_quantity"
    rule_id = "plant_register.redundancy_quantity"
    name = "Redundancy Quantity"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "The quantity is consistent with the redundancy scheme."

    def check(self, loc: str, item: dict[str, Any], context: ValidationContext) -> RuleResult | None:
        return self._result(loc, item["redundancy_ok"], item["code"], item=item["code"])


class ItCdeLinked(_PlantRule):
    """Rule 18: CDE access needed before the gate to execution has its container."""

    key = "it_cde_linked"
    rule_id = "plant_register.it_cde_linked"
    name = "IT CDE Linked"
    description = "CDE access needed before the execution gate is linked to a CDE container."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        gate = _data(context).get("gate_date")
        out = []
        for s in _rows(context, "it_services"):
            if s["kind"] != "cde_access" or s["status"] == "retired" or not s["needed_from"]:
                continue
            if gate and s["needed_from"] > gate:
                continue
            out.append(self._result(loc, bool(s["cde_container_id"]), s["id"]))
        return out


PLANT_RULES: tuple[type[ValidationRule], ...] = (
    LeadTimeHasEnquiryDate,
    LeadTimeFresh,
    SingleBasisQuote,
    CriticalHasMarketEvidence,
    OrderNotOverdue,
    VendorBoundHasReason,
    CriticalHasDecisionPaper,
    RouteConsistentWithPackagePlan,
    SlotTermsComplete,
    SlotNotExpired,
    DeliveryLimitsComplete,
    CriticalHasStrategicSpares,
    RedundancyQuantity,
    ItCdeLinked,
)


def register_plant_rules() -> None:
    """Idempotently register the plant register rules."""
    for rule in PLANT_RULES:
        rule_registry.register(rule(), rule_sets=[PLANT_RULE_SET])


async def run_rules(payload: dict[str, Any], locale: str) -> list[dict[str, Any]]:
    """Every rule against one payload, as plain dicts (router and readiness share this)."""
    context = ValidationContext(data=payload, metadata={"locale": locale})
    out: list[dict[str, Any]] = []
    for rule_cls in PLANT_RULES:
        for r in await rule_cls().validate(context):
            out.append(
                {
                    "rule_id": r.rule_id,
                    "passed": r.passed,
                    "severity": str(getattr(r.severity, "value", r.severity)),
                    "message": r.message,
                    "element_ref": r.element_ref,
                    "suggestion": r.suggestion,
                }
            )
    return out


# Registered on import as well, like the platform rule modules: whoever imports the rules sees them,
# not only an app that ran the startup hook. Registration is idempotent.
register_plant_rules()

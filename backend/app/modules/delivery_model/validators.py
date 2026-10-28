# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Validation rule set ``delivery_model`` (SPEC section 7).

The rules read one payload, built by ``DeliveryModelService.validation_payload``::

    {
      "catalogue": {...pinned delivery forms catalogue body...},
      "model": {"status", "selected_form_code"},
      "comparison": {"options", "criteria", "scores", "weights_total"},
      "allocations": [{"category_code", "party", "basis", "shares", "rationale", "not_applicable", "status"}],
      "packages": [package views with "effective_status" and "linked_contract_type"],
      "ofis": [owner-furnished item views],
      "procurement_released": bool,
      "decisions": [decision views with "four_eyes_violated"]
    }

Every rule calls the same pure function the service uses (``rules.py``) and
keeps the findings of its own codes, so a check has one implementation.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.delivery_model import rules
from app.modules.delivery_model.catalogue import DeliveryForm, DeliveryFormsCatalogue
from app.modules.delivery_model.messages import translate

DELIVERY_RULE_SET = "delivery_model"


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _locale(context: ValidationContext) -> str:
    return str((getattr(context, "metadata", None) or {}).get("locale") or "en")


def _catalogue(context: ValidationContext) -> DeliveryFormsCatalogue | None:
    body = _data(context).get("catalogue")
    try:
        return DeliveryFormsCatalogue.model_validate(body) if isinstance(body, dict) else None
    except Exception:
        return None


def _all_findings(context: ValidationContext) -> list[rules.Finding]:
    data = _data(context)
    catalogue = _catalogue(context)
    if catalogue is None:
        return []
    model = data.get("model") or {}
    form_code = model.get("selected_form_code")
    # The form as the project customised it (option overrides applied); the bare catalogue form otherwise.
    customised = model.get("selected_form")
    form = DeliveryForm.model_validate(customised) if isinstance(customised, dict) else catalogue.form(form_code)
    packages = data.get("packages") or []
    ctypes = {p["id"]: p["linked_contract_type"] for p in packages if p.get("linked_contract_type")}
    return [
        *rules.allocation_findings(catalogue, form_code, data.get("allocations") or [], form=form),
        *rules.package_findings(form, packages, linked_contract_types=ctypes),
        *rules.ofi_findings(
            data.get("ofis") or [], packages, procurement_released=bool(data.get("procurement_released"))
        ),
        *rules.contract_item_findings(
            data.get("contract_items") or [],
            [k.model_dump(mode="json") for k in catalogue.contract_kinds],
            form,
            procurement_released=bool(data.get("procurement_released")),
        ),
    ]


class _DeliveryRule(ValidationRule):
    standard = "delivery_model"
    category = RuleCategory.CONSISTENCY
    severity = Severity.ERROR
    key = ""
    codes: tuple[str, ...] = ()

    @property
    def _base(self) -> str:
        return f"delivery_model.rules.{self.key}"

    def _result(self, locale: str, passed: bool, ref: str, severity: Severity | None = None, **params: Any):
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=severity or self.severity,
            category=self.category,
            passed=passed,
            message=translate("delivery_model.rules.ok", locale=locale)
            if passed
            else translate(f"{self._base}.fail", locale=locale, ref=ref, **params),
            element_ref=ref,
            suggestion=None if passed else translate(f"{self._base}.suggestion", locale=locale),
        )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        found = [f for f in _all_findings(context) if f.code in self.codes]
        if not found:
            return [self._result(loc, True, "project")]
        return [
            self._result(loc, False, f.ref, Severity.WARNING if f.severity == rules.WARNING else Severity.ERROR)
            for f in found
        ]


class DecisionHasAlternatives(_DeliveryRule):
    key = "decision_has_alternatives"
    rule_id = "delivery_model.decision_has_alternatives"
    name = "Decision Has Alternatives"
    description = "A delivery decision compares at least two forms."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        options = (_data(context).get("comparison") or {}).get("options") or []
        return [self._result(loc, len(options) >= 2, "options")]


class WeightsSumTo100(_DeliveryRule):
    key = "weights_sum_to_100"
    rule_id = "delivery_model.weights_sum_to_100"
    name = "Weights Sum To 100"
    description = "Criterion weights add up to exactly 100."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        total = Decimal(str((_data(context).get("comparison") or {}).get("weights_total") or "0"))
        return [self._result(loc, total == rules.HUNDRED, "criteria")]


class EveryRiskAllocated(_DeliveryRule):
    key = "every_risk_allocated"
    rule_id = "delivery_model.every_risk_allocated"
    name = "Every Risk Allocated"
    description = "Every risk category of the catalogue has a party or a reasoned not-applicable."
    codes = ("risk_unallocated", "not_applicable_needs_rationale", "party_unknown")


class SharedRiskSumsTo100(_DeliveryRule):
    key = "shared_risk_sums_to_100"
    rule_id = "delivery_model.shared_risk_sums_to_100"
    name = "Shared Risk Sums To 100"
    description = "A shared risk names its sharing parties with shares summing to 100 and a basis."
    codes = (
        "shared_risk_not_100",
        "shared_needs_two_parties",
        "share_party_unknown",
        "share_invalid",
        "shared_needs_basis",
    )


class DeviationHasRationale(_DeliveryRule):
    key = "deviation_has_rationale"
    rule_id = "delivery_model.deviation_has_rationale"
    name = "Deviation Has Rationale"
    description = "An allocation that differs from the catalogue default for the chosen form says why."
    codes = ("deviation_needs_rationale",)


class AllocationConsistentWithForm(_DeliveryRule):
    key = "allocation_consistent_with_form"
    rule_id = "delivery_model.allocation_consistent_with_form"
    name = "Allocation Consistent With Form"
    description = "Hard attributes of the form decide some allocations; others deviating from the default warn."
    codes = ("allocation_inconsistent_with_form", "allocation_deviates_from_default")


class PackagesConsistentWithForm(_DeliveryRule):
    key = "packages_consistent_with_form"
    rule_id = "delivery_model.packages_consistent_with_form"
    name = "Packages Consistent With Form"
    description = "The package plan has the shape the chosen form needs, and each price basis fits the form."
    codes = ("packages_inconsistent_with_form", "price_basis_inconsistent_with_form")


class ContractTypeConsistentWithForm(_DeliveryRule):
    key = "contract_type_consistent_with_form"
    rule_id = "delivery_model.contract_type_consistent_with_form"
    name = "Contract Type Consistent With Form"
    severity = Severity.WARNING
    description = "A linked contract's type is one the chosen form is compatible with."
    codes = ("contract_type_inconsistent_with_form",)


class OfiHasProcurementRoute(_DeliveryRule):
    key = "ofi_has_procurement_route"
    rule_id = "delivery_model.ofi_has_procurement_route"
    name = "Owner-Furnished Item Has Procurement Route"
    description = "Before procurement is released, every owner-furnished item has a route and an installer."
    codes = ("ofi_without_route",)


class OfiNeedDateFeasible(_DeliveryRule):
    key = "ofi_need_date_feasible"
    rule_id = "delivery_model.ofi_need_date_feasible"
    name = "Owner-Furnished Item Need Date Feasible"
    severity = Severity.WARNING
    description = "An owner-furnished item arrives before its installing package needs it."
    codes = ("ofi_late_for_installer",)


class ContractItemsWellFormed(_DeliveryRule):
    key = "contract_items_well_formed"
    rule_id = "delivery_model.contract_items_well_formed"
    name = "Contract Items Well Formed"
    description = "A contract item has a catalogue kind, consistent dates and a counterparty once it is agreed."
    codes = ("contract_item_kind_unknown", "contract_item_dates_invalid", "contract_item_without_counterparty")


class PartnerSharesSumTo100(_DeliveryRule):
    key = "partner_shares_sum_to_100"
    rule_id = "delivery_model.partner_shares_sum_to_100"
    name = "Partner Shares Sum To 100"
    description = "The shares of the partner structure add up to exactly 100 percent."
    codes = ("partner_shares_not_100",)


class ContractFrameComplete(_DeliveryRule):
    key = "contract_frame_complete"
    rule_id = "delivery_model.contract_frame_complete"
    name = "Contract Frame Complete"
    severity = Severity.WARNING
    description = "Once procurement is released, land tenure, utility contracts and the partner structure are settled."
    codes = ("contract_group_missing", "contract_form_price_basis_inconsistent")


class DecisionApprovedByEntitledUser(_DeliveryRule):
    key = "decision_approved_by_entitled_user"
    rule_id = "delivery_model.decision_approved_by_entitled_user"
    name = "Decision Approved By Entitled User"
    description = "The approved decision was approved at governance by someone other than its proposer under four-eyes."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        approved = [d for d in _data(context).get("decisions") or [] if d.get("status") == "approved"]
        if not approved:
            return [self._result(loc, True, "decision")]
        return [
            self._result(loc, not d.get("four_eyes_violated") and bool(d.get("approved_by")), d["id"]) for d in approved
        ]


DELIVERY_RULES: tuple[type[ValidationRule], ...] = (
    DecisionHasAlternatives,
    WeightsSumTo100,
    EveryRiskAllocated,
    SharedRiskSumsTo100,
    DeviationHasRationale,
    AllocationConsistentWithForm,
    PackagesConsistentWithForm,
    ContractTypeConsistentWithForm,
    OfiHasProcurementRoute,
    OfiNeedDateFeasible,
    ContractItemsWellFormed,
    PartnerSharesSumTo100,
    ContractFrameComplete,
    DecisionApprovedByEntitledUser,
)


def register_delivery_model_rules() -> None:
    """Idempotently register the delivery model rules."""
    for rule in DELIVERY_RULES:
        rule_registry.register(rule(), rule_sets=[DELIVERY_RULE_SET])


# Registered on import as well, like the platform rule modules: whoever imports the rules sees them,
# not only an app that ran the startup hook. Registration is idempotent.
register_delivery_model_rules()

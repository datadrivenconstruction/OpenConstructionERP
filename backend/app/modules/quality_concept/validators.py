# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rule set ``quality_concept`` (spec section 7).

The rules read one payload, built by ``QualityConceptService.validation_payload``;
every finding in it already carries its code, so a rule here is the lens that
picks the findings of its code and turns them into ``RuleResult`` rows with
translated text. A rule with nothing to report returns one passing row, so the
report shows the rule was checked.
"""

from __future__ import annotations

from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.quality_concept.messages import is_key_present, translate

QUALITY_CONCEPT_RULE_SET = "quality_concept"


def _locale(context: ValidationContext) -> str:
    meta = getattr(context, "metadata", None) or {}
    return str(meta.get("locale") or "en")


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


# Finding params that name the proof a message is about.
_NAMING = ("label", "evidence_type", "package")


def _proof_name(locale: str, evidence_type: Any, package: Any) -> str:
    """A proof named by its evidence type (in ``locale``) and package, for a proof with no title."""
    code = str(evidence_type or "")
    if not code:
        return ""
    key = f"quality_concept.evidence_type.{code}"
    name = translate(key, locale=locale) if is_key_present(key, "en") else code.replace("_", " ").capitalize()
    return f"{name} ({package})" if package else name


class _QcRule(ValidationRule):
    standard = "quality_concept"
    category = RuleCategory.COMPLETENESS
    severity = Severity.ERROR
    key = ""
    # (payload group, finding codes) the rule reports.
    source: tuple[str, tuple[str, ...]] = ("", ())

    def _result(self, locale: str, passed: bool, ref: str, **params: Any) -> RuleResult:
        # A finding may carry a human label (a proof title) to show in place of its raw id.
        label = str(params.pop("label", "") or "")
        shown = label or _proof_name(locale, params.pop("evidence_type", ""), params.pop("package", "")) or ref
        params.pop("evidence_type", None)
        params.pop("package", None)
        base = f"quality_concept.rules.{self.key}"
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message=translate("quality_concept.common.ok", locale=locale)
            if passed
            else translate(f"{base}.fail", locale=locale, ref=shown, **{k: str(v) for k, v in params.items()}),
            element_ref=ref or None,
            suggestion=None if passed else translate(f"{base}.suggestion", locale=locale),
        )

    def findings(self, context: ValidationContext) -> list[tuple[str, dict[str, Any]]]:
        group, codes = self.source
        rows = _data(context).get(group) or []
        return [
            (r.get("ref", ""), r.get("params") or {}) for r in rows if isinstance(r, dict) and r.get("code") in codes
        ]

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        loc = _locale(context)
        hits = self.findings(context)
        if not hits:
            return [self._result(loc, True, "")]
        return [self._result(loc, False, ref, **{k: params[k] for k in _NAMING if k in params}) for ref, params in hits]


def _rule(
    key: str, name: str, group: str, codes: tuple[str, ...], severity: Severity = Severity.ERROR
) -> type[_QcRule]:
    return type(
        "".join(p.capitalize() for p in key.split("_")),
        (_QcRule,),
        {
            "key": key,
            "rule_id": f"quality_concept.{key}",
            "name": name,
            "description": name,
            "severity": severity,
            "source": (group, codes),
        },
    )


ConceptComplete = _rule(
    "concept_complete",
    "Concept Complete",
    "completeness",
    (
        "standards_basis_missing",
        "package_without_proofs",
        "stage_model_missing",
        "acceptance_unit_total_missing",
        "acceptance_unit_handover_to_operation_missing",
    ),
)
ProofHasDelivererAndDue = _rule(
    "proof_has_deliverer_and_due",
    "Proof Has Deliverer And Due",
    "completeness",
    (
        "proof_without_deliverer",
        "proof_without_due",
        "proof_due_stage_unknown",
        "proof_due_unit_unknown",
        "proof_due_date_invalid",
    ),
)
EvidenceWithExpiredCalibration = _rule(
    "evidence_with_expired_calibration",
    "Evidence With Expired Calibration",
    "evidence",
    ("evidence_with_expired_calibration",),
)
StageHasOwnerAndReleaseParty = _rule(
    "stage_has_owner_and_release_party",
    "Stage Has Owner And Release Party",
    "completeness",
    ("stage_without_owner", "stage_without_release_party"),
)
AcceptanceUnitPerPackage = _rule(
    "acceptance_unit_per_package", "Acceptance Unit Per Package", "completeness", ("acceptance_unit_per_package",)
)
AcceptanceRegimeSet = _rule(
    "acceptance_regime_set", "Acceptance Regime Set", "completeness", ("acceptance_regime_missing",)
)
DeemedAcceptanceDue = _rule(
    "deemed_acceptance_due", "Deemed Acceptance Due", "deemed", ("deemed_acceptance_due",), Severity.WARNING
)
CertificationTargetAtRisk = _rule(
    "certification_target_at_risk",
    "Certification Target At Risk",
    "certification",
    ("certification_target_at_risk",),
    Severity.WARNING,
)
PreservationBeforeStart = _rule(
    "preservation_before_start", "Preservation Before Start", "preservation", ("preservation_missing_before_start",)
)
PreservationAcknowledged = _rule(
    "preservation_acknowledged",
    "Preservation Acknowledged",
    "preservation",
    ("preservation_acknowledged", "preservation_after_unpaired"),
    Severity.WARNING,
)
MaterialTestFrequencyShort = _rule(
    "material_test_frequency_short",
    "Material Test Frequency Short",
    "material",
    ("material_test_frequency_short",),
    Severity.WARNING,
)


ProofQuantityKnown = _rule(
    "proof_quantity_known", "Proof Quantity Known", "evidence", ("placed_quantity_missing",), Severity.WARNING
)


class EvidenceKindAllowed(_QcRule):
    """Rule 3 is enforced at write; this re-checks stored links against the pinned catalogue."""

    key = "evidence_kind_allowed"
    rule_id = "quality_concept.evidence_kind_allowed"
    name = "Evidence Kind Allowed"
    description = "Every linked evidence row is of a kind the proof's evidence type accepts."
    source = ("evidence", ("evidence_kind_not_allowed",))


class _IdList(_QcRule):
    group = ""

    def findings(self, context: ValidationContext) -> list[tuple[str, dict[str, Any]]]:
        return [(str(i), {}) for i in _data(context).get(self.group) or []]


class StageOrderRespected(_IdList):
    key = "stage_order_respected"
    rule_id = "quality_concept.stage_order_respected"
    name = "Stage Order Respected"
    description = "A stage is tested or released only after the previous stage of the unit is released."
    group = "stage_order_violations"


class StageReleasedViaGate(_IdList):
    key = "stage_released_via_gate"
    rule_id = "quality_concept.stage_released_via_gate"
    name = "Stage Released Via Gate"
    description = "A released stage names the hold gate that released it."
    group = "released_without_gate"


class PartialAcceptanceScoped(_IdList):
    key = "partial_acceptance_scoped"
    rule_id = "quality_concept.partial_acceptance_scoped"
    name = "Partial Acceptance Scoped"
    description = "A partial acceptance names the packages it covers."
    group = "partial_scoped"


class CommissionedWithoutFinalStage(_IdList):
    key = "commissioned_without_final_stage"
    rule_id = "quality_concept.commissioned_without_final_stage"
    name = "Commissioned Without Final Stage"
    description = "A commissioned system has its final commissioning stage released."
    group = "commissioned_outside"


class AcceptancePreconditionsMet(_QcRule):
    """Units already accepted without reservations while the plan still lists unmet preconditions."""

    key = "acceptance_preconditions_met"
    rule_id = "quality_concept.acceptance_preconditions_met"
    name = "Acceptance Preconditions Met"
    description = "Accepted units record their reservations."
    severity = Severity.WARNING

    def findings(self, context: ValidationContext) -> list[tuple[str, dict[str, Any]]]:
        rows = _data(context).get("unmet_accepted") or []
        return [(str(r), {}) for r in rows]


QUALITY_CONCEPT_RULES: tuple[type[ValidationRule], ...] = (
    ConceptComplete,
    ProofHasDelivererAndDue,
    EvidenceKindAllowed,
    EvidenceWithExpiredCalibration,
    StageHasOwnerAndReleaseParty,
    StageOrderRespected,
    StageReleasedViaGate,
    AcceptanceUnitPerPackage,
    AcceptanceRegimeSet,
    AcceptancePreconditionsMet,
    PartialAcceptanceScoped,
    DeemedAcceptanceDue,
    CertificationTargetAtRisk,
    PreservationBeforeStart,
    PreservationAcknowledged,
    MaterialTestFrequencyShort,
    ProofQuantityKnown,
    CommissionedWithoutFinalStage,
)


def register_quality_concept_rules() -> None:
    """Idempotently register the quality concept rules."""
    for rule in QUALITY_CONCEPT_RULES:
        rule_registry.register(rule(), rule_sets=[QUALITY_CONCEPT_RULE_SET])


# Registered on import as well, like the platform rule modules: whoever imports the rules sees them,
# not only an app that ran the startup hook. Registration is idempotent.
register_quality_concept_rules()

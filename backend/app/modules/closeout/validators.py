# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Closeout validation rules.

Ships two first-class rules registered with the platform rule registry:

* ``CloseoutCompletenessRule`` (ERROR) - any required slot left unbound is a
  blocking gap in the handover package.
* ``CloseoutEvidenceRule`` (WARNING) - a bound required slot whose evidence
  has not yet been human-verified is flagged for sign-off.

The rules run against a plain dict context (no ORM), shaped by the service /
caller as ``{"slots": [{slot_key, title, is_required, status,
source_kind, generated_artifact}], "project_id": ...}``. ``status`` is one of
``empty`` / ``bound`` / ``verified``. This keeps the rules pure and trivially
unit-testable while satisfying the platform "no module without validation
rules" requirement.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.i18n import t
from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)

logger = logging.getLogger(__name__)

# Generated artifacts the build always produces; they are never a hard gap.
_GENERATED_ARTIFACTS = {"cobie_xlsx", "punch_closure_report", "inspection_cert_pdf"}


def _slots(context: ValidationContext) -> list[dict[str, Any]]:
    data = context.data
    if isinstance(data, dict):
        slots = data.get("slots", [])
        return [s for s in slots if isinstance(s, dict)]
    if isinstance(data, list):
        return [s for s in data if isinstance(s, dict)]
    return []


def _is_generated(slot: dict[str, Any]) -> bool:
    return slot.get("source_kind") == "generated" and slot.get("generated_artifact") in _GENERATED_ARTIFACTS


class CloseoutCompletenessRule(ValidationRule):
    """Every required slot must carry evidence before the package is issued."""

    rule_id = "closeout.completeness"
    name = "Closeout required items bound"
    standard = "closeout"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Every required closeout checklist item must be bound to evidence"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for slot in _slots(context):
            if not slot.get("is_required"):
                continue
            if _is_generated(slot):
                # Produced by the build itself; not a binding gap.
                continue
            status = str(slot.get("status", "empty"))
            passed = status in ("bound", "verified")
            title = slot.get("title") or slot.get("slot_key") or "item"
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK" if passed else f"Required item '{title}' has no evidence bound",
                    element_ref=str(slot.get("slot_key") or ""),
                    suggestion=None if passed else "Bind a CDE document or external reference to this item",
                )
            )
        return results


class CloseoutEvidenceRule(ValidationRule):
    """A bound required slot should be human-verified before handover."""

    rule_id = "closeout.evidence_verified"
    name = "Closeout evidence verified"
    standard = "closeout"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Bound required closeout items should be human-verified before issue"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for slot in _slots(context):
            if not slot.get("is_required"):
                continue
            if _is_generated(slot):
                continue
            status = str(slot.get("status", "empty"))
            if status == "empty":
                # Completeness rule already covers unbound; no double-flag.
                continue
            passed = status == "verified"
            title = slot.get("title") or slot.get("slot_key") or "item"
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=passed,
                    message="OK" if passed else f"Evidence for '{title}' is not yet verified",
                    element_ref=str(slot.get("slot_key") or ""),
                    suggestion=None if passed else "Review and verify the bound evidence (manager sign-off)",
                )
            )
        return results


# ── Handover dossier rules ──────────────────────────────────────────────────
#
# They read the context built by ``DossierService.check_context``:
# ``{"config": {...}, "categories": {cat: {"present", "verified", "titles"}},
# "punch": {"open": [{id, title}], "without_photo": [{id, title}]},
# "commissioning": {"pending": [{id, name}], "open_critical_issues": int},
# "acceptance": {"bound": bool, "signed": bool, "signing_status": str|None}}``.
# Each rule is silent when the checklist switches its requirement off.

#: Most per-item findings one rule reports; the rest are summarised in one row.
_MAX_ITEM_FINDINGS = 50


def _dossier(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _dconfig(context: ValidationContext) -> dict[str, Any]:
    cfg = _dossier(context).get("config")
    return cfg if isinstance(cfg, dict) else {}


def _loc(context: ValidationContext) -> str | None:
    value = (context.metadata or {}).get("locale")
    return str(value) if value else None


def _row(
    rule: ValidationRule,
    passed: bool,
    message: str,
    *,
    element_ref: str = "",
    suggestion: str | None = None,
    details: dict[str, Any] | None = None,
) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=element_ref,
        suggestion=suggestion,
        details=details or {},
    )


def _item_rows(
    rule: ValidationRule,
    items: list[Any],
    message_key: str,
    fix_key: str,
    context: ValidationContext,
    *,
    label_field: str = "title",
) -> list[RuleResult]:
    """One failing row per item (capped), or one passing row when there are none."""
    loc = _loc(context)
    entries = [i for i in items if isinstance(i, dict)]
    if not entries:
        return [_row(rule, True, "OK")]
    rows = [
        _row(
            rule,
            False,
            t(message_key, loc, name=str(e.get(label_field) or e.get("id") or "")),
            element_ref=str(e.get("id") or ""),
            suggestion=t(fix_key, loc),
        )
        for e in entries[:_MAX_ITEM_FINDINGS]
    ]
    if len(entries) > _MAX_ITEM_FINDINGS:
        rows.append(
            _row(
                rule,
                False,
                t("closeout_dossier.more_items", loc, count=len(entries) - _MAX_ITEM_FINDINGS),
                details={"total": len(entries)},
            )
        )
    return rows


class DossierCategoryRule(ValidationRule):
    """Every category the checklist requires carries evidence."""

    rule_id = "closeout.dossier_category_present"
    name = "Dossier contains every required document category"
    standard = "closeout"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Each document category required by the dossier checklist must carry evidence"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        cfg = _dconfig(context)
        cats = _dossier(context).get("categories") or {}
        loc = _loc(context)
        results: list[RuleResult] = []
        for cat in cfg.get("required_categories") or []:
            state = cats.get(cat) if isinstance(cats.get(cat), dict) else {}
            present = bool(state.get("present"))
            results.append(
                _row(
                    self,
                    present,
                    "OK" if present else t("closeout_dossier.category_missing", loc, category=cat),
                    element_ref=str(cat),
                    suggestion=None if present else t("closeout_dossier.category_missing_fix", loc),
                )
            )
        return results


class DossierEvidenceVerifiedRule(ValidationRule):
    """Evidence of required categories is verified, when the checklist asks for it."""

    rule_id = "closeout.dossier_evidence_verified"
    name = "Dossier evidence verified"
    standard = "closeout"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Bound evidence of required dossier categories should be verified by a manager"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        cfg = _dconfig(context)
        if not cfg.get("require_verified_evidence"):
            return []
        cats = _dossier(context).get("categories") or {}
        loc = _loc(context)
        results: list[RuleResult] = []
        for cat in cfg.get("required_categories") or []:
            state = cats.get(cat) if isinstance(cats.get(cat), dict) else {}
            if not state.get("present"):
                continue
            verified = bool(state.get("verified"))
            results.append(
                _row(
                    self,
                    verified,
                    "OK" if verified else t("closeout_dossier.category_unverified", loc, category=cat),
                    element_ref=str(cat),
                    suggestion=None if verified else t("closeout_dossier.category_unverified_fix", loc),
                )
            )
        return results


class DossierPunchResolvedRule(ValidationRule):
    """No punch item in scope is still open."""

    rule_id = "closeout.dossier_punch_resolved"
    name = "Punch list resolved"
    standard = "closeout"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Every punch item in the dossier scope must be resolved, verified or closed"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _dconfig(context).get("require_punch_resolved"):
            return []
        punch = _dossier(context).get("punch") or {}
        return _item_rows(
            self,
            list(punch.get("open") or []),
            "closeout_dossier.punch_open",
            "closeout_dossier.punch_open_fix",
            context,
        )


class DossierPunchPhotoRule(ValidationRule):
    """Closed-out punch items in scope carry a photo."""

    rule_id = "closeout.dossier_punch_photos"
    name = "Resolved punch items have photos"
    standard = "closeout"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Every resolved punch item in the dossier scope should carry at least one photo"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _dconfig(context).get("require_punch_photos"):
            return []
        punch = _dossier(context).get("punch") or {}
        return _item_rows(
            self,
            list(punch.get("without_photo") or []),
            "closeout_dossier.punch_no_photo",
            "closeout_dossier.punch_no_photo_fix",
            context,
        )


class DossierCommissioningRule(ValidationRule):
    """Commissioning in scope is complete."""

    rule_id = "closeout.dossier_commissioning_complete"
    name = "Commissioning complete"
    standard = "closeout"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Every commissioning system in scope should be commissioned with no open critical issue"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _dconfig(context).get("require_commissioning_complete"):
            return []
        cx = _dossier(context).get("commissioning") or {}
        rows = _item_rows(
            self,
            list(cx.get("pending") or []),
            "closeout_dossier.system_pending",
            "closeout_dossier.system_pending_fix",
            context,
            label_field="name",
        )
        critical = int(cx.get("open_critical_issues") or 0)
        if critical:
            loc = _loc(context)
            rows = [r for r in rows if not r.passed]
            rows.append(
                _row(
                    self,
                    False,
                    t("closeout_dossier.critical_issues", loc, count=critical),
                    suggestion=t("closeout_dossier.critical_issues_fix", loc),
                    details={"open_critical_issues": critical},
                )
            )
        return rows


class DossierAcceptanceSignedRule(ValidationRule):
    """The acceptance certificate is bound and fully signed."""

    rule_id = "closeout.dossier_acceptance_signed"
    name = "Acceptance signed"
    standard = "closeout"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "The acceptance certificate must be bound and fully signed in the signing registry"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _dconfig(context).get("require_signed_acceptance"):
            return []
        acc = _dossier(context).get("acceptance") or {}
        loc = _loc(context)
        if not acc.get("bound"):
            return [
                _row(
                    self,
                    False,
                    t("closeout_dossier.acceptance_missing", loc),
                    element_ref="acceptance",
                    suggestion=t("closeout_dossier.acceptance_missing_fix", loc),
                )
            ]
        signed = bool(acc.get("signed"))
        message = (
            "OK" if signed else t("closeout_dossier.acceptance_unsigned", loc, status=acc.get("signing_status") or "-")
        )
        return [
            _row(
                self,
                signed,
                message,
                element_ref="acceptance",
                suggestion=None if signed else t("closeout_dossier.acceptance_unsigned_fix", loc),
            )
        ]


_DOSSIER_RULES: tuple[ValidationRule, ...] = (
    DossierCategoryRule(),
    DossierEvidenceVerifiedRule(),
    DossierPunchResolvedRule(),
    DossierPunchPhotoRule(),
    DossierCommissioningRule(),
    DossierAcceptanceSignedRule(),
)


def register_closeout_validation_rules() -> None:
    """Register the closeout rules with the platform rule registry."""
    from app.modules.closeout.dossier import DOSSIER_RULE_SET

    rule_registry.register(CloseoutCompletenessRule(), ["closeout"])
    rule_registry.register(CloseoutEvidenceRule(), ["closeout"])
    for rule in _DOSSIER_RULES:
        rule_registry.register(rule, [DOSSIER_RULE_SET])
    logger.debug("closeout: registered %d validation rules", 2 + len(_DOSSIER_RULES))

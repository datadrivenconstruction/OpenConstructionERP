# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Condition validation rules.

Rules, registered under the ``condition`` rule set, read a plain dict built by
the router: ``{"scales": {key: scale}, "assessments": [...], "actions": [...]}``.

* ``condition.rating_on_scale`` (ERROR): every rating is a level of its scale.
* ``condition.poor_rating_has_action`` (WARNING): an asset whose latest rating
  reaches its scale's action threshold has an approved or proposed action.
* ``condition.action_priced`` (WARNING): every approved action has a unit cost,
  otherwise the plan's totals silently leave it out.
* ``condition.defect_record_complete`` (INFO): a rating at or above the action
  threshold records severity and extent, the inputs that size the work.
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

CONDITION_RULE_SET = "condition"


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _loc(context: ValidationContext) -> str | None:
    value = (context.metadata or {}).get("locale")
    return str(value) if value else None


def _result(rule: ValidationRule, passed: bool, message: str, ref: str, suggestion: str | None = None) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=ref,
        suggestion=suggestion,
    )


def _latest(assessments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Newest assessment per asset; input is ordered newest first."""
    seen: set[str] = set()
    out = []
    for a in assessments:
        key = str(a.get("asset_ref") or a.get("element_name") or "").strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


class RatingOnScaleRule(ValidationRule):
    """A rating must be one of the levels of its scale."""

    rule_id = "condition.rating_on_scale"
    name = "Rating is a level of its scale"
    standard = "condition"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = "Each condition rating must be a level of the scale it was recorded on"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        scales = data.get("scales") or {}
        results = []
        for a in data.get("assessments") or []:
            scale = scales.get(a.get("scale_key")) or {}
            count = len(scale.get("levels") or [])
            rating = a.get("rating")
            passed = isinstance(rating, int) and 1 <= rating <= count
            results.append(
                _result(
                    self,
                    passed,
                    "OK"
                    if passed
                    else t(
                        "condition.rule_rating_off_scale",
                        _loc(context),
                        name=a.get("element_name") or "",
                        rating=rating,
                        scale=a.get("scale_key") or "",
                    ),
                    str(a.get("id") or ""),
                )
            )
        return results


class PoorRatingHasActionRule(ValidationRule):
    """A rating at or past the scale's threshold needs a planned action."""

    rule_id = "condition.poor_rating_has_action"
    name = "Poor condition has a planned action"
    standard = "condition"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "An asset rated at or past its scale's action threshold should have a maintenance action"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        scales = data.get("scales") or {}
        live = {
            str(x.get("assessment_id"))
            for x in data.get("actions") or []
            if x.get("status") in ("proposed", "approved", "done") and x.get("assessment_id")
        }
        live_assets = {
            str(x.get("asset_ref") or x.get("element_name") or "").strip().lower()
            for x in data.get("actions") or []
            if x.get("status") in ("proposed", "approved", "done")
        }
        results = []
        for a in _latest(list(data.get("assessments") or [])):
            threshold = int((scales.get(a.get("scale_key")) or {}).get("action_threshold") or 0)
            if not threshold or int(a.get("rating") or 0) < threshold:
                continue
            asset_key = str(a.get("asset_ref") or a.get("element_name") or "").strip().lower()
            passed = str(a.get("id")) in live or asset_key in live_assets
            results.append(
                _result(
                    self,
                    passed,
                    "OK"
                    if passed
                    else t(
                        "condition.rule_poor_without_action",
                        _loc(context),
                        name=a.get("element_name") or "",
                        rating=a.get("rating"),
                    ),
                    str(a.get("id") or ""),
                    None if passed else t("condition.rule_poor_without_action_fix", _loc(context)),
                )
            )
        return results


class ActionPricedRule(ValidationRule):
    """Approved actions carry a unit cost."""

    rule_id = "condition.action_priced"
    name = "Planned actions are priced"
    standard = "condition"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Every approved maintenance action should carry a unit cost"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results = []
        for x in _data(context).get("actions") or []:
            if x.get("status") != "approved":
                continue
            passed = x.get("unit_cost") not in (None, "")
            results.append(
                _result(
                    self,
                    passed,
                    "OK"
                    if passed
                    else t(
                        "condition.rule_action_unpriced",
                        _loc(context),
                        name=x.get("element_name") or "",
                        year=x.get("first_year"),
                    ),
                    str(x.get("id") or ""),
                    None if passed else t("condition.rule_action_unpriced_fix", _loc(context)),
                )
            )
        return results


class DefectRecordCompleteRule(ValidationRule):
    """A rating that calls for work records severity and extent."""

    rule_id = "condition.defect_record_complete"
    name = "Defect record complete"
    standard = "condition"
    severity = Severity.INFO
    category = RuleCategory.QUALITY
    description = "A rating at or past the action threshold should record severity and extent"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        scales = data.get("scales") or {}
        results = []
        for a in data.get("assessments") or []:
            threshold = int((scales.get(a.get("scale_key")) or {}).get("action_threshold") or 0)
            if not threshold or int(a.get("rating") or 0) < threshold:
                continue
            passed = a.get("severity") is not None and a.get("extent_pct") is not None
            results.append(
                _result(
                    self,
                    passed,
                    "OK"
                    if passed
                    else t("condition.rule_defect_incomplete", _loc(context), name=a.get("element_name") or ""),
                    str(a.get("id") or ""),
                )
            )
        return results


_RULES: tuple[ValidationRule, ...] = (
    RatingOnScaleRule(),
    PoorRatingHasActionRule(),
    ActionPricedRule(),
    DefectRecordCompleteRule(),
)


def register_condition_validation_rules() -> None:
    """Register the condition rules under the ``condition`` rule set."""
    for rule in _RULES:
        rule_registry.register(rule, [CONDITION_RULE_SET])
    logger.debug("condition: registered %d validation rules", len(_RULES))

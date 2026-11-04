# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid / no-bid validation rules (rule set ``bid_no_bid``).

* ``bid_no_bid.weights_sum_100`` - ERROR. The five weights are not negative and add up to 100.
* ``bid_no_bid.all_criteria_rated`` - ERROR. Every criterion has a rating from 1 to 5.
* ``bid_no_bid.override_has_reason`` - ERROR. A decision against the recommendation carries a reason.
* ``bid_no_bid.low_rating_has_note`` - WARNING. A rating of 1 says why.

The rules read the dict :meth:`BidNoBidService.validation_input` builds. Errors block "Record decision";
warnings are shown and the estimator decides.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.i18n import get_locale
from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
    validation_engine,
)
from app.core.validation.messages import translate
from app.modules.bid_no_bid.logic import CRITERIA, MAX_RATING, MIN_RATING

logger = logging.getLogger(__name__)

RULE_SET = "bid_no_bid"


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _result(rule: ValidationRule, passed: bool, message: str, ref: str | None = None, **details: Any) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=ref,
        details=details,
    )


def _msg(rule: ValidationRule, context: ValidationContext, **params: Any) -> str:
    """The rule's failure message in the caller's locale; criterion keys are shown by their translated name."""
    locale = str((context.metadata or {}).get("locale") or "en")
    if "criterion" in params:
        params["criterion"] = translate(f"bid_no_bid.criteria.{params['criterion']}", locale=locale)
    return translate(f"{rule.rule_id}.fail", locale=locale, **params)


class WeightsSum100(ValidationRule):
    rule_id = "bid_no_bid.weights_sum_100"
    name = "Weights Add Up To 100"
    standard = "custom"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "The criterion weights are not negative and add up to 100."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        weights = _data(context).get("weights") or {}
        values = [weights.get(k) for k in CRITERIA]
        numeric = [v for v in values if isinstance(v, int) and not isinstance(v, bool)]
        total = sum(numeric)
        ok = len(numeric) == len(CRITERIA) and all(v >= 0 for v in numeric) and total == 100
        return [_result(self, ok, "OK" if ok else _msg(self, context, total=total), None, total=total)]


class AllCriteriaRated(ValidationRule):
    rule_id = "bid_no_bid.all_criteria_rated"
    name = "Every Criterion Is Rated"
    standard = "custom"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Client, capacity, risk, margin and competition each have a rating from 1 to 5."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        scores = _data(context).get("scores") or {}
        out: list[RuleResult] = []
        for key in CRITERIA:
            v = scores.get(key)
            ok = isinstance(v, int) and not isinstance(v, bool) and MIN_RATING <= v <= MAX_RATING
            out.append(_result(self, ok, "OK" if ok else _msg(self, context, criterion=key), key))
        return out


class OverrideHasReason(ValidationRule):
    rule_id = "bid_no_bid.override_has_reason"
    name = "Override Needs A Reason"
    standard = "custom"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "A decision against the score's recommendation states why."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        decision, rec = data.get("decision") or "", data.get("recommendation") or ""
        if not decision or not rec or decision == rec:
            return []
        ok = bool(str(data.get("decision_reason") or "").strip())
        return [_result(self, ok, "OK" if ok else _msg(self, context))]


class LowRatingHasNote(ValidationRule):
    rule_id = "bid_no_bid.low_rating_has_note"
    name = "Lowest Rating Is Explained"
    standard = "custom"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "A criterion rated 1 carries a short note on why."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        scores, notes = data.get("scores") or {}, data.get("notes") or {}
        return [
            _result(
                self,
                bool(str(notes.get(k) or "").strip()),
                "OK" if str(notes.get(k) or "").strip() else _msg(self, context, criterion=k),
                k,
            )
            for k in CRITERIA
            if scores.get(k) == MIN_RATING
        ]


_RULES: tuple[ValidationRule, ...] = (WeightsSum100(), AllCriteriaRated(), OverrideHasReason(), LowRatingHasNote())
RULE_IDS: tuple[str, ...] = tuple(r.rule_id for r in _RULES)


def register_bid_no_bid_rules() -> None:
    for rule in _RULES:
        rule_registry.register(rule, [RULE_SET])


async def evaluate(data: dict[str, Any], *, target_id: str = "") -> list[RuleResult]:
    """Failed findings for one scorecard; an engine failure logs and returns none."""
    try:
        report = await validation_engine.validate(
            data=data,
            rule_sets=[RULE_SET],
            target_type="bid_no_bid",
            target_id=target_id,
            metadata={"locale": get_locale()},
        )
    except Exception:  # noqa: BLE001 - findings augment a read, never break it
        logger.warning("bid / no-bid validation failed for %s", target_id, exc_info=True)
        return []
    return [r for r in report.results if not r.passed and not r.is_engine_error]

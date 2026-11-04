# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules for rate-feedback proposals (rule set ``rate_feedback``).

* ``rate_feedback.rate_positive``     the suggested rate is a finite number above zero.
* ``rate_feedback.sample_present``    at least one project and one line stand behind it.
* ``rate_feedback.confidence_range``  confidence lies within 0..1.
* ``rate_feedback.unit_matches``      the proposal unit is the cost item's unit.
* ``rate_feedback.low_confidence``    (warning) confidence is below the review floor.
* ``rate_feedback.jump_plausible``    (warning) the change is within a factor of 3 either way.

Each rule reads a plain dict: ``{"proposal": {...}, "item": {"unit", "rate"}}``.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)

RATE_FEEDBACK_RULE_SET = "rate_feedback"
LOW_CONFIDENCE_FLOOR = Decimal("0.3")
MAX_JUMP = Decimal("3")
_ZERO = Decimal(0)
_ONE = Decimal(1)


class RateFeedbackError(Exception):
    """A decision the module refuses; carries the HTTP status and a stable code."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _dec(value: Any) -> Decimal | None:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def check_confirmable(proposal: dict[str, Any], item: dict[str, Any] | None) -> None:
    """Raise when a pending proposal can no longer be applied to the cost item as it stands."""
    if proposal.get("status") != "pending":
        raise RateFeedbackError(409, "not_pending", "Only a pending proposal can be decided.")
    if item is None:
        raise RateFeedbackError(409, "cost_item_gone", "The cost item no longer exists.")
    if (proposal.get("unit") or "") != (item.get("unit") or ""):
        raise RateFeedbackError(409, "unit_changed", "The cost item unit changed since the proposal.")
    if _dec(item.get("rate")) != _dec(proposal.get("current_rate")):
        raise RateFeedbackError(409, "stale_rate", "The cost item rate changed since the proposal; refresh first.")


class _Rule(ValidationRule):
    standard = "universal"
    category = RuleCategory.CONSISTENCY

    @staticmethod
    def _data(context: ValidationContext) -> dict[str, Any]:
        return context.data if isinstance(context.data, dict) else {}

    def _result(self, passed: bool, message: str) -> list[RuleResult]:
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=passed,
                message="OK" if passed else message,
            )
        ]


class RatePositive(_Rule):
    rule_id = "rate_feedback.rate_positive"
    name = "Suggested rate is positive"
    description = "A suggested rate must be a finite number above zero."
    severity = Severity.ERROR

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        rate = _dec(self._data(context).get("proposal", {}).get("suggested_rate"))
        return self._result(rate is not None and rate > _ZERO, "Suggested rate must be above zero.")


class SamplePresent(_Rule):
    rule_id = "rate_feedback.sample_present"
    name = "Proposal has a sample"
    description = "At least one project and one line must stand behind a proposal."
    severity = Severity.ERROR

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        p = self._data(context).get("proposal", {})
        good = int(p.get("project_count") or 0) >= 1 and int(p.get("line_count") or 0) >= 1
        return self._result(good, "A proposal needs at least one project and one line.")


class ConfidenceRange(_Rule):
    rule_id = "rate_feedback.confidence_range"
    name = "Confidence within 0..1"
    description = "Confidence is a score between 0 and 1."
    severity = Severity.ERROR

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        c = _dec(self._data(context).get("proposal", {}).get("confidence"))
        return self._result(c is not None and _ZERO <= c <= _ONE, "Confidence out of range.")


class UnitMatches(_Rule):
    rule_id = "rate_feedback.unit_matches"
    name = "Unit matches the cost item"
    description = "Hours and rate per unit only mean something in the cost item's own unit."
    severity = Severity.ERROR

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = self._data(context)
        same = (d.get("proposal", {}).get("unit") or "") == ((d.get("item") or {}).get("unit") or "")
        return self._result(same, "Proposal unit differs from the cost item unit.")


class LowConfidence(_Rule):
    rule_id = "rate_feedback.low_confidence"
    name = "Confidence below review floor"
    description = "A thin or inconsistent sample is worth a second look before confirming."
    severity = Severity.WARNING

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        c = _dec(self._data(context).get("proposal", {}).get("confidence")) or _ZERO
        return self._result(c >= LOW_CONFIDENCE_FLOOR, "Low confidence: check the sample.")


class JumpPlausible(_Rule):
    rule_id = "rate_feedback.jump_plausible"
    name = "Change is plausible"
    description = "A rate moving more than threefold either way usually points to a unit or data error."
    severity = Severity.WARNING

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        p = self._data(context).get("proposal", {})
        cur, new = _dec(p.get("current_rate")), _dec(p.get("suggested_rate"))
        if not cur or cur <= _ZERO or new is None:
            return self._result(True, "")
        return self._result(_ONE / MAX_JUMP <= new / cur <= MAX_JUMP, "Rate moves more than 3x.")


RATE_FEEDBACK_RULES = (RatePositive, SamplePresent, ConfidenceRange, UnitMatches, LowConfidence, JumpPlausible)


def register_rate_feedback_rules() -> None:
    """Register every rule under the ``rate_feedback`` rule set (idempotent)."""
    for rule_cls in RATE_FEEDBACK_RULES:
        rule_registry.register(rule_cls(), [RATE_FEEDBACK_RULE_SET])


async def run_rules(proposal: dict[str, Any], item: dict[str, Any] | None) -> list[RuleResult]:
    """Run the whole set on one proposal and return the findings that did not pass."""
    ctx = ValidationContext(data={"proposal": proposal, "item": item or {}})
    out: list[RuleResult] = []
    for rule_cls in RATE_FEEDBACK_RULES:
        out.extend(r for r in await rule_cls().validate(ctx) if not r.passed)
    return out

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rule set ``tendering_sealed`` for the sealed submission mode.

The rules read the payload built by ``SealedTenderService.validation_payload``::

    {"mode", "deadline", "deadline_ok", "dual_opening", "first_approver_id",
     "opened_by", "opened", "bids": [{"bid_id", "has_receipt", "received_at",
     "on_time", "intact"}]}

Most of them are also enforced at write time. They exist as rules so a package
can be checked as a whole, after a deadline move or a direct database change.
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

SEALED_RULE_SET = "tendering_sealed"


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _bids(context: ValidationContext) -> list[dict[str, Any]]:
    raw = _data(context).get("bids") or []
    return [b for b in raw if isinstance(b, dict)]


def _sealed(context: ValidationContext) -> bool:
    return _data(context).get("mode") == "sealed"


class _SealedRule(ValidationRule):
    standard = "tendering"
    category = RuleCategory.CONSISTENCY
    severity = Severity.ERROR

    def _result(self, passed: bool, ref: str, fail: str, suggestion: str) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message="OK" if passed else fail,
            element_ref=ref,
            suggestion=None if passed else suggestion,
        )


class SealedDeadlineIsInstant(_SealedRule):
    rule_id = "tendering_sealed.deadline_is_instant"
    name = "Sealed deadline has time and zone"
    description = "A sealed tender needs a deadline with a clock time and a UTC offset."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _sealed(context):
            return []
        ok = bool(_data(context).get("deadline_ok"))
        return [
            self._result(
                ok,
                "deadline",
                "The sealed deadline has no clock time or no time zone",
                "Set the deadline as a date and time with its time zone",
            )
        ]


class SealedBidHasReceipt(_SealedRule):
    rule_id = "tendering_sealed.bid_has_receipt"
    name = "Sealed bid has a receipt"
    description = "Every bid on a sealed package came through a submission that issued a receipt."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _sealed(context):
            return []
        return [
            self._result(
                bool(b.get("has_receipt")),
                str(b.get("bid_id", "")),
                "Bid on a sealed package has no submission receipt",
                "Remove the bid and ask the firm to submit through its bidder link",
            )
            for b in _bids(context)
        ]


class SealedBidOnTime(_SealedRule):
    rule_id = "tendering_sealed.bid_on_time"
    name = "Sealed bid received before the deadline"
    description = "A sealed submission must be received before the deadline."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _sealed(context):
            return []
        return [
            self._result(
                bool(b.get("on_time")),
                str(b.get("bid_id", "")),
                "Sealed bid was received at or after the deadline",
                "Exclude the bid from evaluation",
            )
            for b in _bids(context)
            if b.get("has_receipt")
        ]


class SealedBidIntact(_SealedRule):
    rule_id = "tendering_sealed.bid_intact"
    name = "Sealed bid matches its receipt"
    description = "The stored content of a sealed bid still hashes to the digest on its receipt."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _sealed(context):
            return []
        return [
            self._result(
                bool(b.get("intact")),
                str(b.get("bid_id", "")),
                "Stored bid content differs from what the bidder submitted",
                "Investigate the change in the audit log before evaluating this bid",
            )
            for b in _bids(context)
            if b.get("has_receipt")
        ]


class SealedDualOpeningDistinct(_SealedRule):
    rule_id = "tendering_sealed.dual_opening_distinct"
    name = "Two-person opening by two users"
    description = "A two-person opening is completed by a user other than the first approver."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        if not _sealed(context) or not data.get("dual_opening") or not data.get("opened"):
            return []
        first, second = data.get("first_approver_id"), data.get("opened_by")
        ok = bool(first) and bool(second) and first != second
        return [
            self._result(
                ok,
                "opening",
                "The two-person opening was not completed by two different users",
                "Review the opening in the audit log",
            )
        ]


def register_tendering_validation_rules() -> None:
    """Register the sealed-mode rules with the platform rule registry."""
    for rule in (
        SealedDeadlineIsInstant(),
        SealedBidHasReceipt(),
        SealedBidOnTime(),
        SealedBidIntact(),
        SealedDualOpeningDistinct(),
    ):
        rule_registry.register(rule, [SEALED_RULE_SET])

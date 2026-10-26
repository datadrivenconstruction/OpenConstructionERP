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
    register_tendering_addenda_rules()


# ── Addenda, revisions, questions and bid bonds ─────────────────────────────
# Read the payload built by ``addenda.validation_payload``. Day thresholds come
# from the payload's ``rules`` (country data plus package overrides).

ADDENDA_RULE_SET = "tendering_addenda"


class _AddendaRule(_SealedRule):
    category = RuleCategory.COMPLIANCE


class AddendumAcknowledgedAtClosing(_AddendaRule):
    rule_id = "tendering_addenda.acknowledged_at_closing"
    name = "Every invited firm acknowledged every addendum at closing"
    description = "At closing, each published addendum is acknowledged by every firm it was issued to."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        if not data.get("closed"):
            return []
        return [
            self._result(
                not a.get("pending_recipient_ids"),
                str(a.get("id", "")),
                f"Addendum {a.get('revision_no')} not acknowledged by {len(a.get('pending_recipient_ids') or [])} firm(s)",
                "Obtain the acknowledgement or treat the bid as non-compliant",
            )
            for a in data.get("addenda") or []
        ]


class BidPricedCurrentRevision(_AddendaRule):
    rule_id = "tendering_addenda.bid_on_current_revision"
    name = "Bid priced on the current BOQ revision"
    description = "A bid priced on a superseded tender BOQ revision does not cover the changed lines."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return [
            self._result(
                bool(b.get("revision_current")),
                str(b.get("bid_id", "")),
                f"Bid priced BOQ revision {b.get('boq_revision_no')}, current is {b.get('current_boq_revision')}",
                "Ask the bidder to reprice the changed lines on the current revision",
            )
            for b in _bids(context)
        ]


class QuestionAnsweredInTime(_AddendaRule):
    rule_id = "tendering_addenda.question_answered_in_time"
    name = "Bidder questions answered in time"
    description = "A question is answered no later than the configured number of days before closing."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        need = int((data.get("rules") or {}).get("answer_min_days_before_closing") or 0)
        out = []
        for q in data.get("questions") or []:
            left = q.get("days_left")
            if left is None:
                continue
            late = left < need
            out.append(
                self._result(
                    not late,
                    str(q.get("id", "")),
                    f"Question {q.get('number')} {'answered' if q.get('answered') else 'unanswered'} "
                    f"{left} day(s) before closing, {need} required",
                    "Answer and publish now, or extend the deadline by addendum",
                )
            )
        return out


class AddendumNotTooLate(_AddendaRule):
    rule_id = "tendering_addenda.addendum_not_too_late"
    name = "Addendum issued early enough before closing"
    description = "An addendum issued closer to closing than the configured minimum leaves bidders too little time."
    severity = Severity.WARNING

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        need = int((data.get("rules") or {}).get("addendum_min_days_before_closing") or 0)
        return [
            self._result(
                a.get("days_before_closing") is None or int(a["days_before_closing"]) >= need,
                str(a.get("id", "")),
                f"Addendum {a.get('revision_no')} issued {a.get('days_before_closing')} day(s) before closing, "
                f"{need} recommended",
                "Extend the deadline in the same or a further addendum",
            )
            for a in data.get("addenda") or []
        ]


class BidBondCoversValidity(_AddendaRule):
    rule_id = "tendering_addenda.bid_bond_covers_validity"
    name = "Bid bond runs past the bid validity"
    description = "A bid bond must not expire before the bid validity period ends, also after a deadline extension."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        until = data.get("bid_validity_until")
        if not until:
            return []
        return [
            self._result(
                bool(b.get("expiry_date")) and str(b["expiry_date"]) >= str(until),
                str(b.get("guarantee_id", "")),
                f"Bid bond {b.get('reference')} expires {b.get('expiry_date') or 'never set'}, "
                f"bid validity runs to {until}",
                "Ask the bidder for an extension of the bid bond",
            )
            for b in data.get("bonds") or []
        ]


def register_tendering_addenda_rules() -> None:
    """Register the addenda rules with the platform rule registry."""
    for rule in (
        AddendumAcknowledgedAtClosing(),
        BidPricedCurrentRevision(),
        QuestionAnsweredInTime(),
        AddendumNotTooLate(),
        BidBondCoversValidity(),
    ):
        rule_registry.register(rule, [ADDENDA_RULE_SET])

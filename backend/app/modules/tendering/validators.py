# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Validation rule set ``tendering_sealed`` for the sealed submission mode.

The rules read the payload built by ``SealedTenderService.validation_payload``::

    {"mode", "deadline", "deadline_ok", "dual_opening", "first_approver_id",
     "opened_by", "opened", "bids": [{"bid_id", "has_receipt", "received_at",
     "on_time", "intact"}]}

Most of them are also enforced at write time. They exist as rules so a package
can be checked as a whole, after a deadline move or a direct database change.
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
    register_tendering_parties_rules()
    register_tendering_contents_rules()
    register_award_rules()


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


# ── Parties ─────────────────────────────────────────────────────────────────
# Reads the payload built by ``parties.validation_payload``:
# ``{"bidders": [{"id", "kind", "name", "contact_id"}]}``.

PARTIES_RULE_SET = "tendering_parties"


class BidderHasParty(_SealedRule):
    rule_id = "tendering_parties.bidder_has_party"
    name = "Bidder is linked to a party"
    description = "Every invited firm and every bid should be linked to a contact, so one firm is one identity."
    severity = Severity.WARNING

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        raw = _data(context).get("bidders") or []
        return [
            self._result(
                bool(b.get("contact_id")),
                f"{b.get('kind', 'bidder')}:{b.get('id', '')}",
                f"{b.get('name') or 'A bidder'} is not linked to a party",
                "Link the bidder to a contact, or confirm the suggested one",
            )
            for b in raw
            if isinstance(b, dict)
        ]


def register_tendering_parties_rules() -> None:
    """Register the party rules with the platform rule registry."""
    rule_registry.register(BidderHasParty(), [PARTIES_RULE_SET])


# ── Package contents: lines, budget, resource scope ─────────────────────────
# Reads the payload built by ``package_contents_payload``:
# ``{"item_count", "budget_computed", "budget_override",
#    "lines": [{"id", "ordinal", "split", "unsplittable", "budget_total"}]}``.

CONTENTS_RULE_SET = "tendering_contents"

#: Share by which a hand-entered budget may differ from the sum before it is flagged.
OVERRIDE_TOLERANCE = 0.25


def package_contents_payload(preview: Any) -> dict[str, Any]:
    """The rule payload of a :class:`PackagePreviewResponse`."""
    return {
        "item_count": preview.item_count,
        "budget_computed": float(preview.budget_computed),
        "budget_override": float(preview.budget_override) if preview.budget_override is not None else None,
        "scope_active": preview.scope_active,
        "lines": [
            {
                "id": line.id,
                "ordinal": line.ordinal,
                "split": line.split,
                "unsplittable": line.unsplittable,
                "budget_total": float(line.budget_total or 0),
            }
            for line in preview.lines
            if line.kind == "item"
        ],
    }


class PackageHasLines(_SealedRule):
    rule_id = "tendering_contents.has_lines"
    name = "Package has lines to price"
    description = "A package goes out with at least one line for the bidders to price."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ok = int(_data(context).get("item_count") or 0) > 0
        return [
            self._result(
                ok,
                "package",
                "The package has no lines to price",
                "Link the package to a BOQ, or choose the sections it covers",
            )
        ]


class BudgetOverrideNearComputed(_SealedRule):
    rule_id = "tendering_contents.override_near_computed"
    name = "Entered budget is near the computed one"
    description = "A budget entered by hand that differs from the sum of the lines by more than 25% is flagged."
    severity = Severity.WARNING

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        override = data.get("budget_override")
        computed = float(data.get("budget_computed") or 0)
        if override is None or computed <= 0:
            return []
        ok = abs(float(override) - computed) / computed <= OVERRIDE_TOLERANCE
        return [
            self._result(
                ok,
                "budget",
                "The entered budget differs from the sum of the lines by more than 25%",
                "Check the entered budget, or clear it to use the computed sum",
            )
        ]


class ScopeLeavesCostOnLine(_SealedRule):
    rule_id = "tendering_contents.scope_leaves_cost"
    name = "Every line keeps something to price"
    description = "A resource scope that takes every component of a line out leaves the bidder nothing to price."
    severity = Severity.WARNING

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _data(context).get("scope_active"):
            return []
        return [
            self._result(
                not (line.get("split") and float(line.get("budget_total") or 0) <= 0),
                f"line:{line.get('id', '')}",
                f"Line {line.get('ordinal') or line.get('id')} has no component left in the package",
                "Include at least one component of the line, or take the line out of the package",
            )
            for line in _data(context).get("lines") or []
            if isinstance(line, dict) and line.get("split")
        ]


class ScopeCanSplitLine(_SealedRule):
    rule_id = "tendering_contents.scope_can_split"
    name = "Scoped lines have cost components"
    description = "A line without priced components cannot be split by cost kind and is budgeted in full."
    severity = Severity.WARNING

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if not _data(context).get("scope_active"):
            return []
        return [
            self._result(
                False,
                f"line:{line.get('id', '')}",
                f"Line {line.get('ordinal') or line.get('id')} has no cost components and is budgeted in full",
                "Add the line's resources in the BOQ, or enter the package budget by hand",
            )
            for line in _data(context).get("lines") or []
            if isinstance(line, dict) and line.get("unsplittable")
        ]


def register_tendering_contents_rules() -> None:
    """Register the package-contents rules with the platform rule registry."""
    for rule in (PackageHasLines(), BudgetOverrideNearComputed(), ScopeLeavesCostOnLine(), ScopeCanSplitLine()):
        rule_registry.register(rule, [CONTENTS_RULE_SET])


# ── Award: terms, final offer, contract draft, bidder gate ──────────────────
# Reads the payload built by ``award_terms.AwardTermsService._payload``:
# ``{"rounds_count", "final_round_no", "final_round_approved", "used_round_no",
#    "revisions_count", "offer_total", "discount_percent", "expected_contract_sum",
#    "contract_sum", "contract_type", "line_totals", "gate": {"findings"},
#    "contract": {"total_value", "contract_type", "line_count", "lines_total"} | None}``.

AWARD_RULE_SET = "award"


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _findings(context: ValidationContext, rule_id: str) -> list[dict[str, Any]]:
    gate = _data(context).get("gate") or {}
    raw = gate.get("findings") if isinstance(gate, dict) else None
    return [f for f in raw or [] if isinstance(f, dict) and f.get("rule_id") == rule_id]


class _GateRule(_SealedRule):
    category = RuleCategory.COMPLIANCE
    fail_message = ""
    suggestion_text = "Open the firm in the subcontractor directory and clear the block or file the certificate"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        gate = _data(context).get("gate") or {}
        ref = f"subcontractor:{gate.get('subcontractor_id') or ''}"
        return [
            self._result(
                False,
                ref,
                self.fail_message.format(document=f.get("document_type") or f.get("code") or ""),
                self.suggestion_text,
            )
            for f in _findings(context, self.rule_id)
        ]


class AwardBidderBlocked(_GateRule):
    rule_id = "award.bidder_blocked"
    name = "Bidder is not blocked"
    description = "A firm the subcontractor directory blocks, or whose prequalification is rejected or suspended."
    fail_message = "This firm is blocked and cannot be invited or awarded"


class AwardEvidenceExpired(_GateRule):
    rule_id = "award.evidence_expired"
    name = "Required certificate is valid"
    description = "A certificate the project's pack requires has expired or was revoked."
    fail_message = "A required certificate has expired: {document}"


class AwardEvidenceMissing(_GateRule):
    rule_id = "award.evidence_missing"
    name = "Required certificate is on file"
    description = "A certificate the project's pack requires is not on file; payment will be held."
    severity = Severity.WARNING
    fail_message = "A required certificate is not on file, payment will be held: {document}"


class AwardContractSumMismatch(_SealedRule):
    rule_id = "award.contract_sum_mismatch"
    name = "Contract sum is the final offer minus discount"
    description = "The contract sum equals the final offer (lines sum, or lump sum) less the agreed discount."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        expected = _dec(data.get("expected_contract_sum"))
        contract = data.get("contract")
        actual = _dec(contract.get("total_value")) if isinstance(contract, dict) else _dec(data.get("contract_sum"))
        return [
            self._result(
                actual == expected,
                f"contract:{contract.get('id')}" if isinstance(contract, dict) else "award",
                f"Contract sum {actual} differs from final offer minus discount {expected}",
                "Correct the contract value or the award terms so both name the same figure",
            )
        ]


class AwardLumpSumLinesReconcile(_SealedRule):
    rule_id = "award.lump_sum_lines_reconcile"
    name = "Lump-sum contract lines add up"
    description = "The lines of a lump-sum contract add up to the agreed lump sum."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        contract = data.get("contract")
        if isinstance(contract, dict):
            if contract.get("contract_type") != "lump_sum" or not contract.get("line_count"):
                return []
            total, lines = _dec(contract.get("total_value")), _dec(contract.get("lines_total"))
            ref = f"contract:{contract.get('id')}"
        else:
            raw = data.get("line_totals") or []
            if data.get("contract_type") != "lump_sum" or not raw:
                return []
            total, lines = _dec(data.get("contract_sum")), sum((_dec(v) for v in raw), Decimal("0"))
            ref = "award"
        return [
            self._result(
                lines == total,
                ref,
                f"Contract lines add up to {lines}, not to the agreed lump sum {total}",
                "Spread the lump sum over the lines again",
            )
        ]


class AwardNoFinalRevision(_SealedRule):
    rule_id = "award.no_final_revision"
    name = "A bid revision is marked final"
    description = "The bid was revised but no revision is marked final; the latest one is used."
    severity = Severity.WARNING

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        if int(data.get("rounds_count") or 0) > 0 or int(data.get("revisions_count") or 0) == 0:
            return []
        return [
            self._result(
                False,
                f"bid:{data.get('bid_id', '')}",
                "No bid revision is marked final; the latest one is used",
                "Record the agreed offer as a negotiation round and mark it final",
            )
        ]


class AwardFinalOfferRequired(_SealedRule):
    rule_id = "award.final_offer_required"
    name = "Negotiated bid has a final offer"
    description = "A bid with negotiation rounds is awarded on the round marked final."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        if int(data.get("rounds_count") or 0) == 0:
            return []
        return [
            self._result(
                data.get("final_round_no") is not None,
                f"bid:{data.get('bid_id', '')}",
                "The bid has negotiation rounds but none is marked as the final offer",
                "Mark the round the firm agreed to as final",
            )
        ]


class AwardFinalOfferApproved(_SealedRule):
    rule_id = "award.final_offer_not_approved"
    name = "Final offer is approved"
    description = "The final offer of a negotiated bid is approved before the award."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        if data.get("final_round_no") is None:
            return []
        return [
            self._result(
                bool(data.get("final_round_approved")),
                f"bid:{data.get('bid_id', '')}",
                "The final offer is not approved yet",
                "Approve the final offer; the approval asks the commitment release matrix",
            )
        ]


def register_award_rules() -> None:
    """Register the award rules with the platform rule registry."""
    for rule in (
        AwardBidderBlocked(),
        AwardEvidenceExpired(),
        AwardEvidenceMissing(),
        AwardContractSumMismatch(),
        AwardLumpSumLinesReconcile(),
        AwardNoFinalRevision(),
        AwardFinalOfferRequired(),
        AwardFinalOfferApproved(),
    ):
        rule_registry.register(rule, [AWARD_RULE_SET])

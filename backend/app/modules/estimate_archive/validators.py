# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules for sealed estimates, their openings and rates carried from them.

Three rule sets, each fed a plain dict by the service:

* ``estimate_archive`` - a seal: fingerprint, total against the award value,
  breakdown, markups, timing, receipt and openings left open.
* ``estimate_archive_opening`` - an opening request: reason and reference,
  counterparty presence where the contract requires both parties.
* ``estimate_archive_pricing`` - a change line priced from the seal: basis
  claimed without a seal, unexplained deviations, unevidenced new resources,
  markups outside the sealed stack, carried costs far from a benchmark.

Only failures are reported; a rule that has nothing to say returns nothing.
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
from app.core.validation.messages import translate
from app.core.validation.rules import _fmt_money
from app.modules.estimate_archive.engine import dec

SEAL_RULE_SET = "estimate_archive"
OPENING_RULE_SET = "estimate_archive_opening"
PRICING_RULE_SET = "estimate_archive_pricing"

#: Sub-cent gaps are rounding, not disagreement (rule S3).
_TOLERANCE = Decimal("0.01")
#: An opening left open longer than this is flagged.
OPEN_DAYS_LIMIT = 7
#: Carried unit cost this far (percent) from the benchmark is worth a look.
ABNORMAL_PCT = Decimal("30")


def _locale(context: ValidationContext) -> str:
    meta = getattr(context, "metadata", None) or {}
    return str(meta.get("locale") or "en")


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


class _ArchiveRule(ValidationRule):
    """Shared helper: build one failing result with a translated message."""

    standard = "estimate_archive"
    code = ""

    def fail(self, context: ValidationContext, ref: str = "", **params: Any) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=False,
            message=translate(f"estimate_archive.{self.code.lower()}.fail", locale=_locale(context), **params),
            element_ref=ref or None,
            details={**{k: str(v) for k, v in params.items()}, "code": self.code},
        )


# ── Seal ─────────────────────────────────────────────────────────────────────


class HashMismatch(_ArchiveRule):
    rule_id = "estimate_archive.hash_mismatch"
    code = "ARC_HASH_MISMATCH"
    name = "Sealed fingerprint matches its content"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Recomputes the SHA-256 of the sealed payload and compares it with the stored fingerprint."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = _data(context)
        actual, sealed = d.get("recomputed_hash"), d.get("content_hash")
        if not actual or actual == sealed:
            return []
        return [self.fail(context, str(d.get("seal_id") or ""), actual=str(actual)[:8], sealed=str(sealed)[:8])]


class TotalMismatch(_ArchiveRule):
    rule_id = "estimate_archive.total_mismatch"
    code = "ARC_TOTAL_MISMATCH"
    name = "Sealed total matches the award value"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Positions plus markups must equal the contract's original value within 0.01."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = _data(context)
        if d.get("award_value") in (None, ""):
            return []
        seal, award = dec(d.get("seal_total")), dec(d.get("award_value"))
        diff = seal - award
        if abs(diff) < _TOLERANCE:
            return []
        cur = str(d.get("currency") or "")
        return [
            self.fail(
                context,
                str(d.get("seal_id") or ""),
                seal=_fmt_money(seal, cur),
                award=_fmt_money(award, cur),
                diff=_fmt_money(diff, cur),
            )
        ]


class NoBreakdown(_ArchiveRule):
    rule_id = "estimate_archive.no_breakdown"
    code = "ARC_NO_BREAKDOWN"
    name = "Priced positions carry a resource breakdown"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "A rate without resource lines cannot be carried forward."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        n = int(_data(context).get("positions_without_breakdown") or 0)
        return [self.fail(context, n=n)] if n else []


class NoMarkups(_ArchiveRule):
    rule_id = "estimate_archive.no_markups"
    code = "ARC_NO_MARKUPS"
    name = "Seal holds the markup stack"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Without markup lines carried rates use net cost only."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = _data(context)
        return [self.fail(context)] if int(d.get("markup_count") or 0) == 0 else []


class SealedAfterSigning(_ArchiveRule):
    rule_id = "estimate_archive.sealed_after_signing"
    code = "ARC_SEALED_AFTER_SIGNING"
    name = "Sealed before or at contract signature"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "A seal made after signature is weaker evidence of the tender basis."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        days = _data(context).get("sealed_days_after_signing")
        return [self.fail(context, days=int(days))] if isinstance(days, int) and days > 0 else []


class NoReceipt(_ArchiveRule):
    rule_id = "estimate_archive.no_receipt"
    code = "ARC_NO_RECEIPT"
    name = "Counterparty acknowledged the fingerprint"
    severity = Severity.INFO
    category = RuleCategory.COMPLETENESS
    description = "Shows when no signed or external receipt exists for the seal."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        status = str(_data(context).get("receipt_status") or "none")
        return [] if status in ("signed", "external") else [self.fail(context)]


class OpenNotClosed(_ArchiveRule):
    rule_id = "estimate_archive.open_not_closed"
    code = "ARC_OPEN_NOT_CLOSED"
    name = "Openings are closed"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "An opening left open for more than seven days."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for row in _data(context).get("open_openings") or []:
            days = int(row.get("days") or 0)
            if days > OPEN_DAYS_LIMIT:
                out.append(
                    self.fail(context, str(row.get("id") or ""), id=str(row.get("label") or row.get("id")), days=days)
                )
        return out


# ── Opening ──────────────────────────────────────────────────────────────────


class OpenNoReason(_ArchiveRule):
    rule_id = "estimate_archive.open_no_reason"
    code = "ARC_OPEN_NO_REASON"
    name = "Opening has a reason and a reference"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Every opening names why it happens and what it is for."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = _data(context)
        has_ref = bool(str(d.get("reference_label") or "").strip() or d.get("reference_id"))
        return [] if d.get("reason") and has_ref else [self.fail(context)]


class OpenOneParty(_ArchiveRule):
    rule_id = "estimate_archive.open_one_party"
    code = "ARC_OPEN_ONE_PARTY"
    name = "Counterparty attends where both parties are required"
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    description = "Flags an opening without a counterparty representative under a both-parties rule."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = _data(context)
        if not d.get("require_both_parties"):
            return []
        attendees = d.get("attendees") or []
        if any(str(a.get("side")) == "counterparty" for a in attendees if isinstance(a, dict)):
            return []
        return [self.fail(context)]


# ── Pricing from the seal ────────────────────────────────────────────────────


class BasisNoSeal(_ArchiveRule):
    rule_id = "estimate_archive.var_basis_no_seal"
    code = "VAR_BASIS_NO_SEAL"
    name = "Original basis needs a seal"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "A line priced on the original basis where the contract has no seal."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = _data(context)
        if d.get("basis_method") == "original_basis" and not d.get("has_seal"):
            return [self.fail(context, str(d.get("code") or ""), code=str(d.get("code") or ""))]
        return []


class BasisDeviation(_ArchiveRule):
    rule_id = "estimate_archive.var_basis_deviation"
    code = "VAR_BASIS_DEVIATION"
    name = "Changed sealed values carry a note"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Every change of a sealed consumption or unit cost needs a note."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = _data(context)
        return [
            self.fail(
                context,
                str(dev.get("code") or ""),
                code=str(d.get("code") or ""),
                field=dev.get("field"),
                old=dev.get("old"),
                new=dev.get("new"),
            )
            for dev in d.get("deviations") or []
        ]


class NewResourceNoEvidence(_ArchiveRule):
    rule_id = "estimate_archive.var_new_resource_no_evidence"
    code = "VAR_NEW_RESOURCE_NO_EVIDENCE"
    name = "New resources carry a quote or price date"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "A resource the seal did not hold needs evidence of its price."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return [self.fail(context, str(res), res=str(res)) for res in _data(context).get("unevidenced") or []]


class MarkupNotSealed(_ArchiveRule):
    rule_id = "estimate_archive.var_markup_not_sealed"
    code = "VAR_MARKUP_NOT_SEALED"
    name = "Original basis uses only sealed markups"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "A line on the original basis must use the sealed markup stack."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = _data(context)
        if d.get("basis_method") != "original_basis":
            return []
        sealed = {str(n) for n in d.get("sealed_markups") or []}
        return [
            self.fail(context, str(d.get("code") or ""), code=str(d.get("code") or ""), m=str(m))
            for m in d.get("claimed_markups") or []
            if str(m) not in sealed
        ]


class AbnormalCarriedRate(_ArchiveRule):
    rule_id = "estimate_archive.var_abnormal_carried_rate"
    code = "VAR_ABNORMAL_CARRIED_RATE"
    name = "Carried unit costs near the benchmark"
    severity = Severity.INFO
    category = RuleCategory.QUALITY
    description = "A carried unit cost far from the cost database benchmark; a check, not a verdict."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for row in _data(context).get("carried") or []:
            cost, bench = dec(row.get("unit_cost")), dec(row.get("benchmark"))
            if bench <= 0:
                continue
            pct = (cost - bench) / bench * 100
            if abs(pct) >= ABNORMAL_PCT:
                out.append(
                    self.fail(context, str(row.get("code") or ""), c=str(row.get("unit_cost")), pct=f"{pct:+.0f}")
                )
        return out


_SEAL_RULES = (HashMismatch, TotalMismatch, NoBreakdown, NoMarkups, SealedAfterSigning, NoReceipt, OpenNotClosed)
_OPENING_RULES = (OpenNoReason, OpenOneParty)
_PRICING_RULES = (BasisNoSeal, BasisDeviation, NewResourceNoEvidence, MarkupNotSealed, AbnormalCarriedRate)

#: Every rule code the module reports, including the 409 message for a refused mutation.
RULE_CODES = (
    *(r.code for r in (*_SEAL_RULES, *_OPENING_RULES, *_PRICING_RULES)),
    "ARC_MUTATION_REFUSED",
)


def register_estimate_archive_rules() -> None:
    """Idempotently register the three rule sets."""
    for cls in _SEAL_RULES:
        rule_registry.register(cls(), rule_sets=[SEAL_RULE_SET])
    for cls in _OPENING_RULES:
        rule_registry.register(cls(), rule_sets=[OPENING_RULE_SET])
    for cls in _PRICING_RULES:
        rule_registry.register(cls(), rule_sets=[PRICING_RULE_SET])

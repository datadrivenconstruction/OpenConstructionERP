# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Claims evidence validation rules (rule set ``claims_evidence``).

The module assembles an evidence pack and scores its provability; it holds no
money of its own, so the rules check that the pack is internally sound before
it is relied on in a claim. Context::

    {
        "pack": {"subject_ref", "basis", "entry_count", "date_from", "date_to",
                 "sections": [{"name", "entries": [{"ref_id", "source_module",
                                                    "kind", "occurred_at"}]}]},
        "score": {"subject_id", "score", "sub_scores": [{"signal", "weight",
                                                         "earned"}]},
    }
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, blank, section, to_dec

CLAIMS_EVIDENCE_RULE_SET = "claims_evidence"

_ZERO = Decimal("0")


def _entries(pack: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sec in pack.get("sections") or []:
        if isinstance(sec, dict):
            out.extend(e for e in sec.get("entries") or [] if isinstance(e, dict))
    return out


class EvidenceCountMatchesEntriesRule(MoneyRule):
    """The pack's entry count equals the entries its sections hold."""

    rule_id = "claims_evidence.count_matches_entries"
    name = "Evidence pack entry count equals its entries"
    standard = CLAIMS_EVIDENCE_RULE_SET
    description = "entry_count must equal the number of entries across all sections"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        pack = section(context, "pack")
        ref = str(pack.get("subject_ref", ""))
        stated = to_dec(pack.get("entry_count"))
        if stated is None:
            return [self.ok(ref)]
        bad = self.total_mismatch(context, ref, "entry count", stated, Decimal(len(_entries(pack))), "")
        return [bad] if bad else [self.ok(ref)]


class ProvabilityScoreRule(MoneyRule):
    """The score lies in 0..100 and equals the points earned by its signals."""

    rule_id = "claims_evidence.score_in_range"
    name = "Provability score is within range and adds up"
    standard = CLAIMS_EVIDENCE_RULE_SET
    description = "0 <= score <= 100; score equals the sum of earned points; earned <= weight"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        score = section(context, "score")
        ref = str(score.get("subject_id", ""))
        if not score:
            return [self.ok(ref)]
        out: list[RuleResult] = []
        value = to_dec(score.get("score"))
        bad = self.out_of_range(context, ref, "score", value, _ZERO, Decimal("100"))
        if bad:
            out.append(bad)
        subs = [s for s in score.get("sub_scores") or [] if isinstance(s, dict)]
        earned_total = _ZERO
        complete = bool(subs)
        for sub in subs:
            weight, earned = to_dec(sub.get("weight")), to_dec(sub.get("earned"))
            if weight is None or earned is None:
                complete = False
                continue
            earned_total += earned
            bad = self.out_of_range(context, str(sub.get("signal", ref)), "earned", earned, _ZERO, weight)
            if bad:
                out.append(bad)
        if value is not None and complete:
            bad = self.total_mismatch(context, ref, "score", value, earned_total, "")
            if bad:
                out.append(bad)
        return out or [self.ok(ref)]


class EvidenceReferencesRule(MoneyRule):
    """The pack names its subject and basis, and every entry names where it came from."""

    rule_id = "claims_evidence.references_present"
    name = "Evidence pack references present"
    standard = CLAIMS_EVIDENCE_RULE_SET
    description = "subject_ref and basis on the pack; ref_id and source_module on every entry"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        pack = section(context, "pack")
        ref = str(pack.get("subject_ref", ""))
        if not pack:
            return [self.ok(ref)]
        out = [
            self.fail(context, "reference_present", ref=ref, field=field)
            for field in ("subject_ref", "basis")
            if blank(pack.get(field))
        ]
        for entry in _entries(pack):
            for field in ("ref_id", "source_module"):
                if blank(entry.get(field)):
                    out.append(self.fail(context, "reference_present", ref=str(entry.get("ref_id", ref)), field=field))
        return out or [self.ok(ref)]


class EvidenceDatesOrderedRule(MoneyRule):
    """The pack's date window is ordered and contains every dated entry."""

    rule_id = "claims_evidence.dates_ordered"
    name = "Evidence pack dates are in order"
    standard = CLAIMS_EVIDENCE_RULE_SET
    description = "date_from <= date_to, and each entry falls inside the window (ISO dates compared as text)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        pack = section(context, "pack")
        ref = str(pack.get("subject_ref", ""))
        start, end = pack.get("date_from"), pack.get("date_to")
        out: list[RuleResult] = []
        if not blank(start) and not blank(end) and str(start)[:10] > str(end)[:10]:
            out.append(self.fail(context, "dates_ordered", ref=ref, earlier=start, later=end))
        for entry in _entries(pack):
            when = entry.get("occurred_at")
            if blank(when):
                continue
            day = str(when)[:10]
            before = not blank(start) and day < str(start)[:10]
            after = not blank(end) and day > str(end)[:10]
            if before or after:
                out.append(
                    self.fail(
                        context,
                        "dates_ordered",
                        ref=str(entry.get("ref_id", ref)),
                        severity=Severity.WARNING,
                        earlier=start or "",
                        later=when,
                    )
                )
        return out or [self.ok(ref)]


CLAIMS_EVIDENCE_RULES = (
    EvidenceCountMatchesEntriesRule,
    ProvabilityScoreRule,
    EvidenceReferencesRule,
    EvidenceDatesOrderedRule,
)


def register_claims_evidence_validation_rules() -> None:
    """Register the claims evidence rules with the platform rule registry."""
    for rule_class in CLAIMS_EVIDENCE_RULES:
        rule_registry.register(rule_class(), [CLAIMS_EVIDENCE_RULE_SET])

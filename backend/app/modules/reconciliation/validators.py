# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Event reconciliation validation rules (rule set ``reconciliation``).

Rules run over a plain dict built by the service, one decision on a link under the key ``link``::

    {"link": {"id", "left_type", "left_id", "right_type", "right_id", "relation", "status", "confidence"}}

``confidence`` is what the reviewer sent, so a value outside the range is seen as sent instead of being
dropped quietly.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, blank, section, to_dec
from app.modules.reconciliation.correlate import DEFAULT_THRESHOLD

RECONCILIATION_RULE_SET = "reconciliation"

LINK_FIELDS = ("left_type", "left_id", "right_type", "right_id", "relation", "status", "confidence")

#: The record types the gatherers project onto the engine (kept equal to the service's TYPE_* tokens).
RECORD_TYPES = frozenset(
    {"correspondence", "change_order", "variation_request", "variation_order", "notice", "moc"},
)


class _ReconciliationRule(MoneyRule):
    standard = RECONCILIATION_RULE_SET
    message_section = "reconciliation"


class LinkEndpointsRule(_ReconciliationRule):
    """A link joins two named records, and not a record to itself."""

    rule_id = "reconciliation.link_endpoints"
    name = "Link names two different records"
    description = "both endpoints need a type and an id, and they must differ"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        link = section(context, "link")
        ref = str(link.get("id", ""))
        left = (str(link.get("left_type") or "").strip(), str(link.get("left_id") or "").strip())
        right = (str(link.get("right_type") or "").strip(), str(link.get("right_id") or "").strip())
        if not all(left) or not all(right):
            return [self.fail(context, "endpoints_missing", ref=ref)]
        if left == right:
            return [self.fail(context, "link_to_itself", ref=ref, record=f"{left[0]}:{left[1]}")]
        return [self.ok(ref)]


class LinkRecordTypeRule(_ReconciliationRule):
    """Only records the engine can gather are linked."""

    rule_id = "reconciliation.record_type"
    name = "Link joins reconcilable record types"
    description = "left_type and right_type must be record types the reconciliation gathers"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        link = section(context, "link")
        ref = str(link.get("id", ""))
        for side in ("left_type", "right_type"):
            value = str(link.get(side) or "").strip()
            if value and value not in RECORD_TYPES:
                return [self.fail(context, "record_type_unknown", ref=ref, record_type=value)]
        return [self.ok(ref)]


class LinkConfidenceRule(_ReconciliationRule):
    """A match confidence is a ratio between nought and one."""

    rule_id = "reconciliation.confidence_range"
    name = "Match confidence is between 0 and 1"
    description = "confidence must lie in the range 0 to 1"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        link = section(context, "link")
        ref = str(link.get("id", ""))
        raw = link.get("confidence")
        value = to_dec(raw)
        if not blank(raw) and (value is None or value < 0 or value > 1):
            return [self.fail(context, "confidence_out_of_range", ref=ref, confidence=raw)]
        return [self.ok(ref)]


class ConfirmedConfidenceRule(_ReconciliationRule):
    """A reviewer who confirms a weak match is asked to look once more."""

    rule_id = "reconciliation.confirmed_confidence"
    name = "Confirmed link is not a weak match"
    severity = Severity.WARNING
    description = "a confirmed link scored below the suggestion threshold is flagged"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        link = section(context, "link")
        ref = str(link.get("id", ""))
        value = to_dec(link.get("confidence"))
        threshold = Decimal(str(DEFAULT_THRESHOLD))
        if link.get("status") == "confirmed" and value is not None and 0 < value < threshold:
            return [self.fail(context, "confirmed_below_threshold", ref=ref, confidence=value, threshold=threshold)]
        return [self.ok(ref)]


RECONCILIATION_RULES = (LinkEndpointsRule, LinkRecordTypeRule, LinkConfidenceRule, ConfirmedConfidenceRule)


def register_reconciliation_validation_rules() -> None:
    """Register the reconciliation rules with the platform rule registry."""
    for rule_class in RECONCILIATION_RULES:
        rule_registry.register(rule_class(), [RECONCILIATION_RULE_SET])


__all__ = [
    "LINK_FIELDS",
    "RECONCILIATION_RULES",
    "RECONCILIATION_RULE_SET",
    "RECORD_TYPES",
    "register_reconciliation_validation_rules",
]

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Transmittal validation rules (rule set ``transmittals``).

Rules run over a plain dict built by the service::

    {
        "transmittal": {"id", "issuing", "response_due_date"},
        "recipients": [{"recipient_org_id", "recipient_user_id", "recipient_name",
                        "recipient_email", "action_required"}],
        "items": [{"item_number", "document_id", "revision_id", "description"}],
    }

``issuing`` is true only when the transmittal is being sent. A draft may carry
unfinished lines and recipients, so the completeness rules wait for the issue.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, blank, rows, section

TRANSMITTALS_RULE_SET = "transmittals"


class _TransmittalRule(MoneyRule):
    standard = TRANSMITTALS_RULE_SET
    message_section = "transmittals"
    suggestion_key = "transmittals.suggestion"


def _ref(context: ValidationContext) -> str:
    return str(section(context, "transmittal").get("id", ""))


def _issuing(context: ValidationContext) -> bool:
    return bool(section(context, "transmittal").get("issuing"))


class UniqueItemNumbersRule(_TransmittalRule):
    """No two lines of a transmittal share a line number."""

    rule_id = "transmittals.unique_item_numbers"
    name = "Transmittal line numbers are unique"
    description = "Each line of the document list has its own number, so a recipient can cite it"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        counts = Counter(i.get("item_number") for i in rows(context, "items") if i.get("item_number") is not None)
        dup = sorted(str(n) for n, c in counts.items() if c > 1)
        if dup:
            return [self.fail(context, "unique_item_numbers", ref=ref, numbers=", ".join(dup))]
        return [self.ok(ref)]


class ItemIdentifiesDocumentRule(_TransmittalRule):
    """Every line sent names a document, a revision or at least says what it is."""

    rule_id = "transmittals.item_identifies_document"
    name = "Transmittal lines identify what is sent"
    description = "On issue, a line needs a document, a revision or a description"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        if not _issuing(context):
            return [self.ok(ref)]
        empty = [
            str(i.get("item_number", "?"))
            for i in rows(context, "items")
            if blank(i.get("document_id")) and blank(i.get("revision_id")) and blank(i.get("description"))
        ]
        if empty:
            return [self.fail(context, "item_identifies_document", ref=ref, numbers=", ".join(empty))]
        return [self.ok(ref)]


class RecipientIdentifiedRule(_TransmittalRule):
    """Every recipient can actually be reached."""

    rule_id = "transmittals.recipient_identified"
    name = "Transmittal recipients are identified"
    description = "On issue, a recipient needs an organisation, a user, an e-mail address or a name"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        if not _issuing(context):
            return [self.ok(ref)]
        fields = ("recipient_org_id", "recipient_user_id", "recipient_email", "recipient_name")
        unnamed = sum(1 for r in rows(context, "recipients") if all(blank(r.get(f)) for f in fields))
        if unnamed:
            return [self.fail(context, "recipient_identified", ref=ref, count=unnamed)]
        return [self.ok(ref)]


class ActionNeedsDeadlineRule(_TransmittalRule):
    """A recipient asked to act has a date to act by."""

    rule_id = "transmittals.action_needs_deadline"
    name = "Requested action has a response date"
    severity = Severity.WARNING
    description = "On issue, an action requested from a recipient should come with a response due date"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        ref = _ref(context)
        if not _issuing(context) or not blank(section(context, "transmittal").get("response_due_date")):
            return [self.ok(ref)]
        asked = sum(1 for r in rows(context, "recipients") if not blank(r.get("action_required")))
        if asked:
            return [self.fail(context, "action_needs_deadline", ref=ref, count=asked)]
        return [self.ok(ref)]


TRANSMITTALS_RULES = (
    UniqueItemNumbersRule,
    ItemIdentifiesDocumentRule,
    RecipientIdentifiedRule,
    ActionNeedsDeadlineRule,
)


def register_transmittals_validation_rules() -> None:
    """Register the transmittal rules with the platform rule registry."""
    for rule_class in TRANSMITTALS_RULES:
        rule_registry.register(rule_class(), [TRANSMITTALS_RULE_SET])


def snapshot(transmittal: Any, recipients: list[Any], items: list[Any], *, issuing: bool) -> dict[str, Any]:
    """The rule input for a transmittal and its children (ORM rows or schema objects)."""
    rec_fields = ("recipient_org_id", "recipient_user_id", "recipient_name", "recipient_email", "action_required")
    item_fields = ("item_number", "document_id", "revision_id", "description")
    return {
        "transmittal": {
            "id": str(getattr(transmittal, "id", "") or ""),
            "issuing": issuing,
            "response_due_date": getattr(transmittal, "response_due_date", None),
        },
        "recipients": [{f: getattr(r, f, None) for f in rec_fields} for r in recipients],
        "items": [{f: getattr(i, f, None) for f in item_fields} for i in items],
    }


__all__ = ["TRANSMITTALS_RULES", "TRANSMITTALS_RULE_SET", "register_transmittals_validation_rules", "snapshot"]

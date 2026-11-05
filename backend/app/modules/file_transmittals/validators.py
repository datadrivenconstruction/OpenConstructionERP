# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File transmittal validation rules (rule set ``file_transmittals``).

Rules run over a plain dict built by the service, one record under one key::

    {"transmittal": {"id", "status", "reason_code",
                     "items": [{"file_kind", "file_id", "name", "version"}],
                     "recipients": ["a@example.com", ...]}}

``status`` is the status the write leaves the transmittal in, so the send rules fire only when the
write is the dispatch.
"""

from __future__ import annotations

from typing import Any

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import blank, section
from app.core.validation.quality_rules import QualityRule

FILE_TRANSMITTALS_RULE_SET = "file_transmittals"

TRANSMITTAL_FIELDS = ("status", "reason_code", "items", "recipients")


def _items(record: dict[str, Any]) -> list[dict[str, Any]]:
    raw = record.get("items")
    return [i for i in raw if isinstance(i, dict)] if isinstance(raw, list) else []


class _TransmittalRule(QualityRule):
    standard = FILE_TRANSMITTALS_RULE_SET
    message_section = "file_transmittals"


class SendNeedsItemsRule(_TransmittalRule):
    """A transmittal that goes out lists at least one file."""

    rule_id = "file_transmittals.send_has_items"
    name = "Sent transmittal lists files"
    description = "a transmittal being sent needs at least one item"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        t = section(context, "transmittal")
        ref = str(t.get("id", ""))
        if t.get("status") == "sent" and not _items(t):
            return [self.fail(context, "send_without_items", ref=ref)]
        return [self.ok(ref)]


class SendNeedsRecipientsRule(_TransmittalRule):
    """A transmittal that goes out names at least one recipient."""

    rule_id = "file_transmittals.send_has_recipients"
    name = "Sent transmittal names recipients"
    description = "a transmittal being sent needs at least one recipient"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        t = section(context, "transmittal")
        ref = str(t.get("id", ""))
        recipients = t.get("recipients")
        if t.get("status") == "sent" and not (isinstance(recipients, list) and recipients):
            return [self.fail(context, "send_without_recipients", ref=ref)]
        return [self.ok(ref)]


class DuplicateItemRule(_TransmittalRule):
    """The same file revision is listed once; a repeat only inflates the cover sheet."""

    rule_id = "file_transmittals.duplicate_item"
    name = "File is listed once"
    description = "the same file_kind, file_id and version must not appear twice"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        t = section(context, "transmittal")
        ref = str(t.get("id", ""))
        seen: set[tuple[str, str, str]] = set()
        out: list[RuleResult] = []
        for item in _items(t):
            key = (str(item.get("file_kind") or ""), str(item.get("file_id") or ""), str(item.get("version") or ""))
            if key in seen:
                out.append(self.fail(context, "item_duplicate", ref=ref, name=item.get("name") or key[1]))
            seen.add(key)
        return out or [self.ok(ref)]


class ConstructionItemVersionRule(_TransmittalRule):
    """Files issued for construction say which revision they are."""

    rule_id = "file_transmittals.construction_item_version"
    name = "Construction issue names revisions"
    severity = Severity.WARNING
    description = "every item of a for_construction transmittal should carry a version"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        t = section(context, "transmittal")
        ref = str(t.get("id", ""))
        if t.get("reason_code") != "for_construction":
            return [self.ok(ref)]
        out = [
            self.fail(context, "construction_unversioned", ref=ref, name=item.get("name") or item.get("file_id") or "")
            for item in _items(t)
            if blank(item.get("version"))
        ]
        return out or [self.ok(ref)]


FILE_TRANSMITTALS_RULES = (
    SendNeedsItemsRule,
    SendNeedsRecipientsRule,
    DuplicateItemRule,
    ConstructionItemVersionRule,
)


def register_file_transmittals_validation_rules() -> None:
    """Register the file transmittal rules with the platform rule registry."""
    for rule_class in FILE_TRANSMITTALS_RULES:
        rule_registry.register(rule_class(), [FILE_TRANSMITTALS_RULE_SET])


__all__ = [
    "FILE_TRANSMITTALS_RULES",
    "FILE_TRANSMITTALS_RULE_SET",
    "TRANSMITTAL_FIELDS",
    "register_file_transmittals_validation_rules",
]

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Timeline validation rules.

A timeline is only worth reading if the rows on it can be reached, linked and
attributed. These rules are the reader that objects when they cannot:

* ``timeline.unroutable_entry``    - ERROR. A row carrying neither a parent
                                     project nor an entity id. No timeline
                                     query can ever return it, so it is a write
                                     that reads as coverage.
* ``timeline.entry_without_entity`` - WARNING. A row that reaches a project feed
                                     but names no record, so a reader cannot
                                     open the thing it is about.
* ``timeline.unattributed_entry``  - WARNING. The event named an actor and the
                                     row lost them, so "who did this" is
                                     unanswerable for a row that could answer it.

The rules read plain :class:`app.core.audit_log.ActivityLog` rows so they can
run over any slice of the log - a project feed, one record's history, or a
backfill batch:

    {"entries": [ActivityLog, ...]}

They deliberately do not check *what* the timeline captures. That is a question
about the event allowlist versus the events ``app/`` publishes, which is
answered statically and gated in
``tests/modules/timeline/test_timeline_coverage.py``; a runtime rule could only
see the events that already arrived, which is the very set the allowlist
decides.

Registration follows the module convention: :func:`register_timeline_rules` is
idempotent and is called from the module's ``on_startup`` hook, and from the
test suite's fixture because no test process runs application startup.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.timeline.mapping import ACTOR_ID_KEYS

logger = logging.getLogger(__name__)

# The rule set every timeline rule registers under.
TIMELINE_RULE_SET = "timeline"

# Metadata keys the bridge adds itself; they are never event payload content.
_BRIDGE_KEYS: frozenset[str] = frozenset({"_via", "event_id"})


def _payload(context: ValidationContext) -> dict[str, Any]:
    """Read the rule payload out of the context, tolerating an empty run."""
    data = context.data
    return data if isinstance(data, dict) else {}


def _entries(context: ValidationContext) -> list[Any]:
    """The activity-log rows under validation."""
    entries = _payload(context).get("entries")
    return list(entries) if isinstance(entries, (list, tuple)) else []


def _ok(rule: ValidationRule, message: str) -> RuleResult:
    """A single passing result, so a clean run still counts as checked."""
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=True,
        message=message,
    )


def _label(entry: Any) -> str:
    """A human-readable name for one row."""
    return f"{entry.action or entry.entity_type or 'event'}"


class UnroutableEntryRule(ValidationRule):
    """A row no timeline query can ever return."""

    rule_id = "timeline.unroutable_entry"
    name = "Timeline entry is unreachable"
    standard = "timeline"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = (
        "The row carries neither a parent project nor an entity id, so neither "
        "the project feed nor a record history can ever select it."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for entry in _entries(context):
            if entry.parent_entity_id or entry.entity_id:
                continue
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=(
                        f"{_label(entry)} is recorded with no project and no entity, "
                        "so it can never appear on a timeline."
                    ),
                    element_ref=str(entry.id),
                    suggestion=(
                        "Have the publisher send a project id with the event, or stop "
                        "recording the event until it can be placed on a project."
                    ),
                    details={
                        "action": entry.action,
                        "entity_type": entry.entity_type,
                        "module": entry.module,
                    },
                )
            )
        return results or [_ok(self, "Every entry can be reached by a timeline query.")]


class EntryWithoutEntityRule(ValidationRule):
    """A row that reaches a feed but names no record."""

    rule_id = "timeline.entry_without_entity"
    name = "Timeline entry names no record"
    standard = "timeline"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = (
        "The row rolls up to a project but carries no entity id, so a reader cannot open the record it describes."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for entry in _entries(context):
            if entry.entity_id or not entry.parent_entity_id:
                # No parent either: that is the unroutable rule's finding, and
                # reporting it twice would double-count one broken row.
                continue
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=(f"{_label(entry)} appears on the project feed but names no record."),
                    element_ref=str(entry.id),
                    suggestion=(
                        "Have the publisher include the affected record's id under a "
                        "'<record>_id' key so the entry can link back to it."
                    ),
                    details={
                        "action": entry.action,
                        "entity_type": entry.entity_type,
                        "project_id": entry.parent_entity_id,
                    },
                )
            )
        return results or [_ok(self, "Every entry names the record it is about.")]


class UnattributedEntryRule(ValidationRule):
    """The event named an actor and the row lost them."""

    rule_id = "timeline.unattributed_entry"
    name = "Timeline entry lost its actor"
    standard = "timeline"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = (
        "The recorded payload names an acting user but the row has no actor, so "
        "the timeline cannot say who did this even though the event said."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for entry in _entries(context):
            if entry.actor_id is not None:
                continue
            metadata = entry.metadata_ or {}
            named = sorted(
                key for key in metadata if key in ACTOR_ID_KEYS and key not in _BRIDGE_KEYS and metadata.get(key)
            )
            if not named:
                # A system event with no actor is normal, not a finding.
                continue
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=(f"{_label(entry)} names an actor under {', '.join(named)} but the entry records none."),
                    element_ref=str(entry.id),
                    suggestion=(
                        "Publish the acting user's id as a UUID; a name or an email "
                        "cannot be stored in the actor column and is dropped."
                    ),
                    details={
                        "action": entry.action,
                        "actor_keys_present": named,
                        "values": [str(metadata.get(k)) for k in named],
                    },
                )
            )
        return results or [_ok(self, "No entry lost an actor the event had named.")]


TIMELINE_RULES: tuple[type[ValidationRule], ...] = (
    UnroutableEntryRule,
    EntryWithoutEntityRule,
    UnattributedEntryRule,
)


def register_timeline_rules() -> None:
    """Register every timeline rule under the ``timeline`` rule set.

    Idempotent: the registry keys on ``rule_id``, so calling this twice (module
    startup plus a test fixture) leaves one copy of each rule.
    """
    for rule_cls in TIMELINE_RULES:
        rule_registry.register(rule_cls(), [TIMELINE_RULE_SET])
    logger.debug("Registered %d timeline validation rules", len(TIMELINE_RULES))


__all__ = [
    "TIMELINE_RULES",
    "TIMELINE_RULE_SET",
    "EntryWithoutEntityRule",
    "UnattributedEntryRule",
    "UnroutableEntryRule",
    "register_timeline_rules",
]

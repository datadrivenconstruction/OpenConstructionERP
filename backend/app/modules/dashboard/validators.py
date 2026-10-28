# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Validation rules for inbox actions.

The inbox is the one screen where a person clears work off their plate, so the
write path it just gained is the write path most worth guarding. Three rules in
the ``inbox_action`` rule set:

* ``inbox_action.item_id_recognised`` - ERROR. The id must name a source this
  module produces and carry a UUID. The id is not a foreign key - the row it
  refers to lives in whichever module produced it - so nothing else in the
  stack would catch a typo, and the state row would simply sit there being read
  by nobody.
* ``inbox_action.state_known``        - ERROR. The state must be
  ``acknowledged`` or ``dismissed``. A third value would be stored happily and
  then ignored by the filter, which reads as "the dismiss button did nothing".
* ``inbox_action.dismissal_decides_nothing`` - INFO, and the reason this rule
  set exists rather than a pair of ``if`` statements. Dismissing an approval
  takes it off one person's triage list; the step stays ``pending`` and stays
  visible in the module that owns it. The finding is persisted on the state row
  so an audit of who cleared what can tell a hidden approval from a decided
  one, which is exactly the distinction a dispute turns on.

Every rule reads the plain dict the service hands it, so none of them needs a
database session and all of them are unit-testable in isolation.
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
from app.modules.dashboard.inbox_logic import (
    INBOX_SOURCES,
    INBOX_STATES,
    STATE_DISMISSED,
    parse_item_id,
    source_is_approval,
)

logger = logging.getLogger(__name__)

#: The rule set every inbox-action rule registers under, and the one the
#: service passes to ``validation_engine.validate``.
INBOX_ACTION_RULE_SET = "inbox_action"


def _action(context: ValidationContext) -> dict[str, Any]:
    """The action payload carried on the context (or an empty dict)."""
    return context.data if isinstance(context.data, dict) else {}


def _item_id(context: ValidationContext) -> str:
    return str(_action(context).get("item_id") or "")


def _state(context: ValidationContext) -> str:
    return str(_action(context).get("state") or "")


def _result(
    rule: ValidationRule,
    passed: bool,
    message: str,
    *,
    element_ref: str | None = None,
    suggestion: str | None = None,
    details: dict[str, Any] | None = None,
) -> RuleResult:
    """Build a RuleResult carrying the rule's own id / name / severity / category."""
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=element_ref,
        suggestion=suggestion,
        details=details or {},
    )


class InboxActionItemIdRecognised(ValidationRule):
    """An action must name an item id this module could have produced."""

    rule_id = "inbox_action.item_id_recognised"
    name = "Inbox Item Id Is Addressable"
    standard = "inbox_action"
    severity = Severity.ERROR
    category = RuleCategory.STRUCTURE
    description = (
        "An inbox item id is '<source>:<uuid>'. The id is not a foreign key, so a "
        "malformed one records a state nothing will ever read."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        item_id = _item_id(context)
        parsed = parse_item_id(item_id)
        if parsed is not None:
            return [_result(self, True, "OK", element_ref=item_id)]
        return [
            _result(
                self,
                False,
                f"Inbox item id '{item_id}' does not name a known source and row.",
                element_ref=item_id,
                suggestion=f"Use '<source>:<uuid>' with source one of: {', '.join(INBOX_SOURCES)}.",
                details={"item_id": item_id, "sources": list(INBOX_SOURCES)},
            )
        ]


class InboxActionStateKnown(ValidationRule):
    """An action must record one of the two states the reader understands."""

    rule_id = "inbox_action.state_known"
    name = "Inbox Action State Is Understood"
    standard = "inbox_action"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = (
        "Only acknowledged and dismissed change what the inbox returns. Any other "
        "value stores cleanly and is then ignored, which reads as a dead button."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        state = _state(context)
        if state in INBOX_STATES:
            return [_result(self, True, "OK", element_ref=state)]
        return [
            _result(
                self,
                False,
                f"Inbox action state '{state}' is not one the inbox reads.",
                element_ref=state,
                suggestion=f"Use one of: {', '.join(INBOX_STATES)}.",
                details={"state": state, "known": list(INBOX_STATES)},
            )
        ]


class InboxActionDismissalDecidesNothing(ValidationRule):
    """Dismissing an approval is triage, not a decision, and says so."""

    rule_id = "inbox_action.dismissal_decides_nothing"
    name = "Dismissing An Approval Leaves It Pending"
    standard = "inbox_action"
    severity = Severity.INFO
    category = RuleCategory.COMPLETENESS
    description = (
        "Taking an approval off your inbox does not approve or reject it. The step "
        "stays pending and stays visible in the module that owns it."
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _state(context) != STATE_DISMISSED:
            return []
        parsed = parse_item_id(_item_id(context))
        if parsed is None or not source_is_approval(parsed[0]):
            # An alert dismissal is the whole truth: the same action marks the
            # notification read, so there is nothing left pending to warn about.
            return []
        source, source_id = parsed
        return [
            _result(
                self,
                False,
                "This approval was removed from the inbox but is still pending a decision.",
                element_ref=_item_id(context),
                suggestion="Approve or reject it in the module that owns it to close it out.",
                details={"source": source, "source_id": source_id},
            )
        ]


_INBOX_ACTION_RULES: tuple[ValidationRule, ...] = (
    InboxActionItemIdRecognised(),
    InboxActionStateKnown(),
    InboxActionDismissalDecidesNothing(),
)


def register_inbox_action_rules() -> None:
    """Register the inbox-action rules with the core rule registry.

    Idempotent - the registry overwrites a rule by id, so a re-import or hot
    reload re-registers cleanly. Called from the module ``on_startup`` hook,
    which is what makes ``inbox_action`` a reachable rule set rather than a
    name nothing answers to.
    """
    for rule in _INBOX_ACTION_RULES:
        rule_registry.register(rule, [INBOX_ACTION_RULE_SET])
    logger.debug("Registered %d inbox_action validation rules", len(_INBOX_ACTION_RULES))


__all__ = [
    "INBOX_ACTION_RULE_SET",
    "InboxActionDismissalDecidesNothing",
    "InboxActionItemIdRecognised",
    "InboxActionStateKnown",
    "register_inbox_action_rules",
]

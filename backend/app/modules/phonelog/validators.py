# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Phone-log validation rules (rule set ``phonelog``).

Rules run over a plain dict built by the service, one call under the key ``call``::

    {"call": {"id", "status", "occurred_at", "ended_at", "parties", "transcript", "summary", "instructions"}}

A draft built from a recording passes with its transcript still to be reviewed; only a record that
is being logged has to carry content.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, blank, section
from app.core.validation.quality_rules import latest_local_day, parse_day

PHONELOG_RULE_SET = "phonelog"

CALL_FIELDS = ("status", "occurred_at", "ended_at", "parties", "transcript", "summary", "instructions")


class _PhonelogRule(MoneyRule):
    standard = PHONELOG_RULE_SET
    message_section = "phonelog"


class CallNotInFutureRule(_PhonelogRule):
    """A call cannot have taken place on a day that has not come."""

    rule_id = "phonelog.call_not_in_future"
    name = "Call is not dated in the future"
    description = "occurred_at must be no later than today"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        call = section(context, "call")
        ref = str(call.get("id", ""))
        day = parse_day(call.get("occurred_at"))
        if day is not None and day > latest_local_day(context):
            return [self.fail(context, "call_in_future", ref=ref, occurred=day.isoformat())]
        return [self.ok(ref)]


class CallTimesOrderedRule(_PhonelogRule):
    """A call does not end before it starts."""

    rule_id = "phonelog.call_times_ordered"
    name = "Call ends after it starts"
    description = "ended_at must not be before occurred_at"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        call = section(context, "call")
        ref = str(call.get("id", ""))
        started, ended = _moment(call.get("occurred_at")), _moment(call.get("ended_at"))
        if started is not None and ended is not None and _before(ended, started, call):
            return [
                self.fail(
                    context, "call_ends_before_start", ref=ref, started=started.isoformat(), ended=ended.isoformat()
                )
            ]
        return [self.ok(ref)]


class LoggedCallHasContentRule(_PhonelogRule):
    """A call that is logged as a record says what was said."""

    rule_id = "phonelog.logged_has_content"
    name = "Logged call carries a transcript or summary"
    description = "a call with status logged needs a transcript or a summary"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        call = section(context, "call")
        ref = str(call.get("id", ""))
        if call.get("status") == "logged" and blank(call.get("transcript")) and blank(call.get("summary")):
            return [self.fail(context, "logged_without_content", ref=ref)]
        return [self.ok(ref)]


class InstructionNamesPartyRule(_PhonelogRule):
    """An instruction given by phone is only worth something when you can say who gave it."""

    rule_id = "phonelog.instruction_names_party"
    name = "Recorded instructions name the people on the call"
    severity = Severity.WARNING
    description = "a call with instructions should list its parties"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        call = section(context, "call")
        ref = str(call.get("id", ""))
        parties = [p for p in (call.get("parties") or []) if not blank(p)]
        if call.get("instructions") and not parties:
            return [self.fail(context, "instruction_without_party", ref=ref)]
        return [self.ok(ref)]


def _before(ended: datetime, started: datetime, call: dict) -> bool:
    """Whether the call ends before it starts; a bare date on either side is compared by day only."""
    if any(len(str(call.get(name) or "").strip()) <= 10 for name in ("occurred_at", "ended_at")):
        return ended.date() < started.date()
    return ended < started


def _moment(value: object) -> datetime | None:
    """A timestamp as an aware datetime (naive means UTC), or ``None`` when absent or not a date."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


PHONELOG_RULES = (
    CallNotInFutureRule,
    CallTimesOrderedRule,
    LoggedCallHasContentRule,
    InstructionNamesPartyRule,
)


def register_phonelog_validation_rules() -> None:
    """Register the phone-log rules with the platform rule registry."""
    for rule_class in PHONELOG_RULES:
        rule_registry.register(rule_class(), [PHONELOG_RULE_SET])


__all__ = ["CALL_FIELDS", "PHONELOG_RULES", "PHONELOG_RULE_SET", "register_phonelog_validation_rules"]

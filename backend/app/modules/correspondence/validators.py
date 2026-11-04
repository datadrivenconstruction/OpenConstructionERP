# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Correspondence validation rules (rule set ``correspondence``).

Rules run over a plain dict built by the service::

    {"correspondence": {"id", "direction", "correspondence_type", "date_sent",
                        "date_received", "response_required_by", "contract_clause_ref"}}

Every rule needs the fields it compares, so a record with a date still to be
filled in passes until it has both.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, blank, section

CORRESPONDENCE_RULE_SET = "correspondence"

#: Types that formally notify the other party and so must cite the clause relied on.
NOTICE_TYPE = "notice"


def _day(value: Any) -> date | None:
    """A calendar day from an ISO string or date; ``None`` when absent or malformed."""
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value.strip()) >= 10:
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


class _CorrespondenceRule(MoneyRule):
    standard = CORRESPONDENCE_RULE_SET
    message_section = "correspondence"
    suggestion_key = "correspondence.suggestion"


class ReceivedNotBeforeSentRule(_CorrespondenceRule):
    """A letter is not received before it was sent."""

    rule_id = "correspondence.received_not_before_sent"
    name = "Correspondence received on or after the day it was sent"
    description = "date_received must not be earlier than date_sent"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        rec = section(context, "correspondence")
        ref = str(rec.get("id", ""))
        sent, received = _day(rec.get("date_sent")), _day(rec.get("date_received"))
        if sent and received and received < sent:
            return [self.fail(context, "received_not_before_sent", ref=ref, sent=sent, received=received)]
        return [self.ok(ref)]


class ResponseDeadlineAfterNoticeRule(_CorrespondenceRule):
    """The reply deadline falls on or after the day the letter reached us or left us."""

    rule_id = "correspondence.response_deadline_after_notice"
    name = "Response deadline not before the notice date"
    description = "response_required_by must not precede the date received (incoming) or sent (outgoing)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        rec = section(context, "correspondence")
        ref = str(rec.get("id", ""))
        sent, received = _day(rec.get("date_sent")), _day(rec.get("date_received"))
        due = _day(rec.get("response_required_by"))
        start = (received or sent) if rec.get("direction") == "incoming" else (sent or received)
        if due and start and due < start:
            return [self.fail(context, "response_deadline_after_notice", ref=ref, due=due, start=start)]
        return [self.ok(ref)]


class NoticeCitesClauseRule(_CorrespondenceRule):
    """A formal notice names the contract clause it is given under."""

    rule_id = "correspondence.notice_cites_clause"
    name = "Notice cites the contract clause"
    severity = Severity.WARNING
    description = "A notice without a contract clause reference may not count as notice under the contract"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        rec = section(context, "correspondence")
        ref = str(rec.get("id", ""))
        if rec.get("correspondence_type") == NOTICE_TYPE and blank(rec.get("contract_clause_ref")):
            return [self.fail(context, "notice_cites_clause", ref=ref)]
        return [self.ok(ref)]


CORRESPONDENCE_RULES = (
    ReceivedNotBeforeSentRule,
    ResponseDeadlineAfterNoticeRule,
    NoticeCitesClauseRule,
)


def register_correspondence_validation_rules() -> None:
    """Register the correspondence rules with the platform rule registry."""
    for rule_class in CORRESPONDENCE_RULES:
        rule_registry.register(rule_class(), [CORRESPONDENCE_RULE_SET])


FIELDS = (
    "direction",
    "correspondence_type",
    "date_sent",
    "date_received",
    "response_required_by",
    "contract_clause_ref",
)


def snapshot(record: Any, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """The rule input for a record (ORM row or schema object), with pending field changes applied."""
    body = {f: getattr(record, f, None) for f in FIELDS}
    body["id"] = str(getattr(record, "id", "") or "")
    body.update({k: v for k, v in (overrides or {}).items() if k in FIELDS})
    return {"correspondence": body}


__all__ = [
    "CORRESPONDENCE_RULES",
    "CORRESPONDENCE_RULE_SET",
    "register_correspondence_validation_rules",
    "snapshot",
]

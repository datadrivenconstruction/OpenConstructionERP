# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Clash coordination validation rules (rule set ``clash``).

Rules run over a plain dict built by the service, one record under one key::

    {"clash": {"id", "status", "severity", "assigned_to", "due_date"}}
    {"run":   {"id", "clash_type", "clearance_m"}}

Clashes found by a run and clashes synchronised from a BCF topic are system-created: their findings
are reported and never refused. ``metadata['today']`` pins the reference day in tests.
"""

from __future__ import annotations

import re

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import blank, section, to_dec
from app.core.validation.quality_rules import QualityRule, parse_day, today_of

CLASH_RULE_SET = "clash"

CLASH_FIELDS = ("status", "severity", "assigned_to", "due_date")
RUN_FIELDS = ("clash_type", "clearance_m")

_OPEN = frozenset({"new", "active", "reviewed"})
_WORKED = frozenset({"active", "reviewed"})
_SEVERE = frozenset({"critical", "high"})
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ].*)?$")


class _ClashRule(QualityRule):
    standard = CLASH_RULE_SET
    message_section = "clash"


class DueDateFormatRule(_ClashRule):
    """A clash due date is a real calendar day, so the coordination register can sort and chase it."""

    rule_id = "clash.due_date_format"
    name = "Clash due date is a calendar day"
    description = "due_date, when given, must be an ISO date such as 2026-11-30"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        c = section(context, "clash")
        ref = str(c.get("id", ""))
        raw = c.get("due_date")
        if not blank(raw):
            text = str(raw).strip()
            if not _ISO_DAY.match(text) or parse_day(text) is None:
                return [self.fail(context, "due_date_invalid", ref=ref, value=text)]
        return [self.ok(ref)]


class DueDatePastRule(_ClashRule):
    """An open clash is not left with a deadline that has already gone by."""

    rule_id = "clash.due_date_past"
    name = "Open clash is not overdue"
    severity = Severity.WARNING
    description = "an open clash should not have a due_date before today"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        c = section(context, "clash")
        ref = str(c.get("id", ""))
        due = parse_day(c.get("due_date")) if _ISO_DAY.match(str(c.get("due_date") or "")) else None
        if due is not None and c.get("status") in _OPEN and due < today_of(context):
            return [self.fail(context, "due_date_past", ref=ref, due=due)]
        return [self.ok(ref)]


class SevereClashOwnerRule(_ClashRule):
    """A critical or high clash being worked has someone named to resolve it."""

    rule_id = "clash.severe_has_assignee"
    name = "Severe clash in work has an assignee"
    severity = Severity.WARNING
    description = "a critical or high clash that is active or reviewed should have assigned_to"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        c = section(context, "clash")
        ref = str(c.get("id", ""))
        if c.get("severity") in _SEVERE and c.get("status") in _WORKED and blank(c.get("assigned_to")):
            return [self.fail(context, "severe_unassigned", ref=ref, level=c.get("severity"))]
        return [self.ok(ref)]


class ClearanceDistanceRule(_ClashRule):
    """A clearance run needs a clearance distance, or it reports nothing at all."""

    rule_id = "clash.clearance_distance"
    name = "Clearance run has a distance"
    description = "clash_type clearance requires clearance_m above zero"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        r = section(context, "run")
        ref = str(r.get("id", ""))
        if r.get("clash_type") == "clearance":
            distance = to_dec(r.get("clearance_m"))
            if distance is None or distance <= 0:
                return [self.fail(context, "clearance_distance_missing", ref=ref)]
        return [self.ok(ref)]


CLASH_RULES = (DueDateFormatRule, DueDatePastRule, SevereClashOwnerRule, ClearanceDistanceRule)


def register_clash_validation_rules() -> None:
    """Register the clash coordination rules with the platform rule registry."""
    for rule_class in CLASH_RULES:
        rule_registry.register(rule_class(), [CLASH_RULE_SET])


__all__ = ["CLASH_FIELDS", "CLASH_RULES", "CLASH_RULE_SET", "RUN_FIELDS", "register_clash_validation_rules"]

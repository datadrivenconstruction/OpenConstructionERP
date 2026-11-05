# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site supervision validation rules (rule set ``site_supervision``).

Rules run over a plain dict built by the service. A visit is checked as::

    {"visit": {"id", "status", "planned_date", "actual_date", "summary"}}

and a log entry as::

    {"entry": {"id", "category", "status", "observation", "structured_fields"}}

Each rule looks only at the stage it guards, so a visit that is still planned or an entry that is
still open passes with the outcome not yet filled in. (``validators.py`` holds the pure plan-versus-fact
domain logic; the registered rules live here.)
"""

from __future__ import annotations

from app.core.validation.engine import RuleResult, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, blank, section
from app.core.validation.quality_rules import parse_day, today_of

SITE_SUPERVISION_RULE_SET = "site_supervision"

VISIT_FIELDS = ("status", "planned_date", "actual_date", "summary")
ENTRY_FIELDS = ("category", "status", "observation", "structured_fields")

_HELD_VISIT = frozenset({"conducted", "reported"})
#: Categories whose entry is meaningless without the observation behind it.
_NEEDS_OBSERVATION = frozenset({"deviation", "instruction", "hidden_works", "motivated_refusal"})
_ACCEPTED_ENTRY = frozenset({"addressed", "closed"})
_HIDDEN_WORKS_IDENTITY = ("element", "location")


class _SupervisionRule(MoneyRule):
    standard = SITE_SUPERVISION_RULE_SET
    message_section = "site_supervision"


class ConductedVisitDatedRule(_SupervisionRule):
    """A visit that took place says when."""

    rule_id = "site_supervision.visit_dated"
    name = "Conducted visit has an actual date"
    description = "a conducted or reported visit needs its actual_date"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        visit = section(context, "visit")
        ref = str(visit.get("id", ""))
        if visit.get("status") in _HELD_VISIT and blank(visit.get("actual_date")):
            return [self.fail(context, "visit_undated", ref=ref, status=visit.get("status"))]
        return [self.ok(ref)]


class VisitNotInFutureRule(_SupervisionRule):
    """A visit cannot already have happened on a day still to come."""

    rule_id = "site_supervision.visit_not_in_future"
    name = "Conducted visit is not dated in the future"
    description = "a conducted or reported visit must have an actual_date no later than today"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        visit = section(context, "visit")
        ref = str(visit.get("id", ""))
        day = parse_day(visit.get("actual_date"))
        if visit.get("status") in _HELD_VISIT and day is not None and day > today_of(context):
            return [self.fail(context, "visit_in_future", ref=ref, status=visit.get("status"), date=day.isoformat())]
        return [self.ok(ref)]


class EntryObservationRule(_SupervisionRule):
    """A deviation, instruction, hidden-works item or refusal records what was observed."""

    rule_id = "site_supervision.entry_observation"
    name = "Supervision entry states its observation"
    description = "deviation, instruction, hidden_works and motivated_refusal entries need observation text"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        entry = section(context, "entry")
        ref = str(entry.get("id", ""))
        if entry.get("category") in _NEEDS_OBSERVATION and blank(entry.get("observation")):
            return [self.fail(context, "observation_missing", ref=ref, category=entry.get("category"))]
        return [self.ok(ref)]


class HiddenWorksIdentifiedRule(_SupervisionRule):
    """Hidden works are only accepted once the element and its location are on record."""

    rule_id = "site_supervision.hidden_works_identified"
    name = "Accepted hidden works name the element and location"
    description = "an addressed or closed hidden_works entry needs structured_fields element and location"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        entry = section(context, "entry")
        ref = str(entry.get("id", ""))
        if entry.get("category") != "hidden_works" or entry.get("status") not in _ACCEPTED_ENTRY:
            return [self.ok(ref)]
        fields = entry.get("structured_fields")
        fields = fields if isinstance(fields, dict) else {}
        missing = [k for k in _HIDDEN_WORKS_IDENTITY if blank(fields.get(k))]
        if missing:
            return [self.fail(context, "hidden_works_unidentified", ref=ref, missing=", ".join(missing))]
        return [self.ok(ref)]


SITE_SUPERVISION_RULES = (
    ConductedVisitDatedRule,
    VisitNotInFutureRule,
    EntryObservationRule,
    HiddenWorksIdentifiedRule,
)


def register_site_supervision_validation_rules() -> None:
    """Register the site supervision rules with the platform rule registry."""
    for rule_class in SITE_SUPERVISION_RULES:
        rule_registry.register(rule_class(), [SITE_SUPERVISION_RULE_SET])


__all__ = ["SITE_SUPERVISION_RULES", "SITE_SUPERVISION_RULE_SET", "register_site_supervision_validation_rules"]

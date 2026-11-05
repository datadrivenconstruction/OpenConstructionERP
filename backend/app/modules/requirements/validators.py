# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Requirements validation rules (rule set ``requirements``).

Rules run over a plain dict built by the service. A requirement is checked as::

    {"requirement": {"id", "entity", "attribute", "constraint_type", "constraint_value", "unit",
                     "priority", "verification_method"}}

and a requirement set as::

    {"set": {"id", "status", "requirement_count"}}

These are the questions an estimator or BIM manager asks of a requirement before relying on it: can the
check actually be run, is the number tied to a unit, and does anyone know how it will be proven.
"""

from __future__ import annotations

import re

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, blank, section, to_dec
from app.modules.requirements.evaluator import NUMERIC_OPERATORS, VALUE_OPTIONAL, _parse_range

REQUIREMENTS_RULE_SET = "requirements"

REQUIREMENT_FIELDS = (
    "entity",
    "attribute",
    "constraint_type",
    "constraint_value",
    "unit",
    "priority",
    "verification_method",
)
SET_FIELDS = ("status", "requirement_count")


def _name(req: dict) -> str:
    return f"{req.get('entity') or '?'}.{req.get('attribute') or '?'}"


class _RequirementsRule(MoneyRule):
    standard = REQUIREMENTS_RULE_SET
    message_section = "requirements"


class ConstraintValueUsableRule(_RequirementsRule):
    """The constraint can be evaluated: it has a value of the kind its operator reads."""

    rule_id = "requirements.constraint_value_usable"
    name = "Requirement constraint value is usable"
    description = "min/max need a number, range needs low..high, regex must compile, other operators need a value"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        req = section(context, "requirement")
        ref = str(req.get("id", ""))
        kind = str(req.get("constraint_type") or "equals").strip().lower()
        if kind in VALUE_OPTIONAL:
            return [self.ok(ref)]
        value = str(req.get("constraint_value") or "").strip()
        if not value:
            return [self.fail(context, "value_missing", ref=ref, type=kind, name=_name(req))]
        bad = False
        if kind in NUMERIC_OPERATORS and kind != "range":
            bad = to_dec(value.replace(",", ".")) is None
        elif kind == "range":
            bad = _parse_range(value) is None
        elif kind == "regex":
            try:
                re.compile(value)
            except re.error:
                bad = True
        if bad:
            return [self.fail(context, "value_invalid", ref=ref, type=kind, name=_name(req), value=value)]
        return [self.ok(ref)]


class NumericUnitRule(_RequirementsRule):
    """A numeric limit says what it is measured in."""

    rule_id = "requirements.numeric_unit"
    name = "Numeric requirement states a unit"
    severity = Severity.WARNING
    description = "min, max and range constraints should carry a unit"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        req = section(context, "requirement")
        ref = str(req.get("id", ""))
        kind = str(req.get("constraint_type") or "").strip().lower()
        if kind in NUMERIC_OPERATORS and not blank(req.get("constraint_value")) and blank(req.get("unit")):
            return [self.fail(context, "unit_missing", ref=ref, type=kind, name=_name(req))]
        return [self.ok(ref)]


class MustHaveVerificationRule(_RequirementsRule):
    """A mandatory requirement says how compliance will be proven."""

    rule_id = "requirements.must_have_verification"
    name = "Mandatory requirement has a verification method"
    severity = Severity.WARNING
    description = "a must requirement should name its verification_method"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        req = section(context, "requirement")
        ref = str(req.get("id", ""))
        if req.get("priority") == "must" and blank(req.get("verification_method")):
            return [self.fail(context, "verification_missing", ref=ref, name=_name(req))]
        return [self.ok(ref)]


class LockedSetNotEmptyRule(_RequirementsRule):
    """A set is locked as the baseline only when it holds requirements."""

    rule_id = "requirements.locked_set_not_empty"
    name = "Locked requirement set is not empty"
    description = "a set with status locked must contain at least one requirement"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        req_set = section(context, "set")
        ref = str(req_set.get("id", ""))
        count = req_set.get("requirement_count")
        if req_set.get("status") == "locked" and isinstance(count, int) and count == 0:
            return [self.fail(context, "locked_set_empty", ref=ref)]
        return [self.ok(ref)]


REQUIREMENTS_RULES = (
    ConstraintValueUsableRule,
    NumericUnitRule,
    MustHaveVerificationRule,
    LockedSetNotEmptyRule,
)


def register_requirements_validation_rules() -> None:
    """Register the requirements rules with the platform rule registry."""
    for rule_class in REQUIREMENTS_RULES:
        rule_registry.register(rule_class(), [REQUIREMENTS_RULE_SET])


__all__ = ["REQUIREMENTS_RULES", "REQUIREMENTS_RULE_SET", "register_requirements_validation_rules"]

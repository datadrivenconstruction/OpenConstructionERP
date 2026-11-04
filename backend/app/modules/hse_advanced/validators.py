# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""HSE validation rules (rule set ``hse_advanced``).

Each rule reads one record under its own key, built by the service from the stored
record merged with the incoming change::

    {"certification": {"id", "issue_date", "valid_until"}}
    {"ppe": {"id", "issued_at", "returned_at", "valid_until"}}
    {"permit": {"id", "permit_type", "work_start", "work_end"}}
    {"talk": {"id", "conducted_at"}}
    {"capa": {"id", "target_date"}}

A rule whose record is absent, or whose fields are not stated yet, passes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import section
from app.core.validation.site_rules import SiteRule, parse_instant

HSE_RULE_SET = "hse_advanced"

#: A permit for these hazards covers one shift; anything longer is re-issued after a fresh gas test or fire watch.
_SHIFT_PERMIT_TYPES = frozenset({"hot_work", "confined_space"})
_SHIFT_PERMIT_HOURS = Decimal("24")
#: No permit to work outlives a month without being re-issued.
_MAX_PERMIT_HOURS = Decimal("720")


class CertificationDatesRule(SiteRule):
    """A certificate expires after it was issued."""

    rule_id = "hse_advanced.certification_dates"
    name = "Certification validity follows its issue date"
    standard = HSE_RULE_SET
    description = "valid_until must not be earlier than issue_date"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        c = section(context, "certification")
        ref = str(c.get("id", ""))
        issued, until = parse_instant(c.get("issue_date")), parse_instant(c.get("valid_until"))
        if issued is not None and until is not None and until < issued:
            return [
                self.fail(context, "dates_ordered", ref=ref, earlier=c.get("issue_date"), later=c.get("valid_until"))
            ]
        return [self.ok(ref)]


class PPEDatesRule(SiteRule):
    """Protective equipment is returned after it was issued and is valid on the day it was issued."""

    rule_id = "hse_advanced.ppe_dates"
    name = "PPE issue, return and validity dates are in order"
    standard = HSE_RULE_SET
    description = "returned_at must not precede issued_at; valid_until must not precede the issue day"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        p = section(context, "ppe")
        ref = str(p.get("id", ""))
        issued = parse_instant(p.get("issued_at"))
        returned, until = parse_instant(p.get("returned_at")), parse_instant(p.get("valid_until"))
        if issued is not None and returned is not None and returned < issued:
            return [
                self.fail(context, "dates_ordered", ref=ref, earlier=p.get("issued_at"), later=p.get("returned_at"))
            ]
        if issued is not None and until is not None and until.date() < issued.date():
            return [
                self.fail(context, "dates_ordered", ref=ref, earlier=p.get("issued_at"), later=p.get("valid_until"))
            ]
        return [self.ok(ref)]


class PermitWindowRule(SiteRule):
    """A permit to work covers a shift for hot work and confined space, and never a month."""

    rule_id = "hse_advanced.permit_window"
    name = "Permit window is no longer than the hazard allows"
    standard = HSE_RULE_SET
    severity = Severity.WARNING
    description = "hot_work and confined_space permits over 24 hours, any permit over 30 days"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        p = section(context, "permit")
        ref = str(p.get("id", ""))
        start, end = parse_instant(p.get("work_start")), parse_instant(p.get("work_end"))
        if start is None or end is None or end <= start:
            return [self.ok(ref)]
        hours = Decimal(str((end - start).total_seconds())) / Decimal("3600")
        limit = _SHIFT_PERMIT_HOURS if p.get("permit_type") in _SHIFT_PERMIT_TYPES else _MAX_PERMIT_HOURS
        if hours > limit:
            return [
                self.site_fail(
                    context,
                    "limit_exceeded",
                    ref=ref,
                    field="work_window_hours",
                    value=hours.quantize(Decimal("0.1")),
                    limit_field="permit_type " + str(p.get("permit_type") or ""),
                    limit=limit,
                )
            ]
        return [self.ok(ref)]


class ToolboxNotFutureRule(SiteRule):
    """A toolbox talk that is recorded has been held."""

    rule_id = "hse_advanced.toolbox_not_future"
    name = "Toolbox talk was not held in the future"
    standard = HSE_RULE_SET
    description = "conducted_at must not be later than now (one day of slack)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        t = section(context, "talk")
        ref = str(t.get("id", ""))
        bad = self.future_date(context, ref, "conducted_at", t.get("conducted_at"))
        return [bad] if bad else [self.ok(ref)]


class CapaTargetDateRule(SiteRule):
    """A new corrective action is due today or later."""

    rule_id = "hse_advanced.capa_target_date"
    name = "New corrective action is not already overdue"
    standard = HSE_RULE_SET
    severity = Severity.WARNING
    description = "target_date earlier than today on a newly raised corrective action"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        c = section(context, "capa")
        ref = str(c.get("id", ""))
        due = parse_instant(c.get("target_date"))
        today = datetime.now(UTC).date()
        if due is not None and due.date() < today:
            return [self.fail(context, "dates_ordered", ref=ref, earlier=today.isoformat(), later=c.get("target_date"))]
        return [self.ok(ref)]


HSE_RULES = (
    CertificationDatesRule,
    PPEDatesRule,
    PermitWindowRule,
    ToolboxNotFutureRule,
    CapaTargetDateRule,
)


def register_hse_validation_rules() -> None:
    """Register the HSE rules with the platform rule registry."""
    for rule_class in HSE_RULES:
        rule_registry.register(rule_class(), [HSE_RULE_SET])


__all__ = ["HSE_RULES", "HSE_RULE_SET", "register_hse_validation_rules"]

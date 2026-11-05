# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Construction control validation rules (rule set ``construction_control``).

Rules run over a plain dict built by the service, one record under one key::

    {"criterion":  {"id", "acceptance_rule", "nominal_value", "tolerance_lower", "tolerance_upper"}}
    {"material":   {"id", "status", "issued_at", "valid_from", "valid_until"}}
    {"test":       {"id", "status", "lab_name", "lab_accreditation", "is_accredited", "sampled_at", "tested_at"}}
    {"inspection": {"id", "performed_at"}}
    {"asbuilt":    {"id", "survey_date"}}

A rule looks only at the record kinds it guards, so a draft record passes with its evidence not yet entered.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, blank, section, to_dec
from app.core.validation.quality_rules import latest_local_day, parse_day, today_of

CONSTRUCTION_CONTROL_RULE_SET = "construction_control"

CRITERION_FIELDS = ("acceptance_rule", "nominal_value", "tolerance_lower", "tolerance_upper")
MATERIAL_FIELDS = ("status", "issued_at", "valid_from", "valid_until")
TEST_FIELDS = ("status", "lab_name", "lab_accreditation", "is_accredited", "sampled_at", "tested_at")
INSPECTION_FIELDS = ("performed_at",)
ASBUILT_FIELDS = ("survey_date",)

#: Statuses in which the material is being relied on, so its certificate has to be in date.
_RELIED_ON = frozenset({"submitted", "under_review", "accepted"})
#: Record kind -> the date fields that cannot lie in the future.
_PAST_DATES = (
    ("inspection", ("performed_at",)),
    ("test", ("sampled_at", "tested_at")),
    ("asbuilt", ("survey_date",)),
)


def _num(value: Any) -> Decimal | None:
    """A decimal from text that may use a decimal comma."""
    return to_dec(value.replace(",", ".") if isinstance(value, str) else value)


class _ControlRule(MoneyRule):
    standard = CONSTRUCTION_CONTROL_RULE_SET
    message_section = "construction_control"


class CriterionToleranceBandRule(_ControlRule):
    """A range criterion has a lower bound under its upper bound, and a nominal between them."""

    rule_id = "construction_control.criterion_tolerance_band"
    name = "Acceptance criterion tolerance band is consistent"
    description = "for a range criterion tolerance_lower <= nominal_value <= tolerance_upper"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        crit = section(context, "criterion")
        ref = str(crit.get("id", ""))
        if crit.get("acceptance_rule") != "range":
            return [self.ok(ref)]
        lower, upper, nominal = (_num(crit.get(k)) for k in ("tolerance_lower", "tolerance_upper", "nominal_value"))
        if lower is not None and upper is not None and lower > upper:
            return [self.fail(context, "band_inverted", ref=ref, lower=lower, upper=upper)]
        if nominal is not None and ((lower is not None and nominal < lower) or (upper is not None and nominal > upper)):
            return [
                self.fail(context, "nominal_outside", ref=ref, nominal=nominal, lower=lower or "-", upper=upper or "-")
            ]
        return [self.ok(ref)]


class CertificateWindowRule(_ControlRule):
    """A material certificate does not expire before it starts."""

    rule_id = "construction_control.certificate_window"
    name = "Material certificate validity window is ordered"
    description = "valid_until must not be before valid_from"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        mat = section(context, "material")
        ref = str(mat.get("id", ""))
        start, end = parse_day(mat.get("valid_from")), parse_day(mat.get("valid_until"))
        if start is not None and end is not None and end < start:
            return [self.fail(context, "certificate_window", ref=ref, start=start.isoformat(), until=end.isoformat())]
        return [self.ok(ref)]


class CertificateInDateRule(_ControlRule):
    """A material that is being relied on has a certificate that has not lapsed."""

    rule_id = "construction_control.certificate_in_date"
    name = "Material certificate is in date"
    severity = Severity.WARNING
    description = "a submitted, under review or accepted material must not carry an expired certificate"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        mat = section(context, "material")
        ref = str(mat.get("id", ""))
        end = parse_day(mat.get("valid_until"))
        if mat.get("status") in _RELIED_ON and end is not None and end < today_of(context):
            return [self.fail(context, "certificate_expired", ref=ref, date=end.isoformat(), status=mat.get("status"))]
        return [self.ok(ref)]


class EvidenceDatesRule(_ControlRule):
    """Evidence is dated on or before today, and a test is not run before its sample was taken."""

    rule_id = "construction_control.evidence_dates"
    name = "Inspection, test and survey dates are real"
    description = "performed, sampled, tested and survey dates not in the future; tested_at not before sampled_at"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        today = latest_local_day(context)
        out: list[RuleResult] = []
        for key, fields in _PAST_DATES:
            rec = section(context, key)
            for field in fields:
                day = parse_day(rec.get(field))
                if day is not None and day > today:
                    out.append(
                        self.fail(
                            context, "date_in_future", ref=str(rec.get("id", "")), field=field, date=day.isoformat()
                        )
                    )
        test = section(context, "test")
        sampled, tested = parse_day(test.get("sampled_at")), parse_day(test.get("tested_at"))
        if sampled is not None and tested is not None and tested < sampled:
            out.append(
                self.fail(
                    context,
                    "test_before_sample",
                    ref=str(test.get("id", "")),
                    tested=tested.isoformat(),
                    sampled=sampled.isoformat(),
                )
            )
        return out or [self.ok("")]


class TestLabAccreditedRule(_ControlRule):
    """A recorded test names an accredited laboratory."""

    __test__ = False  # not a pytest class despite the name

    rule_id = "construction_control.test_lab_accredited"
    name = "Recorded test comes from an accredited laboratory"
    severity = Severity.WARNING
    description = "a recorded test from a named lab needs is_accredited or an accreditation reference"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        test = section(context, "test")
        ref = str(test.get("id", ""))
        if (
            test.get("status") == "recorded"
            and not blank(test.get("lab_name"))
            and not test.get("is_accredited")
            and blank(test.get("lab_accreditation"))
        ):
            return [self.fail(context, "lab_unaccredited", ref=ref, lab=test.get("lab_name"))]
        return [self.ok(ref)]


CONSTRUCTION_CONTROL_RULES = (
    CriterionToleranceBandRule,
    CertificateWindowRule,
    CertificateInDateRule,
    EvidenceDatesRule,
    TestLabAccreditedRule,
)


def register_construction_control_validation_rules() -> None:
    """Register the construction control rules with the platform rule registry."""
    for rule_class in CONSTRUCTION_CONTROL_RULES:
        rule_registry.register(rule_class(), [CONSTRUCTION_CONTROL_RULE_SET])


__all__ = [
    "CONSTRUCTION_CONTROL_RULES",
    "CONSTRUCTION_CONTROL_RULE_SET",
    "register_construction_control_validation_rules",
]

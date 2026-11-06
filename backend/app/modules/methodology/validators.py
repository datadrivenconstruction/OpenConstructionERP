# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Estimating-methodology validation rules (rule set ``methodology``).

Rules run over a plain dict built by the service. A methodology is checked as::

    {"methodology": {"id", "vat_rate", "base_mapping", "composites", "cascade_steps": [{"key", "kind", "rate", "base"}]}}

a funding source as ``{"funding": {"id", "code", "code_taken"}}`` (``code_taken`` is true when another source
of the project already uses the code) and an analytical dimension as::

    {"dimension": {"id", "key", "values": [{"code", "parent_code"}]}}

A methodology with no markup steps yet passes: the cascade is built up step by step.
"""

from __future__ import annotations

from decimal import Decimal

from app.core.validation.engine import RuleResult, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, blank, section, to_dec

METHODOLOGY_RULE_SET = "methodology"

METHODOLOGY_FIELDS = ("vat_rate", "base_mapping", "composites", "cascade_steps")
FUNDING_FIELDS = ("code", "code_taken")
DIMENSION_FIELDS = ("key", "values")

#: A markup above this is a typo for a percentage, not an overhead (a 300% labour burden is already extreme).
MAX_MARKUP_PERCENT = Decimal(300)
_HUNDRED = Decimal(100)


class _MethodologyRule(MoneyRule):
    standard = METHODOLOGY_RULE_SET
    message_section = "methodology"


def _steps(methodology: dict) -> list[dict]:
    value = methodology.get("cascade_steps")
    return [s for s in value if isinstance(s, dict)] if isinstance(value, list) else []


class CascadeRateRule(_MethodologyRule):
    """A markup step charges a rate that makes sense as a percentage."""

    rule_id = "methodology.cascade_rate"
    name = "Markup step rate is within range"
    description = "a percentage step is -100 to 300%, a gross-up step 0 to under 100%"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        methodology = section(context, "methodology")
        ref = str(methodology.get("id", ""))
        found: list[RuleResult] = []
        for step in _steps(methodology):
            kind = step.get("kind") or "percentage"
            rate = to_dec(step.get("rate"))
            if rate is None or kind not in ("percentage", "gross_up"):
                continue
            # A tender discount is a negative percentage step, so a percentage may go below zero.
            low = -_HUNDRED if kind == "percentage" else Decimal(0)
            high = MAX_MARKUP_PERCENT if kind == "percentage" else _HUNDRED
            below_ceiling = rate < high if kind == "gross_up" else rate <= high
            if rate < low or not below_ceiling:
                found.append(
                    self.fail(
                        context,
                        "cascade_rate_out_of_range",
                        ref=ref,
                        step=step.get("key", ""),
                        rate=rate,
                        low=low,
                        high=high,
                    )
                )
        return found or [self.ok(ref)]


class CascadeBaseRule(_MethodologyRule):
    """A markup step is charged on something that exists above it."""

    rule_id = "methodology.cascade_base"
    name = "Markup step base resolves"
    description = "each base token is a cost base, a composite or an earlier step"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        methodology = section(context, "methodology")
        ref = str(methodology.get("id", ""))
        mapping, composites = methodology.get("base_mapping"), methodology.get("composites")
        # A methodology with no base mapping prices everything against the one "direct" base.
        known = set(mapping) if isinstance(mapping, dict) and mapping else {"direct"}
        known |= set(composites) if isinstance(composites, dict) else set()
        found: list[RuleResult] = []
        for step in _steps(methodology):
            for token in step.get("base") or []:
                if token not in known:
                    found.append(
                        self.fail(context, "cascade_base_unknown", ref=ref, step=step.get("key", ""), base=token)
                    )
            known.add(step.get("key"))
        return found or [self.ok(ref)]


class VatRateRule(_MethodologyRule):
    """A VAT rate is a percentage."""

    rule_id = "methodology.vat_rate"
    name = "VAT rate is a percentage"
    description = "vat_rate must lie between 0 and 100"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        methodology = section(context, "methodology")
        ref = str(methodology.get("id", ""))
        rate = to_dec(methodology.get("vat_rate"))
        if rate is not None and (rate < 0 or rate > _HUNDRED):
            return [self.fail(context, "vat_rate_out_of_range", ref=ref, rate=rate)]
        return [self.ok(ref)]


class FundingCodeRule(_MethodologyRule):
    """Two funding sources of one project do not share a code."""

    rule_id = "methodology.funding_code"
    name = "Funding source code is unique in the project"
    description = "code must not be used by another funding source of the project"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        funding = section(context, "funding")
        ref = str(funding.get("id", ""))
        if not blank(funding.get("code")) and funding.get("code_taken"):
            return [self.fail(context, "funding_code_duplicate", ref=ref, code=str(funding["code"]).strip())]
        return [self.ok(ref)]


class DimensionValuesRule(_MethodologyRule):
    """Dimension values have their own codes, and a parent is one of the values."""

    rule_id = "methodology.dimension_values"
    name = "Dimension values are coherent"
    description = "value codes are unique and every parent_code names a value of the dimension"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        dimension = section(context, "dimension")
        ref = str(dimension.get("id", ""))
        label = str(dimension.get("key", ""))
        values = [v for v in (dimension.get("values") or []) if isinstance(v, dict)]
        codes = [str(v.get("code", "")) for v in values]
        found: list[RuleResult] = []
        seen: set[str] = set()
        for code in codes:
            if code in seen and not any(f.details and f.details.get("code") == code for f in found):
                found.append(self.fail(context, "dimension_value_duplicate", ref=ref, dimension=label, code=code))
            seen.add(code)
        for value in values:
            parent = value.get("parent_code")
            if not blank(parent) and parent not in seen:
                found.append(
                    self.fail(
                        context,
                        "dimension_parent_unknown",
                        ref=ref,
                        dimension=label,
                        code=value.get("code", ""),
                        parent=parent,
                    )
                )
        return found or [self.ok(ref)]


METHODOLOGY_RULES = (CascadeRateRule, CascadeBaseRule, VatRateRule, FundingCodeRule, DimensionValuesRule)


def register_methodology_validation_rules() -> None:
    """Register the methodology rules with the platform rule registry."""
    for rule_class in METHODOLOGY_RULES:
        rule_registry.register(rule_class(), [METHODOLOGY_RULE_SET])


__all__ = [
    "DIMENSION_FIELDS",
    "FUNDING_FIELDS",
    "METHODOLOGY_FIELDS",
    "METHODOLOGY_RULES",
    "METHODOLOGY_RULE_SET",
    "register_methodology_validation_rules",
]

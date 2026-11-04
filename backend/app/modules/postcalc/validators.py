# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Post-calculation validation rules (rule set ``postcalc``).

Post-calculation is a stateless analysis, so the rules check a computed report
rather than a stored record. Context::

    {
        "project": {"project_id", "currency", "total_planned_hours",
                    "total_actual_hours", "total_planned_labour_cost",
                    "line_count"},
        "lines": [{"ref", "currency", "planned_quantity", "actual_quantity",
                   "planned_hours", "actual_hours", "planned_labour_cost",
                   "productivity_factor"}],
    }
"""

from __future__ import annotations

from decimal import Decimal

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import (
    MAX_SANE_AMOUNT,
    MONEY_TOLERANCE,
    MoneyRule,
    blank,
    currency_of,
    rows,
    section,
    to_dec,
)

POSTCALC_RULE_SET = "postcalc"

#: A crew twenty times faster or slower than the norm is a data slip, not a result.
MAX_PRODUCTIVITY_FACTOR = Decimal("20")

_ZERO = Decimal("0")


class ProjectRollupMatchesLinesRule(MoneyRule):
    """The project totals equal the sums over the lines."""

    rule_id = "postcalc.rollup_matches_lines"
    name = "Post-calculation project totals equal the sum of lines"
    standard = POSTCALC_RULE_SET
    description = "Planned hours, actual hours, planned labour cost and line count roll up from the lines"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        project = section(context, "project")
        lines = rows(context, "lines")
        ref = str(project.get("project_id", ""))
        currency = currency_of(project)
        out: list[RuleResult] = []
        for label, total_key, line_key, money in (
            ("planned hours", "total_planned_hours", "planned_hours", False),
            ("actual hours", "total_actual_hours", "actual_hours", False),
            ("planned labour cost", "total_planned_labour_cost", "planned_labour_cost", True),
        ):
            stated = to_dec(project.get(total_key))
            parts = [to_dec(line.get(line_key)) for line in lines]
            if stated is None or any(p is None for p in parts):
                continue
            # Each line is rounded on its own, the total once: allow half a unit of drift per line.
            slack = MONEY_TOLERANCE + Decimal("0.005") * len(parts)
            bad = self.total_mismatch(
                context, ref, label, stated, sum(parts, _ZERO), currency if money else "", tolerance=slack
            )
            if bad:
                out.append(bad)
        count = to_dec(project.get("line_count"))
        if count is not None:
            bad = self.total_mismatch(context, ref, "line count", count, Decimal(len(lines)), "")
            if bad:
                out.append(bad)
        return out or [self.ok(ref)]


class LineValuesInRangeRule(MoneyRule):
    """Quantities and hours are non-negative; the productivity factor is plausible."""

    rule_id = "postcalc.values_in_range"
    name = "Post-calculation quantities and factors are sane"
    standard = POSTCALC_RULE_SET
    description = "Quantities, hours and cost >= 0 and < 1e12; productivity factor in (0, 20]"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out: list[RuleResult] = []
        for line in rows(context, "lines"):
            ref = str(line.get("ref", ""))
            for field in (
                "planned_quantity",
                "actual_quantity",
                "planned_hours",
                "actual_hours",
                "planned_labour_cost",
            ):
                bad = self.out_of_range(context, ref, field, to_dec(line.get(field)), _ZERO, MAX_SANE_AMOUNT)
                if bad:
                    out.append(bad)
            factor = to_dec(line.get("productivity_factor"))
            if factor is not None and (factor <= 0 or factor > MAX_PRODUCTIVITY_FACTOR):
                out.append(
                    self.fail(
                        context,
                        "value_in_range",
                        ref=ref,
                        severity=Severity.WARNING,
                        field="productivity_factor",
                        value=factor,
                        low=">0",
                        high=MAX_PRODUCTIVITY_FACTOR,
                    )
                )
        return out or [self.ok(str(section(context, "project").get("project_id", "")))]


class PostcalcCurrencyRule(MoneyRule):
    """A report that prices labour states a currency, the same on every line."""

    rule_id = "postcalc.currency_consistent"
    name = "Post-calculation currency stated and consistent"
    standard = POSTCALC_RULE_SET
    description = "Project currency present when costs are present and equal to each line currency"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        project = section(context, "project")
        lines = rows(context, "lines")
        ref = str(project.get("project_id", ""))
        if not any(to_dec(line.get("planned_labour_cost")) for line in lines):
            return [self.ok(ref)]
        header = currency_of(project)
        if not header:
            # Projects are created without a currency; the report is still readable, so this warns.
            return [self.fail(context, "currency_present", ref=ref, severity=Severity.WARNING)]
        found = self.currency_findings(context, ref, header, [currency_of(line) for line in lines])
        return found or [self.ok(ref)]


class PostcalcReferencesRule(MoneyRule):
    """The report names its project and every line names the position it reconciles."""

    rule_id = "postcalc.references_present"
    name = "Post-calculation references present"
    standard = POSTCALC_RULE_SET
    description = "project_id on the report and ref on every line"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        project = section(context, "project")
        ref = str(project.get("project_id", ""))
        out = []
        if blank(project.get("project_id")):
            out.append(self.fail(context, "reference_present", ref=ref, field="project_id"))
        out += [
            # A draft position may have no ordinal yet: flag it, do not hide the whole report.
            self.fail(
                context,
                "reference_present",
                ref=str(line.get("position_id", "")),
                severity=Severity.WARNING,
                field="ref",
            )
            for line in rows(context, "lines")
            if blank(line.get("ref"))
        ]
        return out or [self.ok(ref)]


POSTCALC_RULES = (
    ProjectRollupMatchesLinesRule,
    LineValuesInRangeRule,
    PostcalcCurrencyRule,
    PostcalcReferencesRule,
)


def register_postcalc_validation_rules() -> None:
    """Register the post-calculation rules with the platform rule registry."""
    for rule_class in POSTCALC_RULES:
        rule_registry.register(rule_class(), [POSTCALC_RULE_SET])

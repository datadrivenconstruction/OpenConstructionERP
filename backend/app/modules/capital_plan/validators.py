# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules for a capital plan scenario (rule set ``capital_plan``).

The payload handed to every rule (``ValidationContext.data``)::

    {"plan": {currency, start_year, horizon_years},
     "envelopes": [{year, amount, label}],
     "items": [{id, project_id, title, start_year, duration_years, total_cost, phasing, status}],
     "baseline_count": int,
     "project_currencies": {project_id: currency}}

Each rule returns one failing ``RuleResult`` per offending element, or a single passing
result. ``details`` carries the numbers so the UI can render the finding in the reader's
language from the rule id; ``message`` is the English fallback.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.capital_plan.logic import (
    ACTIVE_STATUSES,
    envelope_by_year,
    item_spend_by_year,
    money,
    plan_years,
)

CAPITAL_PLAN_RULE_SET = "capital_plan"
_PHASING_TOLERANCE = Decimal("0.0001")


class _Rule(ValidationRule):
    standard = "capital_plan"
    category = RuleCategory.CONSISTENCY

    def _result(
        self, passed: bool, message: str, ref: str | None = None, details: dict[str, Any] | None = None
    ) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message=message,
            element_ref=ref,
            details=details or {},
        )

    def _ok(self) -> list[RuleResult]:
        return [self._result(True, "OK")]


def _items(context: ValidationContext) -> list[dict[str, Any]]:
    return list(context.data.get("items") or [])


class PhasingSumsToOne(_Rule):
    rule_id = "cp.phasing_sums_to_one"
    name = "Phasing sums to one"
    severity = Severity.ERROR
    description = "The yearly fractions of an item must add up to 1."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for item in _items(context):
            phasing = item.get("phasing") or []
            if not phasing:
                continue
            total = sum((Decimal(str(x)) for x in phasing), Decimal(0))
            if abs(total - 1) > _PHASING_TOLERANCE:
                out.append(
                    self._result(
                        False,
                        f"{item['title']}: phasing adds up to {total}, not 1",
                        str(item["id"]),
                        {"title": item["title"], "total": str(total)},
                    )
                )
        return out or self._ok()


class PhasingLengthMatchesDuration(_Rule):
    rule_id = "cp.phasing_length_matches_duration"
    name = "Phasing length matches duration"
    severity = Severity.ERROR
    description = "An item needs one phasing fraction per year of its duration."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for item in _items(context):
            phasing = item.get("phasing") or []
            duration = int(item.get("duration_years") or 1)
            if phasing and len(phasing) != duration:
                out.append(
                    self._result(
                        False,
                        f"{item['title']}: {len(phasing)} phasing values for {duration} years",
                        str(item["id"]),
                        {"title": item["title"], "values": len(phasing), "duration": duration},
                    )
                )
        return out or self._ok()


class ItemWithinHorizon(_Rule):
    rule_id = "cp.item_within_horizon"
    name = "Item within the plan horizon"
    severity = Severity.WARNING
    description = "Spend that falls outside the plan years is not counted against any envelope."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        plan = context.data["plan"]
        years = set(plan_years(plan["start_year"], plan["horizon_years"]))
        out = []
        for item in _items(context):
            outside = sorted(y for y in item_spend_by_year(item) if y not in years)
            if outside:
                out.append(
                    self._result(
                        False,
                        f"{item['title']}: spend in {outside[0]} is outside the plan horizon",
                        str(item["id"]),
                        {"title": item["title"], "year": outside[0]},
                    )
                )
        return out or self._ok()


class YearOverEnvelope(_Rule):
    rule_id = "cp.year_over_envelope"
    name = "Demand within the envelope"
    severity = Severity.ERROR
    description = "Demand in a year must not exceed the funding available in that year."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        plan = context.data["plan"]
        env = envelope_by_year(context.data.get("envelopes") or [])
        demand: dict[int, Decimal] = {}
        for item in _items(context):
            if item.get("status") in ACTIVE_STATUSES:
                for year, amount in item_spend_by_year(item).items():
                    demand[year] = demand.get(year, Decimal(0)) + amount
        out = []
        for year in plan_years(plan["start_year"], plan["horizon_years"]):
            # A year with no envelope at all is the job of cp.no_envelope_for_year.
            if year in env and demand.get(year, Decimal(0)) > env[year]:
                over = demand[year] - env[year]
                out.append(
                    self._result(
                        False,
                        f"{year}: demand exceeds the envelope by {over}",
                        str(year),
                        {"year": year, "demand": str(demand[year]), "envelope": str(env[year]), "over": str(over)},
                    )
                )
        return out or self._ok()


class NoEnvelopeForYear(_Rule):
    rule_id = "cp.no_envelope_for_year"
    name = "Envelope defined for every year"
    severity = Severity.WARNING
    description = "A plan year without a funding envelope has nothing to fund against."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        plan = context.data["plan"]
        env = envelope_by_year(context.data.get("envelopes") or [])
        out = [
            self._result(False, f"{year}: no envelope defined", str(year), {"year": year})
            for year in plan_years(plan["start_year"], plan["horizon_years"])
            if year not in env
        ]
        return out or self._ok()


class ItemWithoutCost(_Rule):
    rule_id = "cp.item_without_cost"
    name = "Item has a cost"
    severity = Severity.WARNING
    description = "An item with no cost always fits and hides real demand."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = [
            self._result(False, f"{i['title']}: no cost entered", str(i["id"]), {"title": i["title"]})
            for i in _items(context)
            if money(i.get("total_cost")) <= 0
        ]
        return out or self._ok()


class DuplicateProjectInScenario(_Rule):
    rule_id = "cp.duplicate_project_in_scenario"
    name = "Project appears once per scenario"
    severity = Severity.ERROR
    description = "The same project listed twice counts its money twice."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        seen: dict[str, dict[str, Any]] = {}
        out = []
        for item in _items(context):
            pid = item.get("project_id")
            if not pid:
                continue
            if str(pid) in seen:
                out.append(
                    self._result(
                        False,
                        f"{item['title']}: project already listed as {seen[str(pid)]['title']}",
                        str(item["id"]),
                        {"title": item["title"], "other": seen[str(pid)]["title"]},
                    )
                )
            else:
                seen[str(pid)] = item
        return out or self._ok()


class SingleBaseline(_Rule):
    rule_id = "cp.single_baseline"
    name = "One baseline per plan"
    severity = Severity.ERROR
    description = "A plan has at most one baseline scenario."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        count = int(context.data.get("baseline_count") or 0)
        if count > 1:
            return [self._result(False, f"{count} baseline scenarios, expected one", None, {"count": count})]
        return self._ok()


class CurrencyMismatchWithProject(_Rule):
    rule_id = "cp.currency_mismatch_with_project"
    name = "Currency matches the project"
    severity = Severity.WARNING
    description = "A linked project in another currency makes the cost a different unit than the envelope."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        currency = (context.data["plan"].get("currency") or "").upper()
        projects = context.data.get("project_currencies") or {}
        out = []
        for item in _items(context):
            theirs = (projects.get(str(item.get("project_id"))) or "").upper()
            if theirs and currency and theirs != currency:
                out.append(
                    self._result(
                        False,
                        f"{item['title']}: project is in {theirs}, plan is in {currency}",
                        str(item["id"]),
                        {"title": item["title"], "project": theirs, "plan": currency},
                    )
                )
        return out or self._ok()


CAPITAL_PLAN_RULES: tuple[type[ValidationRule], ...] = (
    PhasingSumsToOne,
    PhasingLengthMatchesDuration,
    ItemWithinHorizon,
    YearOverEnvelope,
    NoEnvelopeForYear,
    ItemWithoutCost,
    DuplicateProjectInScenario,
    SingleBaseline,
    CurrencyMismatchWithProject,
)


def register_capital_plan_rules() -> None:
    """Idempotently register the capital plan rules."""
    for rule in CAPITAL_PLAN_RULES:
        rule_registry.register(rule(), rule_sets=[CAPITAL_PLAN_RULE_SET])


async def run_rules(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Run every capital plan rule; return the failing findings sorted by rule id."""
    register_capital_plan_rules()
    context = ValidationContext(data=data)
    findings: list[dict[str, Any]] = []
    for rule in sorted(rule_registry.get_rules_for_sets([CAPITAL_PLAN_RULE_SET]), key=lambda r: r.rule_id):
        for result in await rule.validate(context):
            if not result.passed:
                findings.append(
                    {
                        "rule_id": result.rule_id,
                        "severity": str(result.severity),
                        "message": result.message,
                        "element_ref": result.element_ref,
                        "details": result.details,
                    }
                )
    return findings

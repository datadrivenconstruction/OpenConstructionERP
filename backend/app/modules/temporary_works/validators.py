# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Temporary works validation rules (rule set ``temporary_works``).

Rules run over a plain dict built by the service. An item is checked as::

    {"item": {"id", "status", "design_check_category", "designer_name", "checker_name",
              "twc_name", "twc_user_id", "required_load_date", "required_strike_date",
              "design_due_date"}}

and a permit as::

    {"permit": {"id", "permit_type", "status", "issued_at", "valid_from", "valid_to",
                "closed_at", "prereq_design_check_accepted", "prereq_inspection_passed"}}

Each rule looks only at the stage it guards, so an item still being identified or
briefed passes with the people and dates not yet filled in.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, blank, section

TEMPORARY_WORKS_RULE_SET = "temporary_works"

#: From the design check onward a category 2 or 3 design needs its independent check on record.
_CHECKED_STATUSES = frozenset({"design_checked", "approved_to_load", "loaded", "in_use", "approved_to_strike"})
#: From approval to load onward a coordinator answers for the works.
_COORDINATED_STATUSES = frozenset({"approved_to_load", "loaded", "in_use", "approved_to_strike"})
_IN_FORCE_PERMIT = frozenset({"issued", "active"})
_INDEPENDENT_CHECK_CATEGORIES = frozenset({"2", "3"})


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


class _TemporaryWorksRule(MoneyRule):
    standard = TEMPORARY_WORKS_RULE_SET
    message_section = "temporary_works"
    suggestion_key = "temporary_works.suggestion"


class IndependentCheckRule(_TemporaryWorksRule):
    """A category 2 or 3 design is checked by someone other than its designer."""

    rule_id = "temporary_works.independent_check"
    name = "Design check is independent"
    description = "Category 2 and 3 designs need a named checker who is not the designer once checked"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        item = section(context, "item")
        ref = str(item.get("id", ""))
        category = item.get("design_check_category")
        if item.get("status") not in _CHECKED_STATUSES or category not in _INDEPENDENT_CHECK_CATEGORIES:
            return [self.ok(ref)]
        checker = str(item.get("checker_name") or "").strip().casefold()
        designer = str(item.get("designer_name") or "").strip().casefold()
        if not checker:
            return [self.fail(context, "checker_missing", ref=ref, category=category)]
        if checker == designer:
            return [self.fail(context, "checker_is_designer", ref=ref, name=item.get("checker_name"))]
        return [self.ok(ref)]


class CoordinatorAssignedRule(_TemporaryWorksRule):
    """Works cleared to load have a temporary works coordinator."""

    rule_id = "temporary_works.coordinator_assigned"
    name = "Coordinator assigned before loading"
    description = "From approved to load onward the item names its temporary works coordinator"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        item = section(context, "item")
        ref = str(item.get("id", ""))
        unassigned = blank(item.get("twc_name")) and blank(item.get("twc_user_id"))
        if item.get("status") in _COORDINATED_STATUSES and unassigned:
            return [self.fail(context, "coordinator_assigned", ref=ref)]
        return [self.ok(ref)]


class DatesInOrderRule(_TemporaryWorksRule):
    """The design is due before loading, and striking comes after loading."""

    rule_id = "temporary_works.dates_in_order"
    name = "Design, load and strike dates in order"
    description = "required_strike_date must not precede required_load_date; design_due_date should not follow it"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        item = section(context, "item")
        ref = str(item.get("id", ""))
        load = _day(item.get("required_load_date"))
        strike = _day(item.get("required_strike_date"))
        due = _day(item.get("design_due_date"))
        out: list[RuleResult] = []
        if load and strike and strike < load:
            out.append(self.fail(context, "strike_before_load", ref=ref, load=load, strike=strike))
        if load and due and due > load:
            out.append(
                self.fail(context, "design_due_after_load", ref=ref, severity=Severity.WARNING, due=due, load=load)
            )
        return out or [self.ok(ref)]


class PermitValidityWindowRule(_TemporaryWorksRule):
    """A permit is valid from a day to a later day, and closed after it was issued."""

    rule_id = "temporary_works.permit_validity_window"
    name = "Permit dates in order"
    description = "valid_to must not precede valid_from, closed_at must not precede issued_at"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        permit = section(context, "permit")
        ref = str(permit.get("id", ""))
        start, end = _day(permit.get("valid_from")), _day(permit.get("valid_to"))
        issued, closed = _day(permit.get("issued_at")), _day(permit.get("closed_at"))
        out: list[RuleResult] = []
        if start and end and end < start:
            out.append(self.fail(context, "valid_to_before_from", ref=ref, start=start, end=end))
        if issued and closed and closed < issued:
            out.append(self.fail(context, "closed_before_issued", ref=ref, issued=issued, closed=closed))
        return out or [self.ok(ref)]


class PermitToLoadPrerequisitesRule(_TemporaryWorksRule):
    """A permit to load is in force only with the design check accepted and the inspection passed."""

    rule_id = "temporary_works.permit_to_load_prerequisites"
    name = "Permit to load has its prerequisites"
    description = "An issued or active permit to load records both the accepted design check and the passed inspection"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        permit = section(context, "permit")
        ref = str(permit.get("id", ""))
        if permit.get("permit_type") != "permit_to_load" or permit.get("status") not in _IN_FORCE_PERMIT:
            return [self.ok(ref)]
        out = [
            self.fail(context, key, ref=ref)
            for key, field in (
                ("design_check_not_accepted", "prereq_design_check_accepted"),
                ("inspection_not_passed", "prereq_inspection_passed"),
            )
            if not permit.get(field)
        ]
        return out or [self.ok(ref)]


TEMPORARY_WORKS_RULES = (
    IndependentCheckRule,
    CoordinatorAssignedRule,
    DatesInOrderRule,
    PermitValidityWindowRule,
    PermitToLoadPrerequisitesRule,
)


def register_temporary_works_validation_rules() -> None:
    """Register the temporary works rules with the platform rule registry."""
    for rule_class in TEMPORARY_WORKS_RULES:
        rule_registry.register(rule_class(), [TEMPORARY_WORKS_RULE_SET])


ITEM_FIELDS = (
    "status",
    "design_check_category",
    "designer_name",
    "checker_name",
    "twc_name",
    "twc_user_id",
    "required_load_date",
    "required_strike_date",
    "design_due_date",
)
PERMIT_FIELDS = (
    "permit_type",
    "status",
    "issued_at",
    "valid_from",
    "valid_to",
    "closed_at",
    "prereq_design_check_accepted",
    "prereq_inspection_passed",
)


def _body(record: Any, fields: tuple[str, ...], overrides: dict[str, Any] | None) -> dict[str, Any]:
    body = {f: getattr(record, f, None) for f in fields}
    body["id"] = str(getattr(record, "id", "") or "")
    body.update({k: v for k, v in (overrides or {}).items() if k in fields})
    return body


def item_snapshot(record: Any, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """The rule input for an item (ORM row or schema), with pending field changes applied."""
    return {"item": _body(record, ITEM_FIELDS, overrides)}


def permit_snapshot(record: Any, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """The rule input for a permit (ORM row or schema), with pending field changes applied."""
    return {"permit": _body(record, PERMIT_FIELDS, overrides)}


__all__ = [
    "TEMPORARY_WORKS_RULES",
    "TEMPORARY_WORKS_RULE_SET",
    "item_snapshot",
    "permit_snapshot",
    "register_temporary_works_validation_rules",
]

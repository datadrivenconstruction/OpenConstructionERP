# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Approval route validation rules (rule set ``approval_routes``).

Rules run over a plain dict built by the service, one record under one key::

    {"route":      {"id", "is_active", "steps": [{"ordinal", "approver_role", "approver_user_id", "sla_hours"}]}}
    {"delegation": {"id", "starts_at", "ends_at"}}

A rule looks only at the record kind it guards.
"""

from __future__ import annotations

from typing import Any

from app.core.permissions import _resolve_role
from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import blank, section
from app.core.validation.quality_rules import QualityRule, parse_day, today_of

APPROVAL_ROUTES_RULE_SET = "approval_routes"

ROUTE_FIELDS = ("is_active", "steps")
DELEGATION_FIELDS = ("starts_at", "ends_at")


def _steps(route: dict[str, Any]) -> list[dict[str, Any]]:
    raw = route.get("steps")
    return [s for s in raw if isinstance(s, dict)] if isinstance(raw, list) else []


class _ApprovalRule(QualityRule):
    standard = APPROVAL_ROUTES_RULE_SET
    message_section = "approval_routes"


class ApproverRoleKnownRule(_ApprovalRule):
    """A role-based step names a role someone can actually hold, or the route would stall there."""

    rule_id = "approval_routes.approver_role_known"
    name = "Step approver role exists"
    description = "approver_role must resolve to a platform role or role alias"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        route = section(context, "route")
        ref = str(route.get("id", ""))
        out = [
            self.fail(context, "approver_role_unknown", ref=ref, step=s.get("ordinal"), role=s.get("approver_role"))
            for s in _steps(route)
            if not blank(s.get("approver_role")) and _resolve_role(str(s["approver_role"])) is None
        ]
        return out or [self.ok(ref)]


class StepSlaRule(_ApprovalRule):
    """Every step of a live route has a time limit, or an idle approver stalls the chain unnoticed."""

    rule_id = "approval_routes.step_sla"
    name = "Step has an SLA"
    severity = Severity.WARNING
    description = "steps of an active route should set sla_hours"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        route = section(context, "route")
        ref = str(route.get("id", ""))
        if route.get("is_active") is False:
            return [self.ok(ref)]
        out = [
            self.fail(context, "step_sla_missing", ref=ref, step=s.get("ordinal"))
            for s in _steps(route)
            if s.get("sla_hours") in (None, "", 0)
        ]
        return out or [self.ok(ref)]


class DelegationEndedRule(_ApprovalRule):
    """A hand-off is not created already over."""

    rule_id = "approval_routes.delegation_ended"
    name = "Delegation has not already ended"
    description = "ends_at must not be before today"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = section(context, "delegation")
        ref = str(d.get("id", ""))
        ends = parse_day(d.get("ends_at"))
        if ends is not None and ends < today_of(context):
            return [self.fail(context, "delegation_ended", ref=ref, ends=ends)]
        return [self.ok(ref)]


class DelegationOpenEndedRule(_ApprovalRule):
    """A hand-off with no end date is a permanent transfer of someone's approvals."""

    rule_id = "approval_routes.delegation_open_ended"
    name = "Delegation has an end date"
    severity = Severity.WARNING
    description = "a delegation should state ends_at"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        d = section(context, "delegation")
        ref = str(d.get("id", ""))
        if d and blank(d.get("ends_at")):
            return [self.fail(context, "delegation_open_ended", ref=ref)]
        return [self.ok(ref)]


APPROVAL_ROUTES_RULES = (ApproverRoleKnownRule, StepSlaRule, DelegationEndedRule, DelegationOpenEndedRule)


def register_approval_routes_validation_rules() -> None:
    """Register the approval route rules with the platform rule registry."""
    for rule_class in APPROVAL_ROUTES_RULES:
        rule_registry.register(rule_class(), [APPROVAL_ROUTES_RULE_SET])


__all__ = [
    "APPROVAL_ROUTES_RULES",
    "APPROVAL_ROUTES_RULE_SET",
    "DELEGATION_FIELDS",
    "ROUTE_FIELDS",
    "register_approval_routes_validation_rules",
]

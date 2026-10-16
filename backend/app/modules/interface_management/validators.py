# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rule set ``interface_management``.

The rules read one payload, built by
:meth:`app.modules.interface_management.service.InterfaceManagementService.validation_payload`:
``{"interfaces": [...]}`` where every row already carries what the database
said about its links (``activity_found``, ``activity_end_date``, ``rfi_found``)
and about its approval (``approval_status`` of the latest approval-routes
instance on it). The rules themselves are pure over that dict, so they are
asserted without a database.

The service enforces the link and lifecycle checks at write time too (HTTP 422 /
409). The rules exist because the data also moves without a write here: a
schedule activity or an RFI is deleted after the link was made, an approval is
rejected after someone agreed the interface by hand on an older build, a row is
imported. ``need_by_date`` falling after the linked activity's finish is only a
warning: the date may be deliberate, but the person planning the activity has
to hear about it.

Rules:
    interface_management.schedule_activity_in_project (ERROR)
    interface_management.rfi_in_project (ERROR)
    interface_management.agreed_has_agreed_date (ERROR)
    interface_management.agreed_through_route (ERROR)
    interface_management.closed_was_agreed (ERROR)
    interface_management.need_by_before_activity_finish (WARNING)
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)

logger = logging.getLogger(__name__)

RULE_SET = "interface_management"

_SETTLED = frozenset({"agreed", "closed"})


def _interfaces(context: ValidationContext) -> list[dict[str, Any]]:
    data = context.data
    rows = data.get("interfaces", []) if isinstance(data, dict) else data
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _as_date(value: Any) -> date | None:
    """Parse an ISO date (or the date part of an ISO datetime); ``None`` for anything else."""
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


class _InterfaceRule(ValidationRule):
    """Shared result builder: one result per interface the rule applies to."""

    standard = RULE_SET
    category = RuleCategory.CONSISTENCY
    severity = Severity.ERROR
    suggestion = ""

    def applies(self, row: dict[str, Any]) -> bool:
        """Whether this rule has anything to say about ``row``."""
        raise NotImplementedError

    def problem(self, row: dict[str, Any]) -> str | None:
        """The failure message for ``row``, or ``None`` when it passes."""
        raise NotImplementedError

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for row in _interfaces(context):
            if not self.applies(row):
                continue
            problem = self.problem(row)
            ref = str(row.get("reference") or row.get("id") or "")
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=problem is None,
                    message="OK" if problem is None else f"{ref}: {problem}",
                    element_ref=str(row.get("id") or ""),
                    suggestion=None if problem is None else self.suggestion,
                )
            )
        return results


class ScheduleActivityInProjectRule(_InterfaceRule):
    """A linked Schedule ID must name an existing activity of the same project."""

    rule_id = "interface_management.schedule_activity_in_project"
    name = "Linked schedule activity exists in this project"
    category = RuleCategory.CONSISTENCY
    description = "The Schedule ID on an interface must reference an activity in one of the project's schedules"
    suggestion = "Pick the activity again from the project's schedule, or clear the link"

    def applies(self, row: dict[str, Any]) -> bool:
        return bool(row.get("schedule_activity_id"))

    def problem(self, row: dict[str, Any]) -> str | None:
        if row.get("activity_found"):
            return None
        return f"schedule activity {row.get('schedule_activity_id')} is not an activity of this project"


class RfiInProjectRule(_InterfaceRule):
    """A linked RFI must be an existing RFI of the same project."""

    rule_id = "interface_management.rfi_in_project"
    name = "Linked RFI exists in this project"
    category = RuleCategory.CONSISTENCY
    description = "The RFI linked to an interface must be an RFI of the same project"
    suggestion = "Pick the RFI again from the project's RFI register, or clear the link"

    def applies(self, row: dict[str, Any]) -> bool:
        return bool(row.get("rfi_id"))

    def problem(self, row: dict[str, Any]) -> str | None:
        if row.get("rfi_found"):
            return None
        return f"RFI {row.get('rfi_id')} is not an RFI of this project"


class AgreedHasAgreedDateRule(_InterfaceRule):
    """An agreed or closed interface records the date it was agreed."""

    rule_id = "interface_management.agreed_has_agreed_date"
    name = "Agreed interface has an agreed date"
    category = RuleCategory.COMPLETENESS
    description = "An interface that is agreed or closed must carry the date the agreement was reached"
    suggestion = "Enter the date the interface was agreed"

    def applies(self, row: dict[str, Any]) -> bool:
        return row.get("status") in _SETTLED

    def problem(self, row: dict[str, Any]) -> str | None:
        return None if row.get("agreed_date") else "agreed or closed without an agreed date"


class AgreedThroughRouteRule(_InterfaceRule):
    """Once an interface was sent through an approval route, only an approved route agrees it."""

    rule_id = "interface_management.agreed_through_route"
    name = "Agreement follows the approval route"
    category = RuleCategory.COMPLIANCE
    description = (
        "When an interface agreement was routed for approval, the interface may be agreed or closed "
        "only after that approval was granted"
    )
    suggestion = "Finish the approval route, or route the agreement again"

    def applies(self, row: dict[str, Any]) -> bool:
        return row.get("status") in _SETTLED and row.get("approval_status") in {"pending", "rejected", "approved"}

    def problem(self, row: dict[str, Any]) -> str | None:
        approval = row.get("approval_status")
        if approval == "approved":
            return None
        return f"agreed while its approval is {approval}"


class ClosedWasAgreedRule(_InterfaceRule):
    """A closed interface went through agreement first (closed only from agreed)."""

    rule_id = "interface_management.closed_was_agreed"
    name = "Closed interface was agreed first"
    category = RuleCategory.CONSISTENCY
    description = "An interface is closed only after it was agreed; a closed interface carries both dates in order"
    suggestion = "Record the agreement (and its date) before closing the interface"

    def applies(self, row: dict[str, Any]) -> bool:
        return row.get("status") == "closed"

    def problem(self, row: dict[str, Any]) -> str | None:
        agreed = _as_date(row.get("agreed_date"))
        closed = _as_date(row.get("closed_date"))
        if agreed is None:
            return "closed without ever being agreed"
        if closed is not None and closed < agreed:
            return f"closed on {closed.isoformat()}, before it was agreed on {agreed.isoformat()}"
        return None


class NeedByBeforeActivityFinishRule(_InterfaceRule):
    """The need-by date should not fall after the finish of the activity the interface gates."""

    rule_id = "interface_management.need_by_before_activity_finish"
    name = "Need-by date is not after the linked activity's finish"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = (
        "An interface that gates a schedule activity has to be agreed by the time that activity finishes; "
        "a later need-by date means the programme assumes an agreement that is not due yet"
    )
    suggestion = "Bring the need-by date forward, or re-plan the linked activity"

    def applies(self, row: dict[str, Any]) -> bool:
        return (
            bool(row.get("activity_found"))
            and _as_date(row.get("need_by_date")) is not None
            and _as_date(row.get("activity_end_date")) is not None
        )

    def problem(self, row: dict[str, Any]) -> str | None:
        need_by = _as_date(row.get("need_by_date"))
        finish = _as_date(row.get("activity_end_date"))
        if need_by is None or finish is None or need_by <= finish:
            return None
        return f"need-by {need_by.isoformat()} is after the linked activity finishes on {finish.isoformat()}"


ALL_RULES: tuple[type[_InterfaceRule], ...] = (
    ScheduleActivityInProjectRule,
    RfiInProjectRule,
    AgreedHasAgreedDateRule,
    AgreedThroughRouteRule,
    ClosedWasAgreedRule,
    NeedByBeforeActivityFinishRule,
)


def register_interface_management_validation_rules() -> None:
    """Register the interface-management rules with the platform rule registry (idempotent)."""
    for rule_cls in ALL_RULES:
        rule_registry.register(rule_cls(), [RULE_SET])
    logger.debug("interface_management: registered %d validation rules", len(ALL_RULES))

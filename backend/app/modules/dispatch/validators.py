# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dispatch board validation rules, registered under the ``dispatch`` rule set.

Each rule reads ``{"day": "YYYY-MM-DD", "conflicts": [Conflict.as_dict(), ...]}`` built by
``DispatchService.validate_day`` from ``logic.detect_conflicts`` and reports one failed
result per conflict of its kind, so the board and the validation report never disagree.

* ``dispatch.no_double_booking`` (ERROR): a person or unit is at one location per day.
* ``dispatch.unit_not_down`` (ERROR): a unit down for maintenance is not sent to a site.
* ``dispatch.maintenance_not_overdue`` (WARNING): a dispatched unit has no overdue maintenance.
* ``dispatch.operator_certified`` (WARNING): the operator holds every certificate the unit requires.
* ``dispatch.worker_not_absent`` (WARNING): nobody on leave, holiday or sick is dispatched.
* ``dispatch.crew_min_size`` (WARNING): a crew has at least its minimum number of people present.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.dispatch import logic

logger = logging.getLogger(__name__)

DISPATCH_RULE_SET = "dispatch"


class _ConflictRule(ValidationRule):
    standard = "dispatch"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    conflict_kind = ""

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data: dict[str, Any] = context.data if isinstance(context.data, dict) else {}
        hits = [c for c in data.get("conflicts") or [] if c.get("kind") == self.conflict_kind]
        if not hits:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message="OK",
                    element_ref=str(data.get("day") or ""),
                )
            ]
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=False,
                message=str(c.get("message") or ""),
                element_ref=f"{c.get('card_kind')}:{c.get('card_ref')}",
                details=dict(c.get("details") or {}),
            )
            for c in hits
        ]


class NoDoubleBookingRule(_ConflictRule):
    rule_id = "dispatch.no_double_booking"
    name = "One place per person and unit per day"
    severity = Severity.ERROR
    description = "A person or machine cannot be at two locations on the same day"
    conflict_kind = logic.DOUBLE_BOOKED


class UnitNotDownRule(_ConflictRule):
    rule_id = "dispatch.unit_not_down"
    name = "No machine sent out while down for maintenance"
    severity = Severity.ERROR
    description = "A unit held by a maintenance work order stays off site that day"
    conflict_kind = logic.MAINTENANCE_BLOCK


class MaintenanceNotOverdueRule(_ConflictRule):
    rule_id = "dispatch.maintenance_not_overdue"
    name = "Dispatched machine has no overdue maintenance"
    category = RuleCategory.COMPLIANCE
    description = "A unit with a scheduled work order in the past is flagged before it goes out"
    conflict_kind = logic.MAINTENANCE_OVERDUE


class OperatorCertifiedRule(_ConflictRule):
    rule_id = "dispatch.operator_certified"
    name = "Operator holds the certificates the machine needs"
    category = RuleCategory.COMPLIANCE
    description = "The required certificate types on the unit are valid for the operator on the day"
    conflict_kind = logic.MISSING_CERTIFICATE


class WorkerNotAbsentRule(_ConflictRule):
    rule_id = "dispatch.worker_not_absent"
    name = "Nobody on leave is dispatched"
    description = "People with an unavailable, holiday, sick or leave window that day are flagged"
    conflict_kind = logic.WORKER_ABSENT


class CrewMinSizeRule(_ConflictRule):
    rule_id = "dispatch.crew_min_size"
    name = "Crew is not under its minimum size"
    description = "Present members of a crew reach the minimum set on the crew"
    conflict_kind = logic.CREW_UNDER_MINIMUM


_RULES: tuple[ValidationRule, ...] = (
    NoDoubleBookingRule(),
    UnitNotDownRule(),
    MaintenanceNotOverdueRule(),
    OperatorCertifiedRule(),
    WorkerNotAbsentRule(),
    CrewMinSizeRule(),
)


def register_dispatch_validation_rules() -> None:
    """Register the dispatch rules under the ``dispatch`` rule set."""
    for rule in _RULES:
        rule_registry.register(rule, [DISPATCH_RULE_SET])
    logger.debug("dispatch: registered %d validation rules", len(_RULES))

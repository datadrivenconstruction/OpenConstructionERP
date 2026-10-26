# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Last Planner validation rules​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ - the ``last_planner`` rule set.

The payload is built by :meth:`LastPlannerService.validation_payload`. The
checks are pure functions over that dict, so they test without a database.

* ``last_planner.commitment_constraints_open`` (error) - a commitment was made
  on a task that still has open constraints: the promise is not sound.
* ``last_planner.week_ppc_recorded`` (warning) - a past week with commitments
  was never closed, so it has no PPC.
* ``last_planner.missed_commitment_reason`` (warning) - a missed commitment
  has no reason for variance, so it never reaches the Pareto.
* ``last_planner.constraint_overdue`` (warning) - an open constraint is past
  its target clear date.
* ``last_planner.constraint_owner`` (warning) - an open constraint has no owner.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.modules.schedule_advanced.messages import translate

RULE_SET = "last_planner"
_OPEN = ("open", "in_progress", "escalated")
_MADE = ("committed", "in_progress", "at_risk")


def _rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    v = payload.get(key)
    return [r for r in v if isinstance(r, dict)] if isinstance(v, list) else []


def _as_of(payload: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(str(payload.get("as_of"))[:10])
    except ValueError:
        return None


def check_commitment_constraints_open(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Live commitments whose task still has open constraints."""
    return [
        c for c in _rows(payload, "commitments") if c.get("status") in _MADE and int(c.get("open_constraints") or 0)
    ]


def check_week_ppc_recorded(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Weeks that ended before ``as_of``, had commitments, and are not closed with a PPC."""
    as_of = _as_of(payload)
    if as_of is None:
        return []
    out = []
    for w in _rows(payload, "weeks"):
        start = date.fromisoformat(w["week_start_date"])
        if start + timedelta(days=7) <= as_of and int(w.get("committed") or 0) > 0:
            if w.get("status") != "closed" or w.get("ppc_percent") is None:
                out.append(w)
    return out


def check_missed_commitment_reason(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Missed commitments with no reason for variance."""
    return [c for c in _rows(payload, "commitments") if c.get("status") == "missed" and not c.get("has_rnc")]


def check_constraint_overdue(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Open constraints whose target clear date has passed."""
    as_of = _as_of(payload)
    if as_of is None:
        return []
    return [
        c
        for c in _rows(payload, "constraints")
        if c.get("status") in _OPEN
        and c.get("target_clear_date")
        and date.fromisoformat(c["target_clear_date"]) < as_of
    ]


def check_constraint_owner(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Open constraints nobody owns."""
    return [c for c in _rows(payload, "constraints") if c.get("status") in _OPEN and not c.get("owner_user_id")]


class _LpsRule(ValidationRule):
    standard = RULE_SET
    check: Any = None
    collection = ""

    def _judged(self, payload: dict[str, Any]) -> bool:
        return bool(_rows(payload, self.collection))

    def _params(self, row: dict[str, Any]) -> dict[str, Any]:
        return {}

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = context.data if isinstance(context.data, dict) else {}
        locale = str((context.metadata or {}).get("locale") or "en")
        if not payload or not self._judged(payload):
            return []
        found = type(self).check(payload)
        if not found:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message=translate("common.ok", locale=locale),
                )
            ]
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=False,
                message=translate(f"{self.rule_id}.fail", locale=locale, **self._params(row)),
                element_ref=str(row.get("id") or ""),
                details=dict(row),
                suggestion=translate(f"{self.rule_id}.suggestion", locale=locale),
            )
            for row in found
        ]


class CommitmentConstraintsOpen(_LpsRule):
    """A commitment needs a ready task: no open constraints."""

    rule_id = "last_planner.commitment_constraints_open"
    name = "Commitment On A Ready Task"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Flags a commitment made on a task that still has open constraints."
    check = staticmethod(check_commitment_constraints_open)
    collection = "commitments"

    def _params(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "crew": row.get("worker_or_crew") or "-",
            "count": row.get("open_constraints"),
            "week": row.get("week_start_date"),
        }


class WeekPpcRecorded(_LpsRule):
    """Every finished week with commitments must be closed with a PPC."""

    rule_id = "last_planner.week_ppc_recorded"
    name = "Week PPC Recorded"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Flags a past week with commitments that has no PPC recorded."
    check = staticmethod(check_week_ppc_recorded)
    collection = "weeks"

    def _params(self, row: dict[str, Any]) -> dict[str, Any]:
        return {"week": row.get("week_start_date")}


class MissedCommitmentReason(_LpsRule):
    """A missed commitment needs a reason for variance."""

    rule_id = "last_planner.missed_commitment_reason"
    name = "Missed Commitment Has A Reason"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Flags a missed commitment with no reason for variance recorded."
    check = staticmethod(check_missed_commitment_reason)
    collection = "commitments"

    def _params(self, row: dict[str, Any]) -> dict[str, Any]:
        return {"crew": row.get("worker_or_crew") or "-", "week": row.get("week_start_date")}


class ConstraintOverdue(_LpsRule):
    """An open constraint past its target clear date threatens the look-ahead."""

    rule_id = "last_planner.constraint_overdue"
    name = "Constraint Overdue"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Flags an open constraint whose target clear date has passed."
    check = staticmethod(check_constraint_overdue)
    collection = "constraints"

    def _params(self, row: dict[str, Any]) -> dict[str, Any]:
        return {"description": row.get("description") or "-", "date": row.get("target_clear_date")}


class ConstraintOwner(_LpsRule):
    """An open constraint needs someone responsible for clearing it."""

    rule_id = "last_planner.constraint_owner"
    name = "Constraint Has An Owner"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Flags an open constraint with no owner."
    check = staticmethod(check_constraint_owner)
    collection = "constraints"

    def _params(self, row: dict[str, Any]) -> dict[str, Any]:
        return {"description": row.get("description") or "-"}


LPS_RULES: tuple[type[ValidationRule], ...] = (
    CommitmentConstraintsOpen,
    WeekPpcRecorded,
    MissedCommitmentReason,
    ConstraintOverdue,
    ConstraintOwner,
)


def register_lps_rules() -> str:
    """Register the rule set once; a second call is a no-op."""
    if rule_registry.has_rules(RULE_SET):
        return RULE_SET
    for rule_class in LPS_RULES:
        rule_registry.register(rule_class(), [RULE_SET])
    return RULE_SET

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project tax profile validation rules, registered under ``project_tax``.

Market-neutral checks on the profile itself. Country rules that read the same
profile (which bases may elect a simplified method, until when) live in the
country's pack and run in its own rule set.

* ``project_tax.election_dated``  - WARNING. A simplified or exempt method
                                     names the day it was elected; without it
                                     no lock can be computed.
* ``project_tax.edition_stated``  - INFO. The bill standard edition is a
                                     proposal until a person stores it.
* ``project_tax.history_in_lock`` - ERROR. A change recorded in the history
                                     falls inside the lock of the election it
                                     left.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.line_tax import method_change_locked, parse_date
from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
    validation_engine,
)

logger = logging.getLogger(__name__)

PROJECT_TAX_RULE_SET = "project_tax"


def _record(context: ValidationContext) -> dict[str, Any]:
    data = context.data
    if isinstance(data, dict) and data.get("record_type") == "project_tax_profile":
        return data
    return {}


def _result(rule: ValidationRule, passed: bool, message: str, details: dict[str, Any] | None = None) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        details=details or {},
    )


class ElectionIsDated(ValidationRule):
    rule_id = "project_tax.election_dated"
    name = "Tax Method Election Is Dated"
    standard = PROJECT_TAX_RULE_SET
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "A simplified or exempt tax method states the day it was elected"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        if not record or record.get("tax_method") == "general":
            return []
        passed = parse_date(record.get("election_date")) is not None
        return [
            _result(
                self,
                passed,
                "OK" if passed else "The tax method has no election date, so its lock period cannot be checked.",
                {"tax_method": record.get("tax_method")},
            )
        ]


class EditionIsStated(ValidationRule):
    rule_id = "project_tax.edition_stated"
    name = "Bill Standard Edition Is Stated"
    standard = PROJECT_TAX_RULE_SET
    severity = Severity.INFO
    category = RuleCategory.COMPLETENESS
    description = "The edition of the bill standard is stored on the project, not inferred"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        if not record or not record.get("editions"):
            return []
        passed = record.get("edition_source") == "stored"
        return [
            _result(
                self,
                passed,
                "OK" if passed else "The bill standard edition is a proposal until it is saved on the project.",
                {"proposed": record.get("standard_edition") or ""},
            )
        ]


class HistoryRespectsLock(ValidationRule):
    rule_id = "project_tax.history_in_lock"
    name = "Tax Method Changes Respect The Lock"
    standard = PROJECT_TAX_RULE_SET
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "No recorded change of tax method falls inside the lock of the election it left"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        record = _record(context)
        if not record:
            return []
        lock = record.get("lock_months")
        results: list[RuleResult] = []
        for entry in record.get("method_history") or []:
            if not isinstance(entry, dict):
                continue
            election = parse_date(entry.get("election_date"))
            changed = parse_date(entry.get("changed_on"))
            if changed is None:
                continue
            locked = method_change_locked(election, lock, changed)
            results.append(
                _result(
                    self,
                    not locked,
                    "OK"
                    if not locked
                    else f"The method changed on {changed.isoformat()}, inside the lock of the election on "
                    f"{election.isoformat() if election else '?'}.",
                    {"changed_on": changed.isoformat(), "election_date": election.isoformat() if election else ""},
                )
            )
        return results


_RULES: tuple[ValidationRule, ...] = (ElectionIsDated(), EditionIsStated(), HistoryRespectsLock())


def register_project_tax_rules() -> None:
    """Register the rules with the core registry. Idempotent."""
    for rule in _RULES:
        rule_registry.register(rule, [PROJECT_TAX_RULE_SET])


async def evaluate_profile(record: dict[str, Any]) -> list[RuleResult]:
    """Run the rules over one profile record; failing results only, never raising."""
    try:
        report = await validation_engine.validate(
            data=record,
            rule_sets=[PROJECT_TAX_RULE_SET],
            target_type="project_tax_profile",
            target_id=str(record.get("project_id") or ""),
        )
    except Exception:  # noqa: BLE001 - validation augments the save; never break it
        logger.warning("project tax validation failed", exc_info=True)
        return []
    return [r for r in report.results if not r.passed and not r.is_engine_error]


# Registered at import as well as at startup, so a registry read without the app sees the set.
register_project_tax_rules()

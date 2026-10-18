# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost control validation rules, rule set ``cost_control``.

Registered against the global ``rule_registry`` at import time (the module
loader imports ``validators`` for autodiscovery). The cost control report runs
this rule set on every read, so what the page lists under "worth a look" is
exactly what these rules return.

Each rule reads the payload the report builds, a dict with ``lines`` (a list
of :class:`~app.modules.costmodel.cost_control.LineInput`) and the project
figures, and is silent when the payload is not a cost control payload.
Messages and suggestions come from the validation message bundle
(``cost_control.<rule>.fail`` and ``.suggestion``) in the caller's locale.
"""

from __future__ import annotations

import logging
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
from app.core.validation.messages import DEFAULT_LOCALE, translate
from app.modules.costmodel.chain_rules import register_cost_chain_rules
from app.modules.costmodel.cost_control import (
    FINDING_CERTIFIED_OVER_COMMITTED,
    FINDING_OVER_PLAN,
    FINDING_PARTLY_AWARDED,
    FINDING_PENDING_CHANGES,
    FINDING_STALE_SNAPSHOT,
    FINDING_UNASSIGNED,
    Finding,
    LineInput,
    line_findings,
    project_findings,
)
from app.modules.costmodel.forecast_rules import register_cost_forecast_rules
from app.modules.costmodel.structure_rules import register_cost_structure_rules

logger = logging.getLogger(__name__)

RULE_SET = "cost_control"
PAYLOAD_KEY = "cost_control"


def _payload(context: ValidationContext) -> dict[str, Any] | None:
    data = context.data
    if isinstance(data, dict) and isinstance(data.get(PAYLOAD_KEY), dict):
        return data[PAYLOAD_KEY]
    return None


def _locale(context: ValidationContext) -> str:
    metadata = getattr(context, "metadata", None)
    if isinstance(metadata, dict):
        locale = metadata.get("locale")
        if isinstance(locale, str) and locale.strip():
            return locale.strip()
    return DEFAULT_LOCALE


def _to_result(rule: ValidationRule, finding: Finding, locale: str = DEFAULT_LOCALE) -> RuleResult:
    """A finding as a rule result, message and suggestion in ``locale`` (keys ``<rule id>.fail``/``.suggestion``)."""
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=Severity.WARNING if finding.severity == "warning" else Severity.INFO,
        category=rule.category,
        passed=False,
        message=translate(f"{finding.rule_id}.fail", locale),
        element_ref=finding.line_key,
        details={"code": finding.code, "amount": str(finding.amount), **finding.details},
        suggestion=translate(f"{finding.rule_id}.suggestion", locale),
    )


class _CostControlRule(ValidationRule):
    """Shared plumbing: compute the findings once per payload, keep this rule's."""

    standard = "universal"
    category = RuleCategory.CONSISTENCY

    def _findings(self, payload: dict[str, Any]) -> list[Finding]:
        lines = [row for row in payload.get("lines") or [] if isinstance(row, LineInput)]
        found = line_findings(lines)
        found += project_findings(
            unassigned_committed=Decimal(str(payload.get("unassigned_committed") or "0")),
            pending_changes=Decimal(str(payload.get("pending_changes") or "0")),
            pending_count=int(payload.get("pending_count") or 0),
            days_since_snapshot=payload.get("days_since_snapshot"),
            has_money=bool(payload.get("has_money")),
        )
        return [f for f in found if f.rule_id == self.rule_id]

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        if payload is None:
            return []
        return [_to_result(self, f, _locale(context)) for f in self._findings(payload)]


class UnassignedMoneyRule(_CostControlRule):
    rule_id = FINDING_UNASSIGNED
    name = "Committed money without a cost line"
    severity = Severity.WARNING
    description = "Contract and order lines that bind the project but sit on no cost line."


class CertifiedOverCommittedRule(_CostControlRule):
    rule_id = FINDING_CERTIFIED_OVER_COMMITTED
    name = "Certified above award plus changes"
    severity = Severity.WARNING
    description = "Work certified on a cost line beyond what was awarded plus approved changes."


class ForecastOverPlanRule(_CostControlRule):
    rule_id = FINDING_OVER_PLAN
    name = "Forecast above plan"
    severity = Severity.WARNING
    description = "A cost line whose forecast exceeds its budget (or its estimate when there is no budget)."


class PartlyAwardedRule(_CostControlRule):
    rule_id = FINDING_PARTLY_AWARDED
    name = "Line only partly awarded"
    severity = Severity.INFO
    description = "Less than half of a line's planned amount is awarded, so the forecast may be too low."


class PendingChangesRule(_CostControlRule):
    rule_id = FINDING_PENDING_CHANGES
    name = "Change orders awaiting a decision"
    severity = Severity.INFO
    description = "Submitted change orders the forecast does not include yet."


class StaleSnapshotRule(_CostControlRule):
    rule_id = FINDING_STALE_SNAPSHOT
    name = "Forecast not saved recently"
    severity = Severity.INFO
    description = "No forecast snapshot within the last 35 days."
    category = RuleCategory.COMPLETENESS


COST_CONTROL_RULES: tuple[type[_CostControlRule], ...] = (
    UnassignedMoneyRule,
    CertifiedOverCommittedRule,
    ForecastOverPlanRule,
    PartlyAwardedRule,
    PendingChangesRule,
    StaleSnapshotRule,
)


def register_costmodel_validation_rules() -> None:
    """Register the cost control rules, the structure rules (V1 to V5), the chain rules (V6 to V10, V15)
    and the forecast documentation rules (V19, V20, V22).

    Each family goes into its own rule set.
    """
    for rule_cls in COST_CONTROL_RULES:
        rule_registry.register(rule_cls(), [RULE_SET])
    register_cost_structure_rules()
    register_cost_chain_rules()
    register_cost_forecast_rules()
    logger.debug("Registered cost control validation rules")


# Side-effect registration on import (module-loader autodiscovery contract).
register_costmodel_validation_rules()

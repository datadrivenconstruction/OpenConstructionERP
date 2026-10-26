# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""WIP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ report validation rules (rule set ``wip_report``).

* ``wip_report.billed_exceeds_contract`` - ERROR. Billed to date is more than the contract
  value with approved changes: an unapproved change is being billed, or a claim is wrong.
* ``wip_report.percent_complete_over_100`` - ERROR. Cost to date over the estimate gives a
  cost-to-cost completion above 100 percent; earned revenue is capped until the estimate is revised.
* ``wip_report.eac_below_cost_to_date`` - ERROR. The estimate at completion is lower than the
  cost already incurred, so the cost to complete is negative.
* ``wip_report.large_fade`` - WARNING. Projected gross profit fell by more than the threshold
  (default 2 percent of contract value) since the previous close.
* ``wip_report.loss_job`` - WARNING. The estimate exceeds the contract value: the whole
  expected loss is recognised now under percentage-of-completion accounting.

Every rule reads ``{"rows": [...], "fade_threshold_pct": ...}`` built by the service, so the
rules run against a plain dict with no database.
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
    validation_engine,
)
from app.modules.wip_report import logic

logger = logging.getLogger(__name__)

WIP_RULE_SET = "wip_report"


def _rows(context: ValidationContext) -> list[dict[str, Any]]:
    data = context.data if isinstance(context.data, dict) else {}
    rows = data.get("rows")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _threshold(context: ValidationContext) -> Decimal:
    data = context.data if isinstance(context.data, dict) else {}
    return logic.dec(data.get("fade_threshold_pct"), logic.DEFAULT_FADE_THRESHOLD_PCT)


def _money(amount: Decimal, currency: str) -> str:
    return f"{format(amount, ',.2f')} {currency}".strip()


class _WipRule(ValidationRule):
    standard = "ASC 606"
    category = RuleCategory.CONSISTENCY

    def failed(self, row: dict[str, Any]) -> str | None:  # pragma: no cover - overridden
        raise NotImplementedError

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for row in _rows(context):
            row = {**row, "_threshold": _threshold(context)}
            message = self.failed(row)
            ref = str(row.get("project_name") or row.get("project_id") or "")
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=message is None,
                    message=message or "OK",
                    element_ref=ref,
                    details={"project_id": str(row.get("project_id") or "")},
                )
            )
        return results


class BilledExceedsContract(_WipRule):
    """Billed to date over the contract value with approved changes."""

    rule_id = "wip_report.billed_exceeds_contract"
    name = "Billed To Date Within Contract Value"
    severity = Severity.ERROR
    description = "Billings to date do not exceed the contract value including approved change orders."

    def failed(self, row: dict[str, Any]) -> str | None:
        contract, billed = logic.dec(row.get("contract_value")), logic.dec(row.get("billed_to_date"))
        if contract <= 0 or billed <= contract:
            return None
        ccy = str(row.get("currency") or "")
        return f"Billed {_money(billed, ccy)} exceeds the contract value of {_money(contract, ccy)}."


class PercentCompleteOver100(_WipRule):
    """Cost-to-cost completion above 100 percent."""

    rule_id = "wip_report.percent_complete_over_100"
    name = "Percent Complete Not Above 100"
    severity = Severity.ERROR
    description = "Cost to date divided by the estimate at completion stays at or below 100 percent."

    def failed(self, row: dict[str, Any]) -> str | None:
        raw = logic.dec(row.get("percent_complete_raw"))
        if raw <= logic.HUNDRED:
            return None
        return f"Percent complete is {raw}% on a cost-to-cost basis; revise the estimate at completion."


class EacBelowCostToDate(_WipRule):
    """Estimate at completion lower than cost already incurred."""

    rule_id = "wip_report.eac_below_cost_to_date"
    name = "Estimate At Completion Not Below Cost To Date"
    severity = Severity.ERROR
    description = "The estimate at completion is at least the cost already incurred."

    def failed(self, row: dict[str, Any]) -> str | None:
        eac, ctd = logic.dec(row.get("estimated_cost")), logic.dec(row.get("cost_to_date"))
        if eac <= 0 or eac >= ctd:
            return None
        ccy = str(row.get("currency") or "")
        return f"Estimate at completion {_money(eac, ccy)} is below cost to date {_money(ctd, ccy)}."


class LargeFade(_WipRule):
    """Projected gross profit fell sharply since the previous close."""

    rule_id = "wip_report.large_fade"
    name = "No Large Gross Profit Fade"
    severity = Severity.WARNING
    category = RuleCategory.QUALITY
    description = "Projected gross profit does not fall by more than the threshold share of contract value."

    def failed(self, row: dict[str, Any]) -> str | None:
        fade = row.get("fade")
        fade_dec = logic.dec(fade) if fade is not None else None
        contract = logic.dec(row.get("contract_value"))
        if not logic.is_large_fade(fade_dec, contract, row["_threshold"]):
            return None
        ccy = str(row.get("currency") or "")
        return (
            f"Projected gross profit faded by {_money(-fade_dec, ccy)} since {row.get('previous_period')}, "
            f"more than {row['_threshold']}% of contract value."
        )


class LossJob(_WipRule):
    """The estimate exceeds the contract value."""

    rule_id = "wip_report.loss_job"
    name = "Projected Loss Recognised"
    severity = Severity.WARNING
    description = "A job whose estimate exceeds its contract value is flagged so the full loss is provided for."

    def failed(self, row: dict[str, Any]) -> str | None:
        gp = logic.dec(row.get("projected_gross_profit"))
        if gp >= 0 or logic.dec(row.get("estimated_cost")) <= 0:
            return None
        return f"The job is projected to lose {_money(-gp, str(row.get('currency') or ''))}."


_RULES: tuple[ValidationRule, ...] = (
    BilledExceedsContract(),
    PercentCompleteOver100(),
    EacBelowCostToDate(),
    LargeFade(),
    LossJob(),
)
RULE_IDS: tuple[str, ...] = tuple(r.rule_id for r in _RULES)


def register_wip_report_rules() -> None:
    """Register the rules with the core registry (idempotent: the registry overwrites by id)."""
    for rule in _RULES:
        rule_registry.register(rule, [WIP_RULE_SET])


async def evaluate(snapshot: dict[str, Any], *, target_id: str = "") -> list[RuleResult]:
    """Run the rule set over a snapshot and return the failing results only; never raises."""
    try:
        report = await validation_engine.validate(
            data=snapshot, rule_sets=[WIP_RULE_SET], target_type="wip_report", target_id=target_id
        )
    except Exception:  # noqa: BLE001 - findings augment a read, never break it
        logger.warning("wip_report validation failed for %s", target_id, exc_info=True)
        return []
    return [r for r in report.results if not r.passed and not r.is_engine_error]


__all__ = ["RULE_IDS", "WIP_RULE_SET", "evaluate", "register_wip_report_rules"]

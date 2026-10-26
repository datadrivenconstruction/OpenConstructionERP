# DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cash-flow forecast rules, rule set ``cashflow_forecast``.

* ``cashflow_forecast.negative_position``: the cumulative cash position of a
  currency falls below minus the project's threshold (zero when none is set).
* ``cashflow_forecast.receipt_overdue``: an issued receivable (invoice or
  claim) is past its due date and still open.
* ``cashflow_forecast.forecast_missing``: an active project has no record the
  forecast can be built from.

Each rule reads ``context.data["cashflow_forecast"]`` and is silent on any other
payload. Messages come from the validation message bundle in the caller's locale.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from app.core.currency_registry import sentence_amount
from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.core.validation.messages import DEFAULT_LOCALE, translate

logger = logging.getLogger(__name__)

RULE_SET = "cashflow_forecast"
PAYLOAD_KEY = "cashflow_forecast"
ACTIVE_STATUSES = frozenset({"active", "in_progress", "construction", "planning"})


def _payload(context: ValidationContext) -> dict[str, Any] | None:
    data = context.data
    if isinstance(data, dict) and isinstance(data.get(PAYLOAD_KEY), dict):
        return data[PAYLOAD_KEY]
    return None


def _locale(context: ValidationContext) -> str:
    metadata = getattr(context, "metadata", None)
    if isinstance(metadata, dict) and isinstance(metadata.get("locale"), str) and metadata["locale"].strip():
        return metadata["locale"].strip()
    return DEFAULT_LOCALE


def _money(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return Decimal("0")


class _CashRule(ValidationRule):
    standard = "universal"
    category = RuleCategory.CONSISTENCY

    def _fail(self, context: ValidationContext, key: str, *, element_ref: str | None, **params: str) -> RuleResult:
        locale = _locale(context)
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=False,
            message=translate(f"cashflow_forecast.{key}.fail", locale, **params),
            element_ref=element_ref,
            details={"problem": key, **params},
            suggestion=translate(f"cashflow_forecast.{key}.suggestion", locale, **params),
        )

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        raise NotImplementedError

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        if payload is None:
            return []
        return self.check(context, payload) or [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=True,
                message="",
            )
        ]


class NegativePositionRule(_CashRule):
    rule_id = "cashflow_forecast.negative_position"
    name = "Cash position below the threshold"
    severity = Severity.ERROR
    description = "The cumulative cash position of the project falls below minus its funding threshold."

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        threshold = _money(payload.get("threshold"))
        out: list[RuleResult] = []
        for cur in payload.get("currencies") or []:
            peak = cur.get("peak_funding")
            if not peak or _money(peak.get("amount")) <= threshold:
                continue
            ccy = str(cur.get("currency") or "")
            out.append(
                self._fail(
                    context,
                    "negative_position",
                    element_ref=f"{ccy}:{peak.get('period')}",
                    amount=sentence_amount(_money(peak.get("amount")), ccy),
                    period=str(peak.get("period")),
                    threshold=sentence_amount(threshold, ccy),
                )
            )
        return out


class ReceiptOverdueRule(_CashRule):
    rule_id = "cashflow_forecast.receipt_overdue"
    name = "Receipt overdue"
    severity = Severity.WARNING
    description = "An issued receivable is past its due date and still open."

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        return [
            self._fail(
                context,
                "receipt_overdue",
                element_ref=str(row.get("ref") or ""),
                document=str(row.get("label") or ""),
                amount=sentence_amount(_money(row.get("amount")), str(row.get("currency") or "")),
                due=str(row.get("due") or ""),
                days=str(row.get("days") or "0"),
            )
            for row in payload.get("overdue") or []
        ]


class ForecastMissingRule(_CashRule):
    rule_id = "cashflow_forecast.forecast_missing"
    name = "Forecast missing for an active project"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "An active project has no contract, invoice, order, subcontract or plan to forecast from."

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        if payload.get("has_inputs") or str(payload.get("project_status") or "") not in ACTIVE_STATUSES:
            return []
        return [self._fail(context, "forecast_missing", element_ref=None, project=str(payload.get("project_name")))]


CASHFLOW_RULES: tuple[type[_CashRule], ...] = (NegativePositionRule, ReceiptOverdueRule, ForecastMissingRule)


def register_cashflow_forecast_rules() -> None:
    """Register the three rules into the ``cashflow_forecast`` rule set."""
    for rule_cls in CASHFLOW_RULES:
        rule_registry.register(rule_cls(), [RULE_SET])
    logger.debug("Registered cash-flow forecast validation rules")

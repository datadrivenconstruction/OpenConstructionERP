# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bid day validation rules (rule set ``bid_day``).

* ``bid_day.package_has_quote`` - WARNING. A package has no quote; the estimate's plug carries it.
* ``bid_day.chosen_exclusions_resolved`` - ERROR. The chosen quote still has open exclusions.
* ``bid_day.quote_not_stale`` - WARNING. A quote is older than the board's limit (default 30 days).
* ``bid_day.more_than_one_quote`` - WARNING. A package has a single quote, nothing to compare it with.
* ``bid_day.total_near_estimate`` - WARNING. Direct cost differs from the estimate by more than the limit.

The rules read the dict :meth:`BidDayService.validation_input` builds. Errors
block "Freeze and submit"; warnings are shown and the estimator decides.
"""

from __future__ import annotations

import logging
from datetime import datetime
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
from app.modules.bid_day.logic import deviation_pct, to_decimal

logger = logging.getLogger(__name__)

RULE_SET = "bid_day"
DEFAULT_STALE_DAYS = 30
DEFAULT_DEVIATION_PCT = Decimal("10")


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _rows(context: ValidationContext) -> list[dict[str, Any]]:
    rows = _data(context).get("rows")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _result(rule: ValidationRule, passed: bool, message: str, ref: str | None = None, **details: Any) -> RuleResult:
    return RuleResult(
        rule_id=rule.rule_id,
        rule_name=rule.name,
        severity=rule.severity,
        category=rule.category,
        passed=passed,
        message=message,
        element_ref=ref,
        details=details,
    )


class PackageHasQuote(ValidationRule):
    rule_id = "bid_day.package_has_quote"
    name = "Every Package Has A Quote"
    standard = "custom"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Each trade package on the board has at least one quote; otherwise the estimate's plug is used."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for row in _rows(context):
            ok = bool(row.get("quotes"))
            msg = "OK" if ok else f"{row.get('name')} has no quote; the estimate figure is used."
            out.append(_result(self, ok, msg, row.get("id"), name=row.get("name")))
        return out


class ChosenExclusionsResolved(ValidationRule):
    rule_id = "bid_day.chosen_exclusions_resolved"
    name = "Chosen Quotes Have No Open Exclusions"
    standard = "custom"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Every exclusion of a chosen quote is either plugged with an amount or confirmed as included."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for row in _rows(context):
            chosen = next((q for q in row.get("quotes") or [] if q.get("id") == row.get("chosen_id")), None)
            if chosen is None:
                continue
            n_open = sum(1 for x in chosen.get("exclusions") or [] if x.get("status", "open") == "open")
            ok = n_open == 0
            msg = (
                "OK"
                if ok
                else f"{row.get('name')}: the chosen quote from {chosen.get('vendor')} has {n_open} open exclusion(s)."
            )
            out.append(
                _result(self, ok, msg, row.get("id"), name=row.get("name"), vendor=chosen.get("vendor"), count=n_open)
            )
        return out


class QuoteNotStale(ValidationRule):
    rule_id = "bid_day.quote_not_stale"
    name = "Quotes Are Recent"
    standard = "custom"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "No quote on the board is older than the board's limit in days."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        limit = int(data.get("stale_days") or DEFAULT_STALE_DAYS)
        now = data.get("now")
        if not isinstance(now, datetime):
            return []
        out = []
        for row in _rows(context):
            for q in row.get("quotes") or []:
                at = q.get("received_at")
                if not isinstance(at, datetime):
                    continue
                age = (now - at).days
                ok = age <= limit
                msg = "OK" if ok else f"{row.get('name')}: the quote from {q.get('vendor')} is {age} days old."
                out.append(_result(self, ok, msg, q.get("id"), name=row.get("name"), vendor=q.get("vendor"), days=age))
        return out


class MoreThanOneQuote(ValidationRule):
    rule_id = "bid_day.more_than_one_quote"
    name = "Packages Have Competing Quotes"
    standard = "custom"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "A package priced on a single quote has nothing to compare it with."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for row in _rows(context):
            n = len(row.get("quotes") or [])
            if n == 0:
                continue
            ok = n > 1
            msg = "OK" if ok else f"{row.get('name')} rests on a single quote."
            out.append(_result(self, ok, msg, row.get("id"), name=row.get("name")))
        return out


class TotalNearEstimate(ValidationRule):
    rule_id = "bid_day.total_near_estimate"
    name = "Direct Cost Is Close To The Estimate"
    standard = "custom"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "Direct cost on the board differs from the estimate's figures by no more than the limit."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        direct, estimate = to_decimal(data.get("direct")), to_decimal(data.get("estimate"))
        dev = deviation_pct(direct, estimate)
        if dev is None:
            return []
        limit = to_decimal(data.get("deviation_pct_limit"), DEFAULT_DEVIATION_PCT)
        ok = abs(dev) <= limit
        pct = f"{dev.quantize(Decimal('0.1'))}"
        msg = "OK" if ok else f"Direct cost is {pct}% away from the estimate (limit {limit}%)."
        return [_result(self, ok, msg, None, pct=pct, limit=str(limit))]


_RULES: tuple[ValidationRule, ...] = (
    PackageHasQuote(),
    ChosenExclusionsResolved(),
    QuoteNotStale(),
    MoreThanOneQuote(),
    TotalNearEstimate(),
)
RULE_IDS: tuple[str, ...] = tuple(r.rule_id for r in _RULES)


def register_bid_day_rules() -> None:
    for rule in _RULES:
        rule_registry.register(rule, [RULE_SET])


async def evaluate(data: dict[str, Any], *, target_id: str = "") -> list[RuleResult]:
    """Failed findings for one board; an engine failure logs and returns none."""
    try:
        report = await validation_engine.validate(
            data=data, rule_sets=[RULE_SET], target_type="bid_day", target_id=target_id
        )
    except Exception:  # noqa: BLE001 - findings augment a read, never break it
        logger.warning("bid day validation failed for %s", target_id, exc_info=True)
        return []
    return [r for r in report.results if not r.passed and not r.is_engine_error]

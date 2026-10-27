# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Quote​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ capture validation rules (rule set ``quote_capture``).

* ``quote_capture.line_arithmetic`` - ERROR. Quantity times rate is not the line total.
* ``quote_capture.total_matches_lines`` - ERROR. The stated quote total is not the sum of the lines.
* ``quote_capture.currency_matches_project`` - WARNING. The quote is in another currency than the project.
* ``quote_capture.validity_not_expired`` - WARNING. The validity date has passed.
* ``quote_capture.low_confidence_reviewed`` - ERROR. A low-confidence line has not been reviewed.
* ``quote_capture.lines_matched`` - WARNING. A line matches no BOQ position or package item.
* ``quote_capture.exclusions_acknowledged`` - ERROR. A flagged exclusion has not been acknowledged.

The rules read :func:`app.modules.quote_capture.logic.validation_snapshot`. Errors
block the confirm; warnings are shown and the reviewer decides.
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
from app.modules.quote_capture.numbers import to_decimal

logger = logging.getLogger(__name__)

RULE_SET = "quote_capture"
_TOL = Decimal("0.02")


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _lines(context: ValidationContext) -> list[dict[str, Any]]:
    rows = _data(context).get("lines")
    return [r for r in rows if isinstance(r, dict) and not r.get("ignored")] if isinstance(rows, list) else []


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


class LineArithmetic(ValidationRule):
    rule_id = "quote_capture.line_arithmetic"
    name = "Quantity Times Rate Equals The Line Total"
    standard = "custom"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Each line's quantity multiplied by its unit rate equals its total within one cent."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out: list[RuleResult] = []
        for line in _lines(context):
            qty, rate, total = (to_decimal(line.get(k)) for k in ("quantity", "unit_rate", "total"))
            if qty is None or rate is None or total is None:
                continue
            tol = max(_TOL, abs(total) * Decimal("0.0005"))
            ok = abs(qty * rate - total) <= tol
            msg = "OK" if ok else f"{line.get('description')}: {qty} x {rate} = {qty * rate}, the quote says {total}."
            out.append(_result(self, ok, msg, line.get("id"), expected=str(qty * rate), stated=str(total)))
        return out


class TotalMatchesLines(ValidationRule):
    rule_id = "quote_capture.total_matches_lines"
    name = "Quote Total Equals The Sum Of Its Lines"
    standard = "custom"
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "The stated quote total (net) equals the sum of the line totals within half a percent."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        stated = to_decimal((data.get("header") or {}).get("quote_total"))
        if stated is None:
            return []
        lines = _lines(context)
        if not lines:
            return []
        total = sum((to_decimal(ln.get("total")) or Decimal("0") for ln in lines), Decimal("0"))
        net = to_decimal(data.get("net_total")) or stated
        candidates = {stated, net}
        ok = any(abs(c - total) <= max(_TOL, abs(c) * Decimal("0.005")) for c in candidates)
        msg = "OK" if ok else f"The lines add up to {total}, the quote total is {stated}."
        return [_result(self, ok, msg, None, lines_sum=str(total), stated=str(stated))]


class CurrencyMatchesProject(ValidationRule):
    rule_id = "quote_capture.currency_matches_project"
    name = "Quote Currency Matches The Project"
    standard = "custom"
    severity = Severity.WARNING
    category = RuleCategory.CONSISTENCY
    description = "The quote is priced in the project currency; another currency needs conversion before levelling."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        cur = str((data.get("header") or {}).get("currency") or "").upper()
        proj = str(data.get("project_currency") or "").upper()
        if not cur or not proj:
            return []
        ok = cur == proj
        return [_result(self, ok, "OK" if ok else f"The quote is in {cur}, the project in {proj}.", None)]


class ValidityNotExpired(ValidationRule):
    rule_id = "quote_capture.validity_not_expired"
    name = "Quote Validity Has Not Expired"
    standard = "custom"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "The quote is still within its stated validity period."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = _data(context)
        until = str((data.get("header") or {}).get("valid_until") or "")[:10]
        today = str(data.get("today") or "")[:10]
        if not until or not today:
            return []
        ok = until >= today
        return [_result(self, ok, "OK" if ok else f"The quote was valid until {until}.", None, valid_until=until)]


class LowConfidenceReviewed(ValidationRule):
    rule_id = "quote_capture.low_confidence_reviewed"
    name = "Low-Confidence Lines Are Reviewed"
    standard = "custom"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Every line the extraction read with low confidence has been reviewed by a person."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        threshold = float(_data(context).get("low_confidence") or 0.7)
        out: list[RuleResult] = []
        for line in _lines(context):
            if float(line.get("confidence") or 0) >= threshold:
                continue
            ok = bool(line.get("reviewed"))
            msg = "OK" if ok else f"{line.get('description')} was read with low confidence and is not reviewed."
            out.append(_result(self, ok, msg, line.get("id"), confidence=line.get("confidence")))
        return out


class LinesMatched(ValidationRule):
    rule_id = "quote_capture.lines_matched"
    name = "Quote Lines Match The Scope"
    standard = "custom"
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "Each quote line matches a BOQ position or tender package item."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out: list[RuleResult] = []
        for line in _lines(context):
            match = line.get("match") or {}
            ok = bool(match.get("position_id")) and match.get("status") in {"suggested", "confirmed"}
            msg = "OK" if ok else f"{line.get('description')} matches no position of the scope."
            out.append(_result(self, ok, msg, line.get("id")))
        return out


class ExclusionsAcknowledged(ValidationRule):
    rule_id = "quote_capture.exclusions_acknowledged"
    name = "Exclusions Are Acknowledged"
    standard = "custom"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "Every exclusion or condition flagged in the quote has been read and acknowledged."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        notes = _data(context).get("notes") or []
        out: list[RuleResult] = []
        for note in notes:
            if not isinstance(note, dict) or note.get("kind") != "exclusion":
                continue
            ok = bool(note.get("acknowledged"))
            msg = "OK" if ok else f"Exclusion not acknowledged: {str(note.get('text'))[:120]}"
            out.append(_result(self, ok, msg, note.get("id")))
        return out


_RULES: tuple[ValidationRule, ...] = (
    LineArithmetic(),
    TotalMatchesLines(),
    CurrencyMatchesProject(),
    ValidityNotExpired(),
    LowConfidenceReviewed(),
    LinesMatched(),
    ExclusionsAcknowledged(),
)
RULE_IDS: tuple[str, ...] = tuple(r.rule_id for r in _RULES)


def register_quote_capture_rules() -> None:
    for rule in _RULES:
        rule_registry.register(rule, [RULE_SET])


async def evaluate(snapshot: dict[str, Any], *, target_id: str = "") -> list[RuleResult]:
    """Failed findings for one quote; an engine failure logs and returns none."""
    try:
        report = await validation_engine.validate(
            data=snapshot, rule_sets=[RULE_SET], target_type="quote_capture", target_id=target_id
        )
    except Exception:  # noqa: BLE001 - findings augment a read, never break it
        logger.warning("quote capture validation failed for %s", target_id, exc_info=True)
        return []
    return [r for r in report.results if not r.passed and not r.is_engine_error]

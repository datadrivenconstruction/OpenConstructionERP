# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Shared building blocks for the quality-module rule sets (NCR, inspections).

Both ask the same kinds of question of a record: is a field present that its
status demands, is a due or scheduled date already behind us, does a recorded
result agree with the evidence under it. Messages live in the shared bundle
under the ``quality`` section.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from app.core.validation.engine import RuleResult, Severity, ValidationContext
from app.core.validation.failure import finding, rule_failure_detail
from app.core.validation.messages import translate
from app.core.validation.money_rules import MoneyRule, locale_of


def parse_day(value: Any) -> date | None:
    """Parse an ISO date or datetime (``Z`` allowed) to a calendar day; ``None`` when absent or malformed."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def today_of(context: ValidationContext) -> date:
    """The reference day: ``metadata['today']`` when given (tests, back-dated runs), else the UTC day."""
    given = parse_day((context.metadata or {}).get("today"))
    return given or datetime.now(UTC).date()


class QualityRule(MoneyRule):
    """Base for the quality-module rules: result building from the ``quality`` message section."""

    def fail(
        self,
        context: ValidationContext,
        key: str,
        *,
        ref: str = "",
        severity: Severity | None = None,
        **params: Any,
    ) -> RuleResult:
        """A failing result whose text is ``quality.<key>`` in the caller's locale."""
        locale = locale_of(context)
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=severity or self.severity,
            category=self.category,
            passed=False,
            message=translate(f"quality.{key}.fail", locale=locale, **params),
            element_ref=ref,
            suggestion=translate(f"quality.{key}.suggestion", locale=locale),
            details={k: str(v) for k, v in params.items()},
        )


def rule_errors_detail(report: Any, message: str, errors: Any = None) -> dict[str, Any]:
    """The 422 body a gated quality write answers with."""
    return rule_failure_detail(report, error="quality_rules_failed", errors=errors, message=message)


def warning_findings(report: Any) -> list[dict[str, Any]]:
    """Non-blocking findings, in the shape a response carries them."""
    return [finding(r) for r in report.warnings]

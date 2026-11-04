# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Shared building blocks for the site-operations rule sets.

Daily diary, safety, HSE and site inventory write records that a site manager
signs and an inspector may read years later: dates that cannot lie in the
future, figures that must not contradict each other, stock that cannot go below
zero. This module holds the rule base and the write-point gate those modules
share, so each module's ``validators.py`` only says which fields to look at.

Messages live in the shared bundle under the ``site`` section; range, ordering
and currency findings reuse the ``money`` section.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status

from app.core.i18n import get_locale
from app.core.validation.engine import RuleResult, Severity, ValidationContext, validation_engine
from app.core.validation.messages import translate
from app.core.validation.money_rules import MoneyRule, locale_of

logger = logging.getLogger(__name__)

#: A site ahead of UTC may legitimately be a calendar day ahead of the server.
FUTURE_SLACK = timedelta(days=1)


def parse_instant(value: Any) -> datetime | None:
    """A datetime or ISO 8601 text as an aware UTC datetime; ``None`` when absent or unreadable."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        out = value
    elif isinstance(value, date):
        out = datetime(value.year, value.month, value.day)
    else:
        try:
            out = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return out.replace(tzinfo=UTC) if out.tzinfo is None else out.astimezone(UTC)


def is_future(value: Any, *, slack: timedelta = FUTURE_SLACK) -> bool:
    """True when ``value`` lies beyond now plus the timezone slack."""
    moment = parse_instant(value)
    return moment is not None and moment > datetime.now(UTC) + slack


class SiteRule(MoneyRule):
    """Base for the site-operations rules: results in the caller's locale."""

    def site_fail(
        self,
        context: ValidationContext,
        key: str,
        *,
        ref: str = "",
        severity: Severity | None = None,
        **params: Any,
    ) -> RuleResult:
        """A failing result whose text is ``site.<key>`` in the caller's locale."""
        locale = locale_of(context)
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=severity or self.severity,
            category=self.category,
            passed=False,
            message=translate(f"site.{key}", locale=locale, **params),
            element_ref=ref,
            suggestion=translate("site.suggestion", locale=locale),
            details={k: str(v) for k, v in params.items()},
        )

    def future_date(self, context: ValidationContext, ref: str, field: str, value: Any) -> RuleResult | None:
        """A failure when ``value`` lies in the future."""
        if not is_future(value):
            return None
        return self.site_fail(context, "future_date", ref=ref, field=field, value=value)


def _serialise(r: RuleResult) -> dict[str, Any]:
    return {
        "rule_id": r.rule_id,
        "severity": r.severity.value,
        "message": r.message,
        "element_ref": r.element_ref,
        "suggestion": r.suggestion,
    }


async def check_site_rules(
    rule_set: str,
    register: Callable[[], None],
    data: dict[str, Any],
    *,
    target_type: str,
    target_id: str = "",
    project_id: Any = None,
) -> list[RuleResult]:
    """Run one rule set at a write point.

    Errors raise a 422 whose body carries the first blocking rule id as ``code``;
    warnings are logged and returned for the caller to report, never blocking.
    """
    register()
    report = await validation_engine.validate(
        data=data,
        rule_sets=[rule_set],
        target_type=target_type,
        target_id=target_id,
        project_id=str(project_id) if project_id else None,
        metadata={"locale": get_locale()},
    )
    if report.errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "validation_failed",
                "code": report.errors[0].rule_id,
                "rule_set": rule_set,
                "message": report.errors[0].message,
                "errors": [_serialise(r) for r in report.errors],
                "warnings": [_serialise(r) for r in report.warnings],
            },
        )
    for w in report.warnings:
        logger.info("%s warning %s: %s", rule_set, w.rule_id, w.message)
    return list(report.warnings)

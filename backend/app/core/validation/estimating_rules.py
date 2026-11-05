# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Shared building blocks for the estimating-module rule sets (costs, takeoff, DWG takeoff, basis of estimate).

Messages live in the shared bundle: the generic findings (range, currency, mandatory
field) are the ``money`` and ``quality`` sections the other rule sets already use,
the estimating-specific ones are in the ``estimating`` section.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, status

from app.core.validation.engine import RuleResult, Severity, ValidationReport, rule_registry, validation_engine
from app.core.validation.failure import finding, introduced_errors, raise_rule_failure
from app.core.validation.messages import translate
from app.core.validation.money_rules import MoneyRule, locale_of

_QUALITY_KEYS = frozenset({"field_required_for_state", "overdue"})
_MONEY_KEYS = frozenset(
    {"value_in_range", "currency_present", "currency_consistent", "total_matches_lines", "status_transition"}
)

#: Upper bound for one measured quantity (m, m2, m3, pcs): beyond this a scale or unit slip is the only explanation.
MAX_MEASUREMENT = 10_000_000


class EstimatingRule(MoneyRule):
    """Base for the estimating rules: result text from the ``estimating`` section, generic keys from their own."""

    def fail(
        self,
        context: Any,
        key: str,
        *,
        ref: str = "",
        severity: Severity | None = None,
        **params: Any,
    ) -> RuleResult:
        """A failing result whose text is ``<section>.<key>`` in the caller's locale."""
        section_name = "quality" if key in _QUALITY_KEYS else "money" if key in _MONEY_KEYS else "estimating"
        locale = locale_of(context)
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=severity or self.severity,
            category=self.category,
            passed=False,
            message=translate(f"{section_name}.{key}.fail", locale=locale, **params),
            element_ref=ref,
            suggestion=translate(f"{section_name}.{key}.suggestion", locale=locale),
            details={k: str(v) for k, v in params.items()},
        )


async def gate_rules(
    rule_set: str,
    data: dict[str, Any],
    *,
    target_type: str,
    target_id: str,
    project_id: str | None,
    operation: str,
    before: dict[str, Any] | None = None,
    warn_only: bool = False,
    register: Callable[[], None] | None = None,
) -> ValidationReport:
    """Run a rule set over the record as it will be stored; ERROR findings answer a coded 422.

    WARNING findings never block: the caller attaches them to the response. With ``before``
    (the stored state of an edited record) only errors the edit introduces block, so a record
    saved before the rules existed stays editable. ``warn_only`` is for records the platform
    creates itself (imports, detectors): the errors are returned as warnings and nothing is refused.
    ``register`` loads the rule set when the module startup hook did not run (scripts, service-level tests).
    """
    if register is not None and not rule_registry.has_rules(rule_set):
        register()
    from app.core.i18n import get_locale  # noqa: PLC0415

    metadata = {"locale": get_locale(), "operation": operation}

    async def _run(payload: dict[str, Any]) -> ValidationReport:
        return await validation_engine.validate(
            data=payload,
            rule_sets=[rule_set],
            target_type=target_type,
            target_id=target_id,
            project_id=project_id,
            metadata=metadata,
        )

    report = await _run(data)
    if rule_set in report.unsupported_rule_sets:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"The '{rule_set}' validation rules are not loaded on this deployment.",
        )
    blocking = await introduced_errors(report, (lambda: _run(before)) if before is not None else None)
    if blocking and warn_only:
        return report
    raise_rule_failure(
        report,
        blocking[:50],
        error=f"{rule_set}_rules_failed",
        message=f"This record cannot be saved ({operation}) until the errors listed below are corrected.",
    )
    return report


def all_findings(report: ValidationReport) -> list[dict[str, Any]]:
    """Every finding a ``warn_only`` gate saw (errors included), in the response shape of a warning."""
    return [finding(r) for r in [*report.errors, *report.warnings]]

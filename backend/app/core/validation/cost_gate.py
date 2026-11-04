# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Run a module's rule set at a write point: errors block with a coded 422, warnings are reported."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.core.i18n import get_locale
from app.core.validation.engine import RuleResult, ValidationReport, validation_engine


def finding(result: RuleResult) -> dict[str, Any]:
    """One failed rule result as a plain dict for an API body."""
    return {
        "rule_id": result.rule_id,
        "severity": result.severity.value,
        "message": result.message,
        "suggestion": result.suggestion,
        "element_ref": result.element_ref,
    }


async def run_rule_set(
    rule_set: str,
    data: dict[str, Any],
    *,
    target_type: str,
    target_id: str,
    project_id: str | None = None,
) -> ValidationReport:
    """Validate ``data`` against one rule set in the caller's language."""
    return await validation_engine.validate(
        data=data,
        rule_sets=[rule_set],
        target_type=target_type,
        target_id=target_id,
        project_id=project_id,
        metadata={"locale": get_locale()},
    )


def warnings_of(report: ValidationReport) -> list[dict[str, Any]]:
    """The non-blocking findings of a report."""
    return [finding(r) for r in report.warnings]


def raise_on_errors(report: ValidationReport, *, error: str) -> None:
    """Raise 422 whose ``code`` is the first failing rule id; no-op when nothing blocks.

    ``error`` is the module's stable error name, e.g. ``assemblies_rules_failed``.
    """
    errors = report.errors
    if not errors:
        return
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "error": error,
            "code": errors[0].rule_id,
            "message": errors[0].message,
            "errors": [finding(r) for r in errors],
            "warnings": warnings_of(report),
        },
    )

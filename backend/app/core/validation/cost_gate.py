# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Run a module's rule set at a write point: errors block with a coded 422, warnings are reported."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.core.i18n import get_locale
from app.core.validation.engine import ValidationReport, validation_engine
from app.core.validation.failure import finding, introduced_errors, raise_rule_failure


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
    raise_rule_failure(report, error=error)


async def raise_on_introduced(
    report: ValidationReport,
    before: Callable[[], Awaitable[ValidationReport]] | None,
    *,
    error: str,
) -> None:
    """Like :func:`raise_on_errors`, but an edit is blocked only by errors it introduces."""
    raise_rule_failure(report, await introduced_errors(report, before), error=error)

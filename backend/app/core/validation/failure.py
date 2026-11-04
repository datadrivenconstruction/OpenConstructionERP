# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The one 422 body every rule gate answers with, and the "only what the edit introduces" filter.

Body: ``error`` (the module's stable name), ``code`` (first blocking rule id), ``message``,
``rule_set`` / ``rule_sets``, ``status``, ``results`` (every finding) plus ``errors`` and
``warnings`` split out. Each finding carries ``rule_id``, ``code``, ``message`` and ``params``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from fastapi import HTTPException, status

from app.core.validation.engine import RuleResult, ValidationReport


def finding(r: RuleResult) -> dict[str, Any]:
    """One rule result as a plain dict for an API body."""
    return {
        "rule_id": r.rule_id,
        "code": r.rule_id,
        "rule_name": r.rule_name,
        "severity": r.severity.value,
        "message": r.message,
        "params": dict(r.details or {}),
        "element_ref": r.element_ref,
        "suggestion": r.suggestion,
    }


def heads_of(errors: Sequence[RuleResult], limit: int = 3) -> str:
    """The first messages of ``errors`` joined for the body's ``message``."""
    heads = "; ".join(r.message for r in errors[:limit])
    more = len(errors) - limit
    return f"{heads} (+{more})" if more > 0 else heads


def rule_failure_detail(
    report: ValidationReport,
    *,
    error: str,
    errors: Sequence[RuleResult] | None = None,
    warnings: Sequence[RuleResult] | None = None,
    message: str | None = None,
    rule_set: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build the 422 detail for ``errors`` (default: every error of ``report``)."""
    errors = list(report.errors if errors is None else errors)
    warnings = list(report.warnings if warnings is None else warnings)
    detail: dict[str, Any] = {
        "error": error,
        "code": errors[0].rule_id if errors else error,
        "message": message or heads_of(errors),
        "rule_set": rule_set or (report.rule_sets_applied[0] if report.rule_sets_applied else None),
        "rule_sets": list(report.rule_sets_applied),
        "status": report.status.value,
        "results": [finding(r) for r in [*errors, *warnings]],
        "errors": [finding(r) for r in errors],
        "warnings": [finding(r) for r in warnings],
    }
    detail.update(extra)
    return detail


def raise_rule_failure(report: ValidationReport, errors: Sequence[RuleResult] | None = None, **kwargs: Any) -> None:
    """Raise the coded 422 when there is anything to block on; no-op otherwise."""
    if report.errors if errors is None else errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=rule_failure_detail(report, errors=errors, **kwargs),
        )


async def introduced_errors(
    report: ValidationReport,
    before: Callable[[], Awaitable[ValidationReport]] | None,
) -> list[RuleResult]:
    """Errors of ``report`` that the edit introduces.

    A record saved before the rules existed is not frozen: with ``before`` (a thunk running the rules
    over the stored record) an error the stored record already had does not block the edit.
    """
    blocking = list(report.errors)
    if blocking and before is not None:
        legacy = {(r.rule_id, r.message) for r in (await before()).errors}
        blocking = [r for r in blocking if (r.rule_id, r.message) not in legacy]
    return blocking

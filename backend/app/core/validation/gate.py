# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Run a rule set at a service write point.

Errors block the write with a coded 422, warnings are returned for the caller to
report. The 422 body carries the rule id of the first error as ``code`` so a
client can branch on it, the full list under ``errors`` and the warnings under
``warnings``; messages are in the request locale.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.core.i18n import get_locale
from app.core.validation.engine import RuleResult, validation_engine


def _row(r: RuleResult) -> dict[str, Any]:
    return {
        "code": r.rule_id,
        "severity": r.severity.value,
        "message": r.message,
        "suggestion": r.suggestion,
        "element_ref": r.element_ref or None,
    }


async def run_gate(
    data: dict[str, Any], rule_set: str, *, target_type: str, target_id: str = ""
) -> list[dict[str, Any]]:
    """Validate ``data`` against ``rule_set``; raise 422 on errors, return the warnings."""
    report = await validation_engine.validate(
        data=data,
        rule_sets=[rule_set],
        target_type=target_type,
        target_id=target_id,
        metadata={"locale": get_locale()},
    )
    errors = [r for r in report.errors if not r.is_engine_error]
    if errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": "validation_failed",
                "code": errors[0].rule_id,
                "message": "; ".join(r.message for r in errors[:3]),
                "rule_set": rule_set,
                "errors": [_row(r) for r in errors],
                "warnings": [_row(r) for r in report.warnings],
            },
        )
    return [_row(r) for r in report.warnings]

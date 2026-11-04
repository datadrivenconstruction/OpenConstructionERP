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

from app.core.i18n import get_locale
from app.core.validation.engine import validation_engine
from app.core.validation.failure import finding, introduced_errors, raise_rule_failure


async def run_gate(
    data: dict[str, Any],
    rule_set: str,
    *,
    target_type: str,
    target_id: str = "",
    before: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Validate ``data`` against ``rule_set``; raise 422 on errors, return the warnings.

    With ``before`` (the stored record) only errors the edit introduces block.
    """

    async def run(payload: dict[str, Any]) -> Any:
        return await validation_engine.validate(
            data=payload,
            rule_sets=[rule_set],
            target_type=target_type,
            target_id=target_id,
            metadata={"locale": get_locale()},
        )

    report = await run(data)

    async def stored() -> Any:
        return await run(before or {})

    errors = await introduced_errors(report, stored if before is not None else None)
    raise_rule_failure(report, errors, error="validation_failed", rule_set=rule_set)
    return [finding(r) for r in report.warnings]

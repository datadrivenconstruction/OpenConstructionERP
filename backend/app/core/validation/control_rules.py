# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rule base and write gate for the site-control modules (tasks, MoC, risk, progress).

Rules read a plain dict built by the service at the write point and judge the
record as it will be after the write. Errors stop the write with a coded 422,
warnings travel back on the response and never block. A record that has not
reached the stage a rule speaks about (a draft, a half-filled form) passes it.

Messages live in the shared bundle: the ``control`` section for this family,
and the ``money`` section for the generic keys (range, currency, total).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date
from typing import Any

from app.core.i18n import get_locale
from app.core.validation.engine import RuleResult, ValidationReport, validation_engine
from app.core.validation.failure import finding, introduced_errors, raise_rule_failure
from app.core.validation.money_rules import MoneyRule

logger = logging.getLogger(__name__)

#: Keys that live in the generic ``money`` section and are reused as they are.
SHARED_KEYS = frozenset(
    {
        "total_matches_lines",
        "value_in_range",
        "currency_present",
        "currency_consistent",
        "reference_present",
        "status_transition",
        "dates_ordered",
    }
)


def parse_day(value: Any) -> date | None:
    """A calendar date from ``YYYY-MM-DD`` (a longer ISO stamp is cut to its day); ``None`` otherwise."""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


class ControlRule(MoneyRule):
    """Base for the control-module rules; generic keys resolve to the ``money`` section."""

    message_section = "control"

    def fail(self, context: Any, key: str, **kwargs: Any) -> RuleResult:
        """A failing result; shared keys read from ``money``, the rest from ``control``."""
        if key in SHARED_KEYS and "section" not in kwargs:
            kwargs["section"] = "money"
        return super().fail(context, key, **kwargs)


async def gate(
    rule_set: str,
    data: dict[str, Any],
    *,
    target_type: str,
    target_id: str,
    project_id: Any = None,
    only: Iterable[str] | None = None,
    before: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run ``rule_set`` over ``data``; raise a coded 422 on errors, return the warnings.

    ``only`` limits the run to rules whose id is listed, for write points that
    touch one part of a record. The 422 body carries ``code`` (the first
    blocking rule id) next to every error and warning, so a screen can render
    them and a client can branch on the code. With ``before`` (the stored record) only
    errors the edit introduces block.
    """

    async def run(payload: dict[str, Any]) -> ValidationReport:
        return await validation_engine.validate(
            data=payload,
            rule_sets=[rule_set],
            target_type=target_type,
            target_id=target_id,
            project_id=str(project_id) if project_id else None,
            metadata={"locale": get_locale()},
        )

    report = await run(data)
    if rule_set in report.unsupported_rule_sets:
        logger.error("validation: rule set %s is not registered; %s write unchecked", rule_set, target_type)
        return []
    keep = set(only) if only is not None else None

    async def stored() -> ValidationReport:
        return await run(before or {})

    errors = [
        r
        for r in await introduced_errors(report, stored if before is not None else None)
        if keep is None or r.rule_id in keep
    ]
    warnings = [r for r in report.warnings if keep is None or r.rule_id in keep]
    if errors:
        raise_rule_failure(report, errors, warnings=warnings, error="validation_failed", rule_set=rule_set)
    return [finding(r) for r in warnings]

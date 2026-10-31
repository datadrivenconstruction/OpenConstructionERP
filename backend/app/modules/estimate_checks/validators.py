# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Estimate check validation rules (rule set ``estimate_checks``).

One rule per KPI (``estimate_checks.<kpi_id>``). Each rule compares the estimate's
KPI with the usual range of comparable past estimates and returns one result:
passed for Normal, WARNING severity for a Warning, INFO for a Suspect. The rating
details (value, range, comparables, confidence, positions) ride in ``details``.

Rules read ``context.data`` = ``{"kpis": {kpi_id: KpiValue}, "positions": int}``
and ``context.metadata`` = ``{"history": [...], "settings": {...}}``; the service
builds both, so the rules stay pure and cheap.
"""

from __future__ import annotations

import logging
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
from app.modules.estimate_checks.kpis import (
    KPI_DEFS,
    STATUS_NO_DATA,
    STATUS_NORMAL,
    STATUS_WARNING,
    KpiDef,
    assess,
    merge_settings,
)

logger = logging.getLogger(__name__)

RULE_SET = "estimate_checks"


class EstimateKpiRule(ValidationRule):
    """Rates one estimate KPI against comparable past estimates."""

    standard = "universal"
    severity = Severity.WARNING

    def __init__(self, kdef: KpiDef) -> None:
        self.kdef = kdef
        self.rule_id = f"{RULE_SET}.{kdef.kpi_id}"
        self.name = kdef.kpi_id.replace("_", " ").capitalize()
        self.category = RuleCategory.COMPLETENESS if kdef.group == "data_quality" else RuleCategory.QUALITY
        self.description = f"Estimate check KPI {kdef.kpi_id} ({kdef.group})."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data if isinstance(context.data, dict) else {}
        meta = context.metadata or {}
        settings = meta.get("settings") or merge_settings(None)
        if not settings["kpis"].get(self.kdef.kpi_id, {}).get("enabled", True):
            return []
        kv = (data.get("kpis") or {}).get(self.kdef.kpi_id)
        if kv is None:
            return []
        rating = assess(kv, meta.get("history") or [], settings, int(data.get("positions") or 0))
        status = rating["status"]
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=Severity.WARNING if status == STATUS_WARNING else Severity.INFO,
                category=self.category,
                passed=status in (STATUS_NORMAL, STATUS_NO_DATA),
                message=rating["reason"],
                element_ref=None,
                details=rating,
            )
        ]


_RULES: tuple[EstimateKpiRule, ...] = tuple(EstimateKpiRule(k) for k in KPI_DEFS)
RULE_IDS = tuple(r.rule_id for r in _RULES)


def register_estimate_check_rules() -> None:
    """Register the rules with the core registry (idempotent)."""
    for rule in _RULES:
        rule_registry.register(rule, [RULE_SET])


async def evaluate(data: dict[str, Any], metadata: dict[str, Any], *, target_id: str = "") -> list[dict[str, Any]]:
    """Run the rule set and return one rating dict per enabled KPI."""
    register_estimate_check_rules()
    report = await validation_engine.validate(
        data=data, rule_sets=[RULE_SET], target_type="estimate_check", target_id=target_id, metadata=metadata
    )
    out = []
    for r in report.results:
        if r.is_engine_error:
            logger.warning("estimate check rule %s failed for %s", r.rule_id, target_id)
            continue
        out.append(r.details)
    return out


__all__ = ["RULE_IDS", "RULE_SET", "evaluate", "register_estimate_check_rules"]

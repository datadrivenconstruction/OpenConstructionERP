# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost-type rules, rule set ``cost_types``.

* ``cost_types.position_unsplit``: a budget line generated from a bill position
  that had no resources, so its whole total went to ``other``.
* ``cost_types.unknown_type``: a budget line whose category is outside the
  shared vocabulary (an older free-text category), so it reports under no cost
  type.

Both are warnings. Each rule reads ``context.data["cost_types"]["lines"]``, a
list of dicts with ``line_id``, ``label``, ``category`` and ``split_basis``, and
is silent on any other payload. The cost-type grid runs the set on every read.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.cost_types import is_budget_category
from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.core.validation.messages import DEFAULT_LOCALE, translate

logger = logging.getLogger(__name__)

RULE_SET = "cost_types"
PAYLOAD_KEY = "cost_types"
SPLIT_BASIS_NO_RESOURCES = "no_resources"


class _CostTypeRule(ValidationRule):
    standard = "universal"
    severity = Severity.WARNING

    def flagged(self, line: dict[str, Any]) -> bool:
        raise NotImplementedError

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data
        payload = data.get(PAYLOAD_KEY) if isinstance(data, dict) else None
        if not isinstance(payload, dict):
            return []
        meta = getattr(context, "metadata", None)
        locale = meta.get("locale") if isinstance(meta, dict) and meta.get("locale") else DEFAULT_LOCALE
        out: list[RuleResult] = []
        for line in payload.get("lines") or []:
            if not isinstance(line, dict) or not self.flagged(line):
                continue
            params = {"line": str(line.get("label") or ""), "category": str(line.get("category") or "")}
            out.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=translate(f"{self.rule_id}.fail", locale, **params),
                    element_ref=str(line.get("line_id") or ""),
                    details=params,
                    suggestion=translate(f"{self.rule_id}.suggestion", locale, **params),
                )
            )
        return out or [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=True,
                message="",
            )
        ]


class PositionUnsplitRule(_CostTypeRule):
    rule_id = "cost_types.position_unsplit"
    name = "Bill position without resources"
    description = "A budget line from a bill position with no resources went to 'other' whole."
    category = RuleCategory.COMPLETENESS

    def flagged(self, line: dict[str, Any]) -> bool:
        return line.get("split_basis") == SPLIT_BASIS_NO_RESOURCES


class UnknownTypeRule(_CostTypeRule):
    rule_id = "cost_types.unknown_type"
    name = "Budget line without a known cost type"
    description = "A budget line whose category is outside labour, material, equipment, subcontract and other."
    category = RuleCategory.CONSISTENCY

    def flagged(self, line: dict[str, Any]) -> bool:
        return not is_budget_category(line.get("category"))


COST_TYPE_RULES: tuple[type[_CostTypeRule], ...] = (PositionUnsplitRule, UnknownTypeRule)


def register_cost_type_rules() -> None:
    """Register the two rules into the ``cost_types`` rule set."""
    for rule_cls in COST_TYPE_RULES:
        rule_registry.register(rule_cls(), [RULE_SET])
    logger.debug("Registered cost type validation rules")

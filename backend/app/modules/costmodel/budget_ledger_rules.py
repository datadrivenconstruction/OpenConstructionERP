# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Budget ledger rules, rule set ``budget_ledger``.

* ``budget_ledger.net_zero``: a transfer has at least two legs, no zero leg, and its legs add up to zero.
* ``budget_ledger.below_committed``: a transfer or modification would take a line's budget below what is
  already committed on it.
* ``budget_ledger.approved_immutable``: an approved or rejected entry is edited or deleted.

Each rule reads ``context.data["budget_ledger"]`` and is silent on any other payload.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from app.core.currency_registry import sentence_amount
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

RULE_SET = "budget_ledger"
PAYLOAD_KEY = "budget_ledger"


def _money(value: object) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return Decimal("0")


class _LedgerRule(ValidationRule):
    standard = "universal"
    category = RuleCategory.CONSISTENCY
    severity = Severity.ERROR

    def _fail(self, context: ValidationContext, key: str, *, element_ref: str | None, **params: str) -> RuleResult:
        meta = getattr(context, "metadata", None)
        locale = meta.get("locale") if isinstance(meta, dict) and meta.get("locale") else DEFAULT_LOCALE
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=False,
            message=translate(f"budget_ledger.{key}.fail", locale, **params),
            element_ref=element_ref,
            details={"problem": key, **params},
            suggestion=translate(f"budget_ledger.{key}.suggestion", locale, **params),
        )

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        raise NotImplementedError

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data
        payload = data.get(PAYLOAD_KEY) if isinstance(data, dict) else None
        if not isinstance(payload, dict):
            return []
        found = self.check(context, payload)
        return found or [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=self.severity,
                category=self.category,
                passed=True,
                message="",
            )
        ]


class NetZeroRule(_LedgerRule):
    rule_id = "budget_ledger.net_zero"
    name = "Transfer nets to zero"
    description = "The legs of a budget transfer add up to zero, on two or more lines."

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        if payload.get("kind") != "transfer" or payload.get("guard") or payload.get("action") == "delete":
            return []
        legs = payload.get("legs") or []
        total = sum((_money(leg.get("amount")) for leg in legs), Decimal("0"))
        lines = {str(leg.get("cost_line_id")) for leg in legs}
        if len(legs) >= 2 and len(lines) == len(legs) and total == 0 and all(_money(g.get("amount")) for g in legs):
            return []
        ccy = str(payload.get("currency") or "")
        return [self._fail(context, "net_zero", element_ref=None, difference=sentence_amount(total, ccy))]


class BelowCommittedRule(_LedgerRule):
    rule_id = "budget_ledger.below_committed"
    name = "Budget below committed"
    description = "A reduction would leave a cost line with less budget than is already committed on it."

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        if payload.get("guard") or payload.get("action") == "delete":
            return []
        ccy = str(payload.get("currency") or "")
        out: list[RuleResult] = []
        for leg in payload.get("legs") or []:
            amount = _money(leg.get("amount"))
            after = _money(leg.get("budget")) + amount
            committed = _money(leg.get("committed"))
            if amount < 0 and after < committed:
                out.append(
                    self._fail(
                        context,
                        "below_committed",
                        element_ref=str(leg.get("cost_line_id") or ""),
                        line=str(leg.get("code") or ""),
                        budget=sentence_amount(after, ccy),
                        committed=sentence_amount(committed, ccy),
                    )
                )
        return out


class ApprovedImmutableRule(_LedgerRule):
    rule_id = "budget_ledger.approved_immutable"
    name = "Approved entry is final"
    description = "An approved or rejected transfer or modification is never edited or deleted."

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        if payload.get("action") in ("edit", "delete") and payload.get("status") in ("approved", "rejected"):
            return [
                self._fail(
                    context,
                    "approved_immutable",
                    element_ref=str(payload.get("code") or ""),
                    code=str(payload.get("code") or ""),
                    status=str(payload.get("status")),
                )
            ]
        return []


LEDGER_RULES: tuple[type[_LedgerRule], ...] = (NetZeroRule, BelowCommittedRule, ApprovedImmutableRule)


def register_budget_ledger_rules() -> None:
    """Register the three rules into the ``budget_ledger`` rule set."""
    for rule_cls in LEDGER_RULES:
        rule_registry.register(rule_cls(), [RULE_SET])
    logger.debug("Registered budget ledger validation rules")

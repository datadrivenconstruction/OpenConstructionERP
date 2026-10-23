# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The ``pakistan`` rule set: a Pakistani bill read for the sales tax it charges.

A construction service in Pakistan is taxed by the province, not by the
federation, and the rate differs by province and by who pays: Punjab 16 percent,
Sindh and Khyber Pakhtunkhwa 15 percent, and lower rates for government civil
works. The federal sales tax on goods is 18 percent. The bill can answer two
questions without any schedule of rates:

* ``pakistan.sales_tax_line_present`` - a bill that carries markups also carries
  a sales tax line of its own.
* ``pakistan.sales_tax_rate_known`` - that line charges one of the rates the pack
  has read (see ``KNOWN_SALES_TAX_RATES``), so a typing slip such as 61 instead
  of 16 is caught. It does not say which rate is right for the province; the
  person confirming the bill does.

The markup lines are read from ``data["markups"]``. A bill without markups is a
bill of direct costs and both rules stay silent on it.

A third rule reads the positions, so it also runs at contract signature where no
markup lines exist:

* ``pakistan.item_classified`` - each priced line carries a classification code,
  so its quantity rolls up under the work item class the provincial schedules of
  rates group by. Practice rather than statute.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
)
from app.core.validation.messages import translate
from app.core.validation.rules import _get_locale, _ok

PAKISTAN_RULE_SET = "pakistan"

#: Sales tax rates in percent that the pack has read for construction: federal
#: goods 18; Punjab 16 (government civil works 5, legacy 1 and 0); Sindh and
#: Khyber Pakhtunkhwa 15; Khyber Pakhtunkhwa government-funded works 4 (legacy
#: 2). Sources and review status are in the pack's ``pakistan_tax`` rule pack.
KNOWN_SALES_TAX_RATES: frozenset[Decimal] = frozenset(Decimal(r) for r in ("0", "1", "2", "4", "5", "15", "16", "18"))

_TAX_RE = re.compile(
    r"sales\s+tax|\bgst\b|\bpra\b|\bsrb\b|\bkpra\b|\bbra\b|services\s+tax",
    re.IGNORECASE,
)


def _markups(context: ValidationContext) -> list[dict[str, Any]]:
    data = context.data
    markups = data.get("markups") if isinstance(data, dict) else None
    if not isinstance(markups, list):
        return []
    return [m for m in markups if isinstance(m, dict) and m.get("is_active", True)]


def _tax_lines(markups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m for m in markups if m.get("category") == "tax" or _TAX_RE.search(str(m.get("name") or ""))]


def _percent(markup: dict[str, Any]) -> Decimal | None:
    try:
        return Decimal(str(markup.get("percentage")))
    except (InvalidOperation, ValueError):
        return None


class _PakistanRule(ValidationRule):
    standard = PAKISTAN_RULE_SET
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE

    def _result(self, context: ValidationContext, passed: bool, key: str, **params: Any) -> RuleResult:
        locale = _get_locale(context)
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message=_ok(locale) if passed else translate(f"pakistan.{key}.fail", locale=locale, **params),
            suggestion=None if passed else translate(f"pakistan.{key}.suggestion", locale=locale),
        )


class PakistanItemClassified(_PakistanRule):
    rule_id = "pakistan.item_classified"
    name = "Item Classified"
    description = "Each priced line carries a classification code, so it can be grouped by work item class"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data
        positions = data.get("positions") if isinstance(data, dict) else None
        if not isinstance(positions, list):
            return []
        parent_ids = {str(p["parent_id"]) for p in positions if isinstance(p, dict) and p.get("parent_id")}
        results: list[RuleResult] = []
        for pos in positions:
            if not isinstance(pos, dict) or pos.get("type") == "section" or str(pos.get("id")) in parent_ids:
                continue
            classification = pos.get("classification")
            coded = isinstance(classification, dict) and any(str(v).strip() for v in classification.values())
            results.append(self._result(context, coded, "item_classified", ordinal=str(pos.get("ordinal") or "")))
        return results


class PakistanSalesTaxLinePresent(_PakistanRule):
    rule_id = "pakistan.sales_tax_line_present"
    name = "Sales Tax Line Present"
    description = "A Pakistani bill shows the sales tax (federal GST or provincial services tax) as a line of its own"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        markups = _markups(context)
        if not markups:
            return []
        return [self._result(context, bool(_tax_lines(markups)), "sales_tax_line_present")]


class PakistanSalesTaxRateKnown(_PakistanRule):
    rule_id = "pakistan.sales_tax_rate_known"
    name = "Sales Tax Rate Is A Known Rate"
    description = "The sales tax line charges a rate that federal or provincial law sets for construction"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for line in _tax_lines(_markups(context)):
            percent = _percent(line)
            passed = percent in KNOWN_SALES_TAX_RATES
            results.append(self._result(context, passed, "sales_tax_rate_known", percent=str(line.get("percentage"))))
        return results


PAKISTAN_RULES: tuple[type[ValidationRule], ...] = (
    PakistanItemClassified,
    PakistanSalesTaxLinePresent,
    PakistanSalesTaxRateKnown,
)

__all__ = ["KNOWN_SALES_TAX_RATES", "PAKISTAN_RULES", "PAKISTAN_RULE_SET"]

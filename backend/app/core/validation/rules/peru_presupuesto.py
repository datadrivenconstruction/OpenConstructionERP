# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The ``peru`` rule set: a Peruvian budget (presupuesto de obra) read for its tax and its two statutory lines.

A Peruvian presupuesto shows the direct cost, then the gastos generales and the
utilidad, a subtotal, the IGV and the total. Three checks the bill can answer
without any price list:

* ``peru.igv_line_present`` - the bill carries an IGV line at all.
* ``peru.igv_rate_18`` - that line charges 18 percent, being 16 percent IGV and
  2 percent municipal promotion tax (Ley 29666; unconfirmed in the pack notes).
* ``peru.gastos_generales_utilidad_stated`` - gastos generales and utilidad are
  each a line of their own, because a public tender states them separately.

The markup lines are read from ``data["markups"]``, the way the Italian rules
read them. A bill without markups at all is a bill of direct costs and the
three rules stay silent on it rather than flagging a work in progress.
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

PERU_RULE_SET = "peru"

#: Statutory IGV rate in percent: 16 IGV plus 2 municipal promotion tax.
IGV_PERCENT = Decimal("18")

_IGV_RE = re.compile(r"\bigv\b|impuesto\s+general\s+a\s+las\s+ventas", re.IGNORECASE)
_GG_RE = re.compile(r"gastos\s+generales|general\s+(?:expenses|overheads?)", re.IGNORECASE)
_PROFIT_RE = re.compile(r"\butilidad(?:es)?\b|\bprofit\b", re.IGNORECASE)


def _markups(context: ValidationContext) -> list[dict[str, Any]]:
    data = context.data
    markups = data.get("markups") if isinstance(data, dict) else None
    if not isinstance(markups, list):
        return []
    return [m for m in markups if isinstance(m, dict) and m.get("is_active", True)]


def _igv_lines(markups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [m for m in markups if _IGV_RE.search(str(m.get("name") or ""))]


def _percent(markup: dict[str, Any]) -> Decimal | None:
    try:
        return Decimal(str(markup.get("percentage")))
    except (InvalidOperation, ValueError):
        return None


class _PeruRule(ValidationRule):
    standard = PERU_RULE_SET
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
            message=_ok(locale) if passed else translate(f"peru.{key}.fail", locale=locale, **params),
            suggestion=None if passed else translate(f"peru.{key}.suggestion", locale=locale),
        )


class PeruIgvLinePresent(_PeruRule):
    rule_id = "peru.igv_line_present"
    name = "IGV Line Present"
    description = "A Peruvian budget shows the IGV as a line of its own"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        markups = _markups(context)
        if not markups:
            return []
        return [self._result(context, bool(_igv_lines(markups)), "igv_line_present")]


class PeruIgvRate18(_PeruRule):
    rule_id = "peru.igv_rate_18"
    name = "IGV At 18 Percent"
    description = "The IGV line charges 18 percent (16 percent IGV plus 2 percent municipal promotion tax)"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results: list[RuleResult] = []
        for line in _igv_lines(_markups(context)):
            percent = _percent(line)
            passed = percent == IGV_PERCENT
            results.append(self._result(context, passed, "igv_rate_18", percent=str(line.get("percentage"))))
        return results


class PeruGastosGeneralesUtilidadStated(_PeruRule):
    rule_id = "peru.gastos_generales_utilidad_stated"
    name = "Gastos Generales And Utilidad Stated"
    description = "Gastos generales and utilidad are each carried as a line of their own"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        markups = _markups(context)
        if not markups:
            return []
        names = [str(m.get("name") or "") for m in markups]
        missing = [
            label
            for label, pattern in (("gastos generales", _GG_RE), ("utilidad", _PROFIT_RE))
            if not any(pattern.search(name) for name in names)
        ]
        return [
            self._result(
                context,
                not missing,
                "gastos_generales_utilidad_stated",
                missing=", ".join(missing),
            )
        ]


_PARTIDA_RE = re.compile(r"^\d{2}(?:\.\d{2})+$")


class PeruPartidaNumbering(_PeruRule):
    """A priced line is numbered chapter.item, the way a presupuesto lists its partidas.

    Practice rather than statute: it is the numbering every Peruvian budget and
    tender bill uses, and it reads the positions, so it also runs at contract
    signature where no markup lines exist.
    """

    rule_id = "peru.partida_numbering"
    name = "Partida Numbering"
    description = "Each priced line is numbered by chapter and item, two digits per level"

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
            ordinal = str(pos.get("ordinal") or "").strip()
            results.append(
                self._result(context, bool(_PARTIDA_RE.match(ordinal)), "partida_numbering", ordinal=ordinal)
            )
        return results


PERU_RULES: tuple[type[ValidationRule], ...] = (
    PeruPartidaNumbering,
    PeruIgvLinePresent,
    PeruIgvRate18,
    PeruGastosGeneralesUtilidadStated,
)

__all__ = ["IGV_PERCENT", "PERU_RULES", "PERU_RULE_SET"]

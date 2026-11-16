# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rule set ``framework_agreement``: an order checked against its agreement.

The service builds one plain payload per check (see :func:`build_payload` callers in
``service.py``) and every rule reads only its own part of it, so a rule never queries the
database and the same payload drives the order modal, the agreement overview and the API.

Payload keys (all optional; a rule whose part is missing returns nothing):

* ``agreement``: ``code``, ``currency``, ``start_date``, ``end_date``, ``term_limit``
  (``{"years", "source"}``) and ``term_years``
* ``order``: ``order_no``, ``ordered_at``, ``currency``, ``lines`` (``code``, ``in_agreement``,
  ``unit_rate``, ``expected_rate``, ``quantity``, ``measured_qty``)
* ``cap``: ``cap``, ``total_after``, ``headroom_before``, ``pct_after``, ``exceeded``,
  ``threshold_reached``
* ``rate_period``: ``covered``, ``date``; ``escalation_unresolved``: ``[{"series", "period"}]``
* ``items_over_max``, ``duplicates``, ``unknown_tags``, ``min_risk``, ``direct_claim``

Error rules block issuing an order; warnings inform. The ids map one to one onto the
``FWK_*`` codes of the domain spec, which the result carries in ``details["code"]``.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
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
from app.core.validation.messages import translate

RULE_SET = "framework_agreement"


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _money(value: Any, currency: str) -> str:
    return sentence_amount(_dec(value), currency)


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _currency(data: dict[str, Any]) -> str:
    return str((data.get("agreement") or {}).get("currency") or "")


class _FrameworkRule(ValidationRule):
    """Shared shape: subclasses yield ``(element_ref, params)`` for each failure."""

    code = ""
    key = ""
    standard = RULE_SET

    def findings(self, data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:  # pragma: no cover - abstract
        raise NotImplementedError

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        locale = str((context.metadata or {}).get("locale") or "en")
        out: list[RuleResult] = []
        for ref, params in self.findings(_data(context)):
            out.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=False,
                    message=translate(f"{RULE_SET}.{self.key}.fail", locale=locale, **params),
                    element_ref=ref,
                    details={**{f"param_{k}": str(v) for k, v in params.items()}, "code": self.code},
                    suggestion=translate(f"{RULE_SET}.{self.key}.suggestion", locale=locale),
                )
            )
        return out


def _rule(code: str, key: str, severity: Severity, category: RuleCategory, name: str) -> type[_FrameworkRule]:
    """Decorator stamping the class attributes every framework rule shares."""

    def wrap(cls: type[_FrameworkRule]) -> type[_FrameworkRule]:
        cls.code = code
        cls.key = key
        cls.rule_id = f"{RULE_SET}.{key}"
        cls.name = name
        cls.severity = severity
        cls.category = category
        cls.description = name
        return cls

    return wrap  # type: ignore[return-value]


def _lines(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [ln for ln in ((data.get("order") or {}).get("lines") or []) if isinstance(ln, dict)]


@_rule(
    "FWK_ITEM_NOT_IN_AGREEMENT",
    "item_not_in_agreement",
    Severity.ERROR,
    RuleCategory.CONSISTENCY,
    "Order line is an agreement item",
)
class ItemNotInAgreement(_FrameworkRule):
    def findings(self, data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        agreement = str((data.get("agreement") or {}).get("code") or "")
        return [
            (str(ln.get("code")), {"code": ln.get("code"), "agreement": agreement})
            for ln in _lines(data)
            if ln.get("in_agreement") is False
        ]


@_rule(
    "FWK_RATE_DEVIATES",
    "rate_deviates",
    Severity.ERROR,
    RuleCategory.CONSISTENCY,
    "Order rate equals the agreement rate",
)
class RateDeviates(_FrameworkRule):
    def findings(self, data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        cur = _currency(data)
        out = []
        for ln in _lines(data):
            if ln.get("in_agreement") is False or ln.get("expected_rate") in (None, ""):
                continue
            if abs(_dec(ln.get("unit_rate")) - _dec(ln.get("expected_rate"))) >= Decimal("0.005"):
                out.append(
                    (
                        str(ln.get("code")),
                        {
                            "code": ln.get("code"),
                            "rate": _money(ln.get("unit_rate"), cur),
                            "expected": _money(ln.get("expected_rate"), cur),
                        },
                    )
                )
        return out


@_rule(
    "FWK_ORDER_OUTSIDE_VALIDITY",
    "order_outside_validity",
    Severity.ERROR,
    RuleCategory.COMPLIANCE,
    "Order date inside the agreement term",
)
class OrderOutsideValidity(_FrameworkRule):
    def findings(self, data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        agr, order = data.get("agreement") or {}, data.get("order") or {}
        when, start, end = order.get("ordered_at"), agr.get("start_date"), agr.get("end_date")
        if not when or not start or not end:
            return []
        if str(start) <= str(when) <= str(end):
            return []
        return [(str(order.get("order_no") or ""), {"date": when, "from": start, "to": end})]


@_rule(
    "FWK_RATE_PERIOD_GAP",
    "rate_period_gap",
    Severity.ERROR,
    RuleCategory.COMPLETENESS,
    "A rate period covers the order date",
)
class RatePeriodGap(_FrameworkRule):
    def findings(self, data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        period = data.get("rate_period")
        if not isinstance(period, dict) or period.get("covered", True):
            return []
        return [(str(period.get("date") or ""), {"date": period.get("date") or ""})]


@_rule(
    "FWK_ESCALATION_UNRESOLVED",
    "escalation_unresolved",
    Severity.ERROR,
    RuleCategory.COMPLETENESS,
    "Escalation index resolves",
)
class EscalationUnresolved(_FrameworkRule):
    def findings(self, data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        return [
            (str(u.get("series") or ""), {"series": u.get("series") or "", "period": u.get("period") or ""})
            for u in data.get("escalation_unresolved") or []
            if isinstance(u, dict)
        ]


@_rule(
    "FWK_CAP_EXCEEDED", "cap_exceeded", Severity.ERROR, RuleCategory.COMPLIANCE, "Order stays within the agreement cap"
)
class CapExceeded(_FrameworkRule):
    def findings(self, data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        cap = data.get("cap") or {}
        if not cap.get("exceeded"):
            return []
        cur = _currency(data)
        return [
            (
                "cap",
                {
                    "total": _money(cap.get("total_after"), cur),
                    "cap": _money(cap.get("cap"), cur),
                    "headroom": _money(cap.get("headroom_before"), cur),
                },
            )
        ]


@_rule(
    "FWK_CAP_THRESHOLD",
    "cap_threshold",
    Severity.WARNING,
    RuleCategory.QUALITY,
    "Agreement use below the warning threshold",
)
class CapThreshold(_FrameworkRule):
    def findings(self, data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        cap = data.get("cap") or {}
        if cap.get("exceeded") or not cap.get("threshold_reached"):
            return []
        return [("cap", {"pct": cap.get("pct_after")})]


@_rule(
    "FWK_ITEM_MAX_QTY",
    "item_max_qty",
    Severity.WARNING,
    RuleCategory.QUALITY,
    "Item quantity within its stated maximum",
)
class ItemMaxQty(_FrameworkRule):
    def findings(self, data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        return [
            (str(i.get("code")), {"code": i.get("code"), "qty": i.get("qty"), "max": i.get("max")})
            for i in data.get("items_over_max") or []
            if isinstance(i, dict)
        ]


@_rule("FWK_MIN_AT_RISK", "min_at_risk", Severity.WARNING, RuleCategory.QUALITY, "Guaranteed minimum on track")
class MinAtRisk(_FrameworkRule):
    def findings(self, data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        risk = data.get("min_risk") or {}
        if not risk.get("at_risk"):
            return []
        return [("minimum", {"days": risk.get("days"), "pct": risk.get("pct")})]


@_rule(
    "FWK_CURRENCY_MISMATCH",
    "currency_mismatch",
    Severity.ERROR,
    RuleCategory.CONSISTENCY,
    "Order currency is the agreement currency",
)
class CurrencyMismatch(_FrameworkRule):
    def findings(self, data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        agr_cur = _currency(data)
        order_cur = str((data.get("order") or {}).get("currency") or "")
        if not agr_cur or not order_cur or agr_cur == order_cur:
            return []
        return [("currency", {"cur": order_cur, "agr": agr_cur})]


@_rule(
    "FWK_ADJUSTMENT_UNKNOWN",
    "adjustment_unknown",
    Severity.WARNING,
    RuleCategory.CONSISTENCY,
    "Order conditions have an adjustment",
)
class AdjustmentUnknown(_FrameworkRule):
    def findings(self, data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        return [(str(tag), {"tag": tag}) for tag in data.get("unknown_tags") or []]


@_rule(
    "FWK_DIRECT_CLAIM", "direct_claim", Severity.ERROR, RuleCategory.STRUCTURE, "Claims are raised on call-off orders"
)
class DirectClaim(_FrameworkRule):
    def findings(self, data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        return [("agreement", {})] if data.get("direct_claim") else []


@_rule(
    "FWK_DUPLICATE_ITEM",
    "duplicate_item",
    Severity.ERROR,
    RuleCategory.STRUCTURE,
    "Item codes are unique in a rate period",
)
class DuplicateItem(_FrameworkRule):
    def findings(self, data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        return [
            (str(d.get("code")), {"code": d.get("code"), "period": d.get("period") or ""})
            for d in data.get("duplicates") or []
            if isinstance(d, dict)
        ]


@_rule(
    "FWK_MEASURED_OVER_ORDERED",
    "measured_over_ordered",
    Severity.WARNING,
    RuleCategory.QUALITY,
    "Measured quantity within ordered",
)
class MeasuredOverOrdered(_FrameworkRule):
    def findings(self, data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        out = []
        for ln in _lines(data):
            measured = ln.get("measured_qty")
            if measured in (None, "") or _dec(measured) <= _dec(ln.get("quantity")):
                continue
            out.append((str(ln.get("code")), {"m": measured, "o": ln.get("quantity"), "code": ln.get("code")}))
        return out


@_rule(
    "FWK_TERM_OVER_LEGAL_MAX",
    "term_over_legal_max",
    Severity.WARNING,
    RuleCategory.COMPLIANCE,
    "Term within the pack's stated limit",
)
class TermOverLegalMax(_FrameworkRule):
    def findings(self, data: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        agr = data.get("agreement") or {}
        limit = agr.get("term_limit")
        years = agr.get("term_years")
        if not isinstance(limit, dict) or years in (None, "") or _dec(years) <= _dec(limit.get("years")):
            return []
        return [("term", {"years": years, "max": limit.get("years"), "source": limit.get("source") or ""})]


RULES: tuple[type[_FrameworkRule], ...] = (
    ItemNotInAgreement,
    RateDeviates,
    OrderOutsideValidity,
    RatePeriodGap,
    EscalationUnresolved,
    CapExceeded,
    CapThreshold,
    ItemMaxQty,
    MinAtRisk,
    CurrencyMismatch,
    AdjustmentUnknown,
    DirectClaim,
    DuplicateItem,
    MeasuredOverOrdered,
    TermOverLegalMax,
)


def register_framework_rules() -> None:
    """Idempotently register the ``framework_agreement`` rule set (keyed on ``rule_id``)."""
    for cls in RULES:
        rule_registry.register(cls(), rule_sets=[RULE_SET])

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The ``hongkong`` rule set: a Hong Kong bill, contract and payment claim.

Three groups, each read from a plain dict so the rules run on a fixture with no
database:

* Security of Payment (Cap. 652), from ``data["contract"]`` and
  ``data["applications"]``: whether the Ordinance covers the contract, the
  30-day response and 60-day payment ceilings, a response that never came, the
  28-day adjudication window, and the pay-when-paid clause the Ordinance voids.
  The statutory figures are read from the ``hk_sopo`` payment regime
  (``app.modules.payment_clock.data``), or from ``data["regime"]`` when the
  caller passes the stored row, so the numbers live in one place.
* The bill, from ``data["markups"]`` and ``data["positions"]``: the CIC and CWR
  levies above HK$3,000,000, no VAT or GST line, and attendance beside a prime
  cost sum.
* Retention against the contract limit (``data["retention"]``) and the source
  attribution of an imported ArchSD tender price index (``data["index_series"]``).

``data["contract"]`` keys: ``contract_date``, ``contract_value``, ``supply_only``,
``sector`` (public / private), ``is_subcontract``, ``main_contract_covered``,
``private_scope_confirmed``, ``payment_term_days``, ``response_term_days``,
``pay_when_paid``. Each application: ``reference``, ``claim_served``,
``billing_date``, ``claimed_amount``, ``admitted_amount``, ``response_served``.
``data["as_of"]`` is the date the clock is read on.
"""

from __future__ import annotations

import re
from datetime import date
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
from app.core.validation.rules import _get_locale

HONGKONG_RULE_SET = "hongkong"
SOPO_REGIME_CODE = "hk_sopo"

#: The value of construction operations above which the CIC and CWR levies are due (cic.hk, from 30.07.2018).
LEVY_THRESHOLD = Decimal("3000000")
CIC_LEVY_PERCENT = Decimal("0.5")
CWR_LEVY_PERCENT = Decimal("0.03")

_CIC_RE = re.compile(r"\bcic\b|construction industry council|cap\.?\s*587|建造業議會", re.IGNORECASE)
_CWR_RE = re.compile(r"\bcwr\b|workers registration|cap\.?\s*583|工人註冊", re.IGNORECASE)
_TAX_RE = re.compile(r"\bvat\b|\bgst\b|value added tax|goods and services tax", re.IGNORECASE)
_PC_SUM_RE = re.compile(r"\bp\.?\s?c\.?\s+sum\b|\bprime cost\b|主要成本金額", re.IGNORECASE)
_ATTENDANCE_RE = re.compile(r"attendance|照料", re.IGNORECASE)
_PROFIT_RE = re.compile(r"\bprofit\b|利潤", re.IGNORECASE)


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


def _dict(context: ValidationContext, key: str) -> dict[str, Any]:
    value = _data(context).get(key)
    return value if isinstance(value, dict) else {}


def _list(context: ValidationContext, key: str) -> list[dict[str, Any]]:
    value = _data(context).get(key)
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _money(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _regime(context: ValidationContext) -> dict[str, Any] | None:
    stored = _dict(context, "regime")
    if stored:
        return stored
    try:
        from app.modules.payment_clock.data import regime_by_code  # noqa: PLC0415
    except ImportError:
        return None
    return regime_by_code(SOPO_REGIME_CODE)


def _clock(context: ValidationContext) -> Any:
    """The payment clock helpers, or None when the payment clock module is not installed."""
    try:
        from app.modules.payment_clock import applicability, clock  # noqa: PLC0415
    except ImportError:
        return None
    return clock, applicability


def _applicability(context: ValidationContext) -> str | None:
    contract = _dict(context, "contract")
    regime = _regime(context)
    helpers = _clock(context)
    if not contract or regime is None or helpers is None:
        return None
    return helpers[1].regime_applicability(regime, contract).status


def _as_of(context: ValidationContext) -> date:
    helpers = _clock(context)
    parsed = helpers[0].parse_date(_data(context).get("as_of")) if helpers else None
    return parsed or date.today()


def _markups(context: ValidationContext) -> list[dict[str, Any]]:
    return [m for m in _list(context, "markups") if m.get("is_active", True)]


def _bill_value(context: ValidationContext) -> Decimal | None:
    """The value the levy threshold is read against: the contract value, else the bill's direct cost."""
    value = _money(_dict(context, "contract").get("contract_value"))
    if value is not None:
        return value
    value = _money(_data(context).get("total_value"))
    if value is not None:
        return value
    positions = _list(context, "positions")
    totals = [_money(p.get("total")) for p in positions if p.get("type") != "section"]
    known = [t for t in totals if t is not None]
    return sum(known, Decimal("0")) if known else None


class _HongKongRule(ValidationRule):
    standard = HONGKONG_RULE_SET
    severity = Severity.WARNING
    category = RuleCategory.COMPLIANCE
    key = ""

    def _finding(self, context: ValidationContext, *, element_ref: str | None = None, **params: Any) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=False,
            message=translate(f"hongkong.{self.key}.fail", locale=_get_locale(context), **params),
            element_ref=element_ref,
            details=dict(params),
        )


class SopoApplicability(_HongKongRule):
    rule_id = "hk.sopo.applicability"
    name = "Security of Payment Ordinance applies"
    description = "The contract is covered by Cap. 652, so its payment dates are statutory"
    severity = Severity.INFO
    key = "sopo_applicability"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return [self._finding(context)] if _applicability(context) == "applies" else []


class SopoPrivateScopeCheck(_HongKongRule):
    rule_id = "hk.sopo.private_scope_check"
    name = "Private contract scope to confirm"
    description = (
        "A private main contract is covered only for new buildings or works needing Building Authority approval"
    )
    key = "sopo_private_scope_check"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        return [self._finding(context)] if _applicability(context) == "needs_confirmation" else []


def _schedules(context: ValidationContext) -> list[tuple[dict[str, Any], Any]]:
    regime = _regime(context)
    helpers = _clock(context)
    if regime is None or helpers is None or _applicability(context) != "applies":
        return []
    clock = helpers[0]
    out = []
    for application in _list(context, "applications"):
        served = clock.parse_date(application.get("claim_served"))
        if served is None:
            continue
        schedule = clock.compute_schedule(
            regime, application_date=served, period_end=clock.parse_date(application.get("billing_date"))
        )
        out.append((application, schedule))
    return out


class SopoResponseLate(_HongKongRule):
    rule_id = "hk.sopo.response_late"
    name = "Payment response missing"
    description = "No payment response was served by the payment response deadline"
    severity = Severity.ERROR
    key = "sopo_response_late"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        today = _as_of(context)
        results = []
        for application, schedule in _schedules(context):
            deadline = schedule.payment_notice_deadline
            if deadline is None or application.get("response_served") or today <= deadline:
                continue
            results.append(
                self._finding(context, element_ref=str(application.get("reference") or ""), date=deadline.isoformat())
            )
        return results


class SopoAdjudicationWindow(_HongKongRule):
    rule_id = "hk.sopo.adjudication_window"
    name = "Adjudication notice window"
    description = "A payment dispute has arisen; the adjudication notice is due within 28 days"
    key = "sopo_adjudication_window"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        regime = _regime(context) or {}
        helpers = _clock(context)
        today = _as_of(context)
        results = []
        for application, schedule in _schedules(context):
            deadline = schedule.payment_notice_deadline
            claimed = _money(application.get("claimed_amount"))
            admitted = _money(application.get("admitted_amount"))
            if deadline is None or helpers is None:
                continue
            served = bool(application.get("response_served"))
            short = served and claimed is not None and admitted is not None and admitted < claimed
            if not (short or (not served and today > deadline)):
                continue
            closes = helpers[1].adjudication_window_closes(regime, helpers[1].dispute_date(deadline))
            if closes is None or today > closes:
                continue
            results.append(
                self._finding(context, element_ref=str(application.get("reference") or ""), date=closes.isoformat())
            )
        return results


class _TermCeiling(_HongKongRule):
    severity = Severity.ERROR
    field = ""
    regime_field = ""

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        if _applicability(context) != "applies":
            return []
        days = _dict(context, "contract").get(self.field)
        ceiling = (_regime(context) or {}).get(self.regime_field)
        try:
            n = int(days)
        except (TypeError, ValueError):
            return []
        if ceiling is None or n <= int(ceiling):
            return []
        return [self._finding(context, n=n)]


class SopoPaymentTermExceeds60(_TermCeiling):
    rule_id = "hk.sopo.payment_term_exceeds_60"
    name = "Payment period over the statutory maximum"
    description = "The contract payment period is longer than the 60 days Cap. 652 allows"
    key = "sopo_payment_term_exceeds_60"
    field = "payment_term_days"
    regime_field = "final_date_days"


class SopoResponseTermExceeds30(_TermCeiling):
    rule_id = "hk.sopo.response_term_exceeds_30"
    name = "Payment response period over the statutory maximum"
    description = "The contract payment response period is longer than the 30 days Cap. 652 allows"
    key = "sopo_response_term_exceeds_30"
    field = "response_term_days"
    regime_field = "payment_notice_days"


class ContractPayWhenPaid(_HongKongRule):
    rule_id = "hk.contract.pay_when_paid"
    name = "Pay-when-paid clause"
    description = "A conditional payment provision is unenforceable under Cap. 652"
    severity = Severity.ERROR
    key = "contract_pay_when_paid"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        contract = _dict(context, "contract")
        regime = _regime(context) or {}
        if not contract.get("pay_when_paid") or not regime.get("conditional_payment_void"):
            return []
        return [self._finding(context)] if _applicability(context) == "applies" else []


class LevyMissing(_HongKongRule):
    rule_id = "hk.levy.missing"
    name = "CIC and CWR levy lines missing"
    description = "Works over HK$3,000,000 carry the Construction Industry Council and Construction Workers levies"
    key = "levy_missing"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        value = _bill_value(context)
        if value is None or value <= LEVY_THRESHOLD or not _list(context, "markups"):
            return []
        names = [str(m.get("name") or "") for m in _markups(context)]
        if any(_CIC_RE.search(n) for n in names) and any(_CWR_RE.search(n) for n in names):
            return []
        return [self._finding(context)]


class LevyBelowThreshold(_HongKongRule):
    rule_id = "hk.levy.below_threshold"
    name = "Below the levy threshold"
    description = "Works of HK$3,000,000 or less carry no CIC or CWR levy"
    severity = Severity.INFO
    key = "levy_below_threshold"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        value = _bill_value(context)
        return [self._finding(context)] if value is not None and value <= LEVY_THRESHOLD else []


class TaxNonzero(_HongKongRule):
    rule_id = "hk.tax.nonzero"
    name = "Tax line on a Hong Kong bill"
    description = "Hong Kong has no VAT or GST, so a tax line must be zero"
    severity = Severity.ERROR
    key = "tax_nonzero"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results = []
        for markup in _markups(context):
            if markup.get("category") != "tax" and not _TAX_RE.search(str(markup.get("name") or "")):
                continue
            rate = _money(markup.get("percentage")) or Decimal("0")
            fixed = _money(markup.get("fixed_amount")) or Decimal("0")
            if rate != 0 or fixed != 0:
                results.append(self._finding(context, element_ref=str(markup.get("name") or "")))
        return results


class RetentionOverLimit(_HongKongRule):
    rule_id = "hk.retention.over_limit"
    name = "Retention over the contract limit"
    description = "The retention held is more than the limit the contract sets"
    key = "retention_over_limit"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        retention = _dict(context, "retention")
        held = _money(retention.get("held"))
        limit = _money(retention.get("limit"))
        if held is None or limit is None or held <= limit:
            return []
        return [self._finding(context, x=f"{held:,.2f}", limit=f"{limit:,.2f}")]


class PcSumNoAttendance(_HongKongRule):
    rule_id = "hk.boq.pc_sum_no_attendance"
    name = "Prime cost sum without profit and attendance"
    description = "A prime cost sum is followed by the main contractor's profit and attendance items"
    key = "pc_sum_no_attendance"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        positions = _list(context, "positions")
        texts = [str(p.get("description") or "") for p in positions]
        if not any(_PC_SUM_RE.search(t) for t in texts):
            return []
        if any(_ATTENDANCE_RE.search(t) for t in texts) and any(_PROFIT_RE.search(t) for t in texts):
            return []
        return [self._finding(context)]


class IndexAttribution(_HongKongRule):
    rule_id = "hk.index.attribution"
    name = "ArchSD index without attribution"
    description = "An imported ArchSD tender price index carries its source attribution"
    severity = Severity.ERROR
    key = "index_attribution"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        results = []
        for series in _list(context, "index_series"):
            name = str(series.get("name") or "")
            if "archsd" in name.lower() and not str(series.get("source_attribution") or "").strip():
                results.append(self._finding(context, element_ref=name))
        return results


HONGKONG_RULES: tuple[type[ValidationRule], ...] = (
    SopoApplicability,
    SopoPrivateScopeCheck,
    SopoResponseLate,
    SopoPaymentTermExceeds60,
    SopoResponseTermExceeds30,
    SopoAdjudicationWindow,
    ContractPayWhenPaid,
    LevyMissing,
    LevyBelowThreshold,
    TaxNonzero,
    RetentionOverLimit,
    PcSumNoAttendance,
    IndexAttribution,
)

__all__ = ["CIC_LEVY_PERCENT", "CWR_LEVY_PERCENT", "HONGKONG_RULES", "HONGKONG_RULE_SET", "LEVY_THRESHOLD"]

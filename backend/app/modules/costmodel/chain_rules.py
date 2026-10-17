# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost chain validation rules V6 to V10 and V15, rule set ``cost_chain``.

The checks a controller runs on the money downstream of the bill, in the
order the chain has it. Cost control runs this set on every read of its chain
panel (see :mod:`app.modules.costmodel.chain_service`). Each rule reads one
plain-data payload under ``context.data["cost_chain"]`` and is silent on any
other data.

* V6 ``contract_sum``: a contract's sum is its schedule (an error on a
  contract billed by measured quantity, a warning otherwise); a bound contract
  with no schedule is pointed out, its money is on no cost line.
* V7 ``change_approval``: an approved change carries the agreed amount and the
  approval date; a schedule line a change added is not billed while that
  change is not approved.
* V8 ``commitment_within_target``: a contract stays within the bill it was
  let from, and an account's commitment within the account's plan, both up to
  a tolerance.
* V9 ``quantity_overrun``: measured quantity on a schedule line stays within
  the contracted quantity plus a tolerance.
* V10 ``measurement_within_commitment``: what is measured on a contract stays
  within the contract plus its approved changes.
* V15 ``invoice_has_contract``: a supplier invoice belongs to a contract or an
  order, so its money has a commitment and an account.

Messages come from the validation message bundle in the caller's locale.
"""

from __future__ import annotations

import logging
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
from app.core.validation.messages import DEFAULT_LOCALE, translate

logger = logging.getLogger(__name__)

RULE_SET = "cost_chain"
PAYLOAD_KEY = "cost_chain"

#: Money the comparisons let pass as rounding.
MONEY_TOLERANCE = Decimal("0.01")
#: Default share by which a contract may exceed the bill it was let from, or an
#: account its plan, before V8 speaks (a pack or the payload may set its own).
DEFAULT_TARGET_TOLERANCE = Decimal("0.10")
#: Default share by which measured quantity may exceed the contracted quantity before V9 speaks.
DEFAULT_QUANTITY_TOLERANCE = Decimal("0.10")

#: Contract types billed by measured quantity times rate, where the schedule is the contract.
MEASURED_TYPES = frozenset({"unit_price", "remeasurement"})


def _payload(context: ValidationContext) -> dict[str, Any] | None:
    data = context.data
    if isinstance(data, dict) and isinstance(data.get(PAYLOAD_KEY), dict):
        return data[PAYLOAD_KEY]
    return None


def _locale(context: ValidationContext) -> str:
    metadata = getattr(context, "metadata", None)
    if isinstance(metadata, dict):
        locale = metadata.get("locale")
        if isinstance(locale, str) and locale.strip():
            return locale.strip()
    return DEFAULT_LOCALE


def _dec(raw: object) -> Decimal:
    try:
        value = Decimal(str(raw if raw not in (None, "") else "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")
    return value if value.is_finite() else Decimal("0")


def _rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [r for r in payload.get(key) or [] if isinstance(r, dict)]


def _pct(share: Decimal) -> str:
    """A share as a whole percent for a sentence: 0.10 reads 10."""
    return str((share * 100).quantize(Decimal("1")))


class _ChainRule(ValidationRule):
    """Shared plumbing: payload lookup and translated results."""

    standard = "universal"
    category = RuleCategory.CONSISTENCY

    def _result(
        self,
        context: ValidationContext,
        message_key: str,
        *,
        severity: Severity | None = None,
        element_ref: str | None = None,
        money: tuple[str, ...] = (),
        **params: Any,
    ) -> RuleResult:
        """A failed result. Params named in ``money`` are spelled as amounts in the payload currency.

        ``details`` keeps every param as a plain string (a raw decimal for
        money) plus the stable ``problem`` key, so the screen can link the row.
        """
        locale = _locale(context)
        currency = str((_payload(context) or {}).get("currency") or "")
        shown = {k: (sentence_amount(_dec(v), currency) if k in money else v) for k, v in params.items()}
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=severity or self.severity,
            category=self.category,
            passed=False,
            message=translate(f"cost_chain.{message_key}.fail", locale, **shown),
            element_ref=element_ref,
            details={"problem": message_key, **{k: str(v) for k, v in params.items()}},
            suggestion=translate(f"cost_chain.{message_key}.suggestion", locale, **shown),
        )

    def _passed(self) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=True,
            message="",
        )

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        raise NotImplementedError

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        payload = _payload(context)
        if payload is None:
            return []
        found = self.check(context, payload)
        return found or [self._passed()]


class ContractSumRule(_ChainRule):
    """V6: the contract sum is its schedule; a contract without one is on no account."""

    rule_id = "cost_chain.contract_sum"
    name = "Contract sum matches its schedule"
    severity = Severity.ERROR
    description = "A contract's value equals the sum of its schedule lines; a contract without lines is pointed out."

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        out: list[RuleResult] = []
        for c in _rows(payload, "contracts"):
            total = _dec(c.get("total_value"))
            if int(c.get("line_count") or 0) == 0:
                if total != 0:
                    out.append(
                        self._result(
                            context,
                            "contract_without_schedule",
                            severity=Severity.WARNING,
                            element_ref=str(c.get("id") or ""),
                            money=("amount",),
                            code=c.get("code") or "",
                            amount=str(total),
                        )
                    )
                continue
            lines = _dec(c.get("lines_total"))
            difference = total - lines
            if abs(difference) <= MONEY_TOLERANCE:
                continue
            measured = str(c.get("contract_type") or "") in MEASURED_TYPES
            out.append(
                self._result(
                    context,
                    "contract_sum_differs",
                    severity=Severity.ERROR if measured else Severity.WARNING,
                    element_ref=str(c.get("id") or ""),
                    money=("total", "lines", "difference"),
                    code=c.get("code") or "",
                    total=str(total),
                    lines=str(lines),
                    difference=str(difference),
                )
            )
        return out


class ChangeApprovalRule(_ChainRule):
    """V7: an approved change says what was agreed and when; unapproved changes are not billed."""

    rule_id = "cost_chain.change_approval"
    name = "Approved changes are complete"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "An approved change carries its agreed amount and approval date; no billing on an unapproved change."

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        out: list[RuleResult] = []
        for co in _rows(payload, "change_orders"):
            if str(co.get("status") or "") not in ("approved", "executed"):
                continue
            ref = str(co.get("id") or "")
            code = co.get("code") or ""
            if co.get("approved_amount") in (None, ""):
                out.append(self._result(context, "change_without_agreed_amount", element_ref=ref, code=code))
            if not str(co.get("approved_at") or "").strip():
                out.append(self._result(context, "change_without_approval_date", element_ref=ref, code=code))
        for row in _rows(payload, "billed_unapproved"):
            out.append(
                self._result(
                    context,
                    "billed_before_approval",
                    severity=Severity.WARNING,
                    element_ref=str(row.get("line_id") or ""),
                    money=("amount",),
                    code=row.get("change_code") or "",
                    contract=row.get("contract_code") or "",
                    status=row.get("change_status") or "",
                    amount=str(_dec(row.get("billed"))),
                )
            )
        return out


class CommitmentWithinTargetRule(_ChainRule):
    """V8: a contract within the bill it was let from, an account's commitment within its plan."""

    rule_id = "cost_chain.commitment_within_target"
    name = "Commitments within their targets"
    severity = Severity.WARNING
    description = "A contract, changes included, stays within its bill target, and an account within its plan."

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        tolerance = _dec(payload.get("target_tolerance") or DEFAULT_TARGET_TOLERANCE)
        out: list[RuleResult] = []
        for c in _rows(payload, "contracts"):
            target = _dec(c.get("target"))
            committed = _dec(c.get("committed"))
            if target > 0 and committed > target * (1 + tolerance) + MONEY_TOLERANCE:
                out.append(
                    self._result(
                        context,
                        "contract_over_target",
                        element_ref=str(c.get("id") or ""),
                        money=("committed", "target", "difference"),
                        code=c.get("code") or "",
                        committed=str(committed),
                        target=str(target),
                        difference=str(committed - target),
                        tolerance=_pct(tolerance),
                    )
                )
        for a in _rows(payload, "accounts"):
            planned = _dec(a.get("planned"))
            committed = _dec(a.get("committed"))
            if planned > 0 and committed > planned * (1 + tolerance) + MONEY_TOLERANCE:
                out.append(
                    self._result(
                        context,
                        "account_over_plan",
                        element_ref=str(a.get("id") or ""),
                        money=("committed", "planned", "difference"),
                        code=a.get("code") or "",
                        committed=str(committed),
                        planned=str(planned),
                        difference=str(committed - planned),
                        tolerance=_pct(tolerance),
                    )
                )
        return out


class QuantityOverrunRule(_ChainRule):
    """V9: measured quantity within the contracted quantity plus a tolerance."""

    rule_id = "cost_chain.quantity_overrun"
    name = "Measured quantities within the contract"
    severity = Severity.WARNING
    description = "The quantity measured on a schedule line stays within the contracted quantity plus a tolerance."

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        tolerance = _dec(payload.get("quantity_tolerance") or DEFAULT_QUANTITY_TOLERANCE)
        out: list[RuleResult] = []
        for ln in _rows(payload, "lines"):
            contracted = _dec(ln.get("quantity"))
            measured = _dec(ln.get("measured_quantity"))
            if contracted <= 0 or measured <= contracted * (1 + tolerance):
                continue
            over = ((measured - contracted) / contracted * 100).quantize(Decimal("0.1"))
            out.append(
                self._result(
                    context,
                    "quantity_overrun",
                    element_ref=str(ln.get("id") or ""),
                    code=ln.get("code") or "",
                    contract=ln.get("contract_code") or "",
                    measured=str(measured.normalize()),
                    contracted=str(contracted.normalize()),
                    unit=ln.get("unit") or "",
                    over=str(over),
                    tolerance=_pct(tolerance),
                )
            )
        return out


class MeasurementWithinCommitmentRule(_ChainRule):
    """V10: what is measured on a contract stays within the contract and its approved changes."""

    rule_id = "cost_chain.measurement_within_commitment"
    name = "Measurement within the commitment"
    severity = Severity.WARNING
    description = "Measured value on a contract stays within its value plus the approved changes."

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        out: list[RuleResult] = []
        for c in _rows(payload, "contracts"):
            measured = _dec(c.get("measured_value"))
            commitment = _dec(c.get("committed"))
            if measured <= commitment + MONEY_TOLERANCE:
                continue
            out.append(
                self._result(
                    context,
                    "measurement_exceeds_commitment",
                    element_ref=str(c.get("id") or ""),
                    money=("measured", "committed", "difference"),
                    code=c.get("code") or "",
                    measured=str(measured),
                    committed=str(commitment),
                    difference=str(measured - commitment),
                )
            )
        return out


class InvoiceHasContractRule(_ChainRule):
    """V15: every supplier invoice belongs to a contract or an order."""

    rule_id = "cost_chain.invoice_has_contract"
    name = "Supplier invoices belong to a commitment"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "A supplier invoice names its contract, contract lines or order, so its money has an account."

    def check(self, context: ValidationContext, payload: dict[str, Any]) -> list[RuleResult]:
        return [
            self._result(
                context,
                "invoice_without_contract",
                element_ref=str(inv.get("id") or ""),
                money=("amount",),
                number=inv.get("number") or "",
                amount=str(_dec(inv.get("amount"))),
            )
            for inv in _rows(payload, "invoices_without_contract")
        ]


COST_CHAIN_RULES: tuple[type[_ChainRule], ...] = (
    ContractSumRule,
    ChangeApprovalRule,
    CommitmentWithinTargetRule,
    QuantityOverrunRule,
    MeasurementWithinCommitmentRule,
    InvoiceHasContractRule,
)


def register_cost_chain_rules() -> None:
    """Register V6 to V10 and V15 into the ``cost_chain`` rule set."""
    for rule_cls in COST_CHAIN_RULES:
        rule_registry.register(rule_cls(), [RULE_SET])
    logger.debug("Registered cost chain validation rules")

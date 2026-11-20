# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Measured quantity to a payment certificate: preview first, a person confirms.

A survey volume or a mine period measures a quantity on a BOQ position. This
module finds the schedule of works line linked to that position, the open
(draft) certificate on its contract, and states what the certificate line
would carry. Commit goes through ``ContractsService.commit_preview_to_claim``,
the path populate-from-progress commits through, so there is one valuation.

The quantity becomes a percent of the line's own quantity (to date), which the
certificate applies to the line value less what earlier certificates billed.
A progress entry that carries ``measured_quantity`` and ``measured_unit`` is
read the same way by populate-from-progress (see :func:`measured_pct`).

Rule set ``contracts.measured_quantity``:

* ``MQ-001`` WARNING: the quantity exceeds the BOQ quantity.
* ``MQ-002`` ERROR: the measured unit differs from the schedule line's unit.
* ``MQ-003`` ERROR: no open certificate; the latest one is already submitted,
  approved, certified or paid, so it cannot change.
* ``MQ-004`` ERROR: no schedule of works line is linked to the BOQ position.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
    validation_engine,
)

logger = logging.getLogger(__name__)

RULE_SET = "contracts.measured_quantity"
MEASURED_QTY_META_KEY = "measured_quantity"
MEASURED_UNIT_META_KEY = "measured_unit"
_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_Q4 = Decimal("0.0001")

_UNIT_ALIASES = {
    "m3": "m3",
    "cum": "m3",
    "cbm": "m3",
    "cubm": "m3",
    "cubicmetre": "m3",
    "cubicmeter": "m3",
    "m2": "m2",
    "sqm": "m2",
    "t": "t",
    "to": "t",
    "tonne": "t",
    "tonnes": "t",
}


def norm_unit(unit: str | None) -> str:
    """A unit spelled the way two lines can be compared: ``m³``, ``M3`` and ``cu m`` read as ``m3``."""
    s = (unit or "").strip().lower().replace("³", "3").replace("²", "2").replace("^", "")
    s = s.replace(" ", "").replace(".", "")
    return _UNIT_ALIASES.get(s, s)


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError):
        return _ZERO


def measured_pct(quantity: Any, unit: str | None, line: Any) -> Decimal | None:
    """Percent to date of a schedule line that a measured quantity represents.

    ``None`` when the line has no quantity or the units differ, so the caller
    falls back to the percent the entry recorded.
    """
    line_qty = _dec(getattr(line, "quantity", 0))
    if line_qty <= _ZERO or norm_unit(unit) != norm_unit(getattr(line, "unit", "")):
        return None
    return (_dec(quantity) * _HUNDRED / line_qty).quantize(_Q4)


def measured_pct_of_entry(entry: Any, line: Any) -> Decimal | None:
    """The percent a progress entry's measured quantity gives on ``line``, if it carries one."""
    meta = getattr(entry, "metadata_", None)
    if not isinstance(meta, dict) or meta.get(MEASURED_QTY_META_KEY) in (None, ""):
        return None
    return measured_pct(meta.get(MEASURED_QTY_META_KEY), meta.get(MEASURED_UNIT_META_KEY), line)


@dataclass
class MeasuredQuantity:
    """What a measurement offers to a certificate."""

    project_id: uuid.UUID
    boq_position_id: uuid.UUID
    quantity: Decimal
    unit: str
    source: dict[str, Any] = field(default_factory=dict)
    claim_id: uuid.UUID | None = None


# ── Rules ──────────────────────────────────────────────────────────────────


def _m(context: ValidationContext) -> dict[str, Any]:
    data = context.data if isinstance(context.data, dict) else {}
    m = data.get("measured")
    return m if isinstance(m, dict) else {}


class _MeasuredRule(ValidationRule):
    standard = "custom"
    category = RuleCategory.CONSISTENCY

    def _result(self, passed: bool, key: str = "", message: str = "OK", **params: Any) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message=message,
            details={"key": key, **params},
        )


class QuantityWithinBoq(_MeasuredRule):
    rule_id = "MQ-001"
    name = "Measured quantity within the BOQ quantity"
    severity = Severity.WARNING
    description = "A measured quantity above the bill is shown so a person decides; the line caps at 100 %."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        m = _m(context)
        qty, boq = _dec(m.get("quantity")), _dec(m.get("boq_quantity"))
        if boq <= _ZERO or qty <= boq:
            return [self._result(True)]
        return [
            self._result(
                False,
                "over_boq",
                f"The measured {qty} exceeds the BOQ quantity {boq}.",
                quantity=str(qty),
                boq_quantity=str(boq),
                unit=str(m.get("unit") or ""),
            )
        ]


class UnitsAgree(_MeasuredRule):
    rule_id = "MQ-002"
    name = "Measured unit matches the schedule line"
    severity = Severity.ERROR
    description = "A quantity in one unit cannot bill a line measured in another."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        m = _m(context)
        if not m.get("line_found"):
            return []
        if norm_unit(m.get("unit")) == norm_unit(m.get("line_unit")):
            return [self._result(True)]
        return [
            self._result(
                False,
                "unit_mismatch",
                f"The measurement is in {m.get('unit')}, the schedule line in {m.get('line_unit') or '-'}.",
                unit=str(m.get("unit") or ""),
                line_unit=str(m.get("line_unit") or "-"),
            )
        ]


class CertificateOpen(_MeasuredRule):
    rule_id = "MQ-003"
    name = "Certificate still open"
    severity = Severity.ERROR
    category = RuleCategory.COMPLIANCE
    description = "Only a draft certificate takes new quantities; a submitted or approved one is locked."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        m = _m(context)
        if not m.get("line_found"):
            return []
        claim_status = str(m.get("claim_status") or "")
        if claim_status == "draft":
            return [self._result(True)]
        if not claim_status:
            return [
                self._result(
                    False,
                    "no_open_certificate",
                    f"Contract {m.get('contract_code')} has no open payment certificate.",
                    contract=str(m.get("contract_code") or ""),
                )
            ]
        return [
            self._result(
                False,
                "certificate_locked",
                f"Certificate {m.get('claim_number')} is {claim_status}: it can no longer change.",
                number=str(m.get("claim_number") or ""),
                status=claim_status,
            )
        ]


class ScheduleLineLinked(_MeasuredRule):
    rule_id = "MQ-004"
    name = "Schedule line linked to the BOQ position"
    severity = Severity.ERROR
    category = RuleCategory.COMPLETENESS
    description = "The certificate bills schedule lines; one must be linked to the measured position."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        m = _m(context)
        if m.get("line_found"):
            return [self._result(True)]
        return [
            self._result(
                False,
                "no_schedule_line",
                f"No schedule of works line is linked to BOQ position {m.get('ordinal')}.",
                ordinal=str(m.get("ordinal") or ""),
            )
        ]


MEASURED_RULES = (QuantityWithinBoq, UnitsAgree, CertificateOpen, ScheduleLineLinked)


def register_measured_quantity_rules() -> None:
    """Register the rules with the platform rule registry."""
    for rule_class in MEASURED_RULES:
        rule_registry.register(rule_class(), [RULE_SET])


register_measured_quantity_rules()


async def evaluate(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Failed findings as plain dicts: rule id, severity, English message and the key + params to translate."""
    report = await validation_engine.validate(
        data={"measured": snapshot}, rule_sets=[RULE_SET], target_type=RULE_SET, target_id=""
    )
    out = []
    for r in report.results:
        if r.passed or r.is_engine_error:
            continue
        details = dict(r.details or {})
        out.append(
            {
                "rule_id": r.rule_id,
                "severity": str(getattr(r.severity, "value", r.severity)),
                "message": r.message,
                "key": details.pop("key", ""),
                "params": {k: str(v) for k, v in details.items()},
            }
        )
    return out


# ── Preview and commit ─────────────────────────────────────────────────────


async def _linked_lines(session: AsyncSession, project_id: uuid.UUID, position_id: uuid.UUID) -> list[tuple[Any, Any]]:
    """``(contract, line)`` for every billable schedule line of the project linked to the position."""
    from app.modules.contracts.models import Contract, ContractLine  # noqa: PLC0415
    from app.modules.contracts.service import boq_position_id_for_line  # noqa: PLC0415

    rows = (
        await session.execute(
            select(Contract, ContractLine)
            .join(ContractLine, ContractLine.contract_id == Contract.id)
            .where(Contract.project_id == project_id)
            .order_by(Contract.created_at, ContractLine.order_index, ContractLine.code)
        )
    ).all()
    parents = {ln.parent_line_id for _c, ln in rows if ln.parent_line_id is not None}
    return [(c, ln) for c, ln in rows if ln.id not in parents and boq_position_id_for_line(ln) == position_id]


async def _claim_for(session: AsyncSession, contract_id: uuid.UUID, claim_id: uuid.UUID | None) -> Any | None:
    """The chosen claim, else the latest draft, else the latest one that is not rejected."""
    from app.modules.contracts.repository import ProgressClaimRepository  # noqa: PLC0415

    claims = list(await ProgressClaimRepository(session).ordered_for_contract(contract_id))
    if claim_id is not None:
        return next((c for c in claims if c.id == claim_id), None)
    drafts = [c for c in claims if c.status == "draft"]
    if drafts:
        return drafts[-1]
    live = [c for c in claims if c.status != "rejected"]
    return live[-1] if live else None


async def preview(session: AsyncSession, mq: MeasuredQuantity) -> dict[str, Any]:
    """What the certificate line would carry; nothing is written."""
    from app.modules.boq.models import Position  # noqa: PLC0415
    from app.modules.contracts.repository import ProgressClaimLineRepository  # noqa: PLC0415
    from app.modules.contracts.service import compute_progress_claim_line  # noqa: PLC0415

    position = await session.get(Position, mq.boq_position_id)
    if position is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "BOQ position not found")
    qty = mq.quantity.quantize(Decimal("0.001"))
    lines = await _linked_lines(session, mq.project_id, position.id)
    contract = line = claim = None
    if mq.claim_id is not None:
        for c, ln in lines:
            found = await _claim_for(session, c.id, mq.claim_id)
            if found is not None:
                contract, line, claim = c, ln, found
                break
        if claim is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Certificate not found on a contract that bills this line")
    elif lines:
        # A line whose contract has an open certificate wins; else the first, so the finding names it.
        candidates = [(c, ln, await _claim_for(session, c.id, None)) for c, ln in lines]
        open_ones = [x for x in candidates if x[2] is not None and x[2].status == "draft"]
        contract, line, claim = (open_ones or candidates)[0]
    snapshot = {
        "quantity": str(qty),
        "unit": mq.unit,
        "boq_quantity": str(position.quantity or 0),
        "boq_unit": position.unit or "",
        "ordinal": position.ordinal or "",
        "line_found": line is not None,
        "line_unit": (line.unit or "") if line is not None else "",
        "contract_code": contract.code if contract is not None else "",
        "claim_status": claim.status if claim is not None else "",
        "claim_number": claim.claim_number if claim is not None else "",
    }
    findings = await evaluate(snapshot)
    out: dict[str, Any] = {
        "boq_position_id": position.id,
        "ordinal": position.ordinal or "",
        "description": position.description or "",
        "boq_quantity": _dec(position.quantity),
        "boq_unit": position.unit or "",
        "quantity": qty,
        "unit": mq.unit,
        "source": mq.source,
        "contract": None,
        "line": None,
        "claim": None,
        "figures": None,
        "findings": findings,
        "can_commit": not any(f["severity"] == "error" for f in findings),
    }
    if contract is not None:
        out["contract"] = {
            "id": contract.id,
            "code": contract.code,
            "title": contract.title or "",
            "currency": contract.currency or "",
        }
    if line is not None:
        out["line"] = {
            "id": line.id,
            "code": line.code or "",
            "description": line.description or "",
            "unit": line.unit or "",
            "quantity": _dec(line.quantity),
            "unit_rate": _dec(line.unit_rate),
            "total_value": _dec(line.total_value),
        }
    if claim is not None:
        out["claim"] = {
            "id": claim.id,
            "number": claim.claim_number,
            "status": claim.status,
            "currency": claim.currency or "",
        }
    if line is not None and claim is not None:
        pct = measured_pct(qty, mq.unit, line) or _ZERO
        prior = await ProgressClaimLineRepository(session).prior_period_value_by_line(
            contract.id, before_claim_id=claim.id
        )
        derived = compute_progress_claim_line(line, pct, prior_value=prior.get(line.id, _ZERO))
        out["figures"] = {
            "percent_to_date": pct,
            "capped": pct > _HUNDRED,
            "period_qty": derived["period_completed_qty"],
            "period_value": derived["period_completed_value"],
            "prior_value": derived["prior_completed_value"],
            "cumulative_value": derived["cumulative_completed_value"],
        }
    return out


def ensure_committable(view: dict[str, Any]) -> None:
    """Raise 409 with the findings while any error finding stands on a preview."""
    if view["can_commit"] and view["figures"] is not None:
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error": "measured_quantity_blocked",
            "message": "; ".join(f["message"] for f in view["findings"] if f["severity"] == "error"),
            "findings": view["findings"],
        },
    )


async def commit(session: AsyncSession, mq: MeasuredQuantity, *, actor_id: str | None = None) -> dict[str, Any]:
    """Write the previewed line into the open certificate; refuses while any error finding stands."""
    from app.modules.contracts.service import ContractsService  # noqa: PLC0415

    view = await preview(session, mq)
    ensure_committable(view)
    service = ContractsService(session)
    item = SimpleNamespace(
        contract_line_id=view["line"]["id"],
        period_completed_pct=view["figures"]["percent_to_date"],
        period_completed_value=None,
    )
    claim = await service.commit_preview_to_claim(view["claim"]["id"], [item], actor_id=actor_id)
    meta = dict(claim.metadata_ or {})
    sources = [s for s in meta.get("measured_sources") or [] if s.get("contract_line_id") != str(item.contract_line_id)]
    sources.append({"contract_line_id": str(item.contract_line_id), "quantity": str(view["quantity"]), **mq.source})
    meta["measured_sources"] = sources
    claim.metadata_ = meta
    await session.flush()
    view["claim"] = {
        "id": claim.id,
        "number": claim.claim_number,
        "status": claim.status,
        "currency": claim.currency or "",
        "gross_amount": _dec(claim.gross_amount),
        "retention_amount": _dec(claim.retention_amount),
        "net_due": _dec(claim.net_due),
    }
    return view


__all__ = [
    "MEASURED_QTY_META_KEY",
    "MEASURED_UNIT_META_KEY",
    "RULE_SET",
    "MeasuredQuantity",
    "commit",
    "ensure_committable",
    "measured_pct",
    "measured_pct_of_entry",
    "norm_unit",
    "preview",
]

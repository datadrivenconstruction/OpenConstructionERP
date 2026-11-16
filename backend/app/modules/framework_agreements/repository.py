# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Framework agreement data access. Roll-ups run as grouped SQL, never as Python loops over rows (R8)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from sqlalchemy import Numeric, and_, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.contracts.models import Contract, ContractLine, ProgressClaim
from app.modules.framework_agreements.models import FrameworkAdjustment, FrameworkRateItem, FrameworkRatePeriod

AGREEMENT = "framework"
CALL_OFF = "call_off"
#: Contract statuses of an issued call-off order: these count as committed.
COMMITTED_STATUSES = ("active", "suspended", "completed")
#: Claim statuses that count as certified.
CERTIFIED_CLAIM_STATUSES = ("approved", "certified", "paid")
_ZERO = Decimal("0")


def _item_key() -> Any:
    """``framework_item:<item_id>`` out of ``framework_item:<item_id>@<period_id>``."""
    return func.split_part(ContractLine.source_key, "@", 1)


class FrameworkRepository:
    """Queries over agreements (framework contracts), their call-offs and their price lists."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Agreements ──────────────────────────────────────────────────────────

    async def list_agreements(
        self, project_ids: set[uuid.UUID] | None, project_id: uuid.UUID | None = None
    ) -> list[Contract]:
        stmt = select(Contract).where(Contract.contract_type == AGREEMENT)
        if project_id is not None:
            # A child site project shows the agreements of its parent, the project the agreement lives in.
            from app.modules.projects.models import Project

            parent = select(Project.parent_project_id).where(Project.id == project_id).scalar_subquery()
            stmt = stmt.where((Contract.project_id == project_id) | (Contract.project_id == parent))
        if project_ids is not None:
            stmt = stmt.where(Contract.project_id.in_(project_ids))
        return list((await self.session.execute(stmt.order_by(Contract.created_at.desc()))).scalars().all())

    async def consumption(self, agreement_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
        """Committed, certified, invoiced and order counts per agreement, in three grouped queries."""
        ids = list(agreement_ids)
        out: dict[uuid.UUID, dict[str, Any]] = {
            a: {"committed": _ZERO, "certified": _ZERO, "invoiced": _ZERO, "orders": 0, "issued": 0} for a in ids
        }
        if not ids:
            return out
        committed = case((Contract.status.in_(COMMITTED_STATUSES), Contract.total_value), else_=_ZERO)
        issued = case((Contract.status.in_(COMMITTED_STATUSES), 1), else_=0)
        rows = await self.session.execute(
            select(Contract.parent_contract_id, func.sum(committed), func.count(Contract.id), func.sum(issued))
            .where(Contract.contract_type == CALL_OFF, Contract.parent_contract_id.in_(ids))
            .group_by(Contract.parent_contract_id)
        )
        for parent, total, count, n_issued in rows.all():
            out[parent].update(committed=Decimal(total or 0), orders=int(count or 0), issued=int(n_issued or 0))
        rows = await self.session.execute(
            select(Contract.parent_contract_id, func.sum(ProgressClaim.gross_amount))
            .join(ProgressClaim, ProgressClaim.contract_id == Contract.id)
            .where(
                Contract.contract_type == CALL_OFF,
                Contract.parent_contract_id.in_(ids),
                ProgressClaim.status.in_(CERTIFIED_CLAIM_STATUSES),
            )
            .group_by(Contract.parent_contract_id)
        )
        for parent, total in rows.all():
            out[parent]["certified"] = Decimal(total or 0)
        try:
            from app.modules.finance.models import Invoice
        except ImportError:  # finance not installed: invoiced stays zero
            return out
        rows = await self.session.execute(
            select(Contract.parent_contract_id, func.sum(Invoice.amount_total))
            .join(ProgressClaim, ProgressClaim.contract_id == Contract.id)
            .join(Invoice, Invoice.source_claim_id == ProgressClaim.id)
            .where(
                Contract.contract_type == CALL_OFF,
                Contract.parent_contract_id.in_(ids),
                Invoice.status.notin_(("cancelled", "void", "draft")),
            )
            .group_by(Contract.parent_contract_id)
        )
        for parent, total in rows.all():
            out[parent]["invoiced"] = Decimal(total or 0)
        return out

    async def orders_in_month(self, agreement_ids: Iterable[uuid.UUID], month: str) -> dict[uuid.UUID, int]:
        ids = list(agreement_ids)
        if not ids:
            return {}
        rows = await self.session.execute(
            select(Contract.parent_contract_id, func.count(Contract.id))
            .where(
                Contract.contract_type == CALL_OFF,
                Contract.parent_contract_id.in_(ids),
                Contract.status.in_(COMMITTED_STATUSES),
                func.substr(Contract.start_date, 1, 7) == month,
            )
            .group_by(Contract.parent_contract_id)
        )
        return {parent: int(n) for parent, n in rows.all()}

    # ── Price list, periods, adjustments ────────────────────────────────────

    async def items(self, agreement_id: uuid.UUID) -> list[FrameworkRateItem]:
        stmt = (
            select(FrameworkRateItem)
            .where(FrameworkRateItem.agreement_id == agreement_id)
            .order_by(FrameworkRateItem.sort_order, FrameworkRateItem.code)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def periods(self, agreement_id: uuid.UUID) -> list[FrameworkRatePeriod]:
        stmt = (
            select(FrameworkRatePeriod)
            .where(FrameworkRatePeriod.agreement_id == agreement_id)
            .order_by(FrameworkRatePeriod.effective_from)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def adjustments(self, agreement_id: uuid.UUID) -> list[FrameworkAdjustment]:
        stmt = (
            select(FrameworkAdjustment)
            .where(FrameworkAdjustment.agreement_id == agreement_id)
            .order_by(FrameworkAdjustment.code)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def ordered_qty_by_item(self, agreement_id: uuid.UUID) -> dict[str, tuple[Decimal, int]]:
        """``{"framework_item:<id>": (qty ordered on issued orders, orders citing it at all)}``."""
        key = _item_key()
        issued_qty = case((Contract.status.in_(COMMITTED_STATUSES), ContractLine.quantity), else_=_ZERO)
        rows = await self.session.execute(
            select(key, func.sum(issued_qty), func.count(func.distinct(Contract.id)))
            .join(Contract, Contract.id == ContractLine.contract_id)
            .where(
                Contract.contract_type == CALL_OFF,
                Contract.parent_contract_id == agreement_id,
                ContractLine.origin == "framework_item",
            )
            .group_by(key)
        )
        return {k: (Decimal(q or 0), int(n or 0)) for k, q, n in rows.all()}

    # ── Orders ──────────────────────────────────────────────────────────────

    async def call_offs(self, agreement_id: uuid.UUID) -> list[Contract]:
        stmt = (
            select(Contract)
            .where(Contract.contract_type == CALL_OFF, Contract.parent_contract_id == agreement_id)
            .order_by(Contract.start_date.desc().nullslast(), Contract.code.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def order_rollups(self, order_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
        """Per order: line count, framework net, extras, ordered and measured value, claimed."""
        out: dict[uuid.UUID, dict[str, Any]] = {
            o: {
                "lines": 0,
                "extras": _ZERO,
                "claimed": _ZERO,
                "ordered_value": _ZERO,
                "measured_value": _ZERO,
                "over": False,
            }
            for o in order_ids
        }
        if not order_ids:
            return out
        measured_txt = ContractLine.metadata_["measured_qty"].as_string()
        measured = func.coalesce(cast(func.nullif(measured_txt, ""), Numeric(18, 4)), _ZERO)
        is_extra = ContractLine.origin == "variation"
        rows = await self.session.execute(
            select(
                ContractLine.contract_id,
                func.count(ContractLine.id),
                func.sum(case((is_extra, ContractLine.total_value), else_=_ZERO)),
                func.sum(case((is_extra, _ZERO), else_=ContractLine.total_value)),
                func.sum(case((is_extra, _ZERO), else_=measured * ContractLine.unit_rate)),
                func.max(case((and_(~is_extra, measured > ContractLine.quantity), 1), else_=0)),
            )
            .where(ContractLine.contract_id.in_(order_ids))
            .group_by(ContractLine.contract_id)
        )
        for cid, n, extras, ordered, measured_value, over in rows.all():
            out[cid].update(
                lines=int(n or 0),
                extras=Decimal(extras or 0),
                ordered_value=Decimal(ordered or 0),
                measured_value=Decimal(measured_value or 0),
                over=bool(over),
            )
        rows = await self.session.execute(
            select(ProgressClaim.contract_id, func.sum(ProgressClaim.gross_amount), func.count(ProgressClaim.id))
            .where(ProgressClaim.contract_id.in_(order_ids), ProgressClaim.status != "rejected")
            .group_by(ProgressClaim.contract_id)
        )
        for cid, total, n in rows.all():
            out[cid]["claimed"] = Decimal(total or 0)
            out[cid]["claims"] = int(n or 0)
        return out

    async def lines(self, order_id: uuid.UUID) -> list[ContractLine]:
        stmt = select(ContractLine).where(ContractLine.contract_id == order_id).order_by(ContractLine.order_index)
        return list((await self.session.execute(stmt)).scalars().all())

    async def order_codes(self, agreement_id: uuid.UUID) -> list[str]:
        stmt = select(Contract.code).where(
            Contract.contract_type == CALL_OFF, Contract.parent_contract_id == agreement_id
        )
        return [str(c) for c in (await self.session.execute(stmt)).scalars().all()]

    async def code_taken(self, code: str) -> bool:
        stmt = select(func.count(Contract.id)).where(Contract.code == code)
        return int((await self.session.execute(stmt)).scalar() or 0) > 0

    async def breakdown(self, agreement_id: uuid.UUID, by: str) -> list[tuple[str, str, int, Decimal, Decimal]]:
        """Committed value grouped by site, item or month: ``(key, label, orders, committed, quantity)``."""
        base = (
            Contract.contract_type == CALL_OFF,
            Contract.parent_contract_id == agreement_id,
            Contract.status.in_(COMMITTED_STATUSES),
        )
        if by == "item":
            key = _item_key()
            stmt = (
                select(
                    key,
                    func.max(ContractLine.code),
                    func.count(func.distinct(Contract.id)),
                    func.sum(ContractLine.total_value),
                    func.sum(ContractLine.quantity),
                )
                .join(Contract, Contract.id == ContractLine.contract_id)
                .where(*base, ContractLine.origin == "framework_item")
                .group_by(key)
                .order_by(func.sum(ContractLine.total_value).desc())
            )
        else:
            key = (
                func.coalesce(Contract.terms["site_label"].as_string(), "")
                if by == "site"
                else func.substr(Contract.start_date, 1, 7)
            )
            stmt = (
                select(key, key, func.count(Contract.id), func.sum(Contract.total_value), func.sum(_ZERO))
                .where(*base)
                .group_by(key)
                .order_by(key if by == "month" else func.sum(Contract.total_value).desc())
            )
        rows = await self.session.execute(stmt)
        return [
            (str(k or ""), str(lbl or ""), int(n or 0), Decimal(v or 0), Decimal(q or 0))
            for k, lbl, n, v, q in rows.all()
        ]

    async def certified_by_order(self, agreement_id: uuid.UUID) -> dict[uuid.UUID, Decimal]:
        rows = await self.session.execute(
            select(Contract.id, func.sum(ProgressClaim.gross_amount))
            .join(ProgressClaim, ProgressClaim.contract_id == Contract.id)
            .where(
                Contract.contract_type == CALL_OFF,
                Contract.parent_contract_id == agreement_id,
                ProgressClaim.status.in_(CERTIFIED_CLAIM_STATUSES),
            )
            .group_by(Contract.id)
        )
        return {cid: Decimal(v or 0) for cid, v in rows.all()}

# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""WIP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ report service: gathers the inputs from the owning modules and closes periods.

Inputs and where they are read (read-only, nothing is copied until a close):

* contract value  - client head contracts (``oe_contracts_contract``, not subcontracts,
  not draft or terminated) plus approved and executed change orders
  (``oe_changeorders_order``, approved amount when set, else the cost impact);
* cost to date and estimate at completion - the latest cost-value reconciliation
  (``oe_cvr_report`` of the period or earlier: cost to date plus accruals, forecast cost),
  overridden by the project manager's forecast (``oe_wip_report_forecast``) when one is set;
* billed to date - issued progress claims on those contracts (gross, before retention)
  plus approved, sent or paid receivable invoices not raised from a claim (net of tax).

Every amount is a Decimal end to end.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.wip_report import logic
from app.modules.wip_report.models import WipForecast, WipPeriod

logger = logging.getLogger(__name__)

_CONTRACT_EXCLUDED = ("draft", "terminated")
_CO_COUNTED = ("approved", "executed")
_CLAIM_NOT_ISSUED = ("draft", "rejected")
_INVOICE_BILLED = ("approved", "sent", "paid")
_LATEST = "9999-12"


def period_of(day: date) -> str:
    """``YYYY-MM`` of a date."""
    return f"{day.year:04d}-{day.month:02d}"


def _str_details(details: dict[str, Any] | None) -> dict[str, str]:
    return {k: str(v) for k, v in (details or {}).items()}


class WipReportService:
    """Live WIP rows, period closes and the portfolio schedule."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- inputs -------------------------------------------------------------

    async def _contract_value(self, project_id: uuid.UUID, as_of: date) -> tuple[Decimal, Decimal, list[uuid.UUID]]:
        from app.modules.changeorders.models import ChangeOrder
        from app.modules.contracts.models import Contract

        rows = (
            await self.session.execute(
                select(Contract.id, Contract.total_value).where(
                    Contract.project_id == project_id,
                    Contract.counterparty_type == "client",
                    Contract.parent_contract_id.is_(None),
                    Contract.status.notin_(_CONTRACT_EXCLUDED),
                )
            )
        ).all()
        base = sum((logic.dec(v) for _, v in rows), logic.ZERO)
        co_rows = (
            await self.session.execute(
                select(ChangeOrder.approved_amount, ChangeOrder.cost_impact, ChangeOrder.approved_at).where(
                    ChangeOrder.project_id == project_id, ChangeOrder.status.in_(_CO_COUNTED)
                )
            )
        ).all()
        cutoff = as_of.isoformat()
        changes = logic.ZERO
        for approved, impact, approved_at in co_rows:
            if approved_at and str(approved_at)[:10] > cutoff:
                continue
            changes += logic.dec(approved if approved is not None else impact)
        return base, changes, [cid for cid, _ in rows]

    async def _cost(self, project_id: uuid.UUID, as_of: date) -> tuple[Decimal, Decimal, dict[str, Any]]:
        from app.modules.cvr.models import CvrLine, CvrReport

        report = (
            await self.session.execute(
                select(CvrReport)
                .where(CvrReport.project_id == project_id, CvrReport.period <= period_of(as_of))
                .order_by(CvrReport.period.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if report is None:
            return logic.ZERO, logic.ZERO, {}
        ctd, forecast = (
            await self.session.execute(
                select(
                    func.coalesce(func.sum(CvrLine.cost_to_date + CvrLine.accruals), 0),
                    func.coalesce(func.sum(CvrLine.forecast_cost), 0),
                ).where(CvrLine.report_id == report.id)
            )
        ).one()
        return logic.dec(ctd), logic.dec(forecast), {"cvr_report_id": str(report.id), "cvr_period": report.period}

    async def _billed(self, project_id: uuid.UUID, contract_ids: list[uuid.UUID], as_of: date) -> Decimal:
        from app.modules.contracts.models import ProgressClaim
        from app.modules.finance.models import Invoice

        billed = logic.ZERO
        if contract_ids:
            claimed = (
                await self.session.execute(
                    select(func.coalesce(func.sum(ProgressClaim.gross_amount), 0)).where(
                        ProgressClaim.contract_id.in_(contract_ids),
                        ProgressClaim.status.notin_(_CLAIM_NOT_ISSUED),
                        or_(ProgressClaim.period_to.is_(None), ProgressClaim.period_to <= as_of),
                    )
                )
            ).scalar_one()
            billed += logic.dec(claimed)
        invoiced = (
            await self.session.execute(
                select(func.coalesce(func.sum(Invoice.amount_subtotal), 0)).where(
                    Invoice.project_id == project_id,
                    Invoice.invoice_direction == "receivable",
                    Invoice.source_claim_id.is_(None),
                    Invoice.status.in_(_INVOICE_BILLED),
                    func.substr(Invoice.invoice_date, 1, 10) <= as_of.isoformat(),
                )
            )
        ).scalar_one()
        return billed + logic.dec(invoiced)

    async def forecast(self, project_id: uuid.UUID) -> WipForecast | None:
        """The project manager's estimate at completion, if one is set."""
        return (
            await self.session.execute(select(WipForecast).where(WipForecast.project_id == project_id))
        ).scalar_one_or_none()

    async def previous_period(self, project_id: uuid.UUID, before: str) -> WipPeriod | None:
        """The latest closed period strictly before *before* (``YYYY-MM``)."""
        return (
            await self.session.execute(
                select(WipPeriod)
                .where(WipPeriod.project_id == project_id, WipPeriod.period < before)
                .order_by(WipPeriod.period.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    # -- rows ---------------------------------------------------------------

    async def row(self, project_id: uuid.UUID, as_of: date | None = None) -> dict[str, Any]:
        """The WIP row of a project at *as_of* (default today), computed from the source modules."""
        from app.modules.projects.models import Project

        day = as_of or date.today()
        project = await self.session.get(Project, project_id)
        if project is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Project not found")
        base, changes, contract_ids = await self._contract_value(project_id, day)
        ctd, cvr_forecast, sources = await self._cost(project_id, day)
        override = await self.forecast(project_id)
        eac = cvr_forecast
        if override is not None:
            eac = logic.dec(override.estimated_cost)
            sources["forecast_override"] = True
        billed = await self._billed(project_id, contract_ids, day)
        prev = await self.previous_period(project_id, period_of(day))
        figures = logic.compute(
            logic.WipInputs(
                contract_value=base + changes,
                estimated_cost=eac,
                cost_to_date=ctd,
                billed_to_date=billed,
                previous_gross_profit=logic.dec(prev.projected_gross_profit) if prev else None,
            )
        )
        sources["contract_ids"] = [str(c) for c in contract_ids]
        if not contract_ids:
            figures.flags.append("no_contract")
        return {
            "project_id": project_id,
            "project_name": project.name,
            "currency": project.currency or "",
            "as_of": day,
            "previous_period": prev.period if prev else None,
            "original_contract_value": logic.q2(base),
            "approved_changes": logic.q2(changes),
            "forecast_note": override.note if override else None,
            "sources": sources,
            **figures.as_dict(),
        }

    async def portfolio(self, project_ids: set[uuid.UUID] | None, as_of: date | None = None) -> dict[str, Any]:
        """WIP rows of every project with a contract that the caller can see, with totals per currency."""
        from app.modules.contracts.models import Contract
        from app.modules.projects.models import Project

        stmt = (
            select(Project.id)
            .where(Project.status != "archived", Project.id.in_(select(Contract.project_id).distinct()))
            .order_by(Project.name)
        )
        if project_ids is not None:
            stmt = stmt.where(Project.id.in_(project_ids))
        ids = (await self.session.execute(stmt)).scalars().all()
        rows = []
        for pid in ids:
            row = await self.row(pid, as_of)
            if row["contract_value"] > 0 or row["cost_to_date"] > 0:
                rows.append(row)
        return {"as_of": as_of or date.today(), "rows": rows, "totals": logic.totals_by_currency(rows)}

    # -- periods ------------------------------------------------------------

    async def list_periods(self, project_id: uuid.UUID) -> list[WipPeriod]:
        """Closed periods of a project, newest first."""
        stmt = select(WipPeriod).where(WipPeriod.project_id == project_id).order_by(WipPeriod.period.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def page_periods(self, project_id: uuid.UUID, offset: int, limit: int) -> tuple[list[WipPeriod], int]:
        base = select(WipPeriod).where(WipPeriod.project_id == project_id)
        total = (await self.session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        page = base.order_by(WipPeriod.period.desc()).offset(offset).limit(limit)
        return list((await self.session.execute(page)).scalars().all()), total

    async def close_period(
        self, project_id: uuid.UUID, period: str, user_id: str | None = None, notes: str | None = None
    ) -> WipPeriod:
        """Snapshot the WIP row at the period's month end. A closed period is never overwritten."""
        if not logic.valid_period(period):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Invalid period: {period!r}")
        existing = (
            await self.session.execute(
                select(WipPeriod.id).where(WipPeriod.project_id == project_id, WipPeriod.period == period)
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Period {period} is already closed")
        row = await self.row(project_id, logic.month_end(period))
        snap = WipPeriod(
            project_id=project_id,
            period=period,
            as_of=row["as_of"],
            currency=row["currency"],
            notes=notes,
            closed_by=user_id,
            sources=row["sources"],
            flags=list(row["flags"]),
            **{k: row[k] for k in SNAPSHOT_FIGURES},
        )
        self.session.add(snap)
        await self.session.flush()
        from app.core.events import publish_after_commit

        payload = {
            "project_id": str(project_id),
            "period": period,
            "period_id": str(snap.id),
            "fade": str(row["fade"]) if row["fade"] is not None else None,
            "over_billing": str(row["over_billing"]),
            "under_billing": str(row["under_billing"]),
        }
        publish_after_commit(self.session, "wip_report.period.closed", payload, source_module="wip_report")
        if logic.is_large_fade(row["fade"], row["contract_value"], logic.DEFAULT_FADE_THRESHOLD_PCT):
            publish_after_commit(self.session, "wip_report.fade.detected", payload, source_module="wip_report")
        return snap

    async def reopen_period(self, project_id: uuid.UUID, period: str) -> None:
        """Delete the latest closed period so it can be closed again; earlier periods stay locked."""
        latest = await self.previous_period(project_id, _LATEST)
        if latest is None or latest.period != period:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Only the latest closed period can be reopened")
        await self.session.delete(latest)
        await self.session.flush()

    async def set_forecast(
        self, project_id: uuid.UUID, estimated_cost: Decimal | None, note: str | None, user_id: str | None
    ) -> WipForecast | None:
        """Set, or clear with ``None``, the project manager's estimate at completion."""
        current = await self.forecast(project_id)
        if estimated_cost is None:
            if current is not None:
                await self.session.delete(current)
                await self.session.flush()
            return None
        if current is None:
            current = WipForecast(project_id=project_id, estimated_cost=estimated_cost)
            self.session.add(current)
        current.estimated_cost = estimated_cost
        current.note = note
        current.updated_by = user_id
        await self.session.flush()
        return current

    # -- validation ---------------------------------------------------------

    async def findings(self, project_id: uuid.UUID, as_of: date | None = None) -> list[dict[str, Any]]:
        """Failing WIP rules for the project's live row."""
        from app.modules.wip_report.validators import evaluate

        snapshot = {"rows": [await self.row(project_id, as_of)], "fade_threshold_pct": logic.DEFAULT_FADE_THRESHOLD_PCT}
        results = await evaluate(snapshot, target_id=str(project_id))
        return [
            {
                "rule_id": r.rule_id,
                "severity": str(getattr(r.severity, "value", r.severity)),
                "message": r.message,
                "details": _str_details(r.details),
            }
            for r in results
        ]


#: The figures a close copies from the computed row onto the snapshot.
SNAPSHOT_FIGURES: tuple[str, ...] = (
    "original_contract_value",
    "approved_changes",
    "contract_value",
    "estimated_cost",
    "cost_to_date",
    "percent_complete",
    "earned_revenue",
    "billed_to_date",
    "over_billing",
    "under_billing",
    "projected_gross_profit",
    "previous_gross_profit",
    "fade",
    "backlog",
    "loss_job",
)

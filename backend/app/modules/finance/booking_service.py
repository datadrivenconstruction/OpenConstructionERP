# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Use cases of booking export batches: preview and immutable batch files."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.active_markets import pack_active
from app.modules.finance.booking_export import WRITERS, BatchPlan, InvoiceIn, Mapping, plan_batch, q
from app.modules.finance.booking_models import BookingExportBatch, BookingExportItem
from app.modules.finance.connector_models import AccountingConnectorConfig, SyncLog
from app.modules.finance.invoice_capture_models import CapturedInvoice
from app.modules.projects.models import Project


def _day(text: str | None) -> date | None:
    try:
        return date.fromisoformat((text or "")[:10])
    except ValueError:
        return None


class BookingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _config(self, config_id: uuid.UUID, markets: list[str]) -> AccountingConnectorConfig:
        config = await self.session.get(AccountingConnectorConfig, config_id)
        writer = WRITERS.get(config.connector_type) if config else None
        if config is None or writer is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Booking export connector not found")
        if writer.required_markets and not pack_active(markets, writer.required_markets):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Booking export connector not found")
        return config

    async def _invoices(self, project_ids: set[uuid.UUID] | None) -> list[InvoiceIn]:
        stmt = select(CapturedInvoice, Project.project_code).outerjoin(
            Project, Project.id == CapturedInvoice.booking_project_id
        )
        stmt = stmt.where(CapturedInvoice.direction == "payable")
        if project_ids is not None:
            stmt = stmt.where(CapturedInvoice.project_id.in_(project_ids))
        stamps = {
            str(inv_id): f"B-{number}"
            for inv_id, number in (
                await self.session.execute(
                    select(BookingExportItem.invoice_id, BookingExportBatch.number)
                    .join(BookingExportBatch, BookingExportBatch.id == BookingExportItem.batch_id)
                    .order_by(BookingExportBatch.number)
                )
            ).all()
        }
        out: list[InvoiceIn] = []
        for row, code in (await self.session.execute(stmt)).all():
            out.append(
                InvoiceIn(
                    id=str(row.id),
                    number=row.invoice_number,
                    date=_day(row.invoice_date),
                    currency=row.currency_code or "",
                    supplier=row.supplier_name,
                    supplier_key=row.supplier_contact_id or "",
                    net=q(row.amount_net),
                    tax=q(row.amount_tax),
                    gross=q(row.amount_gross),
                    status=row.status,
                    lines=tuple(dict(x) for x in (row.line_items or [])),
                    expense_account=row.booking_expense_account or "",
                    project_code=code or "",
                    cost_code=row.booking_cost_code or "",
                    exported_in=stamps.get(str(row.id)),
                )
            )
        return out

    async def plan(
        self,
        config_id: uuid.UUID,
        period_from: date,
        period_to: date,
        *,
        reexport: bool,
        project_ids: set[uuid.UUID] | None,
        markets: list[str],
    ) -> tuple[AccountingConnectorConfig, dict[str, Any], BatchPlan]:
        if period_to < period_from:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The period ends before it starts")
        config = await self._config(config_id, markets)
        writer = WRITERS[config.connector_type]
        settings = dict(config.settings_ or {})
        plan = plan_batch(
            await self._invoices(project_ids),
            Mapping.from_settings(settings),
            period_from,
            period_to,
            reexport=reexport,
            prefix=writer.rule_prefix,
            base_currency=str(settings.get("base_currency") or ""),
            text_limit=writer.text_limit,
        )
        plan.findings = writer.check_settings(settings, period_from, period_to) + plan.findings
        return config, settings, plan

    async def create(
        self,
        config_id: uuid.UUID,
        period_from: date,
        period_to: date,
        *,
        reexport: bool,
        project_ids: set[uuid.UUID] | None,
        markets: list[str],
        user_id: uuid.UUID | None,
    ) -> BookingExportBatch:
        config, settings, plan = await self.plan(
            config_id, period_from, period_to, reexport=reexport, project_ids=project_ids, markets=markets
        )
        if plan.blocked:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "Fix the issues first",
                    "issues": [f for f in plan.findings if f["severity"] == "error"],
                },
            )
        if not plan.rows:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No approved invoices to export in this period")
        writer = WRITERS[config.connector_type]
        content = writer.render(plan.rows, settings, period_from, period_to)
        codec = str(settings.get("encoding") or writer.encoding)
        top = (await self.session.execute(select(func.max(BookingExportBatch.number)))).scalar()
        number = int(top or 0) + 1
        now = datetime.now(UTC).isoformat()
        log = SyncLog(
            connector_config_id=config.id,
            project_id=config.project_id,
            direction="push",
            trigger="manual",
            status="success",
            records_out=len(plan.rows),
            warnings=[f["rule_id"] for f in plan.findings if f["severity"] != "error"],
            details_={"batch": f"B-{number}"},
            started_at=now,
            finished_at=now,
            created_by=user_id,
        )
        self.session.add(log)
        await self.session.flush()
        batch = BookingExportBatch(
            number=number,
            connector_config_id=config.id,
            connector_type=config.connector_type,
            period_from=period_from,
            period_to=period_to,
            reexport=reexport,
            invoice_count=len(plan.included),
            row_count=len(plan.rows),
            total_amount=sum((r.amount for r in plan.rows), Decimal("0")),
            filename=f"booking-B-{number}-{period_from.isoformat()}-{period_to.isoformat()}.{writer.file_extension}",
            sha256=hashlib.sha256(content).hexdigest(),
            encoding=codec,
            content=content.decode(codec, errors="replace"),
            findings=plan.findings,
            sync_log_id=log.id,
            created_by=user_id,
        )
        self.session.add(batch)
        await self.session.flush()
        numbers = {r.invoice_id: r.invoice_number for r in plan.rows}
        for invoice_id in plan.included:
            self.session.add(
                BookingExportItem(
                    batch_id=batch.id, invoice_id=uuid.UUID(invoice_id), invoice_number=numbers.get(invoice_id, "")
                )
            )
        await self.session.flush()
        return batch

    async def page(
        self, allowed: set[uuid.UUID] | None, offset: int, limit: int
    ) -> tuple[list[BookingExportBatch], int]:
        """Batches newest first; with ``allowed`` only those whose every invoice is in one of those projects."""
        stmt = select(BookingExportBatch)
        if allowed is not None:
            foreign = (
                select(BookingExportItem.id)
                .join(CapturedInvoice, CapturedInvoice.id == BookingExportItem.invoice_id)
                .where(BookingExportItem.batch_id == BookingExportBatch.id, CapturedInvoice.project_id.notin_(allowed))
            )
            stmt = stmt.where(~exists(foreign))
        total = int((await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar() or 0)
        stmt = stmt.order_by(BookingExportBatch.number.desc()).offset(offset).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all()), total

    async def project_ids(self, batch_id: uuid.UUID) -> set[uuid.UUID]:
        """The projects of the invoices a batch carries."""
        stmt = (
            select(CapturedInvoice.project_id)
            .join(BookingExportItem, BookingExportItem.invoice_id == CapturedInvoice.id)
            .where(BookingExportItem.batch_id == batch_id)
            .distinct()
        )
        return set((await self.session.execute(stmt)).scalars().all())

    async def file(self, batch_id: uuid.UUID) -> tuple[BookingExportBatch, bytes]:
        batch = await self.session.get(BookingExportBatch, batch_id)
        if batch is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Export batch not found")
        return batch, batch.content.encode(batch.encoding, errors="replace")

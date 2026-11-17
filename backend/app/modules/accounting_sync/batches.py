# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Accounting export batches: collect records, check them, write one numbered file.

A batch is the unit an accountant receives: a file with a number, a period, totals and a
SHA-256. Each record sits in one active batch only, so a second export of the same record
is refused until the first batch is voided. The file bytes are stored with the batch, so
the hash and the download never drift.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.accounting_sync import templates
from app.modules.accounting_sync.export_validators import evaluate_export
from app.modules.accounting_sync.exports import datev, journal
from app.modules.accounting_sync.models import (
    AccountingConnection,
    BatchItem,
    CostCodeMapping,
    ExportBatch,
    SupplierMapping,
)
from app.modules.accounting_sync.postings import (
    ZERO,
    SyncDocument,
    build_journal,
    journal_for,
    money,
    personal_accounts,
)

logger = logging.getLogger(__name__)

FORMATS = ("csv", "xlsx", "datev", "journal")
DOCUMENT_TYPES = ("ar_invoice", "ap_bill")
RECORD_TYPES = (*DOCUMENT_TYPES, "budget", "po", "subcontract", "cost_code")
#: Formats that carry bookings and therefore only documents.
DOCUMENT_ONLY_FORMATS = ("datev", "journal")
ALREADY_EXPORTED = "accounting_export.already_exported"
_INACTIVE = ("draft", "cancelled", "canceled", "void", "voided", "rejected", "terminated")
GENERIC_COLUMNS = (
    "record_type",
    "record_id",
    "number",
    "date",
    "currency",
    "net",
    "tax",
    "gross",
    "project",
    "counterparty",
    "account",
    "cost_centre",
    "description",
)


@dataclass
class ExportRecord:
    """One exportable record, whatever module it comes from."""

    record_type: str
    record_id: str
    number: str
    record_date: date | None
    currency: str
    net: Decimal = ZERO
    tax: Decimal = ZERO
    project: str = ""
    counterparty: str = ""
    account: str = ""
    cost_centre: str = ""
    description: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    document: SyncDocument | None = None

    @property
    def gross(self) -> Decimal:
        return self.net + self.tax

    def payload_hash(self) -> str:
        """Stable hash of what is exported for this record."""
        if self.document is not None:
            return self.document.payload_hash()
        raw = json.dumps(
            {
                "t": self.record_type,
                "n": self.number,
                "d": str(self.record_date),
                "net": str(self.net),
                "tax": str(self.tax),
                "p": self.payload,
            },
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    def row(self) -> list[str]:
        return [
            self.record_type,
            self.record_id,
            self.number,
            self.record_date.isoformat() if self.record_date else "",
            self.currency,
            f"{self.net:.2f}",
            f"{self.tax:.2f}",
            f"{self.gross:.2f}",
            self.project,
            self.counterparty,
            self.account,
            self.cost_centre,
            self.description,
        ]


@dataclass
class BatchParams:
    fmt: str
    period: tuple[date, date]
    record_types: list[str]


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _dec(value: Any) -> Decimal:
    try:
        return money(value)
    except Exception:  # noqa: BLE001 - a malformed legacy amount counts as zero
        return ZERO


class BatchService:
    """Batch operations of one session; wraps the sync service for documents and mappings."""

    def __init__(self, session: AsyncSession) -> None:
        from app.modules.accounting_sync.service import AccountingSyncService

        self.session = session
        self.sync = AccountingSyncService(session)

    # -- mappings --------------------------------------------------------------

    async def cost_codes(self, conn: AccountingConnection) -> list[CostCodeMapping]:
        rows = await self.session.execute(
            select(CostCodeMapping)
            .where(CostCodeMapping.connection_id == conn.id)
            .order_by(CostCodeMapping.standard, CostCodeMapping.platform_code)
        )
        return list(rows.scalars())

    async def suppliers(self, conn: AccountingConnection) -> list[SupplierMapping]:
        rows = await self.session.execute(
            select(SupplierMapping).where(SupplierMapping.connection_id == conn.id).order_by(SupplierMapping.contact_id)
        )
        return list(rows.scalars())

    async def set_cost_codes(self, conn: AccountingConnection, rows: list[dict[str, str]]) -> None:
        existing = {(m.platform_code, m.standard): m for m in await self.cost_codes(conn)}
        wanted = {(r["platform_code"].strip(), (r.get("standard") or "project").strip()): r for r in rows}
        for key, m in existing.items():
            if key not in wanted:
                await self.session.delete(m)
        for (code, std), r in wanted.items():
            if not code:
                continue
            center = (r.get("external_cost_center") or "").strip()
            if (code, std) in existing:
                existing[(code, std)].external_cost_center = center
            else:
                self.session.add(
                    CostCodeMapping(
                        connection_id=conn.id, platform_code=code, standard=std, external_cost_center=center
                    )
                )
        await self.session.flush()

    async def set_suppliers(self, conn: AccountingConnection, rows: list[dict[str, str]]) -> None:
        existing = {m.contact_id: m for m in await self.suppliers(conn)}
        wanted = {r["contact_id"].strip(): r for r in rows if (r.get("contact_id") or "").strip()}
        for cid, m in existing.items():
            if cid not in wanted:
                await self.session.delete(m)
        for cid, r in wanted.items():
            account = (r.get("external_account") or "").strip()
            if cid in existing:
                existing[cid].external_account = account
            else:
                self.session.add(SupplierMapping(connection_id=conn.id, contact_id=cid, external_account=account))
        await self.session.flush()

    # -- collecting ------------------------------------------------------------

    async def collect(self, conn: AccountingConnection, params: BatchParams) -> list[ExportRecord]:
        """Records in scope for the requested types and period, in a stable order."""
        wanted = set(params.record_types)
        centres = {
            m.platform_code: m.external_cost_center for m in await self.cost_codes(conn) if m.standard == "project"
        }
        out: list[ExportRecord] = []
        if wanted & set(DOCUMENT_TYPES):
            for d in await self.sync.documents(conn, period=params.period):
                if d.record_type not in wanted:
                    continue
                cc = centres.get(d.project_code) or d.project_code
                out.append(
                    ExportRecord(
                        record_type=d.record_type,
                        record_id=d.record_id,
                        number=d.number,
                        record_date=d.doc_date,
                        currency=d.currency,
                        net=d.net_total,
                        tax=d.tax_total,
                        project=d.project_name,
                        counterparty=d.contact.name,
                        cost_centre=cc,
                        description=d.lines[0].description if d.lines else "",
                        document=replace(d, project_code=cc),
                    )
                )
        scope = {uuid.UUID(p) for p in conn.project_ids or []}
        if "budget" in wanted:
            out += await self._budgets(conn, scope)
        if "po" in wanted:
            out += await self._purchase_orders(conn, scope, params.period)
        if "subcontract" in wanted:
            out += await self._agreements(conn, scope, params.period)
        if "cost_code" in wanted:
            out += [
                ExportRecord(
                    record_type="cost_code",
                    record_id=f"{m.standard}:{m.platform_code}",
                    number=m.platform_code,
                    record_date=None,
                    currency="",
                    cost_centre=m.external_cost_center,
                    description=m.standard,
                )
                for m in await self.cost_codes(conn)
            ]
        out.sort(key=lambda r: (r.record_type, r.record_date or date.min, r.number, r.record_id))
        return out

    async def _budgets(self, conn: AccountingConnection, scope: set[uuid.UUID]) -> list[ExportRecord]:
        from app.modules.finance.models import ProjectBudget

        stmt = select(ProjectBudget)
        if scope:
            stmt = stmt.where(ProjectBudget.project_id.in_(scope))
        return [
            ExportRecord(
                record_type="budget",
                record_id=str(b.id),
                number=b.category or "",
                record_date=None,
                currency=b.currency_code or conn.base_currency,
                net=_dec(b.revised_budget),
                project=str(b.project_id),
                description=b.category or "",
                payload={"original": str(b.original_budget), "committed": str(b.committed), "actual": str(b.actual)},
            )
            for b in (await self.session.execute(stmt)).scalars()
        ]

    async def _purchase_orders(
        self, conn: AccountingConnection, scope: set[uuid.UUID], period: tuple[date, date]
    ) -> list[ExportRecord]:
        try:
            from app.modules.procurement.models import PurchaseOrder
        except ImportError:  # pragma: no cover
            return []
        stmt = select(PurchaseOrder)
        if scope:
            stmt = stmt.where(PurchaseOrder.project_id.in_(scope))
        out = []
        for po in (await self.session.execute(stmt)).scalars():
            day = _day(po.issue_date)
            if po.status in _INACTIVE or (day is not None and not period[0] <= day <= period[1]):
                continue
            out.append(
                ExportRecord(
                    record_type="po",
                    record_id=str(po.id),
                    number=po.po_number,
                    record_date=day,
                    currency=po.currency_code or conn.base_currency,
                    net=_dec(po.amount_subtotal),
                    tax=_dec(po.tax_amount),
                    project=str(po.project_id),
                    counterparty=po.vendor_contact_id or "",
                )
            )
        return out

    async def _agreements(
        self, conn: AccountingConnection, scope: set[uuid.UUID], period: tuple[date, date]
    ) -> list[ExportRecord]:
        try:
            from app.modules.subcontractors.models import SubcontractAgreement
        except ImportError:  # pragma: no cover
            return []
        stmt = select(SubcontractAgreement)
        if scope:
            stmt = stmt.where(SubcontractAgreement.project_id.in_(scope))
        out = []
        for a in (await self.session.execute(stmt)).scalars():
            if a.status in _INACTIVE or (a.start_date is not None and not period[0] <= a.start_date <= period[1]):
                continue
            out.append(
                ExportRecord(
                    record_type="subcontract",
                    record_id=str(a.id),
                    number=a.title[:80],
                    record_date=a.start_date,
                    currency=a.currency or conn.base_currency,
                    net=_dec(a.total_value),
                    project=str(a.project_id),
                    counterparty=str(a.subcontractor_id),
                    description=a.title,
                )
            )
        return out

    # -- checks ----------------------------------------------------------------

    async def active_items(self, conn: AccountingConnection, records: list[ExportRecord]) -> dict[tuple[str, str], int]:
        """``(record_type, record_id) -> batch_no`` of the active batch each record already sits in."""
        if not records:
            return {}
        rows = await self.session.execute(
            select(BatchItem.record_type, BatchItem.record_id, ExportBatch.batch_no)
            .join(ExportBatch, ExportBatch.id == BatchItem.batch_id)
            .where(
                BatchItem.connection_id == conn.id,
                BatchItem.active.is_(True),
                BatchItem.record_id.in_([r.record_id for r in records]),
            )
        )
        return {(t, i): n for t, i, n in rows.all()}

    async def findings(
        self, conn: AccountingConnection, params: BatchParams, records: list[ExportRecord]
    ) -> list[dict[str, Any]]:
        docs = [r.document for r in records if r.document is not None]
        out = await self.sync.findings(conn, docs) if docs else []
        for f in out:
            f.setdefault("params", {})
        mapping = await self.sync.mapping(conn)
        tpl = templates.get_template(conn.chart_template)
        settings = dict(conn.settings_ or {})
        costs = await self.cost_codes(conn)
        active = await self.active_items(conn, records)
        snapshot = {
            "format": params.fmt,
            "lock_date": conn.lock_date.isoformat() if conn.lock_date else None,
            "settings": {
                "consultant_number": settings.get("consultant_number"),
                "client_number": settings.get("client_number"),
                "fiscal_year_start": settings.get("fiscal_year_start"),
                "account_length": tpl.get("account_length", 4),
            },
            "cost_codes_mapped": sorted(m.platform_code for m in costs if m.external_cost_center),
            "has_cost_code_map": bool(costs),
            "documents": [self._doc_snapshot(r.document, mapping) for r in records if r.document is not None],
            "records": [
                {
                    "record_type": r.record_type,
                    "record_id": r.record_id,
                    "number": r.number,
                    "currency": r.currency,
                    "batch_no": active.get((r.record_type, r.record_id)),
                }
                for r in records
            ],
        }
        out += [
            {
                "rule_id": x.rule_id,
                "severity": str(x.severity),
                "message": x.message,
                "element_ref": x.element_ref,
                "record_id": (x.details or {}).get("record_id"),
                "params": (x.details or {}).get("params", {}),
            }
            for x in await evaluate_export(snapshot, target_id=str(conn.id))
        ]
        return out

    @staticmethod
    def _doc_snapshot(d: SyncDocument, mapping: Any) -> dict[str, Any]:
        lines = build_journal(d, mapping)
        tax_id_valid = True
        if d.contact.tax_id and d.contact.country_code:
            try:
                from app.modules.subcontractors.tax_id import validate_tax_id

                res = validate_tax_id(d.contact.country_code, d.contact.tax_id)
                tax_id_valid = bool(res.format_valid) or res.standard is None
            except Exception:  # noqa: BLE001 - the check is advisory
                tax_id_valid = True
        return {
            "record_id": d.record_id,
            "number": d.number,
            "doc_date": d.doc_date.isoformat(),
            "currency": d.currency,
            "cost_centre": d.project_code,
            "project_code": d.project_code,
            "debit": str(sum((ln.debit for ln in lines), ZERO)),
            "credit": str(sum((ln.credit for ln in lines), ZERO)),
            "texts": [ln.description or d.contact.name for ln in d.lines],
            "tax_keys": [mapping.tax_key(ln.tax_code, d.tax_direction) or "" for ln in d.lines],
            "accounts": sorted({ln.account for ln in lines if ln.account}),
            "contact": {"name": d.contact.name, "tax_id": d.contact.tax_id, "tax_id_valid": tax_id_valid},
        }

    async def preview(self, conn: AccountingConnection, params: BatchParams) -> dict[str, Any]:
        self._check_params(params)
        records = await self.collect(conn, params)
        return self._summary(records, await self.findings(conn, params, records))

    @staticmethod
    def _summary(records: list[ExportRecord], findings: list[dict[str, Any]]) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        for r in records:
            by_type[r.record_type] = by_type.get(r.record_type, 0) + 1
        return {
            "row_count": len(records),
            "by_type": by_type,
            "total_net": str(sum((r.net for r in records), ZERO)),
            "total_tax": str(sum((r.tax for r in records), ZERO)),
            "total_gross": str(sum((r.gross for r in records), ZERO)),
            "findings": findings,
            "errors": sum(1 for f in findings if f["severity"] == "error"),
            "warnings": sum(1 for f in findings if f["severity"] == "warning"),
        }

    @staticmethod
    def _check_params(params: BatchParams) -> None:
        if params.fmt not in FORMATS:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"format must be one of {', '.join(FORMATS)}"
            )
        bad = [t for t in params.record_types if t not in RECORD_TYPES]
        if bad or not params.record_types:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"record_types must come from {', '.join(RECORD_TYPES)}"
            )
        if params.fmt in DOCUMENT_ONLY_FORMATS and set(params.record_types) - set(DOCUMENT_TYPES):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"{params.fmt} carries invoices and bills only"
            )
        if params.period[1] < params.period[0]:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="date_to is before date_from")

    # -- file ------------------------------------------------------------------

    async def build_file(
        self, conn: AccountingConnection, params: BatchParams, records: list[ExportRecord], created_at: datetime
    ) -> tuple[bytes, str, str]:
        stamp = f"{params.period[0]:%Y%m%d}_{params.period[1]:%Y%m%d}"
        if params.fmt in DOCUMENT_ONLY_FORMATS:
            docs = [r.document for r in records if r.document is not None]
            mapping = await self.sync.mapping(conn)
            if params.fmt == "journal":
                return journal.to_csv(journal_for(docs, mapping)), f"journal_{stamp}.csv", "text/csv; charset=utf-8"
            tpl = templates.get_template(conn.chart_template)
            settings = {**(conn.settings_ or {}), "account_length": tpl.get("account_length", 4)}
            accounts = personal_accounts(
                [d.contact for d in docs], tuple(tpl["debtor_range"]), tuple(tpl["creditor_range"])
            )
            for s in await self.suppliers(conn):
                for d in docs:
                    if d.contact.record_id == s.contact_id and s.external_account.isdigit():
                        accounts[f"{d.contact.kind}:{d.contact.record_id}"] = int(s.external_account)
            content = datev.buchungsstapel(
                docs,
                mapping,
                accounts,
                settings=settings,
                period=params.period,
                skr=tpl.get("skr", ""),
                currency=conn.base_currency,
                created_at=created_at,
            )
            return content, f"EXTF_Buchungsstapel_{stamp}.csv", "text/csv; charset=windows-1252"
        sup = {s.contact_id: s.external_account for s in await self.suppliers(conn)}
        rows = []
        for r in records:
            row = r.row()
            if r.document is not None:
                row[10] = sup.get(r.document.contact.record_id, "")
            rows.append(row)
        if params.fmt == "csv":
            buf = io.StringIO()
            w = csv.writer(buf, lineterminator="\r\n")
            w.writerow(GENERIC_COLUMNS)
            w.writerows(rows)
            return buf.getvalue().encode("utf-8"), f"export_{stamp}.csv", "text/csv; charset=utf-8"
        from openpyxl import Workbook

        wb = Workbook()
        wb.properties.created = created_at.replace(tzinfo=None)
        wb.properties.modified = created_at.replace(tzinfo=None)
        ws = wb.active
        ws.append(list(GENERIC_COLUMNS))
        for row in rows:
            ws.append([*row[:5], *(Decimal(x) for x in row[5:8]), *row[8:]])
        bio = io.BytesIO()
        wb.save(bio)
        return (
            bio.getvalue(),
            f"export_{stamp}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    # -- create / void ---------------------------------------------------------

    async def create(
        self, conn: AccountingConnection, params: BatchParams, *, key: str | None, user_id: str | None
    ) -> tuple[ExportBatch, bool]:
        """Create a batch. Returns ``(batch, created)``; a repeated key returns the first batch."""
        self._check_params(params)
        # Row lock on the connection serialises creates: one number sequence, one batch per key.
        await self.session.execute(
            select(AccountingConnection.id).where(AccountingConnection.id == conn.id).with_for_update()
        )
        if key:
            hit = (
                await self.session.execute(
                    select(ExportBatch).where(ExportBatch.connection_id == conn.id, ExportBatch.idempotency_key == key)
                )
            ).scalar_one_or_none()
            if hit is not None:
                return hit, False
        records = await self.collect(conn, params)
        if not records:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Nothing to export in this period")
        errors = [f for f in await self.findings(conn, params, records) if f["severity"] == "error"]
        if errors:
            code = (
                status.HTTP_409_CONFLICT
                if all(f["rule_id"] == ALREADY_EXPORTED for f in errors)
                else status.HTTP_422_UNPROCESSABLE_CONTENT
            )
            raise HTTPException(code, detail={"message": "Export blocked by findings", "findings": errors})
        created_at = datetime.now(UTC)
        content, name, media = await self.build_file(conn, params, records, created_at)
        last = (
            await self.session.execute(
                select(func.max(ExportBatch.batch_no)).where(ExportBatch.connection_id == conn.id)
            )
        ).scalar_one()
        batch = ExportBatch(
            connection_id=conn.id,
            batch_no=int(last or 0) + 1,
            format=params.fmt,
            period_from=params.period[0],
            period_to=params.period[1],
            record_types=list(params.record_types),
            row_count=len(records),
            total_net=sum((r.net for r in records), ZERO),
            total_tax=sum((r.tax for r in records), ZERO),
            total_gross=sum((r.gross for r in records), ZERO),
            sha256=hashlib.sha256(content).hexdigest(),
            status="exported",
            idempotency_key=key or None,
            file_name=name,
            media_type=media,
            content=content,
            created_by=user_id,
        )
        self.session.add(batch)
        try:
            await self.session.flush()
            self.session.add_all(
                BatchItem(
                    batch_id=batch.id,
                    connection_id=conn.id,
                    record_type=r.record_type,
                    record_id=r.record_id,
                    payload_hash=r.payload_hash(),
                )
                for r in records
            )
            await self.session.flush()
        except IntegrityError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="A record is already in an active batch") from exc
        await self.sync._log(  # noqa: SLF001
            conn,
            action="export",
            record_type=f"batch_{params.fmt}",
            label=f"#{batch.batch_no} {name}",
            status_="success",
            amount=batch.total_gross,
            details={"batch_id": str(batch.id), "rows": len(records)},
        )
        self._publish("accounting_sync.batch.exported", conn, batch)
        return batch, True

    async def get(self, conn: AccountingConnection, batch_id: uuid.UUID) -> ExportBatch:
        batch = await self.session.get(ExportBatch, batch_id)
        if batch is None or batch.connection_id != conn.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Batch not found")
        return batch

    async def page(self, conn: AccountingConnection, *, offset: int, limit: int) -> tuple[list[ExportBatch], int]:
        where = ExportBatch.connection_id == conn.id
        total = (await self.session.execute(select(func.count()).select_from(ExportBatch).where(where))).scalar_one()
        rows = await self.session.execute(
            select(ExportBatch).where(where).order_by(ExportBatch.batch_no.desc()).offset(offset).limit(limit)
        )
        return list(rows.scalars()), int(total)

    async def void(
        self, conn: AccountingConnection, batch: ExportBatch, reason: str, user_id: str | None
    ) -> ExportBatch:
        if batch.status == "voided":
            return batch
        if batch.status == "confirmed":
            raise HTTPException(status.HTTP_409_CONFLICT, detail="A confirmed batch is closed and cannot be voided")
        batch.status = "voided"
        batch.void_reason = reason.strip()
        batch.voided_by = user_id
        await self.session.execute(update(BatchItem).where(BatchItem.batch_id == batch.id).values(active=False))
        await self.session.flush()
        self._publish("accounting_sync.batch.voided", conn, batch, reason=batch.void_reason)
        return batch

    async def confirm(self, batch: ExportBatch) -> ExportBatch:
        if batch.status == "voided":
            raise HTTPException(status.HTTP_409_CONFLICT, detail="A voided batch cannot be confirmed")
        batch.status = "confirmed"
        await self.session.flush()
        return batch

    @staticmethod
    def _publish(event: str, conn: AccountingConnection, batch: ExportBatch, **extra: Any) -> None:
        from app.core.events import event_bus

        try:
            event_bus.publish_detached(
                event,
                {"connection_id": str(conn.id), "batch_id": str(batch.id), "batch_no": batch.batch_no, **extra},
                source_module="accounting_sync",
            )
        except Exception:  # noqa: BLE001 - an event never breaks the export
            logger.warning("%s not published", event, exc_info=True)

# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Haul​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ tickets business logic.

A ticket's derived numbers (missing weight, quantity in its unit, amount) are
recomputed on every write from what the person entered, so the stored figures
never drift from the inputs. Verified and invoiced tickets are the only ones
that count as actuals.
"""

from __future__ import annotations

import csv
import io
import secrets
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.haul_tickets import importer, logic
from app.modules.haul_tickets.models import HaulInvoice, HaulMaterial, HaulRate, HaulSettings, HaulTicket
from app.modules.haul_tickets.repository import HaulRepository
from app.modules.haul_tickets.schemas import InvoiceIn, MaterialIn, RateIn, SettingsIn, TicketCreate, TicketUpdate
from app.modules.haul_tickets.validators import INVOICE_RULE_SET, evaluate

MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_PHOTO_BYTES = 8 * 1024 * 1024
_IMPORT_EXT = (".csv", ".txt", ".xlsx", ".xlsm")
_PHOTO_EXT = (".jpg", ".jpeg", ".png", ".webp", ".heic")


def _snapshot_value(v: Any) -> Any:
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, datetime | date):
        return v.isoformat()
    return v


def ticket_snapshot(row: HaulTicket) -> dict[str, Any]:
    cols = [c.key for c in HaulTicket.__table__.columns]
    data = {c: _snapshot_value(getattr(row, "metadata_" if c == "metadata" else c, None)) for c in cols}
    data.pop("metadata", None)
    return data


def settings_snapshot(s: HaulSettings | None) -> dict[str, Any]:
    if s is None:
        return {"mandatory_fields": [], "max_gross_t": None, "capacity_tolerance_pct": 10, "price_tolerance_pct": 1}
    return {
        "mandatory_fields": list(s.mandatory_fields or []),
        "max_gross_t": str(s.max_gross_t) if s.max_gross_t is not None else None,
        "capacity_tolerance_pct": s.capacity_tolerance_pct,
        "price_tolerance_pct": s.price_tolerance_pct,
    }


class HaulTicketService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = HaulRepository(session)

    # ── tickets ───────────────────────────────────────────────────────────
    async def get(self, ticket_id: uuid.UUID) -> HaulTicket:
        row = await self.repo.get_ticket(ticket_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
        return row

    async def list(self, project_id: uuid.UUID, **filters: Any) -> list[HaulTicket]:
        return await self.repo.list_tickets(project_id, **filters)

    async def _density(self, project_id: uuid.UUID, code: str) -> Decimal | None:
        if not code:
            return None
        for m in await self.repo.materials(project_id):
            if m.code == code:
                return m.density_t_m3
        builtin = next((m for m in logic.DEFAULT_MATERIALS if m["code"] == code), None)
        return logic.dec(builtin.get("density_t_m3")) if builtin else None

    async def _find_rate(self, row: HaulTicket) -> HaulRate | None:
        if not row.haulier_name:
            return None
        candidates = [r for r in await self.repo.rates(row.project_id) if r.haulier_name == row.haulier_name]
        exact = [r for r in candidates if r.material_code == row.material_code]
        generic = [r for r in candidates if not r.material_code]
        return (exact or generic or [None])[0]

    async def recompute(self, row: HaulTicket) -> None:
        w = logic.resolve_weights(row.gross_t, row.tare_t, row.net_t)
        row.gross_t, row.tare_t, row.net_t = w.gross, w.tare, w.net
        density = await self._density(row.project_id, row.material_code)
        row.quantity = logic.quantity_in_unit(
            row.unit, net_t=row.net_t, volume_m3=row.volume_m3, loads=row.loads, density=density
        )
        volume = row.volume_m3
        if volume is None and row.net_t is not None and density:
            volume = row.net_t / density
        billable = logic.billable_quantity(
            row.rate_basis, net_t=row.net_t, volume_m3=volume, loads=row.loads, hours=row.hours
        )
        row.amount = logic.amount(row.rate, billable)
        if row.haul_type == "waste" and row.waste_code:
            entry = logic.waste_entry(row.waste_catalogue, row.waste_code)
            if entry is not None and entry.get("hazardous"):
                row.hazardous = True

    async def _project_currency(self, project_id: uuid.UUID) -> str:
        from app.modules.projects.models import Project

        project = await self.session.get(Project, project_id)
        return (getattr(project, "currency", "") or "") if project else ""

    async def create(self, data: TicketCreate, user_id: str | None) -> tuple[HaulTicket, bool]:
        """Create a ticket; returns ``(row, created)`` - False when the client op id was seen before."""
        from app.core.offline_merge import find_by_client_op_id, stamp_client_op_id

        earlier = await find_by_client_op_id(
            self.session, HaulTicket, data.client_op_id, HaulTicket.project_id == data.project_id
        )
        if earlier is not None:
            return earlier, False
        fields = data.model_dump(exclude={"client_op_id", "project_id", "source"})
        row = HaulTicket(project_id=data.project_id, source=data.source, created_by=user_id, **fields)
        row.ticket_date = data.ticket_date or (data.time_out.date() if data.time_out else date.today())
        row.qr_token = secrets.token_urlsafe(18)
        row.photos = []
        row.metadata_ = {}
        if row.signature:
            row.signed_at = datetime.now(UTC)
        await self._apply_rate_defaults(row)
        await self.recompute(row)
        await self.repo.add(row)
        await stamp_client_op_id(self.session, row, data.client_op_id)
        return row, True

    async def _apply_rate_defaults(self, row: HaulTicket) -> None:
        if row.rate is None and row.truck_source == "hired":
            rate = await self._find_rate(row)
            if rate is not None:
                row.rate, row.rate_basis = rate.rate, rate.rate_basis
                row.po_id = row.po_id or rate.po_id
                row.currency = row.currency or rate.currency
        if not row.currency:
            s = await self.repo.settings(row.project_id)
            row.currency = (s.currency if s and s.currency else "") or await self._project_currency(row.project_id)

    def _ensure_editable(self, row: HaulTicket) -> None:
        if row.status in ("verified", "invoiced"):
            raise HTTPException(status.HTTP_409_CONFLICT, "A verified ticket is locked; return it to delivered first.")

    async def update(self, row: HaulTicket, data: TicketUpdate) -> HaulTicket:
        self._ensure_editable(row)
        changes = data.model_dump(exclude_unset=True)
        for key, value in changes.items():
            setattr(row, key, value)
        if "signature" in changes:
            row.signed_at = datetime.now(UTC) if row.signature else None
        await self._apply_rate_defaults(row)
        await self.recompute(row)
        await self.session.flush()
        return row

    async def delete(self, row: HaulTicket) -> None:
        if row.status == "invoiced":
            raise HTTPException(status.HTTP_409_CONFLICT, "An invoiced ticket cannot be deleted.")
        await self.repo.delete(row)

    async def findings(self, row: HaulTicket) -> list[Any]:
        snapshot = {
            "ticket": ticket_snapshot(row),
            "settings": settings_snapshot(await self.repo.settings(row.project_id)),
            "same_number_count": await self.repo.same_number_count(row),
        }
        return await evaluate(snapshot, target_id=str(row.id))

    async def transition(
        self,
        row: HaulTicket,
        target: str,
        *,
        reason: str = "",
        receiver_name: str | None = None,
        signature: str | None = None,
    ) -> HaulTicket:
        if not logic.can_transition(row.status, target):
            raise HTTPException(status.HTTP_409_CONFLICT, f"A {row.status} ticket cannot become {target}.")
        if target == "rejected":
            if not reason.strip():
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Give a reason for the rejection.")
            row.reject_reason = reason.strip()
        if target == "issued":
            row.reject_reason = ""
        if receiver_name is not None:
            row.receiver_name = receiver_name
        if signature:
            row.signature = signature
            row.signed_at = datetime.now(UTC)
        if target == "delivered" and row.time_in is None:
            row.time_in = datetime.now(UTC)
        previous = row.status
        row.status = target
        if target == "verified":
            errors = [f for f in await self.findings(row) if str(f.severity) == "error"]
            if errors:
                row.status = previous
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    {"code": "validation_failed", "message": "; ".join(f.message for f in errors)},
                )
        await self.session.flush()
        return row

    async def scan(self, project_id: uuid.UUID, code: str) -> dict[str, Any]:
        """Resolve a scanned code: a ticket QR opens the ticket, anything else is read as a truck card."""
        text = (code or "").strip()
        token = text.rsplit("/", 1)[-1]
        row = await self.repo.by_token(token) if token else None
        if row is not None and row.project_id == project_id:
            return {"kind": "ticket", "ticket_id": str(row.id)}
        plate = text.removeprefix("TRUCK:").strip().upper()
        last = (
            await self.session.execute(
                select(HaulTicket)
                .where(HaulTicket.project_id == project_id, func.upper(HaulTicket.plate) == plate)
                .order_by(HaulTicket.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        prefill: dict[str, Any] = {"plate": plate}
        if last is not None:
            for key in (
                "haulier_name",
                "haulier_party_id",
                "driver_name",
                "truck_source",
                "equipment_id",
                "vehicle_max_gross_t",
                "vehicle_capacity",
                "tare_t",
                "material_code",
                "material_name",
                "unit",
                "haul_type",
                "origin",
                "origin_kind",
                "destination",
                "destination_kind",
                "rate_basis",
                "rate",
                "boq_position_id",
                "cost_code",
                "po_id",
            ):
                prefill[key] = _snapshot_value(getattr(last, key))
        return {"kind": "truck", "prefill": prefill}

    async def add_photo(self, row: HaulTicket, file: UploadFile) -> HaulTicket:
        name = (file.filename or "photo.jpg").strip()[:120]
        if not name.lower().endswith(_PHOTO_EXT):
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Unsupported photo type")
        payload = await file.read(MAX_PHOTO_BYTES + 1)
        if not payload or len(payload) > MAX_PHOTO_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "The photo is empty or too large.")
        from app.core.storage import get_storage_backend

        photo_id = uuid.uuid4().hex
        key = f"haul-tickets/{row.project_id}/{row.id}/{photo_id}-{name}"
        await get_storage_backend().put(key, payload)
        row.photos = [*(row.photos or []), {"id": photo_id, "name": name, "key": key}]
        await self.session.flush()
        return row

    async def photo_bytes(self, row: HaulTicket, photo_id: str) -> tuple[bytes, str]:
        photo = next((p for p in row.photos or [] if p.get("id") == photo_id), None)
        if photo is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
        from app.core.storage import get_storage_backend

        return await get_storage_backend().get(photo["key"]), photo["name"]

    # ── expected deliveries (site logistics) ──────────────────────────────
    async def expected(
        self, project_id: uuid.UUID, day: date, *, offset: int = 0, limit: int = 200
    ) -> tuple[list[dict[str, Any]], int]:
        try:
            from app.modules.site_logistics.models import DeliveryBooking
        except ImportError:
            return [], 0
        start = datetime.combine(day, time.min, tzinfo=UTC)
        stmt = (
            select(DeliveryBooking)
            .where(
                DeliveryBooking.project_id == project_id,
                DeliveryBooking.window_start >= start - timedelta(hours=14),
                DeliveryBooking.window_start < start + timedelta(days=1, hours=14),
                DeliveryBooking.status.notin_(("cancelled", "rejected")),
            )
            .order_by(DeliveryBooking.window_start)
        )
        # The 14 h margin is a time zone allowance, so the calendar-day cut happens here, before paging.
        day_bookings = [b for b in (await self.session.execute(stmt)).scalars().all() if b.window_start.date() == day]
        bookings = day_bookings[offset : offset + limit]
        ticketed = set(
            (
                await self.session.execute(
                    select(HaulTicket.delivery_id).where(
                        HaulTicket.project_id == project_id,
                        HaulTicket.delivery_id.in_([b.id for b in bookings]),
                    )
                )
            ).scalars()
        )
        items = [
            {
                "delivery_id": b.id,
                "supplier_name": b.supplier_name,
                "window_start": b.window_start,
                "window_end": b.window_end,
                "vehicle_type": b.vehicle_type,
                "materials_desc": b.materials_desc,
                "po_ref": b.po_ref,
                "direction": b.direction or "inbound",
                "gross_weight_t": str(b.gross_weight_t) if b.gross_weight_t is not None else None,
                "transport_id": b.transport_id,
                "ticketed": b.id in ticketed,
            }
            for b in bookings
        ]
        return items, len(day_bookings)

    # ── weighbridge import ────────────────────────────────────────────────
    async def _read_upload(self, file: UploadFile) -> tuple[list[str], list[list[str]]]:
        name = (file.filename or "").lower()
        if not name.endswith(_IMPORT_EXT):
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Upload a CSV or Excel file.")
        payload = await file.read(MAX_IMPORT_BYTES + 1)
        if not payload or len(payload) > MAX_IMPORT_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "The file is empty or too large.")
        try:
            return importer.read_table(payload, name)
        except Exception as exc:  # noqa: BLE001 - any parser failure is a bad file for the user
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file could not be read.") from exc

    async def import_preview(
        self, project_id: uuid.UUID, file: UploadFile, mapping: dict[str, int] | None, weights_in_kg: bool
    ) -> dict[str, Any]:
        headers, rows = await self._read_upload(file)
        used = mapping or importer.suggest_mapping(headers)
        drafts = importer.map_rows(headers, rows, used, weights_in_kg=weights_in_kg)
        importer.mark_duplicates(drafts, await self.repo.dedupe_rows(project_id))
        return {
            "headers": headers,
            "mapping": used,
            "target_fields": list(importer.TARGET_FIELDS),
            "rows": [{k: _snapshot_value(v) for k, v in d.items()} for d in drafts[:200]],
            "total": len(drafts),
            "duplicates": sum(1 for d in drafts if d.get("duplicate")),
        }

    async def import_commit(
        self,
        project_id: uuid.UUID,
        file: UploadFile,
        mapping: dict[str, int],
        *,
        weights_in_kg: bool,
        defaults: dict[str, Any],
        user_id: str | None,
    ) -> dict[str, Any]:
        headers, rows = await self._read_upload(file)
        drafts = importer.mark_duplicates(
            importer.map_rows(headers, rows, mapping, weights_in_kg=weights_in_kg),
            await self.repo.dedupe_rows(project_id),
        )
        created: list[uuid.UUID] = []
        skipped = 0
        batch = uuid.uuid4().hex[:12]
        for d in drafts:
            if d.pop("duplicate", None):
                skipped += 1
                continue
            payload = {k: v for k, v in d.items() if v not in (None, "")}
            merged = {**defaults, **payload}
            try:
                data = TicketCreate(project_id=project_id, source="import", **merged)
            except ValueError:
                skipped += 1
                continue
            row, _ = await self.create(data, user_id)
            row.metadata_ = {**(row.metadata_ or {}), "import_batch": batch}
            created.append(row.id)
        await self.session.flush()
        return {"created": len(created), "skipped_duplicates": skipped, "ticket_ids": created}

    # ── summaries ─────────────────────────────────────────────────────────
    async def summary(
        self, project_id: uuid.UUID, group_by: str, date_from: date | None, date_to: date | None, only_counted: bool
    ) -> dict[str, Any]:
        rows = await self.repo.list_tickets(project_id, date_from=date_from, date_to=date_to)
        rows = [r for r in rows if r.status != "rejected" and (not only_counted or r.status in logic.COUNTED_STATUSES)]
        groups: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"loads": 0, "tonnes": logic.ZERO, "volume_m3": logic.ZERO, "amount": logic.ZERO, "tickets": 0}
        )
        labels: dict[str, str] = {}
        for r in rows:
            if group_by == "haulier":
                key = r.haulier_name or ("own" if r.truck_source == "own" else "")
                labels[key] = key
            elif group_by == "material":
                key = r.material_code or r.material_name
                labels[key] = r.material_name or key
            elif group_by == "haul_type":
                key = labels.setdefault(r.haul_type, r.haul_type)
            else:
                key = r.ticket_date.isoformat()
                labels[key] = key
            g = groups[key]
            g["loads"] += r.loads or 0
            g["tonnes"] += r.net_t or logic.ZERO
            g["volume_m3"] += r.volume_m3 or logic.ZERO
            g["amount"] += r.amount or logic.ZERO
            g["tickets"] += 1
        out = [{"key": k, "label": labels.get(k, k), **v} for k, v in sorted(groups.items())]
        totals = {
            "key": "total",
            "label": "total",
            "loads": sum(g["loads"] for g in out),
            "tonnes": sum((g["tonnes"] for g in out), logic.ZERO),
            "volume_m3": sum((g["volume_m3"] for g in out), logic.ZERO),
            "amount": sum((g["amount"] for g in out), logic.ZERO),
            "tickets": sum(g["tickets"] for g in out),
        }
        return {"group_by": group_by, "rows": out, "totals": totals}

    # ── invoices ──────────────────────────────────────────────────────────
    async def create_invoice(self, data: InvoiceIn, user_id: str | None) -> HaulInvoice:
        lines = [line.model_dump(mode="json") for line in data.lines]
        total = sum((logic.dec(line.get("amount")) or logic.ZERO for line in lines), logic.ZERO)
        row = HaulInvoice(
            project_id=data.project_id,
            haulier_name=data.haulier_name,
            invoice_number=data.invoice_number,
            invoice_date=data.invoice_date,
            period_from=data.period_from,
            period_to=data.period_to,
            currency=data.currency,
            total=total.quantize(logic.MONEY_Q),
            lines=lines,
            status="open",
            result={},
            created_by=user_id,
        )
        await self.repo.add(row)
        return await self.reconcile(row)

    async def get_invoice(self, invoice_id: uuid.UUID) -> HaulInvoice:
        row = await self.session.get(HaulInvoice, invoice_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found")
        return row

    async def reconcile(self, inv: HaulInvoice) -> HaulInvoice:
        tickets = await self.repo.list_tickets(
            inv.project_id, date_from=inv.period_from, date_to=inv.period_to, haulier=inv.haulier_name
        )
        settings = await self.repo.settings(inv.project_id)
        pct = Decimal(settings.price_tolerance_pct if settings else 1)
        ticket_rows = []
        for t in tickets:
            if t.invoice_id is not None and t.invoice_id != inv.id:
                continue
            volume = t.volume_m3
            billable = logic.billable_quantity(
                t.rate_basis, net_t=t.net_t, volume_m3=volume, loads=t.loads, hours=t.hours
            )
            ticket_rows.append(
                {
                    "id": t.id,
                    "ticket_number": t.ticket_number,
                    "status": t.status,
                    "quantity": billable,
                    "rate": t.rate,
                    "amount": t.amount,
                    "invoice_id": None,
                }
            )
        result = logic.reconcile(inv.lines or [], ticket_rows, price_tolerance_pct=pct)
        inv.result = result.as_dict()
        if inv.status != "accepted":
            inv.status = "reconciled" if result.clean else "discrepancies"
        await self.session.flush()
        return inv

    async def invoice_findings(self, inv: HaulInvoice) -> list[Any]:
        return await evaluate(
            {"lines": (inv.result or {}).get("lines", [])}, rule_set=INVOICE_RULE_SET, target_id=str(inv.id)
        )

    async def accept_invoice(self, inv: HaulInvoice) -> HaulInvoice:
        """Mark the matched verified tickets as invoiced; lines without a ticket block acceptance."""
        if inv.status == "accepted":
            return inv
        inv = await self.reconcile(inv)
        if any(f for f in await self.invoice_findings(inv) if str(f.severity) == "error"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Some invoice lines have no ticket.")
        ids = [
            uuid.UUID(line["ticket_id"])
            for line in inv.result.get("lines", [])
            if line.get("ticket_id") and line.get("status") in ("matched", "overpriced", "quantity_mismatch")
        ]
        for tid in ids:
            t = await self.repo.get_ticket(tid)
            if t is not None and t.status == "verified":
                t.status = "invoiced"
                t.invoice_id = inv.id
        inv.status = "accepted"
        await self.session.flush()
        return inv

    # ── disposal register ─────────────────────────────────────────────────
    async def disposal_rows(self, project_id: uuid.UUID, date_from: date | None, date_to: date | None) -> list[dict]:
        rows = await self.repo.list_tickets(project_id, date_from=date_from, date_to=date_to, haul_type="waste")
        return [
            {
                "ticket_date": r.ticket_date.isoformat(),
                "ticket_number": r.ticket_number,
                "waste_catalogue": r.waste_catalogue or "generic",
                "waste_code": r.waste_code,
                "hazardous": "yes" if r.hazardous else "no",
                "material": r.material_name or r.material_code,
                "net_t": str(r.net_t) if r.net_t is not None else "",
                "volume_m3": str(r.volume_m3) if r.volume_m3 is not None else "",
                "haulier": r.haulier_name,
                "plate": r.plate,
                "origin": r.origin,
                "receiving_facility": r.receiving_facility,
                "facility_permit_ref": r.facility_permit_ref,
                "status": r.status,
            }
            for r in sorted(rows, key=lambda r: (r.ticket_date, r.ticket_number))
            if r.status != "rejected"
        ]

    @staticmethod
    def disposal_csv(rows: list[dict]) -> str:
        buf = io.StringIO()
        if rows:
            writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        return buf.getvalue()

    # ── settings, rates, materials ────────────────────────────────────────
    async def get_settings(self, project_id: uuid.UUID) -> HaulSettings:
        s = await self.repo.settings(project_id)
        return s or HaulSettings(
            project_id=project_id,
            mandatory_fields=[],
            capacity_tolerance_pct=10,
            price_tolerance_pct=1,
            waste_catalogue="",
            currency="",
        )

    async def save_settings(self, project_id: uuid.UUID, data: SettingsIn) -> HaulSettings:
        unknown = [f for f in data.mandatory_fields if f not in logic.MANDATORY_CANDIDATES]
        if unknown:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown fields: {', '.join(unknown)}")
        s = await self.repo.settings(project_id)
        if s is None:
            s = await self.repo.add(HaulSettings(project_id=project_id))
        for key, value in data.model_dump().items():
            setattr(s, key, value)
        await self.session.flush()
        return s

    async def add_rate(self, project_id: uuid.UUID, data: RateIn) -> HaulRate:
        return await self.repo.add(HaulRate(project_id=project_id, **data.model_dump()))

    async def delete_rate(self, project_id: uuid.UUID, rate_id: uuid.UUID) -> None:
        row = await self.session.get(HaulRate, rate_id)
        if row is None or row.project_id != project_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Rate not found")
        await self.repo.delete(row)

    async def materials(
        self, project_id: uuid.UUID, *, offset: int = 0, limit: int = 200
    ) -> tuple[list[dict[str, Any]], int]:
        """Project materials first, then the built-in ones they do not override; paged as one list."""
        own_codes = await self.repo.material_codes(project_id)
        builtin = [m for m in logic.DEFAULT_MATERIALS if m["code"] not in set(own_codes)]
        own_total = len(own_codes)
        own = await self.repo.materials(project_id, offset=offset, limit=limit)
        out = [
            {
                "id": m.id,
                "code": m.code,
                "name": m.name,
                "unit": m.unit,
                "haul_type": m.haul_type,
                "density_t_m3": m.density_t_m3,
                "waste_code": m.waste_code,
                "builtin": False,
            }
            for m in own
        ]
        start = max(0, offset - own_total)
        room = limit - len(own)
        if room > 0:
            out += [
                {**m, "density_t_m3": logic.dec(m.get("density_t_m3")), "waste_code": "", "builtin": True}
                for m in builtin[start : start + room]
            ]
        return out, own_total + len(builtin)

    async def add_material(self, project_id: uuid.UUID, data: MaterialIn) -> HaulMaterial:
        return await self.repo.add(HaulMaterial(project_id=project_id, **data.model_dump()))


async def haul_by_position(
    session: AsyncSession, project_id: uuid.UUID, position_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[Decimal, Decimal]]:
    """Verified haul quantity and cost per BOQ position, for the position actuals."""
    if not position_ids:
        return {}
    stmt = (
        select(HaulTicket.boq_position_id, func.sum(HaulTicket.quantity), func.sum(HaulTicket.amount))
        .where(
            HaulTicket.project_id == project_id,
            HaulTicket.status.in_(logic.COUNTED_STATUSES),
            HaulTicket.boq_position_id.in_(position_ids),
        )
        .group_by(HaulTicket.boq_position_id)
    )
    return {r[0]: (Decimal(str(r[1] or 0)), Decimal(str(r[2] or 0))) for r in (await session.execute(stmt)).all()}

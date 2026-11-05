# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Haul​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ tickets API routes (mounted at ``/api/v1/haul-tickets``).

Every handler checks project access first, then the module permission.
Verification needs ``haul_tickets.verify`` and is gated by the validation rules.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    get_current_user_payload,
    verify_project_access,
)
from app.modules.haul_tickets import logic
from app.modules.haul_tickets.models import HaulInvoice, HaulTicket
from app.modules.haul_tickets.schemas import (
    ExpectedDeliveryListResponse,
    ExpectedDeliveryOut,
    FindingOut,
    ImportCommitOut,
    ImportPreviewOut,
    InvoiceIn,
    InvoiceListResponse,
    InvoiceOut,
    MaterialIn,
    MaterialListResponse,
    MaterialOut,
    RateIn,
    RateListResponse,
    RateOut,
    SettingsIn,
    SettingsOut,
    SummaryOut,
    TicketCreate,
    TicketListResponse,
    TicketOut,
    TicketUpdate,
    TransitionRequest,
)
from app.modules.haul_tickets.service import HaulTicketService

router = APIRouter(tags=["haul_tickets"])
_READ = Depends(RequirePermission("haul_tickets.read"))
_WRITE = Depends(RequirePermission("haul_tickets.write"))
_VERIFY = Depends(RequirePermission("haul_tickets.verify"))


def _findings(items: list[Any]) -> list[FindingOut]:
    return [
        FindingOut(rule_id=f.rule_id, severity=str(f.severity), message=f.message, element_ref=f.element_ref)
        for f in items
    ]


def _out(row: HaulTicket, findings: list[Any] | None = None) -> TicketOut:
    base = TicketOut.model_validate(row)
    photos = [{"id": p.get("id"), "name": p.get("name")} for p in row.photos or []]
    return base.model_copy(
        update={"has_signature": bool(row.signature), "photos": photos, "findings": _findings(findings or [])}
    )


async def _load(ticket_id: uuid.UUID, session: SessionDep, user_id: str) -> tuple[HaulTicketService, HaulTicket]:
    svc = HaulTicketService(session)
    row = await svc.get(ticket_id)
    await verify_project_access(row.project_id, user_id, session)
    return svc, row


async def _detail(svc: HaulTicketService, row: HaulTicket) -> TicketOut:
    return _out(row, await svc.findings(row))


@router.get("/projects/{project_id}/tickets", response_model=TicketListResponse, dependencies=[_READ])
async def list_tickets(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    haulier: str | None = Query(default=None),
    haul_type: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> TicketListResponse:
    await verify_project_access(project_id, user_id, session)
    rows = await HaulTicketService(session).list(
        project_id,
        date_from=date_from,
        date_to=date_to,
        status=status_filter,
        haulier=haulier,
        haul_type=haul_type,
        search=q,
    )
    return TicketListResponse(
        items=[_out(r) for r in rows[offset : offset + limit]], total=len(rows), offset=offset, limit=limit
    )


@router.post("/tickets/", response_model=TicketOut, status_code=201, dependencies=[_WRITE])
async def create_ticket(
    data: TicketCreate, response: Response, session: SessionDep, user_id: CurrentUserId
) -> TicketOut:
    await verify_project_access(data.project_id, user_id, session)
    svc = HaulTicketService(session)
    row, created = await svc.create(data, user_id)
    if not created:
        response.status_code = status.HTTP_200_OK
    return await _detail(svc, row)


@router.get("/tickets/{ticket_id}", response_model=TicketOut, dependencies=[_READ])
async def get_ticket(ticket_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> TicketOut:
    svc, row = await _load(ticket_id, session, user_id)
    return await _detail(svc, row)


@router.patch("/tickets/{ticket_id}", response_model=TicketOut, dependencies=[_WRITE])
async def update_ticket(
    ticket_id: uuid.UUID, data: TicketUpdate, session: SessionDep, user_id: CurrentUserId
) -> TicketOut:
    svc, row = await _load(ticket_id, session, user_id)
    row = await svc.update(row, data)
    return await _detail(svc, row)


@router.delete("/tickets/{ticket_id}", status_code=204, dependencies=[_WRITE])
async def delete_ticket(ticket_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    svc, row = await _load(ticket_id, session, user_id)
    await svc.delete(row)
    return Response(status_code=204)


@router.post("/tickets/{ticket_id}/status", response_model=TicketOut, dependencies=[_WRITE])
async def transition_ticket(
    ticket_id: uuid.UUID,
    data: TransitionRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    payload: dict = Depends(get_current_user_payload),
) -> TicketOut:
    svc, row = await _load(ticket_id, session, user_id)
    if data.status in ("verified", "invoiced"):
        await RequirePermission("haul_tickets.verify")(payload)
    row = await svc.transition(
        row, data.status, reason=data.reason, receiver_name=data.receiver_name, signature=data.signature
    )
    return await _detail(svc, row)


@router.post("/tickets/{ticket_id}/photos", response_model=TicketOut, dependencies=[_WRITE])
async def upload_photo(
    ticket_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, file: UploadFile = File(...)
) -> TicketOut:
    svc, row = await _load(ticket_id, session, user_id)
    row = await svc.add_photo(row, file)
    return await _detail(svc, row)


@router.get("/tickets/{ticket_id}/photos/{photo_id}", dependencies=[_READ])
async def get_photo(ticket_id: uuid.UUID, photo_id: str, session: SessionDep, user_id: CurrentUserId) -> Response:
    svc, row = await _load(ticket_id, session, user_id)
    payload, name = await svc.photo_bytes(row, photo_id)
    media = "image/png" if name.lower().endswith(".png") else "image/jpeg"
    return Response(content=payload, media_type=media, headers={"Cache-Control": "private, max-age=600"})


@router.get("/tickets/{ticket_id}/pdf", dependencies=[_READ])
async def ticket_pdf(ticket_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    from app.modules.haul_tickets.pdf import render_ticket_pdf
    from app.modules.projects.models import Project

    _svc, row = await _load(ticket_id, session, user_id)
    project = await session.get(Project, row.project_id)
    pdf = render_ticket_pdf(row, project_name=getattr(project, "name", "") or "")
    name = f"haul-ticket-{row.ticket_number or row.id}.pdf".replace(" ", "_")
    return Response(
        content=pdf,
        media_type="application/pdf",
        # The ticket's default labels are in English whatever the reader asked for.
        headers={"Content-Disposition": f'inline; filename="{name}"', "Content-Language": "en"},
    )


@router.get("/projects/{project_id}/scan", dependencies=[_READ])
async def scan(
    project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId, code: str = Query(max_length=200)
) -> dict:
    await verify_project_access(project_id, user_id, session)
    return await HaulTicketService(session).scan(project_id, code)


@router.get("/projects/{project_id}/expected", response_model=ExpectedDeliveryListResponse, dependencies=[_READ])
async def expected(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    day: date | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
) -> ExpectedDeliveryListResponse:
    await verify_project_access(project_id, user_id, session)
    rows, total = await HaulTicketService(session).expected(project_id, day or date.today(), offset=offset, limit=limit)
    return ExpectedDeliveryListResponse(
        items=[ExpectedDeliveryOut.model_validate(r) for r in rows], total=total, offset=offset, limit=limit
    )


def _mapping(raw: str | None) -> dict[str, int] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return {str(k): int(v) for k, v in data.items() if v is not None and int(v) >= 0}
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid column mapping") from exc


@router.post("/projects/{project_id}/import/preview", response_model=ImportPreviewOut, dependencies=[_WRITE])
async def import_preview(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    file: UploadFile = File(...),
    mapping: str | None = Form(default=None),
    weights_in_kg: bool = Form(default=False),
) -> dict:
    await verify_project_access(project_id, user_id, session)
    return await HaulTicketService(session).import_preview(project_id, file, _mapping(mapping), weights_in_kg)


@router.post("/projects/{project_id}/import/commit", response_model=ImportCommitOut, dependencies=[_WRITE])
async def import_commit(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    file: UploadFile = File(...),
    mapping: str = Form(...),
    weights_in_kg: bool = Form(default=False),
    defaults: str | None = Form(default=None),
) -> dict:
    await verify_project_access(project_id, user_id, session)
    try:
        extra = json.loads(defaults) if defaults else {}
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid defaults") from exc
    allowed = {
        "haul_type",
        "unit",
        "truck_source",
        "rate_basis",
        "boq_position_id",
        "cost_code",
        "direction",
        "haulier_name",
    }
    return await HaulTicketService(session).import_commit(
        project_id,
        file,
        _mapping(mapping) or {},
        weights_in_kg=weights_in_kg,
        defaults={k: v for k, v in (extra or {}).items() if k in allowed},
        user_id=user_id,
    )


@router.get("/projects/{project_id}/summary", response_model=SummaryOut, dependencies=[_READ])
async def summary(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    group_by: Literal["day", "haulier", "material", "haul_type"] = Query(default="day"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    verified_only: bool = Query(default=False),
) -> dict:
    await verify_project_access(project_id, user_id, session)
    return await HaulTicketService(session).summary(project_id, group_by, date_from, date_to, verified_only)


@router.get("/projects/{project_id}/disposal-register", dependencies=[_READ])
async def disposal_register(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    fmt: Literal["json", "csv"] = Query(default="json", alias="format"),
) -> Any:
    await verify_project_access(project_id, user_id, session)
    svc = HaulTicketService(session)
    rows = await svc.disposal_rows(project_id, date_from, date_to)
    if fmt == "csv":
        return Response(
            content=svc.disposal_csv(rows),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="disposal-register.csv"'},
        )
    return {"items": rows, "total": len(rows)}


# ── invoices ──────────────────────────────────────────────────────────────


async def _invoice_out(svc: HaulTicketService, inv: HaulInvoice) -> InvoiceOut:
    base = InvoiceOut.model_validate(inv)
    return base.model_copy(update={"findings": _findings(await svc.invoice_findings(inv))})


async def _load_invoice(
    invoice_id: uuid.UUID, session: SessionDep, user_id: str
) -> tuple[HaulTicketService, HaulInvoice]:
    svc = HaulTicketService(session)
    inv = await svc.get_invoice(invoice_id)
    await verify_project_access(inv.project_id, user_id, session)
    return svc, inv


@router.get("/projects/{project_id}/invoices", response_model=InvoiceListResponse, dependencies=[_READ])
async def list_invoices(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> InvoiceListResponse:
    await verify_project_access(project_id, user_id, session)
    repo = HaulTicketService(session).repo
    rows = await repo.invoices(project_id, offset=offset, limit=limit)
    return InvoiceListResponse(
        items=[InvoiceOut.model_validate(i) for i in rows],
        total=await repo.count_invoices(project_id),
        offset=offset,
        limit=limit,
    )


@router.post("/invoices/", response_model=InvoiceOut, status_code=201, dependencies=[_WRITE])
async def create_invoice(data: InvoiceIn, session: SessionDep, user_id: CurrentUserId) -> InvoiceOut:
    await verify_project_access(data.project_id, user_id, session)
    svc = HaulTicketService(session)
    return await _invoice_out(svc, await svc.create_invoice(data, user_id))


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut, dependencies=[_READ])
async def get_invoice(invoice_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> InvoiceOut:
    svc, inv = await _load_invoice(invoice_id, session, user_id)
    return await _invoice_out(svc, inv)


@router.post("/invoices/{invoice_id}/reconcile", response_model=InvoiceOut, dependencies=[_WRITE])
async def reconcile_invoice(invoice_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> InvoiceOut:
    svc, inv = await _load_invoice(invoice_id, session, user_id)
    return await _invoice_out(svc, await svc.reconcile(inv))


@router.post("/invoices/{invoice_id}/accept", response_model=InvoiceOut, dependencies=[_VERIFY])
async def accept_invoice(invoice_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> InvoiceOut:
    svc, inv = await _load_invoice(invoice_id, session, user_id)
    return await _invoice_out(svc, await svc.accept_invoice(inv))


@router.delete("/invoices/{invoice_id}", status_code=204, dependencies=[_WRITE])
async def delete_invoice(invoice_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> Response:
    svc, inv = await _load_invoice(invoice_id, session, user_id)
    if inv.status == "accepted":
        raise HTTPException(status.HTTP_409_CONFLICT, "An accepted invoice cannot be deleted.")
    await svc.repo.delete(inv)
    return Response(status_code=204)


# ── settings, rates, materials ───────────────────────────────────────────


def _settings_out(s: Any) -> SettingsOut:
    return SettingsOut(
        mandatory_fields=list(s.mandatory_fields or []),
        max_gross_t=s.max_gross_t,
        capacity_tolerance_pct=s.capacity_tolerance_pct if s.capacity_tolerance_pct is not None else 10,
        price_tolerance_pct=s.price_tolerance_pct if s.price_tolerance_pct is not None else 1,
        waste_catalogue=s.waste_catalogue or "",
        currency=s.currency or "",
        candidates=list(logic.MANDATORY_CANDIDATES),
        waste_catalogues=[{"key": k, "label": v[0]} for k, v in logic.waste_catalogues().items()],
    )


@router.get("/projects/{project_id}/settings", response_model=SettingsOut, dependencies=[_READ])
async def get_settings(project_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId) -> SettingsOut:
    await verify_project_access(project_id, user_id, session)
    return _settings_out(await HaulTicketService(session).get_settings(project_id))


@router.put("/projects/{project_id}/settings", response_model=SettingsOut, dependencies=[_VERIFY])
async def put_settings(
    project_id: uuid.UUID, data: SettingsIn, session: SessionDep, user_id: CurrentUserId
) -> SettingsOut:
    await verify_project_access(project_id, user_id, session)
    return _settings_out(await HaulTicketService(session).save_settings(project_id, data))


@router.get("/projects/{project_id}/rates", response_model=RateListResponse, dependencies=[_READ])
async def list_rates(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
) -> RateListResponse:
    await verify_project_access(project_id, user_id, session)
    repo = HaulTicketService(session).repo
    rows = await repo.rates(project_id, offset=offset, limit=limit)
    return RateListResponse(
        items=[RateOut.model_validate(r, from_attributes=True) for r in rows],
        total=await repo.count_rates(project_id),
        offset=offset,
        limit=limit,
    )


@router.post("/projects/{project_id}/rates", response_model=RateOut, status_code=201, dependencies=[_WRITE])
async def add_rate(project_id: uuid.UUID, data: RateIn, session: SessionDep, user_id: CurrentUserId) -> RateOut:
    await verify_project_access(project_id, user_id, session)
    row = await HaulTicketService(session).add_rate(project_id, data)
    return RateOut.model_validate(row, from_attributes=True)


@router.delete("/projects/{project_id}/rates/{rate_id}", status_code=204, dependencies=[_WRITE])
async def delete_rate(
    project_id: uuid.UUID, rate_id: uuid.UUID, session: SessionDep, user_id: CurrentUserId
) -> Response:
    await verify_project_access(project_id, user_id, session)
    await HaulTicketService(session).delete_rate(project_id, rate_id)
    return Response(status_code=204)


@router.get("/projects/{project_id}/materials", response_model=MaterialListResponse, dependencies=[_READ])
async def list_materials(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
) -> MaterialListResponse:
    await verify_project_access(project_id, user_id, session)
    rows, total = await HaulTicketService(session).materials(project_id, offset=offset, limit=limit)
    return MaterialListResponse(
        items=[MaterialOut.model_validate(m) for m in rows], total=total, offset=offset, limit=limit
    )


@router.post("/projects/{project_id}/materials", response_model=MaterialOut, status_code=201, dependencies=[_WRITE])
async def add_material(
    project_id: uuid.UUID, data: MaterialIn, session: SessionDep, user_id: CurrentUserId
) -> MaterialOut:
    await verify_project_access(project_id, user_id, session)
    row = await HaulTicketService(session).add_material(project_id, data)
    return MaterialOut.model_validate(row, from_attributes=True)


@router.get("/waste-catalogues", dependencies=[_READ])
async def waste_catalogues(catalogue: str | None = Query(default=None)) -> dict:
    cats = logic.waste_catalogues()
    if catalogue:
        entry = cats.get(catalogue)
        if entry is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Catalogue not found")
        return {"key": catalogue, "label": entry[0], "codes": entry[1]()}
    return {"items": [{"key": k, "label": v[0]} for k, v in cats.items()]}

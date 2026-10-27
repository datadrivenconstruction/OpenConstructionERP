# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Accounting​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ sync API routes (mounted at ``/api/v1/accounting_sync``).

Reading the status, log and findings needs ``accounting_sync.read`` (manager);
pushing, pulling, exporting and retrying needs ``accounting_sync.write``; the
connection settings and OAuth secrets are admin only (``accounting_sync.admin``).
Secrets are write-only: responses say whether one is set, never what it is.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.accounting_sync import templates
from app.modules.accounting_sync.exports.journal import JOURNAL_COLUMNS
from app.modules.accounting_sync.models import AccountingConnection, SyncLogEntry
from app.modules.accounting_sync.schemas import (
    AccountMappingRow,
    ConnectionCreate,
    ConnectionResponse,
    ConnectionUpdate,
    Finding,
    LogEntryResponse,
    LogListResponse,
    MappingsResponse,
    MappingsUpdate,
    OAuthComplete,
    OAuthStartResponse,
    PreviewDocument,
    PushRequest,
    SyncCounts,
    TaxMappingRow,
    TemplateApply,
)
from app.modules.accounting_sync.service import AccountingSyncService

router = APIRouter(tags=["accounting_sync"])

_READ = Depends(RequirePermission("accounting_sync.read"))
_WRITE = Depends(RequirePermission("accounting_sync.write"))
_ADMIN = Depends(RequirePermission("accounting_sync.admin"))

EXPORT_KINDS = ("datev_postings", "datev_master", "journal_csv", "journal_xlsx", "saft")


def _out(conn: AccountingConnection) -> ConnectionResponse:
    resp = ConnectionResponse.model_validate(conn)
    return resp.model_copy(
        update={
            "has_client_secret": bool(conn.client_secret_enc),
            "is_authorised": bool(conn.tokens_enc),
            "settings": {k: v for k, v in (conn.settings_ or {}).items() if "secret" not in k and "token" not in k},
        }
    )


def _period(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    today = date.today()
    start = date_from or date(today.year, 1, 1)
    end = date_to or today
    if end < start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="date_to is before date_from")
    return start, end


@router.get("/status", dependencies=[_READ])
async def sync_status(session: SessionDep) -> dict:
    """Dashboard tile: per-connection success and open failure counts."""
    return await AccountingSyncService(session).status_summary()


@router.get("/templates", dependencies=[_READ])
async def list_templates(country_code: str | None = Query(default=None, max_length=2)) -> dict:
    """Mapping templates and tax codes for a country, from country data."""
    return {
        "templates": templates.list_templates(country_code),
        "categories": templates.categories(),
        "tax_codes": templates.tax_codes(country_code),
        "journal_columns": list(JOURNAL_COLUMNS),
        "export_kinds": list(EXPORT_KINDS),
    }


@router.get("/connections", response_model=list[ConnectionResponse], dependencies=[_READ])
async def list_connections(session: SessionDep) -> list[ConnectionResponse]:
    return [_out(c) for c in await AccountingSyncService(session).list_connections()]


@router.post("/connections", response_model=ConnectionResponse, status_code=201, dependencies=[_ADMIN])
async def create_connection(body: ConnectionCreate, session: SessionDep, user_id: CurrentUserId) -> ConnectionResponse:
    svc = AccountingSyncService(session)
    if body.chart_template and body.chart_template not in {
        t["key"] for t in templates.list_templates(body.country_code)
    }:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown chart template for this country")
    conn = await svc.create_connection(body.model_dump(), str(user_id))
    await session.commit()
    return _out(conn)


@router.get("/connections/{connection_id}", response_model=ConnectionResponse, dependencies=[_READ])
async def get_connection(connection_id: uuid.UUID, session: SessionDep) -> ConnectionResponse:
    return _out(await AccountingSyncService(session).get_connection(connection_id))


@router.patch("/connections/{connection_id}", response_model=ConnectionResponse, dependencies=[_ADMIN])
async def update_connection(
    connection_id: uuid.UUID, body: ConnectionUpdate, session: SessionDep
) -> ConnectionResponse:
    svc = AccountingSyncService(session)
    conn = await svc.update_connection(await svc.get_connection(connection_id), body.model_dump(exclude_unset=True))
    await session.commit()
    return _out(conn)


@router.delete("/connections/{connection_id}", status_code=204, dependencies=[_ADMIN])
async def delete_connection(connection_id: uuid.UUID, session: SessionDep) -> Response:
    svc = AccountingSyncService(session)
    await svc.delete_connection(await svc.get_connection(connection_id))
    await session.commit()
    return Response(status_code=204)


@router.post("/connections/{connection_id}/oauth/start", response_model=OAuthStartResponse, dependencies=[_ADMIN])
async def oauth_start(
    connection_id: uuid.UUID, session: SessionDep, redirect_uri: str = Query(..., max_length=500)
) -> OAuthStartResponse:
    svc = AccountingSyncService(session)
    return OAuthStartResponse(
        authorization_url=await svc.authorization_url(await svc.get_connection(connection_id), redirect_uri)
    )


@router.post("/connections/{connection_id}/oauth/complete", response_model=ConnectionResponse, dependencies=[_ADMIN])
async def oauth_complete(connection_id: uuid.UUID, body: OAuthComplete, session: SessionDep) -> ConnectionResponse:
    svc = AccountingSyncService(session)
    conn = await svc.get_connection(connection_id)
    await svc.complete_oauth(conn, body.code, body.redirect_uri, body.tenant_id)
    await session.commit()
    return _out(conn)


@router.get("/connections/{connection_id}/mappings", response_model=MappingsResponse, dependencies=[_READ])
async def get_mappings(connection_id: uuid.UUID, session: SessionDep) -> MappingsResponse:
    svc = AccountingSyncService(session)
    conn = await svc.get_connection(connection_id)
    return MappingsResponse(
        chart_template=conn.chart_template,
        templates=templates.list_templates(conn.country_code),
        tax_codes=templates.tax_codes(conn.country_code),
        accounts=[AccountMappingRow.model_validate(m) for m in await svc.account_mappings(conn)],
        taxes=[TaxMappingRow.model_validate(m) for m in await svc.tax_mappings(conn)],
    )


@router.put("/connections/{connection_id}/mappings", response_model=MappingsResponse, dependencies=[_ADMIN])
async def put_mappings(connection_id: uuid.UUID, body: MappingsUpdate, session: SessionDep) -> MappingsResponse:
    svc = AccountingSyncService(session)
    conn = await svc.get_connection(connection_id)
    known = set(templates.categories())
    bad = [r.category for r in body.accounts if r.category not in known]
    if bad:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"Unknown categories: {', '.join(bad)}")
    await svc.set_account_mappings(conn, [r.model_dump() for r in body.accounts])
    await svc.set_tax_mappings(conn, [r.model_dump() for r in body.taxes])
    await session.commit()
    return await get_mappings(connection_id, session)


@router.post("/connections/{connection_id}/mappings/template", response_model=MappingsResponse, dependencies=[_ADMIN])
async def apply_template(connection_id: uuid.UUID, body: TemplateApply, session: SessionDep) -> MappingsResponse:
    svc = AccountingSyncService(session)
    conn = await svc.get_connection(connection_id)
    if body.chart_template not in {t["key"] for t in templates.list_templates(conn.country_code)}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unknown chart template for this country")
    await svc.apply_template(conn, body.chart_template)
    await session.commit()
    return await get_mappings(connection_id, session)


@router.get("/connections/{connection_id}/documents", response_model=list[PreviewDocument], dependencies=[_READ])
async def preview_documents(
    connection_id: uuid.UUID,
    session: SessionDep,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[PreviewDocument]:
    """Documents in scope with the remote id each already has."""
    svc = AccountingSyncService(session)
    conn = await svc.get_connection(connection_id)
    docs = await svc.documents(conn, period=_period(date_from, date_to) if (date_from or date_to) else None)
    refs = await svc._refs(conn, {d.record_id for d in docs})  # noqa: SLF001
    return [
        PreviewDocument(
            record_id=d.record_id,
            record_type=d.record_type,
            source=d.source,
            number=d.number,
            doc_date=d.doc_date,
            counterparty=d.contact.name,
            project_code=d.project_code,
            currency=d.currency,
            net_total=d.net_total,
            tax_total=d.tax_total,
            gross_total=d.gross_total,
            external_id=(r.external_id if (r := refs.get((d.record_type, d.record_id))) else None),
        )
        for d in docs
    ]


@router.get("/connections/{connection_id}/findings", response_model=list[Finding], dependencies=[_READ])
async def findings(connection_id: uuid.UUID, session: SessionDep) -> list[Finding]:
    svc = AccountingSyncService(session)
    return [Finding(**f) for f in await svc.findings(await svc.get_connection(connection_id))]


@router.post("/connections/{connection_id}/push", response_model=SyncCounts, dependencies=[_WRITE])
async def push(connection_id: uuid.UUID, body: PushRequest, session: SessionDep) -> SyncCounts:
    if not body.record_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Select the reviewed documents to post")
    svc = AccountingSyncService(session)
    conn = await svc.get_connection(connection_id)
    counts = await svc.push(conn, project_id=body.project_id, record_ids=set(body.record_ids))
    await session.commit()
    return SyncCounts(**counts)


@router.post("/connections/{connection_id}/pull-payments", response_model=SyncCounts, dependencies=[_WRITE])
async def pull_payments(connection_id: uuid.UUID, session: SessionDep) -> SyncCounts:
    svc = AccountingSyncService(session)
    counts = await svc.pull_payments(await svc.get_connection(connection_id))
    await session.commit()
    return SyncCounts(**counts)


@router.get("/connections/{connection_id}/export", dependencies=[_WRITE], response_model=None)
async def export(
    connection_id: uuid.UUID,
    session: SessionDep,
    kind: str = Query(..., max_length=30),
    date_from: date | None = None,
    date_to: date | None = None,
    columns: str | None = Query(default=None, max_length=500),
) -> Response:
    """Download a DATEV EXTF, generic journal (CSV or Excel) or SAF-T file."""
    if kind not in EXPORT_KINDS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"kind must be one of {', '.join(EXPORT_KINDS)}"
        )
    svc = AccountingSyncService(session)
    conn = await svc.get_connection(connection_id)
    cols = [c.strip() for c in columns.split(",")] if columns else None
    content, filename, media = await svc.export(conn, kind, _period(date_from, date_to), cols)
    await session.commit()
    return Response(
        content=content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/connections/{connection_id}/log", response_model=LogListResponse, dependencies=[_READ])
async def sync_log(
    connection_id: uuid.UUID,
    session: SessionDep,
    status_filter: str | None = Query(default=None, alias="status", max_length=20),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> LogListResponse:
    svc = AccountingSyncService(session)
    items, total = await svc.list_log(
        await svc.get_connection(connection_id), status_=status_filter, limit=limit, offset=offset
    )
    return LogListResponse(items=[LogEntryResponse.model_validate(i) for i in items], total=total)


@router.post("/log/{entry_id}/retry", response_model=LogEntryResponse, dependencies=[_WRITE])
async def retry(entry_id: uuid.UUID, session: SessionDep) -> LogEntryResponse:
    """Push the record behind a failed entry again; returns the newest entry for that record."""
    entry = await session.get(SyncLogEntry, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Log entry not found")
    svc = AccountingSyncService(session)
    await svc.retry(entry)
    await session.commit()
    items, _ = await svc.list_log(await svc.get_connection(entry.connection_id), limit=1)
    return LogEntryResponse.model_validate(items[0])

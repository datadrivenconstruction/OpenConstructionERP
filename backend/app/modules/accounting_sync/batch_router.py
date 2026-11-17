# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Export batch, ledger import and reconciliation routes (mounted with the module router).

Read needs ``accounting_sync.read``; creating and downloading a batch ``accounting_sync.export``;
voiding ``accounting_sync.void``; importing a books file ``accounting_sync.import``; the cost-centre
and supplier maps are admin only like the other mappings.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Response, UploadFile, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.accounting_sync.batch_schemas import (
    BatchListResponse,
    BatchPreview,
    BatchRequest,
    BatchResponse,
    CostCodeRow,
    ExtraMappingsResponse,
    ExtraMappingsUpdate,
    ImportListResponse,
    ImportRow,
    ImportSummary,
    ReconciliationResponse,
    SupplierRow,
    VoidRequest,
)
from app.modules.accounting_sync.batches import BatchParams, BatchService
from app.modules.accounting_sync.ledger_import import LedgerImportService, reconcile
from app.modules.accounting_sync.service import AccountingSyncService

router = APIRouter(tags=["accounting_sync"])

_READ = Depends(RequirePermission("accounting_sync.read"))
_EXPORT = Depends(RequirePermission("accounting_sync.export"))
_VOID = Depends(RequirePermission("accounting_sync.void"))
_IMPORT = Depends(RequirePermission("accounting_sync.import"))
_ADMIN = Depends(RequirePermission("accounting_sync.admin"))

MAX_UPLOAD = 200 * 1024 * 1024


def _params(body: BatchRequest) -> BatchParams:
    return BatchParams(fmt=body.format, period=(body.date_from, body.date_to), record_types=list(body.record_types))


def _publish(event: str, conn_id: uuid.UUID, **data: object) -> None:
    from app.core.events import event_bus

    event_bus.publish_detached(event, {"connection_id": str(conn_id), **data}, source_module="accounting_sync")


@router.post("/connections/{connection_id}/batches/preview", response_model=BatchPreview, dependencies=[_EXPORT])
async def preview_batch(connection_id: uuid.UUID, body: BatchRequest, session: SessionDep) -> BatchPreview:
    """Dry run: what a batch would hold and which findings block it. Writes nothing."""
    conn = await AccountingSyncService(session).get_connection(connection_id)
    return BatchPreview(**await BatchService(session).preview(conn, _params(body)))


@router.post(
    "/connections/{connection_id}/batches", response_model=BatchResponse, status_code=201, dependencies=[_EXPORT]
)
async def create_batch(
    connection_id: uuid.UUID,
    body: BatchRequest,
    response: Response,
    session: SessionDep,
    user_id: CurrentUserId,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=120),
) -> BatchResponse:
    """Create a numbered batch. The same ``Idempotency-Key`` returns the same batch."""
    conn = await AccountingSyncService(session).get_connection(connection_id)
    batch, created = await BatchService(session).create(conn, _params(body), key=idempotency_key, user_id=str(user_id))
    await session.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
    return BatchResponse.model_validate(batch)


@router.get("/connections/{connection_id}/batches", response_model=BatchListResponse, dependencies=[_READ])
async def list_batches(
    connection_id: uuid.UUID,
    session: SessionDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> BatchListResponse:
    conn = await AccountingSyncService(session).get_connection(connection_id)
    rows, total = await BatchService(session).page(conn, offset=offset, limit=limit)
    return BatchListResponse(
        items=[BatchResponse.model_validate(r) for r in rows], total=total, offset=offset, limit=limit
    )


@router.get("/connections/{connection_id}/batches/{batch_id}", response_model=BatchResponse, dependencies=[_READ])
async def get_batch(connection_id: uuid.UUID, batch_id: uuid.UUID, session: SessionDep) -> BatchResponse:
    conn = await AccountingSyncService(session).get_connection(connection_id)
    return BatchResponse.model_validate(await BatchService(session).get(conn, batch_id))


@router.get("/connections/{connection_id}/batches/{batch_id}/file", dependencies=[_EXPORT], response_model=None)
async def download_batch(connection_id: uuid.UUID, batch_id: uuid.UUID, session: SessionDep) -> Response:
    conn = await AccountingSyncService(session).get_connection(connection_id)
    batch = await BatchService(session).get(conn, batch_id)
    return Response(
        content=batch.content or b"",
        media_type=batch.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{batch.file_name}"',
            "X-Content-SHA256": batch.sha256,
        },
    )


@router.post("/connections/{connection_id}/batches/{batch_id}/void", response_model=BatchResponse, dependencies=[_VOID])
async def void_batch(
    connection_id: uuid.UUID, batch_id: uuid.UUID, body: VoidRequest, session: SessionDep, user_id: CurrentUserId
) -> BatchResponse:
    conn = await AccountingSyncService(session).get_connection(connection_id)
    svc = BatchService(session)
    batch = await svc.void(conn, await svc.get(conn, batch_id), body.reason, str(user_id))
    await session.commit()
    return BatchResponse.model_validate(batch)


@router.post(
    "/connections/{connection_id}/batches/{batch_id}/confirm", response_model=BatchResponse, dependencies=[_EXPORT]
)
async def confirm_batch(connection_id: uuid.UUID, batch_id: uuid.UUID, session: SessionDep) -> BatchResponse:
    """Mark a batch as accepted by the accountant; a confirmed batch can no longer be voided."""
    conn = await AccountingSyncService(session).get_connection(connection_id)
    svc = BatchService(session)
    batch = await svc.confirm(await svc.get(conn, batch_id))
    await session.commit()
    return BatchResponse.model_validate(batch)


@router.get("/connections/{connection_id}/mappings/extra", response_model=ExtraMappingsResponse, dependencies=[_READ])
async def get_extra_mappings(connection_id: uuid.UUID, session: SessionDep) -> ExtraMappingsResponse:
    conn = await AccountingSyncService(session).get_connection(connection_id)
    svc = BatchService(session)
    return ExtraMappingsResponse(
        cost_codes=[CostCodeRow.model_validate(m) for m in await svc.cost_codes(conn)],
        suppliers=[SupplierRow.model_validate(m) for m in await svc.suppliers(conn)],
    )


@router.put("/connections/{connection_id}/mappings/extra", response_model=ExtraMappingsResponse, dependencies=[_ADMIN])
async def put_extra_mappings(
    connection_id: uuid.UUID, body: ExtraMappingsUpdate, session: SessionDep
) -> ExtraMappingsResponse:
    conn = await AccountingSyncService(session).get_connection(connection_id)
    svc = BatchService(session)
    if body.cost_codes is not None:
        await svc.set_cost_codes(conn, [r.model_dump() for r in body.cost_codes])
    if body.suppliers is not None:
        await svc.set_suppliers(conn, [r.model_dump() for r in body.suppliers])
    await session.commit()
    return await get_extra_mappings(connection_id, session)


@router.post(
    "/connections/{connection_id}/imports", response_model=ImportSummary, status_code=201, dependencies=[_IMPORT]
)
async def import_ledger(connection_id: uuid.UUID, session: SessionDep, file: UploadFile = File(...)) -> ImportSummary:
    """Read a CSV or Excel file from the books: ledger lines and payment status."""
    name = file.filename or "ledger.csv"
    if not name.lower().endswith((".csv", ".txt", ".xlsx", ".xlsm")):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Upload a CSV or XLSX file")
    file.file.seek(0, 2)
    if file.file.tell() > MAX_UPLOAD:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail="File is too large")
    file.file.seek(0)
    conn = await AccountingSyncService(session).get_connection(connection_id)
    result = await LedgerImportService(session).import_file(conn, file.file, name)
    await session.commit()
    _publish("accounting_sync.import.completed", conn.id, import_id=str(result.import_id), lines=result.lines)
    return ImportSummary(
        import_id=str(result.import_id),
        file_name=result.file_name,
        lines=result.lines,
        skipped=result.skipped,
        errors=result.errors,
    )


@router.get("/connections/{connection_id}/imports", response_model=ImportListResponse, dependencies=[_READ])
async def list_imports(
    connection_id: uuid.UUID,
    session: SessionDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> ImportListResponse:
    conn = await AccountingSyncService(session).get_connection(connection_id)
    rows = await LedgerImportService(session).list_imports(conn)
    return ImportListResponse(
        items=[ImportRow(**r) for r in rows[offset : offset + limit]], total=len(rows), offset=offset, limit=limit
    )


@router.delete("/connections/{connection_id}/imports/{import_id}", status_code=204, dependencies=[_IMPORT])
async def delete_import(connection_id: uuid.UUID, import_id: uuid.UUID, session: SessionDep) -> Response:
    conn = await AccountingSyncService(session).get_connection(connection_id)
    await LedgerImportService(session).delete_import(conn, import_id)
    await session.commit()
    return Response(status_code=204)


@router.get("/connections/{connection_id}/reconciliation", response_model=ReconciliationResponse, dependencies=[_READ])
async def reconciliation(
    connection_id: uuid.UUID, session: SessionDep, date_from: date, date_to: date
) -> ReconciliationResponse:
    """Platform documents against the imported books for a period."""
    if date_to < date_from:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="date_to is before date_from")
    sync = AccountingSyncService(session)
    conn = await sync.get_connection(connection_id)
    docs = await sync.documents(conn, period=(date_from, date_to))
    platform = [
        {
            "number": d.number,
            "record_id": d.record_id,
            "counterparty": d.contact.name,
            "doc_date": d.doc_date.isoformat(),
            "amount": d.gross_total,
        }
        for d in docs
    ]
    books = await LedgerImportService(session).books_totals(conn, (date_from, date_to))
    report = reconcile(platform, books)
    if report["counts"]["mismatches"] or report["counts"]["platform_only"] or report["counts"]["books_only"]:
        _publish(
            "accounting_sync.reconciliation.mismatch",
            conn.id,
            date_from=date_from.isoformat(),
            date_to=date_to.isoformat(),
            **report["counts"],
        )
    return ReconciliationResponse(**report)

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Payroll API routes (mounted at ``/api/v1/payroll``).

Endpoints (all manager-scoped + project-access checked):
    POST  /projects/{project_id}/batches/        - generate a draft batch
    GET   /projects/{project_id}/batches/        - list batches for a project
    GET   /batches/{batch_id}                     - batch detail with entries
    PATCH /batches/{batch_id}/submit/             - draft -> submitted
    PATCH /batches/{batch_id}/finalize/           - approve + post labour cost
    PATCH /batches/{batch_id}/post/               - approved -> posted (GL)
    POST  /batches/{batch_id}/entries/{entry_id}/deductions/         - add a deduction
    DELETE /batches/{batch_id}/entries/{entry_id}/deductions/{id}/   - remove a deduction
    GET   /batches/{batch_id}/reconcile/          - batch hours vs field hours
    GET   /batches/{batch_id}/export.json         - JSON export (ERP handoff)
    GET   /batches/{batch_id}/export.csv          - CSV export (ERP handoff)
    GET   /projects/{project_id}/labour-cost/     - live labour-cost rollup
"""

import asyncio
import csv
import io
import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.payroll.models import PayrollBatch
from app.modules.payroll.schemas import (
    LabourCostResponse,
    PayrollBatchDetailResponse,
    PayrollBatchGenerate,
    PayrollBatchResponse,
    PayrollDeductionCreate,
    PayrollDeductionResponse,
    PayrollEntryResponse,
    PayrollExportResponse,
    PayrollExportRow,
    ReconciliationResponse,
)
from app.modules.payroll.service import PayrollService

router = APIRouter(tags=["payroll"])


def _get_service(session: SessionDep) -> PayrollService:
    return PayrollService(session)


async def _build_detail(
    batch: PayrollBatch,
    service: PayrollService,
) -> PayrollBatchDetailResponse:
    """Assemble a batch-detail response with entries and their deductions.

    Deductions are bulk-loaded for the whole batch in one query (no N+1) and
    attached to each entry response.
    """
    entries = await service.list_entries(batch.id)
    by_entry = await service.list_deductions_by_entry(batch.id)
    detail = PayrollBatchDetailResponse.model_validate(batch)
    entry_responses: list[PayrollEntryResponse] = []
    for e in entries:
        er = PayrollEntryResponse.model_validate(e)
        er.deductions = [PayrollDeductionResponse.model_validate(d) for d in by_entry.get(e.id, [])]
        entry_responses.append(er)
    detail.entries = entry_responses
    return detail


@router.post(
    "/projects/{project_id}/batches/",
    response_model=PayrollBatchDetailResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("payroll.manage"))],
)
async def generate_batch(
    project_id: uuid.UUID,
    data: PayrollBatchGenerate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: PayrollService = Depends(_get_service),
) -> PayrollBatchDetailResponse:
    """Generate a draft payroll batch by aggregating field labour."""
    await verify_project_access(project_id, user_id, session)
    batch, _entries = await service.generate_batch(
        project_id,
        date_from=data.date_from,
        date_to=data.date_to,
        period_label=data.period_label,
        notes=data.notes,
        user_id=user_id,
    )
    return await _build_detail(batch, service)


@router.get(
    "/projects/{project_id}/batches/",
    response_model=list[PayrollBatchResponse],
    dependencies=[Depends(RequirePermission("payroll.read"))],
)
async def list_batches(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: PayrollService = Depends(_get_service),
) -> list[PayrollBatchResponse]:
    """List payroll batches for a project (most recent first)."""
    await verify_project_access(project_id, user_id, session)
    batches, _ = await service.list_batches(project_id, offset=offset, limit=limit)
    return [PayrollBatchResponse.model_validate(b) for b in batches]


@router.get(
    "/batches/{batch_id}",
    response_model=PayrollBatchDetailResponse,
    dependencies=[Depends(RequirePermission("payroll.read"))],
)
async def get_batch(
    batch_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: PayrollService = Depends(_get_service),
) -> PayrollBatchDetailResponse:
    """Get a payroll batch and its entries."""
    batch = await service.get_batch(batch_id)
    # IDOR guard: the batch's project must be one the caller can access.
    await verify_project_access(batch.project_id, user_id, session)
    return await _build_detail(batch, service)


@router.patch(
    "/batches/{batch_id}/submit/",
    response_model=PayrollBatchDetailResponse,
    dependencies=[Depends(RequirePermission("payroll.manage"))],
)
async def submit_batch(
    batch_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: PayrollService = Depends(_get_service),
) -> PayrollBatchDetailResponse:
    """Submit a draft batch for approval (no money moved).

    Idempotent: a second call on an already-submitted batch returns 200 with the
    unchanged batch. 404 if missing, 400 if not in 'draft'.
    """
    batch = await service.get_batch(batch_id)
    await verify_project_access(batch.project_id, user_id, session)
    batch = await service.submit_batch(batch_id, user_id=user_id)
    return await _build_detail(batch, service)


@router.patch(
    "/batches/{batch_id}/finalize/",
    response_model=PayrollBatchDetailResponse,
    dependencies=[Depends(RequirePermission("payroll.finalize"))],
)
async def finalize_batch(
    batch_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: PayrollService = Depends(_get_service),
) -> PayrollBatchDetailResponse:
    """Approve a draft/submitted batch and post its labour cost to the budget.

    Idempotent: a second call on an already-approved (or posted) batch returns
    200 with the unchanged batch. The labour cost lands on the project's
    cost-spine labour budget line (never double-posted). 404 if the batch is
    missing, 400 if it is in a status that cannot be approved.
    """
    batch = await service.get_batch(batch_id)
    # IDOR guard: the caller must have access to the batch's project.
    await verify_project_access(batch.project_id, user_id, session)
    batch = await service.finalize_batch(batch_id, user_id=user_id)
    return await _build_detail(batch, service)


@router.patch(
    "/batches/{batch_id}/post/",
    response_model=PayrollBatchDetailResponse,
    dependencies=[Depends(RequirePermission("payroll.post"))],
)
async def post_batch(
    batch_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: PayrollService = Depends(_get_service),
) -> PayrollBatchDetailResponse:
    """Post an approved batch to the finance general ledger (terminal).

    Writes a balanced payroll accrual journal (labour expense / wages payable)
    and flips the batch to 'posted'. Idempotent: a second call on an already
    posted batch returns 200 unchanged with no second journal. 404 if missing,
    400 if not in 'approved'.
    """
    batch = await service.get_batch(batch_id)
    await verify_project_access(batch.project_id, user_id, session)
    batch = await service.post_batch(batch_id, user_id=user_id)
    return await _build_detail(batch, service)


@router.post(
    "/batches/{batch_id}/entries/{entry_id}/deductions/",
    response_model=PayrollBatchDetailResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("payroll.manage"))],
)
async def add_deduction(
    batch_id: uuid.UUID,
    entry_id: uuid.UUID,
    data: PayrollDeductionCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: PayrollService = Depends(_get_service),
) -> PayrollBatchDetailResponse:
    """Add a withholding line to a payslip; recomputes net pay and batch totals.

    The deduction amount is derived server-side from ``mode`` + ``value`` (and
    ``base_amount`` for percentages) - the platform never supplies tax rates.
    Refused (400) on an approved/posted batch. Returns the full batch detail so
    the caller sees the updated net everywhere. 404 if the batch or entry is
    missing.
    """
    batch = await service.get_batch(batch_id)
    # IDOR guard: the caller must have access to the batch's project.
    await verify_project_access(batch.project_id, user_id, session)
    await service.add_deduction(
        batch_id,
        entry_id,
        label=data.label,
        deduction_type=data.deduction_type,
        mode=data.mode,
        value=data.value,
        base_amount=data.base_amount,
    )
    batch = await service.get_batch(batch_id)
    return await _build_detail(batch, service)


@router.delete(
    "/batches/{batch_id}/entries/{entry_id}/deductions/{deduction_id}/",
    response_model=PayrollBatchDetailResponse,
    dependencies=[Depends(RequirePermission("payroll.manage"))],
)
async def remove_deduction(
    batch_id: uuid.UUID,
    entry_id: uuid.UUID,
    deduction_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: PayrollService = Depends(_get_service),
) -> PayrollBatchDetailResponse:
    """Remove a withholding line from a payslip; recomputes net + batch totals.

    Refused (400) on an approved/posted batch. Returns the full batch detail.
    404 if the batch, entry, or deduction is missing.
    """
    batch = await service.get_batch(batch_id)
    await verify_project_access(batch.project_id, user_id, session)
    await service.remove_deduction(batch_id, entry_id, deduction_id)
    batch = await service.get_batch(batch_id)
    return await _build_detail(batch, service)


@router.get(
    "/batches/{batch_id}/reconcile/",
    response_model=ReconciliationResponse,
    dependencies=[Depends(RequirePermission("payroll.read"))],
)
async def reconcile_batch(
    batch_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: PayrollService = Depends(_get_service),
) -> ReconciliationResponse:
    """Reconcile a batch's hours against the live field-labour sources.

    Read-only: returns a per-worker/date delta of batch hours vs the field
    report + diary hours for the batch period, plus a balanced flag.
    """
    batch = await service.get_batch(batch_id)
    await verify_project_access(batch.project_id, user_id, session)
    return ReconciliationResponse.model_validate(await service.reconcile_batch(batch_id))


@router.get(
    "/batches/{batch_id}/export.json",
    response_model=PayrollExportResponse,
    dependencies=[Depends(RequirePermission("payroll.read"))],
)
async def export_batch_json(
    batch_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: PayrollService = Depends(_get_service),
) -> PayrollExportResponse:
    """Export a batch as JSON for ERP / payroll-provider handoff."""
    batch = await service.get_batch(batch_id)
    await verify_project_access(batch.project_id, user_id, session)
    batch, rows = await service.export_rows(batch_id)
    return PayrollExportResponse(
        batch_id=batch.id,
        project_id=batch.project_id,
        period_label=batch.period_label,
        status=batch.status,
        currency=batch.currency,
        total_hours=batch.total_hours,
        total_amount=batch.total_amount,
        total_deductions=batch.total_deductions,
        total_net=batch.total_net,
        rows=[PayrollExportRow(**r) for r in rows],
    )


def _render_batch_csv(rows: list[dict]) -> str:
    """Render the payroll batch CSV from the plain export rows."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "worker",
            "resource_id",
            "work_date",
            "hours",
            "rate",
            "amount",
            "deductions",
            "net_amount",
            "currency",
            "source",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r["worker"],
                r["resource_id"],
                r["work_date"],
                r["hours"],
                r["rate"],
                r["amount"],
                r["deductions"],
                r["net_amount"],
                r["currency"],
                r["source"],
            ]
        )
    buf.seek(0)
    return buf.getvalue()


@router.get(
    "/batches/{batch_id}/export.csv",
    dependencies=[Depends(RequirePermission("payroll.read"))],
)
async def export_batch_csv(
    batch_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: PayrollService = Depends(_get_service),
) -> StreamingResponse:
    """Export a batch as CSV for ERP / payroll-provider handoff."""
    batch = await service.get_batch(batch_id)
    await verify_project_access(batch.project_id, user_id, session)
    batch, rows = await service.export_rows(batch_id)

    # Writing the file walks every entry of the batch and is pure CPU, so it
    # runs in a worker thread; the rows are already plain dicts.
    csv_text = await asyncio.to_thread(_render_batch_csv, rows)
    filename = f"payroll-batch-{batch.id}.csv"
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/projects/{project_id}/labour-cost/",
    response_model=LabourCostResponse,
    dependencies=[Depends(RequirePermission("payroll.read"))],
)
async def get_labour_cost(
    project_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    date_from: str | None = Query(default=None, max_length=20),
    date_to: str | None = Query(default=None, max_length=20),
    service: PayrollService = Depends(_get_service),
) -> LabourCostResponse:
    """Live labour-cost rollup (base currency) - surfaced beside the cost model."""
    await verify_project_access(project_id, user_id, session)
    cost, hours, currency = await service.labour_cost(project_id, date_from=date_from, date_to=date_to)
    return LabourCostResponse(
        project_id=project_id,
        currency=currency,
        labour_cost=str(cost),
        total_hours=str(hours),
    )

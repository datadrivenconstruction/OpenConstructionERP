# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Cutting optimisation API routes.

Mounted at ``/api/v1/cutting``.

    GET    /jobs/?project_id=X                  - list jobs with latest plan figures
    POST   /jobs/                               - create a job (optionally with pieces and stock)
    GET    /jobs/{job_id}                       - one job with pieces and stock
    PATCH  /jobs/{job_id}                       - edit job settings and links
    DELETE /jobs/{job_id}                       - delete a job and its plans
    PUT    /jobs/{job_id}/pieces                - replace the cut list
    PUT    /jobs/{job_id}/stocks                - replace the stock on offer
    POST   /jobs/{job_id}/import/rebar          - cut list from a bending schedule
    POST   /jobs/{job_id}/import/takeoff        - cut list from linear takeoff measurements
    POST   /jobs/{job_id}/import/boq            - cut list from a BOQ line split into pieces
    POST   /jobs/{job_id}/import/file           - cut list from CSV / XLSX
    GET    /inventory-offcuts/?project_id=X     - reusable offcuts on hand in site inventory
    POST   /jobs/{job_id}/stocks/from-inventory - add inventory offcuts as free stock
    GET    /jobs/{job_id}/validate              - run the cutting rule set over the job
    POST   /jobs/{job_id}/optimise              - run the optimiser and store a plan
    GET    /jobs/{job_id}/plans                 - plan history
    GET    /plans/{plan_id}                     - one plan with layout
    GET    /plans/{plan_id}/export              - cutting list as PDF or XLSX
    GET    /plans/{plan_id}/proposal            - proposed BOQ / requisition quantities
    POST   /plans/{plan_id}/apply               - write the confirmed proposal
    POST   /plans/{plan_id}/return-offcuts      - book offcuts against site inventory

Reads need ``cutting.read``; editing and optimising need ``cutting.write``;
writing into other modules needs ``cutting.apply``. Every route verifies the
caller may access the job's project; a missing job answers 404.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_locale
from app.core.register_context import (
    AcceptLanguageHeader,
    FormatQuery,
    LocaleQuery,
    generated_now,
    load_project_header,
    register_download,
)
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.cutting.models import CuttingJob, CuttingPlan
from app.modules.cutting.pdf_export import cutting_list
from app.modules.cutting.pdf_translations import cutting_list_filename, resolve_pdf_locale, tr
from app.modules.cutting.schemas import (
    ApplyRequest,
    ApplyResponse,
    BoqImportRequest,
    ImportResult,
    InventoryOffcutListResponse,
    InventoryStockRequest,
    JobCreate,
    JobKind,
    JobList,
    JobOut,
    JobSummary,
    JobUpdate,
    PiecesReplace,
    PlanOut,
    PlanProposal,
    PlanSummary,
    PlanSummaryListResponse,
    RebarImportRequest,
    ReturnOffcutsRequest,
    ReturnOffcutsResponse,
    StocksReplace,
    TakeoffImportRequest,
    ValidationOut,
)
from app.modules.cutting.service import CuttingService

router = APIRouter()

_READ = Depends(RequirePermission("cutting.read"))
_WRITE = Depends(RequirePermission("cutting.write"))
_APPLY = Depends(RequirePermission("cutting.apply"))

MAX_UPLOAD_BYTES = 8 * 1024 * 1024


def _service(session: AsyncSession) -> CuttingService:
    return CuttingService(session)


async def _job(job_id: uuid.UUID, user_id: str, session: AsyncSession) -> CuttingJob:
    job = await _service(session).get_job(job_id)
    await verify_project_access(job.project_id, user_id, session)
    return job


async def _plan(plan_id: uuid.UUID, user_id: str, session: AsyncSession) -> tuple[CuttingJob, CuttingPlan]:
    service = _service(session)
    plan = await service.get_plan(plan_id)
    await verify_project_access(plan.project_id, user_id, session)
    return await service.get_job(plan.job_id), plan


def _job_out(job: CuttingJob) -> JobOut:
    return JobOut.model_validate(job)


# ── Jobs ──────────────────────────────────────────────────────────────────


@router.get("/jobs/", response_model=JobList, dependencies=[_READ])
async def list_jobs(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    kind: JobKind | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> JobList:
    """A project's cutting jobs with their latest plan figures."""
    await verify_project_access(project_id, user_id, session)
    rows, total = await _service(session).list_jobs(project_id, kind=kind, offset=offset, limit=limit)
    return JobList(items=[JobSummary.model_validate(r) for r in rows], total=total, offset=offset, limit=limit)


@router.post("/jobs/", response_model=JobOut, status_code=status.HTTP_201_CREATED, dependencies=[_WRITE])
async def create_job(data: JobCreate, user_id: CurrentUserId, session: SessionDep) -> JobOut:
    """Create a cutting job."""
    await verify_project_access(data.project_id, user_id, session)
    return _job_out(await _service(session).create_job(data, user_id=str(user_id)))


@router.get("/jobs/{job_id}", response_model=JobOut, dependencies=[_READ])
async def get_job(job_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> JobOut:
    """One job with its pieces and stock."""
    return _job_out(await _job(job_id, user_id, session))


@router.patch("/jobs/{job_id}", response_model=JobOut, dependencies=[_WRITE])
async def update_job(job_id: uuid.UUID, data: JobUpdate, user_id: CurrentUserId, session: SessionDep) -> JobOut:
    """Edit a job's settings and links (its kind never changes)."""
    job = await _job(job_id, user_id, session)
    return _job_out(await _service(session).update_job(job, data))


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[_WRITE])
async def delete_job(job_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> Response:
    """Delete a job with its pieces, stock and plans."""
    job = await _job(job_id, user_id, session)
    await _service(session).delete_job(job)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/jobs/{job_id}/pieces", response_model=JobOut, dependencies=[_WRITE])
async def replace_pieces(job_id: uuid.UUID, data: PiecesReplace, user_id: CurrentUserId, session: SessionDep) -> JobOut:
    """Replace the job's cut list."""
    job = await _job(job_id, user_id, session)
    return _job_out(await _service(session).replace_pieces(job, data.pieces))


@router.put("/jobs/{job_id}/stocks", response_model=JobOut, dependencies=[_WRITE])
async def replace_stocks(job_id: uuid.UUID, data: StocksReplace, user_id: CurrentUserId, session: SessionDep) -> JobOut:
    """Replace the job's stock on offer."""
    job = await _job(job_id, user_id, session)
    return _job_out(await _service(session).replace_stocks(job, data.stocks))


# ── Imports ───────────────────────────────────────────────────────────────


async def _import_result(service: CuttingService, job: CuttingJob, outcome: tuple[int, int, list[str]]) -> ImportResult:
    imported, skipped, messages = outcome
    fresh = await service.reload(job.id)
    return ImportResult(imported=imported, skipped=skipped, messages=messages, job=_job_out(fresh))


@router.post("/jobs/{job_id}/import/rebar", response_model=ImportResult, dependencies=[_WRITE])
async def import_rebar(
    job_id: uuid.UUID, data: RebarImportRequest, user_id: CurrentUserId, session: SessionDep
) -> ImportResult:
    """Bars of one diameter from a stored bending schedule become the cut list."""
    job = await _job(job_id, user_id, session)
    if job.kind != "linear":
        raise HTTPException(status_code=422, detail="Bending schedules feed linear jobs only")
    service = _service(session)
    return await _import_result(service, job, await service.import_rebar(job, data))


@router.post("/jobs/{job_id}/import/takeoff", response_model=ImportResult, dependencies=[_WRITE])
async def import_takeoff(
    job_id: uuid.UUID, data: TakeoffImportRequest, user_id: CurrentUserId, session: SessionDep
) -> ImportResult:
    """Linear takeoff measurements of the project become the cut list."""
    job = await _job(job_id, user_id, session)
    if job.kind != "linear":
        raise HTTPException(status_code=422, detail="Linear measurements feed linear jobs only")
    service = _service(session)
    return await _import_result(service, job, await service.import_takeoff(job, data))


@router.post("/jobs/{job_id}/import/boq", response_model=ImportResult, dependencies=[_WRITE])
async def import_boq(
    job_id: uuid.UUID, data: BoqImportRequest, user_id: CurrentUserId, session: SessionDep
) -> ImportResult:
    """A BOQ line split into pieces of a known size becomes the cut list."""
    job = await _job(job_id, user_id, session)
    service = _service(session)
    return await _import_result(service, job, await service.import_boq(job, data))


@router.post("/jobs/{job_id}/import/file", response_model=ImportResult, dependencies=[_WRITE])
async def import_file(
    job_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    upload: UploadFile = File(...),
) -> ImportResult:
    """A CSV or XLSX cut list becomes the cut list."""
    job = await _job(job_id, user_id, session)
    content = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File exceeds the {MAX_UPLOAD_BYTES} byte limit")
    service = _service(session)
    return await _import_result(
        service, job, await service.import_file(job, content, upload.filename or "cut-list.csv")
    )


# ── Site inventory ────────────────────────────────────────────────────────


@router.get("/inventory-offcuts/", response_model=InventoryOffcutListResponse, dependencies=[_READ])
async def inventory_offcuts(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    kind: JobKind = Query(default="linear"),
    material: str | None = Query(default=None, max_length=120),
) -> InventoryOffcutListResponse:
    """Reusable offcuts on hand in the project's site inventory."""
    await verify_project_access(project_id, user_id, session)
    items = await _service(session).inventory_offcuts(project_id, kind=kind, material=material)
    return InventoryOffcutListResponse(items=items, total=len(items), limit=len(items))


@router.post("/jobs/{job_id}/stocks/from-inventory", response_model=JobOut, dependencies=[_WRITE])
async def stock_from_inventory(
    job_id: uuid.UUID, data: InventoryStockRequest, user_id: CurrentUserId, session: SessionDep
) -> JobOut:
    """Add inventory offcuts to the job's stock as free entries."""
    job = await _job(job_id, user_id, session)
    return _job_out(await _service(session).add_inventory_stock(job, data.inventory_item_ids))


# ── Validation and optimisation ───────────────────────────────────────────


@router.get("/jobs/{job_id}/validate", response_model=ValidationOut, dependencies=[_READ])
async def validate_job(job_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> ValidationOut:
    """Run the cutting rule set over the job (before optimising)."""
    job = await _job(job_id, user_id, session)
    return ValidationOut(**await _service(session).validate(job, locale=get_locale()))


@router.post(
    "/jobs/{job_id}/optimise", response_model=PlanOut, status_code=status.HTTP_201_CREATED, dependencies=[_WRITE]
)
async def optimise_job(job_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> PlanOut:
    """Run the optimiser over the job and store the result as a new plan."""
    job = await _job(job_id, user_id, session)
    plan = await _service(session).optimise(job, user_id=str(user_id), locale=get_locale())
    return PlanOut.model_validate(plan)


@router.get("/jobs/{job_id}/plans", response_model=PlanSummaryListResponse, dependencies=[_READ])
async def list_plans(job_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> PlanSummaryListResponse:
    """The job's plans, newest first."""
    job = await _job(job_id, user_id, session)
    plans = await _service(session).repo.list_plans(job.id)
    items = [PlanSummary.model_validate(p) for p in plans]
    return PlanSummaryListResponse(items=items, total=len(items), limit=len(items))


@router.get("/plans/{plan_id}", response_model=PlanOut, dependencies=[_READ])
async def get_plan(plan_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> PlanOut:
    """One plan with its layout, offcuts and validation."""
    _job_row, plan = await _plan(plan_id, user_id, session)
    return PlanOut.model_validate(plan)


@router.get("/plans/{plan_id}/export", dependencies=[_READ])
async def export_plan(
    plan_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    export_format: FormatQuery = "pdf",
    locale: LocaleQuery = None,
    accept_language: AcceptLanguageHeader = None,
) -> StreamingResponse:
    """The plan's cutting list as a printable PDF or a workbook."""
    job, plan = await _plan(plan_id, user_id, session)
    doc_locale = resolve_pdf_locale(locale, accept_language)
    project = await load_project_header(session, job.project_id)
    document = cutting_list(
        job,
        plan,
        project=project,
        locale=doc_locale,
        generated=generated_now(tr(doc_locale, "datetime_format"), project),
    )
    return await register_download(document, export_format, lambda ext: cutting_list_filename(doc_locale, ext))


# ── Proposal, apply, inventory ────────────────────────────────────────────


@router.get("/plans/{plan_id}/proposal", response_model=PlanProposal, dependencies=[_READ])
async def plan_proposal(plan_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> PlanProposal:
    """Quantities the plan would write to the linked BOQ line and requisition item."""
    job, plan = await _plan(plan_id, user_id, session)
    return await _service(session).proposal(job, plan)


@router.post("/plans/{plan_id}/apply", response_model=ApplyResponse, dependencies=[_APPLY])
async def apply_plan(
    plan_id: uuid.UUID, data: ApplyRequest, user_id: CurrentUserId, session: SessionDep
) -> ApplyResponse:
    """Write the proposal the user confirmed; figures are recomputed server-side."""
    job, plan = await _plan(plan_id, user_id, session)
    return await _service(session).apply(
        job, plan, apply_boq=data.apply_boq, apply_procurement=data.apply_procurement, user_id=str(user_id)
    )


@router.post("/plans/{plan_id}/return-offcuts", response_model=ReturnOffcutsResponse, dependencies=[_APPLY])
async def return_offcuts(
    plan_id: uuid.UUID, data: ReturnOffcutsRequest, user_id: CurrentUserId, session: SessionDep
) -> ReturnOffcutsResponse:
    """Book the plan against site inventory: reused offcuts out, new offcuts in."""
    job, plan = await _plan(plan_id, user_id, session)
    return await _service(session).return_offcuts(job, plan, location_id=data.location_id, user_id=str(user_id))

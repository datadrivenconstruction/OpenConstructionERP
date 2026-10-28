# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Drawing revision compare API routes.

Route prefix (mounted by the module loader): ``/api/v1/drawing-compare``.

Endpoints:
    GET    /comparisons/                       - compares of a project
    POST   /comparisons/                       - store a PDF sheet compare (computed in the browser)
    POST   /comparisons/dwg/                   - diff two DWG/DXF revisions on the server
    GET    /comparisons/{id}                   - one compare with its changes
    DELETE /comparisons/{id}                   - delete a compare
    GET    /comparisons/{id}/validation/       - rule set ``drawing_compare``
    GET    /comparisons/{id}/report.pdf        - printable change report
    PATCH  /changes/{id}                       - triage: status and comment
    POST   /changes/{id}/rfi/                  - raise a draft RFI from a change
    POST   /changes/{id}/markup/               - cloud the change on the new revision
    POST   /changes/{id}/remeasure/            - list (dry run) or flag what sits inside
    DELETE /changes/{id}/remeasure/            - lift the flags this change raised
    GET    /previous-revision/                 - the revision a takeoff document supersedes

Every handler resolves the project from the stored row (or the request body)
and calls ``verify_project_access`` before reading or writing, so a caller
only ever sees compares of projects they can open.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.core.document_locale import normalize_document_locale
from app.core.i18n import SUPPORTED_LOCALES, get_locale
from app.dependencies import CurrentUserId, CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.drawing_compare.models import DrawingChange, DrawingComparison
from app.modules.drawing_compare.schemas import (
    ChangeMarkupCreate,
    ChangeResponse,
    ChangeRfiCreate,
    ChangeUpdate,
    ComparisonListResponse,
    ComparisonResponse,
    ComparisonSummary,
    DwgComparisonCreate,
    FollowUpResponse,
    PdfComparisonCreate,
    PreviousRevisionResponse,
    RemeasureResponse,
    ValidationResponse,
    ValidationResultOut,
)
from app.modules.drawing_compare.service import DrawingCompareService

router = APIRouter(tags=["drawing-compare"])

_READ = Depends(RequirePermission("drawing_compare.read"))
_CREATE = Depends(RequirePermission("drawing_compare.create"))
_UPDATE = Depends(RequirePermission("drawing_compare.update"))
_DELETE = Depends(RequirePermission("drawing_compare.delete"))


def _service(session: SessionDep) -> DrawingCompareService:
    return DrawingCompareService(session)


def _full(cmp: DrawingComparison) -> ComparisonResponse:
    return ComparisonResponse.model_validate(cmp)


async def _comparison(
    comparison_id: uuid.UUID, user_id: str, session: SessionDep, service: DrawingCompareService, *, changes: bool
) -> DrawingComparison:
    cmp = await service.get(comparison_id, with_changes=changes)
    await verify_project_access(cmp.project_id, user_id, session)
    return cmp


async def _change(
    change_id: uuid.UUID, user_id: str, session: SessionDep, service: DrawingCompareService
) -> tuple[DrawingChange, DrawingComparison]:
    change, cmp = await service.get_change(change_id)
    await verify_project_access(cmp.project_id, user_id, session)
    return change, cmp


@router.get("/comparisons/", response_model=ComparisonListResponse, dependencies=[_READ])
async def list_comparisons(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    ref_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: DrawingCompareService = Depends(_service),
) -> ComparisonListResponse:
    """Compares of a project, newest first; ``ref_id`` narrows to those touching one revision."""
    await verify_project_access(project_id, user_id, session)
    rows = await service.list_comparisons(project_id, ref_id=ref_id, limit=limit, offset=offset)
    total = await service.count_comparisons(project_id, ref_id=ref_id)
    items = [ComparisonSummary.model_validate(r) for r in rows]
    return ComparisonListResponse(items=items, total=total, offset=offset, limit=limit)


@router.post("/comparisons/", response_model=ComparisonResponse, status_code=201, dependencies=[_CREATE])
async def create_pdf_comparison(
    data: PdfComparisonCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: DrawingCompareService = Depends(_service),
) -> ComparisonResponse:
    """Store a sheet compare whose regions were found in the browser."""
    await verify_project_access(data.project_id, user_id, session)
    cmp = await service.create_pdf_comparison(data, user_id)
    await session.commit()
    return _full(await service.get(cmp.id))


@router.post("/comparisons/dwg/", response_model=ComparisonResponse, status_code=201, dependencies=[_CREATE])
async def create_dwg_comparison(
    data: DwgComparisonCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: DrawingCompareService = Depends(_service),
) -> ComparisonResponse:
    """Diff two DWG/DXF revisions entity by entity and store the changed regions."""
    await verify_project_access(data.project_id, user_id, session)
    cmp = await service.create_dwg_comparison(data, user_id)
    await session.commit()
    return _full(await service.get(cmp.id))


@router.get("/comparisons/{comparison_id}", response_model=ComparisonResponse, dependencies=[_READ])
async def get_comparison(
    comparison_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: DrawingCompareService = Depends(_service),
) -> ComparisonResponse:
    """One compare with every change."""
    return _full(await _comparison(comparison_id, user_id, session, service, changes=True))


@router.delete("/comparisons/{comparison_id}", status_code=204, dependencies=[_DELETE])
async def delete_comparison(
    comparison_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: DrawingCompareService = Depends(_service),
) -> Response:
    """Delete a compare and its changes."""
    cmp = await _comparison(comparison_id, user_id, session, service, changes=False)
    await service.delete(cmp)
    await session.commit()
    return Response(status_code=204)


@router.get(
    "/comparisons/{comparison_id}/validation/",
    response_model=ValidationResponse,
    dependencies=[_READ],
)
async def validate_comparison(
    comparison_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: DrawingCompareService = Depends(_service),
) -> ValidationResponse:
    """Traffic-light check of a compare: distinct revisions, alignment, regions, triage, follow-up."""
    cmp = await _comparison(comparison_id, user_id, session, service, changes=False)
    report = await service.validate(cmp)
    return ValidationResponse(
        status=str(report.status),
        score=report.score,
        errors=len(report.errors),
        warnings=len(report.warnings),
        results=[
            ValidationResultOut(
                rule_id=r.rule_id,
                severity=str(r.severity),
                passed=r.passed,
                message=r.message,
                element_ref=r.element_ref,
                suggestion=r.suggestion,
                details=r.details,
            )
            for r in report.results
        ],
    )


@router.get("/comparisons/{comparison_id}/report.pdf", response_model=None, dependencies=[_READ])
async def comparison_report_pdf(
    comparison_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: DrawingCompareService = Depends(_service),
) -> Response:
    """The printable change report."""
    cmp = await _comparison(comparison_id, user_id, session, service, changes=True)
    language = normalize_document_locale(get_locale(), SUPPORTED_LOCALES, "en")
    pdf, filename = await service.report_pdf(cmp, locale=language)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Content-Language": language},
    )


@router.patch("/changes/{change_id}", response_model=ChangeResponse, dependencies=[_UPDATE])
async def update_change(
    change_id: uuid.UUID,
    data: ChangeUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: DrawingCompareService = Depends(_service),
) -> ChangeResponse:
    """Mark a change relevant or not and comment on it."""
    change, _cmp = await _change(change_id, user_id, session, service)
    change = await service.update_change(change, data, user_id)
    await session.commit()
    return ChangeResponse.model_validate(change)


@router.post(
    "/changes/{change_id}/rfi/",
    response_model=FollowUpResponse,
    status_code=201,
    dependencies=[_UPDATE, Depends(RequirePermission("rfi.create"))],
)
async def create_rfi_from_change(
    change_id: uuid.UUID,
    data: ChangeRfiCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: DrawingCompareService = Depends(_service),
) -> FollowUpResponse:
    """Raise a draft RFI about a change; the RFI links the new revision."""
    change, cmp = await _change(change_id, user_id, session, service)
    rfi_id, number = await service.create_rfi(change, cmp, data, user_id)
    await session.commit()
    return FollowUpResponse(target_id=rfi_id, label=number, change=ChangeResponse.model_validate(change))


@router.post(
    "/changes/{change_id}/markup/",
    response_model=FollowUpResponse,
    status_code=201,
    dependencies=[_UPDATE, Depends(RequirePermission("markups.create"))],
)
async def create_markup_from_change(
    change_id: uuid.UUID,
    data: ChangeMarkupCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    service: DrawingCompareService = Depends(_service),
) -> FollowUpResponse:
    """Cloud the change on the new revision (a markup on a sheet, an annotation on a DWG)."""
    change, cmp = await _change(change_id, user_id, session, service)
    target_id, label = await service.create_markup(change, cmp, data, user_id)
    await session.commit()
    return FollowUpResponse(target_id=target_id, label=label, change=ChangeResponse.model_validate(change))


@router.post("/changes/{change_id}/remeasure/", response_model=RemeasureResponse, dependencies=[_UPDATE])
async def remeasure_change(
    change_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
    dry_run: bool = Query(default=True),
    service: DrawingCompareService = Depends(_service),
) -> RemeasureResponse:
    """What sits inside a change; with ``dry_run=false`` flag it all for re-measure."""
    change, cmp = await _change(change_id, user_id, session, service)
    can_flag_boq = True
    if not dry_run:
        try:
            await RequirePermission("boq.update")(payload)
        except HTTPException:
            can_flag_boq = False
    out = await service.remeasure(change, cmp, user_id, dry_run=dry_run, can_flag_boq=can_flag_boq)
    if not dry_run:
        await session.commit()
    return out


@router.delete("/changes/{change_id}/remeasure/", response_model=ChangeResponse, dependencies=[_UPDATE])
async def clear_remeasure(
    change_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: DrawingCompareService = Depends(_service),
) -> ChangeResponse:
    """Lift the re-measure flags this change raised, once the quantities are re-taken."""
    change, cmp = await _change(change_id, user_id, session, service)
    change = await service.clear_remeasure(change, cmp)
    await session.commit()
    return ChangeResponse.model_validate(change)


@router.get("/previous-revision/", response_model=PreviousRevisionResponse, dependencies=[_READ])
async def previous_revision(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    document_id: str = Query(..., min_length=1, max_length=64),
    service: DrawingCompareService = Depends(_service),
) -> PreviousRevisionResponse:
    """Suggest the older revision to compare a document with, from the documents revision chain."""
    await verify_project_access(project_id, user_id, session)
    return await service.previous_revision(project_id, document_id)

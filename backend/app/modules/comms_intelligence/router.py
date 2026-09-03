# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Comms Intelligence API routes.

Mounted by the module loader at ``/api/v1/comms-intelligence/``.

Endpoints:
    GET  /                                        - module ping
    GET  /analyses?project_id=&status=            - list analyses (review queue)
    GET  /analyses/by-correspondence/{id}         - the analysis for one record
    POST /analyses/{correspondence_id}/analyze    - run / re-run the pipeline
    POST /analyses/{analysis_id}/confirm          - apply selected suggestions
    POST /analyses/{analysis_id}/dismiss          - reject a suggestion
    GET  /drafts?correspondence_id=               - drafts for one record
    POST /drafts/{correspondence_id}              - draft a reply or chaser
    PATCH /drafts/{draft_id}                      - accept / dismiss a draft
    GET  /dashboard?project_id=                   - who-owes-whom aggregates
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access

# Imported for its side effect: registers comms_intelligence.* in the live
# permission registry. Nothing else imports this file (the module loader
# only loads router/models/hooks/events), and an UNregistered permission
# is denied for every non-admin role - without this line only admins
# could use the module.
from app.modules.comms_intelligence import permissions as _permissions  # noqa: F401
from app.modules.comms_intelligence import service
from app.modules.comms_intelligence.repository import (
    CommsAnalysisRepository,
    CommsDraftRepository,
)
from app.modules.comms_intelligence.schemas import (
    AnalysisListResponse,
    AnalysisRead,
    AnalyzeRequest,
    ConfirmRequest,
    DashboardRead,
    DraftListResponse,
    DraftRead,
    DraftRequest,
    DraftStatusUpdate,
)

router = APIRouter(tags=["comms_intelligence"])
logger = logging.getLogger(__name__)


@router.get("/")
async def module_info() -> dict[str, str]:
    """Health-style ping so operators can confirm the module mounted."""
    return {"module": "oe_comms_intelligence", "status": "active"}


# ── Analyses ─────────────────────────────────────────────────────────────


@router.get("/analyses", response_model=AnalysisListResponse)
async def list_analyses(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    status_filter: str | None = Query(default=None, alias="status", pattern=r"^(suggested|confirmed|dismissed)$"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    _perm: None = Depends(RequirePermission("comms_intelligence.read")),
) -> AnalysisListResponse:
    await verify_project_access(project_id, user_id, session)
    repo = CommsAnalysisRepository(session)
    rows = await repo.list_for_project(project_id, status=status_filter, offset=offset, limit=limit)
    return AnalysisListResponse(
        items=[AnalysisRead.model_validate(r) for r in rows],
        total=await repo.count_for_project(project_id, status=status_filter),
        limit=limit,
        offset=offset,
    )


@router.get("/analyses/by-correspondence/{correspondence_id}", response_model=AnalysisRead)
async def get_analysis_for_correspondence(
    correspondence_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("comms_intelligence.read")),
) -> AnalysisRead:
    row = await CommsAnalysisRepository(session).get_for_correspondence(str(correspondence_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No analysis for this correspondence")
    await verify_project_access(row.project_id, user_id, session)
    return AnalysisRead.model_validate(row)


@router.post(
    "/analyses/{correspondence_id}/analyze",
    response_model=AnalysisRead,
    status_code=status.HTTP_201_CREATED,
)
async def analyze(
    correspondence_id: uuid.UUID,
    payload: AnalyzeRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("comms_intelligence.analyze")),
) -> AnalysisRead:
    """Run (or re-run) enrichment. ``use_ai=true`` spends the caller's AI budget."""
    try:
        project_id = await service.project_id_of_correspondence(session, str(correspondence_id))
    except service.CorrespondenceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Correspondence not found") from None
    await verify_project_access(project_id, user_id, session)
    try:
        analysis = await service.analyze_correspondence(
            session,
            str(correspondence_id),
            use_ai=payload.use_ai,
            user_id=user_id,
        )
    except service.CorrespondenceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Correspondence not found") from None
    except service.AIUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None
    await session.commit()
    return AnalysisRead.model_validate(analysis)


@router.post("/analyses/{analysis_id}/confirm", response_model=AnalysisRead)
async def confirm(
    analysis_id: uuid.UUID,
    payload: ConfirmRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("comms_intelligence.review")),
) -> AnalysisRead:
    """Apply the reviewer-selected suggestions - the human-confirmation gate."""
    repo = CommsAnalysisRepository(session)
    existing = await repo.get_by_id(analysis_id)
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found")
    await verify_project_access(existing.project_id, user_id, session)
    try:
        analysis = await service.confirm_analysis(
            session,
            analysis_id,
            user_id=user_id,
            apply_status=payload.apply_status,
            apply_response_required_by=payload.apply_response_required_by,
            apply_link_rfi=payload.apply_link_rfi,
            apply_type=payload.apply_type,
        )
    except service.AnalysisAlreadyReviewed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Analysis already reviewed ({exc})") from None
    except service.CorrespondenceNotFound:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The correspondence record behind this analysis no longer exists",
        ) from None
    await session.commit()
    return AnalysisRead.model_validate(analysis)


@router.post("/analyses/{analysis_id}/dismiss", response_model=AnalysisRead)
async def dismiss(
    analysis_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("comms_intelligence.review")),
) -> AnalysisRead:
    repo = CommsAnalysisRepository(session)
    existing = await repo.get_by_id(analysis_id)
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found")
    await verify_project_access(existing.project_id, user_id, session)
    try:
        analysis = await service.dismiss_analysis(session, analysis_id, user_id=user_id)
    except service.AnalysisAlreadyReviewed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Analysis already reviewed ({exc})") from None
    await session.commit()
    return AnalysisRead.model_validate(analysis)


# ── Drafts ───────────────────────────────────────────────────────────────


@router.get("/drafts", response_model=DraftListResponse)
async def list_drafts(
    correspondence_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    _perm: None = Depends(RequirePermission("comms_intelligence.read")),
) -> DraftListResponse:
    rows = await CommsDraftRepository(session).list_for_correspondence(str(correspondence_id))
    if rows:
        await verify_project_access(rows[0].project_id, user_id, session)
    window = rows[offset : offset + limit]
    return DraftListResponse(
        items=[DraftRead.model_validate(r) for r in window],
        total=len(rows),
        limit=limit,
        offset=offset,
    )


@router.post(
    "/drafts/{correspondence_id}",
    response_model=DraftRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_draft(
    correspondence_id: uuid.UUID,
    payload: DraftRequest,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("comms_intelligence.draft")),
) -> DraftRead:
    """Draft a reply or chase-up. Text only - this module never sends mail."""
    try:
        project_id = await service.project_id_of_correspondence(session, str(correspondence_id))
    except service.CorrespondenceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Correspondence not found") from None
    await verify_project_access(project_id, user_id, session)
    try:
        draft = await service.create_draft(
            session,
            str(correspondence_id),
            kind=payload.kind,
            instructions=payload.instructions,
            use_ai=payload.use_ai,
            user_id=user_id,
        )
    except service.CorrespondenceNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Correspondence not found") from None
    except service.AIUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None
    await session.commit()
    return DraftRead.model_validate(draft)


@router.patch("/drafts/{draft_id}", response_model=DraftRead)
async def update_draft_status(
    draft_id: uuid.UUID,
    payload: DraftStatusUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("comms_intelligence.draft")),
) -> DraftRead:
    repo = CommsDraftRepository(session)
    draft = await repo.get_by_id(draft_id)
    if draft is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Draft not found")
    await verify_project_access(draft.project_id, user_id, session)
    draft.status = payload.status
    await session.commit()
    return DraftRead.model_validate(draft)


# ── Dashboard ────────────────────────────────────────────────────────────


@router.get("/dashboard", response_model=DashboardRead)
async def get_dashboard(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("comms_intelligence.read")),
) -> DashboardRead:
    await verify_project_access(project_id, user_id, session)
    data = await service.dashboard(session, project_id)
    return DashboardRead.model_validate(data)

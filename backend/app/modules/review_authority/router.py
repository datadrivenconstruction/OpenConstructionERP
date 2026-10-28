# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠FastAPI router for the external-review-authority module.

Auto-mounted at ``/api/v1/review_authority/``. Every endpoint is project-scoped
via :func:`app.dependencies.verify_project_access` - the same guard the
credentials and compliance-docs modules use - so a caller cannot see or mutate a
cycle or remark on a project they lack access to, and a cross-project id
surfaces as 404 (not 403) so the endpoint can't be turned into an id-existence
oracle.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query

from app.dependencies import (
    CurrentUserId,
    LangDep,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.review_authority import intl
from app.modules.review_authority.models import Remark, ReviewCycle
from app.modules.review_authority.schemas import (
    AUTHORITY_KINDS,
    CYCLE_STATUSES,
    REMARK_CLASSIFICATIONS,
    REMARK_DECISIONS,
    REMARK_SEVERITIES,
    REMARK_STATUSES,
    RemarkCreate,
    RemarkDecide,
    RemarkRespond,
    RemarkResponse,
    ReviewCycleCreate,
    ReviewCycleResponse,
    ReviewCycleSubmit,
    ReviewCycleTransition,
    ReviewCycleUpdate,
)
from app.modules.review_authority.service import (
    ReviewAuthorityService,
    cycle_timeline,
    is_remark_stale,
)

router = APIRouter(tags=["review_authority"])


def _get_service(session: SessionDep) -> ReviewAuthorityService:
    return ReviewAuthorityService(session)


def _to_cycle_response(cycle: ReviewCycle) -> ReviewCycleResponse:
    """Build a cycle response with the computed SLA fields."""
    timeline = cycle_timeline(
        opened_at=cycle.opened_at,
        sla_days=cycle.sla_days,
        due_at=cycle.due_at,
        status=cycle.status,
    )
    resp = ReviewCycleResponse.model_validate(cycle)
    return resp.model_copy(
        update={
            "days_remaining": timeline["days_remaining"],
            "overdue": timeline["overdue"],
        }
    )


def _to_remark_response(remark: Remark, cycle: ReviewCycle) -> RemarkResponse:
    """Build a remark response with the computed ``is_stale`` flag."""
    stale = is_remark_stale(cycle.pinned_document_version, cycle.current_document_version)
    resp = RemarkResponse.model_validate(remark)
    return resp.model_copy(update={"is_stale": stale})


# ── Meta ───────────────────────────────────────────────────────────────


@router.get(
    "/meta",
    dependencies=[Depends(RequirePermission("review_authority.read"))],
)
async def get_meta(lang: LangDep) -> dict:
    """Expose the validated vocabularies with localized labels for the UI."""
    return {
        "authority_kinds": [{"code": c, "label": intl.describe_authority_kind(c, lang)} for c in AUTHORITY_KINDS],
        "cycle_statuses": [{"code": s, "label": intl.describe_cycle_status(s, lang)} for s in CYCLE_STATUSES],
        "remark_statuses": list(REMARK_STATUSES),
        "remark_classifications": [
            {"code": c, "label": intl.describe_classification(c, lang)} for c in REMARK_CLASSIFICATIONS
        ],
        "remark_severities": list(REMARK_SEVERITIES),
        "remark_decisions": list(REMARK_DECISIONS),
    }


# ── Cycle CRUD ─────────────────────────────────────────────────────────


@router.get(
    "/cycles/",
    response_model=list[ReviewCycleResponse],
    dependencies=[Depends(RequirePermission("review_authority.read"))],
)
async def list_cycles(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    status_filter: str | None = Query(default=None, alias="status"),
    authority_kind: str | None = Query(default=None),
    service: ReviewAuthorityService = Depends(_get_service),
) -> list[ReviewCycleResponse]:
    """List review cycles for a project, optionally filtered."""
    await verify_project_access(project_id, user_id, session)
    items = await service.list_cycles(project_id, status=status_filter, authority_kind=authority_kind)
    return [_to_cycle_response(i) for i in items]


@router.post(
    "/cycles/",
    response_model=ReviewCycleResponse,
    status_code=201,
)
async def create_cycle(
    data: ReviewCycleCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("review_authority.create")),
    service: ReviewAuthorityService = Depends(_get_service),
) -> ReviewCycleResponse:
    """Open a new review cycle against a project."""
    await verify_project_access(data.project_id, user_id, session)
    cycle = await service.create_cycle(data, user_id=user_id)
    return _to_cycle_response(cycle)


@router.get(
    "/cycles/{cycle_id}/",
    response_model=ReviewCycleResponse,
    dependencies=[Depends(RequirePermission("review_authority.read"))],
)
async def get_cycle(
    cycle_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ReviewAuthorityService = Depends(_get_service),
) -> ReviewCycleResponse:
    """Read a single review cycle."""
    cycle = await service.get_cycle(cycle_id)
    await verify_project_access(cycle.project_id, user_id, session)
    return _to_cycle_response(cycle)


@router.patch(
    "/cycles/{cycle_id}/",
    response_model=ReviewCycleResponse,
)
async def update_cycle(
    cycle_id: uuid.UUID,
    data: ReviewCycleUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("review_authority.update")),
    service: ReviewAuthorityService = Depends(_get_service),
) -> ReviewCycleResponse:
    """Patch a review cycle (e.g. advance the live document version)."""
    existing = await service.get_cycle(cycle_id)
    await verify_project_access(existing.project_id, user_id, session)
    cycle = await service.update_cycle(cycle_id, data, user_id=user_id)
    return _to_cycle_response(cycle)


@router.delete(
    "/cycles/{cycle_id}/",
    status_code=204,
)
async def delete_cycle(
    cycle_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("review_authority.delete")),
    service: ReviewAuthorityService = Depends(_get_service),
) -> None:
    """Delete a review cycle and its remarks."""
    existing = await service.get_cycle(cycle_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_cycle(cycle_id)


# ── Cycle FSM ──────────────────────────────────────────────────────────


@router.post(
    "/cycles/{cycle_id}/submit",
    response_model=ReviewCycleResponse,
)
async def submit_cycle(
    cycle_id: uuid.UUID,
    data: ReviewCycleSubmit,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("review_authority.update")),
    service: ReviewAuthorityService = Depends(_get_service),
) -> ReviewCycleResponse:
    """Submit the cycle: freeze the pinned document version and open the clock."""
    existing = await service.get_cycle(cycle_id)
    await verify_project_access(existing.project_id, user_id, session)
    cycle = await service.submit_cycle(cycle_id, data, user_id=user_id)
    return _to_cycle_response(cycle)


@router.post(
    "/cycles/{cycle_id}/transition",
    response_model=ReviewCycleResponse,
)
async def transition_cycle(
    cycle_id: uuid.UUID,
    data: ReviewCycleTransition,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("review_authority.update")),
    service: ReviewAuthorityService = Depends(_get_service),
) -> ReviewCycleResponse:
    """Move a cycle along its FSM (illegal transitions return 400)."""
    existing = await service.get_cycle(cycle_id)
    await verify_project_access(existing.project_id, user_id, session)
    cycle = await service.transition_cycle(cycle_id, data.target_status)
    return _to_cycle_response(cycle)


# ── Remarks ────────────────────────────────────────────────────────────


@router.get(
    "/cycles/{cycle_id}/remarks/",
    response_model=list[RemarkResponse],
    dependencies=[Depends(RequirePermission("review_authority.read"))],
)
async def list_remarks(
    cycle_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ReviewAuthorityService = Depends(_get_service),
) -> list[RemarkResponse]:
    """List remarks on a cycle."""
    cycle = await service.get_cycle(cycle_id)
    await verify_project_access(cycle.project_id, user_id, session)
    remarks = await service.repo.list_remarks(cycle_id)
    return [_to_remark_response(r, cycle) for r in remarks]


@router.post(
    "/cycles/{cycle_id}/remarks",
    response_model=RemarkResponse,
    status_code=201,
)
async def add_remark(
    cycle_id: uuid.UUID,
    data: RemarkCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("review_authority.update")),
    service: ReviewAuthorityService = Depends(_get_service),
) -> RemarkResponse:
    """Add a remark to a cycle (auto-classified, repeat-radar linked)."""
    cycle = await service.get_cycle(cycle_id)
    await verify_project_access(cycle.project_id, user_id, session)
    remark = await service.add_remark(cycle_id, data, user_id=user_id)
    return _to_remark_response(remark, cycle)


@router.post(
    "/remarks/{remark_id}/respond",
    response_model=RemarkResponse,
)
async def respond_remark(
    remark_id: uuid.UUID,
    data: RemarkRespond,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("review_authority.update")),
    service: ReviewAuthorityService = Depends(_get_service),
) -> RemarkResponse:
    """Record a response to a remark (open -> responded)."""
    remark = await service.get_remark(remark_id)
    await verify_project_access(remark.project_id, user_id, session)
    remark = await service.respond_remark(remark_id, data.response_text, user_id=user_id)
    cycle = await service.get_cycle(remark.cycle_id)
    return _to_remark_response(remark, cycle)


@router.post(
    "/remarks/{remark_id}/decide",
    response_model=RemarkResponse,
)
async def decide_remark(
    remark_id: uuid.UUID,
    data: RemarkDecide,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("review_authority.update")),
    service: ReviewAuthorityService = Depends(_get_service),
) -> RemarkResponse:
    """Apply a terminal decision to a remark (accepted|contested|withdrawn)."""
    remark = await service.get_remark(remark_id)
    await verify_project_access(remark.project_id, user_id, session)
    remark = await service.decide_remark(remark_id, data.decision, note=data.note, user_id=user_id)
    cycle = await service.get_cycle(remark.cycle_id)
    return _to_remark_response(remark, cycle)


# ── Derived views ──────────────────────────────────────────────────────


@router.get(
    "/cycles/{cycle_id}/stale-remarks",
    response_model=list[RemarkResponse],
    dependencies=[Depends(RequirePermission("review_authority.read"))],
)
async def stale_remarks(
    cycle_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ReviewAuthorityService = Depends(_get_service),
) -> list[RemarkResponse]:
    """Remarks raised against a document version the project has moved past."""
    cycle = await service.get_cycle(cycle_id)
    await verify_project_access(cycle.project_id, user_id, session)
    remarks = await service.stale_remarks(cycle_id)
    return [_to_remark_response(r, cycle) for r in remarks]


@router.get(
    "/cycles/{cycle_id}/repeat-radar",
    dependencies=[Depends(RequirePermission("review_authority.read"))],
)
async def repeat_radar(
    cycle_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ReviewAuthorityService = Depends(_get_service),
) -> list[dict]:
    """Remarks the radar linked to a prior accepted remark on this cycle."""
    cycle = await service.get_cycle(cycle_id)
    await verify_project_access(cycle.project_id, user_id, session)
    return await service.repeat_radar(cycle_id)


@router.get(
    "/cycles/{cycle_id}/dossier",
    dependencies=[Depends(RequirePermission("review_authority.read"))],
)
async def get_dossier(
    cycle_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    lang: LangDep,
    service: ReviewAuthorityService = Depends(_get_service),
) -> dict:
    """Assemble the full cycle dossier (cycle + remarks + decisions + evidence)."""
    cycle = await service.get_cycle(cycle_id)
    await verify_project_access(cycle.project_id, user_id, session)
    return await service.build_dossier(cycle_id, locale=lang)


__all__ = ["router"]

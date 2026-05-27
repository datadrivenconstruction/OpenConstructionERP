"""Management of Change (MoC) API routes — mounted at /api/v1/moc/."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.moc.schemas import (
    MoCEntryCreate,
    MoCEntryResponse,
    MoCEntryUpdate,
    MoCImpactCreate,
    MoCImpactResponse,
    MoCImpactUpdate,
)
from app.modules.moc.service import MoCService

router = APIRouter()
logger = logging.getLogger(__name__)


def _svc(session: SessionDep) -> MoCService:
    return MoCService(session)


class _TransitionBody(BaseModel):
    notes: str | None = Field(default=None)


# ── MoC Entries ─────────────────────────────────────────────────────────────


@router.get("/", response_model=list[MoCEntryResponse])
async def list_moc_entries(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    _perm: None = Depends(RequirePermission("moc.read")),
    svc: MoCService = Depends(_svc),
) -> list[MoCEntryResponse]:
    """List MoC entries for a project. IDOR: 404 on unowned project."""
    await verify_project_access(project_id, str(user_id), session)
    rows, _ = await svc.list_entries(project_id, offset=offset, limit=limit, status=status)
    return [MoCEntryResponse.model_validate(r) for r in rows]


@router.post("/", response_model=MoCEntryResponse, status_code=201)
async def create_moc_entry(
    data: MoCEntryCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("moc.create")),
    svc: MoCService = Depends(_svc),
) -> MoCEntryResponse:
    """Create a new MoC entry in 'proposed' status."""
    await verify_project_access(data.project_id, str(user_id), session)
    entry = await svc.create_entry(data, user_id=str(user_id))
    return MoCEntryResponse.model_validate(entry)


@router.get("/{entry_id}", response_model=MoCEntryResponse)
async def get_moc_entry(
    entry_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("moc.read")),
    svc: MoCService = Depends(_svc),
) -> MoCEntryResponse:
    """Get a MoC entry by ID. IDOR: 404 on unowned project."""
    entry = await svc.get_entry(entry_id)
    await verify_project_access(entry.project_id, str(user_id), session)
    return MoCEntryResponse.model_validate(entry)


@router.patch("/{entry_id}", response_model=MoCEntryResponse)
async def update_moc_entry(
    entry_id: uuid.UUID,
    data: MoCEntryUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("moc.update")),
    svc: MoCService = Depends(_svc),
) -> MoCEntryResponse:
    """Update a MoC entry (not allowed in terminal states)."""
    existing = await svc.get_entry(entry_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    entry = await svc.update_entry(entry_id, data)
    return MoCEntryResponse.model_validate(entry)


@router.delete("/{entry_id}", status_code=204)
async def delete_moc_entry(
    entry_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("moc.delete")),
    svc: MoCService = Depends(_svc),
) -> None:
    """Delete a proposed MoC entry. Rejected/implemented entries cannot be deleted."""
    existing = await svc.get_entry(entry_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    await svc.delete_entry(entry_id)


# ── FSM transitions ──────────────────────────────────────────────────────────


@router.post("/{entry_id}/review", response_model=MoCEntryResponse)
async def review_moc_entry(
    entry_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    body: _TransitionBody = Body(default=_TransitionBody()),
    _perm: None = Depends(RequirePermission("moc.review")),
    svc: MoCService = Depends(_svc),
) -> MoCEntryResponse:
    """Transition proposed -> reviewed. Requires moc.review (Manager+)."""
    existing = await svc.get_entry(entry_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    entry = await svc.transition(entry_id, "reviewed", user_id=str(user_id), notes=body.notes)
    return MoCEntryResponse.model_validate(entry)


@router.post("/{entry_id}/accept", response_model=MoCEntryResponse)
async def accept_moc_entry(
    entry_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    body: _TransitionBody = Body(default=_TransitionBody()),
    _perm: None = Depends(RequirePermission("moc.approve")),
    svc: MoCService = Depends(_svc),
) -> MoCEntryResponse:
    """Transition reviewed -> accepted. Requires moc.approve (Manager+)."""
    existing = await svc.get_entry(entry_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    entry = await svc.transition(entry_id, "accepted", user_id=str(user_id), notes=body.notes)
    return MoCEntryResponse.model_validate(entry)


@router.post("/{entry_id}/decline", response_model=MoCEntryResponse)
async def decline_moc_entry(
    entry_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    body: _TransitionBody = Body(default=_TransitionBody()),
    _perm: None = Depends(RequirePermission("moc.approve")),
    svc: MoCService = Depends(_svc),
) -> MoCEntryResponse:
    """Transition reviewed -> declined. Requires moc.approve (Manager+)."""
    existing = await svc.get_entry(entry_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    entry = await svc.transition(entry_id, "declined", user_id=str(user_id), notes=body.notes)
    return MoCEntryResponse.model_validate(entry)


@router.post("/{entry_id}/implement", response_model=MoCEntryResponse)
async def implement_moc_entry(
    entry_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    body: _TransitionBody = Body(default=_TransitionBody()),
    _perm: None = Depends(RequirePermission("moc.implement")),
    svc: MoCService = Depends(_svc),
) -> MoCEntryResponse:
    """Transition accepted -> implemented. Requires moc.implement (Editor+)."""
    existing = await svc.get_entry(entry_id)
    await verify_project_access(existing.project_id, str(user_id), session)
    entry = await svc.transition(entry_id, "implemented", user_id=str(user_id), notes=body.notes)
    return MoCEntryResponse.model_validate(entry)


# ── Impact lines ─────────────────────────────────────────────────────────────


@router.get("/{entry_id}/impacts", response_model=list[MoCImpactResponse])
async def list_moc_impacts(
    entry_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("moc.read")),
    svc: MoCService = Depends(_svc),
) -> list[MoCImpactResponse]:
    """List impact lines for a MoC entry. IDOR-guarded via parent entry."""
    entry = await svc.get_entry(entry_id)
    await verify_project_access(entry.project_id, str(user_id), session)
    impacts = await svc.list_impacts(entry_id)
    return [MoCImpactResponse.model_validate(i) for i in impacts]


@router.post("/{entry_id}/impacts", response_model=MoCImpactResponse, status_code=201)
async def add_moc_impact(
    entry_id: uuid.UUID,
    data: MoCImpactCreate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("moc.update")),
    svc: MoCService = Depends(_svc),
) -> MoCImpactResponse:
    """Add an impact-assessment line to a MoC entry."""
    entry = await svc.get_entry(entry_id)
    await verify_project_access(entry.project_id, str(user_id), session)
    impact = await svc.add_impact(entry_id, data)
    return MoCImpactResponse.model_validate(impact)


@router.patch("/{entry_id}/impacts/{impact_id}", response_model=MoCImpactResponse)
async def update_moc_impact(
    entry_id: uuid.UUID,
    impact_id: uuid.UUID,
    data: MoCImpactUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("moc.update")),
    svc: MoCService = Depends(_svc),
) -> MoCImpactResponse:
    """Update an impact-assessment line."""
    entry = await svc.get_entry(entry_id)
    await verify_project_access(entry.project_id, str(user_id), session)
    impact = await svc.update_impact(impact_id, data)
    # IDOR guard: impact must belong to the requested entry.
    if impact.moc_entry_id != entry_id:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="MoC impact not found")
    return MoCImpactResponse.model_validate(impact)


@router.delete("/{entry_id}/impacts/{impact_id}", status_code=204)
async def delete_moc_impact(
    entry_id: uuid.UUID,
    impact_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("moc.update")),
    svc: MoCService = Depends(_svc),
) -> None:
    """Delete an impact-assessment line."""
    entry = await svc.get_entry(entry_id)
    await verify_project_access(entry.project_id, str(user_id), session)
    impact = await svc.get_impact(impact_id)
    if impact.moc_entry_id != entry_id:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="MoC impact not found")
    await svc.delete_impact(impact_id)

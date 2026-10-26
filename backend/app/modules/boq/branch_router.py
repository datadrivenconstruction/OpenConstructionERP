# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Routes for estimate branches (variants) of a BOQ.

Included into the BOQ ``router`` so the routes mount under ``/api/v1/boq``:

    GET   /boqs/{boq_id}/branches/                       - tree of the bill's main estimate
    POST  /boqs/{boq_id}/branches/                       - fork a branch from this bill
    PATCH /boqs/{boq_id}/branch/                         - rename, note, archive / reopen
    GET   /boqs/{boq_id}/branches/compare/{other_id}     - position-level compare
    GET   /boqs/{boq_id}/branches/compare/{other_id}/export - the compare as XLSX or PDF
    POST  /boqs/{boq_id}/branches/plan/                  - preview carrying changes into this bill
    POST  /boqs/{boq_id}/branches/cherry-pick/           - carry chosen changes into this bill
    POST  /boqs/{boq_id}/branch/merge/                   - merge this branch into its main estimate
    PUT   /boqs/{boq_id}/branch/design-option/           - link a design option to this bill

Writing into a main estimate (merge, or a cherry-pick whose target is main)
needs ``boq.branch_merge`` on top of ``boq.update``.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select

from app.core.content_disposition import attachment_disposition
from app.core.i18n import get_locale
from app.core.permissions import permission_registry
from app.dependencies import (
    CurrentUserId,
    CurrentUserPayload,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.boq import branch_export
from app.modules.boq.branch_schemas import (
    ApplyPlanRequest,
    ApplyPlanResponse,
    ApplyResult,
    BranchCompareResponse,
    BranchCreate,
    BranchTreeResponse,
    BranchUpdate,
    CherryPickRequest,
    DesignOptionLinkBody,
    MergeRequest,
)
from app.modules.boq.branch_service import BranchService, _refuse
from app.modules.boq.models import BOQ
from app.modules.boq.schemas import BOQResponse

branch_router = APIRouter(tags=["boq"])

MERGE_PERMISSION = "boq.branch_merge"


async def _verify_boq_access(session: SessionDep, boq_id: uuid.UUID, user_id: str) -> uuid.UUID:
    """404 unless the caller may see the BOQ's project; returns the project id."""
    row = (await session.execute(select(BOQ.project_id).where(BOQ.id == boq_id))).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOQ not found")
    try:
        await verify_project_access(row[0], user_id, session)
    except HTTPException as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOQ not found") from exc
    return row[0]


def _user_uuid(user_id: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(user_id))
    except (TypeError, ValueError):
        return None


def can_merge(payload: dict[str, Any]) -> bool:
    """Whether the caller may write into a main estimate from a branch."""
    role = str(payload.get("role", ""))
    if role == "admin":
        return True
    if MERGE_PERMISSION in (payload.get("permissions") or []):
        return True
    return permission_registry.role_has_permission(role, MERGE_PERMISSION)


def _require_merge(payload: dict[str, Any]) -> None:
    if not can_merge(payload):
        raise _refuse(status.HTTP_403_FORBIDDEN, "merge_forbidden")


@branch_router.get(
    "/boqs/{boq_id}/branches/",
    response_model=BranchTreeResponse,
    summary="Branch tree of an estimate",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def get_branch_tree(
    boq_id: uuid.UUID,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> BranchTreeResponse:
    """The main estimate and every branch of it, with author, date, total and delta vs parent."""
    await _verify_boq_access(session, boq_id, user_id)
    tree = await BranchService(session).tree(boq_id)
    return BranchTreeResponse(**tree, can_merge=can_merge(payload))


@branch_router.post(
    "/boqs/{boq_id}/branches/",
    response_model=BOQResponse,
    status_code=201,
    summary="Create an estimate branch",
    dependencies=[Depends(RequirePermission("boq.create"))],
)
async def create_branch(
    boq_id: uuid.UUID,
    body: BranchCreate,
    user_id: CurrentUserId,
    session: SessionDep,
) -> BOQResponse:
    """Fork a branch from this bill's current state or from one of its snapshots."""
    await _verify_boq_access(session, boq_id, user_id)
    boq = await BranchService(session).create_branch(
        boq_id,
        name=body.name,
        note=body.note,
        snapshot_id=body.snapshot_id,
        actor_id=_user_uuid(user_id),
    )
    return BOQResponse.model_validate(boq)


@branch_router.patch(
    "/boqs/{boq_id}/branch/",
    response_model=BranchTreeResponse,
    summary="Rename, annotate, archive or reopen a branch",
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def update_branch(
    boq_id: uuid.UUID,
    body: BranchUpdate,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> BranchTreeResponse:
    """Change a branch's name, note or status and return the refreshed tree."""
    await _verify_boq_access(session, boq_id, user_id)
    service = BranchService(session)
    await service.update_branch(boq_id, name=body.name, note=body.note, new_status=body.status)
    return BranchTreeResponse(**await service.tree(boq_id), can_merge=can_merge(payload))


@branch_router.get(
    "/boqs/{boq_id}/branches/compare/{other_id}",
    response_model=BranchCompareResponse,
    summary="Compare two branches position by position",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def compare_branches(
    boq_id: uuid.UUID,
    other_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
) -> BranchCompareResponse:
    """Added, removed and changed positions (quantity, rate, text) and totals by section and cost group."""
    await _verify_boq_access(session, boq_id, user_id)
    await _verify_boq_access(session, other_id, user_id)
    return BranchCompareResponse(**await BranchService(session).compare(boq_id, other_id))


@branch_router.get(
    "/boqs/{boq_id}/branches/compare/{other_id}/export",
    summary="Export a branch comparison to XLSX or PDF",
    response_class=Response,
    dependencies=[Depends(RequirePermission("boq.export"))],
)
async def export_branch_compare(
    boq_id: uuid.UUID,
    other_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    fmt: Literal["xlsx", "pdf"] = Query("xlsx", alias="format"),
    view: Literal["positions", "sections", "cost_groups"] = Query("positions"),
    locale: str | None = Query(None, max_length=16),
) -> Response:
    """The compare as a printable register: every changed position, or totals by section / cost group."""
    project_id = await _verify_boq_access(session, boq_id, user_id)
    await _verify_boq_access(session, other_id, user_id)
    compare = await BranchService(session).compare(boq_id, other_id)
    from app.modules.projects.models import Project

    project = await session.get(Project, project_id)
    document = branch_export.comparison_document(
        compare,
        view=view,
        project_name=project.name if project else "",
        country=getattr(project, "country_code", None) if project else None,
        locale=(locale or get_locale()).strip() or "en",
    )
    content = await asyncio.to_thread(branch_export.render, document, fmt)
    media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if fmt == "xlsx" else "application/pdf"
    name = branch_export.filename(compare["a_name"], compare["b_name"], fmt)
    return Response(content=content, media_type=media, headers={"Content-Disposition": attachment_disposition(name)})


@branch_router.post(
    "/boqs/{boq_id}/branches/plan/",
    response_model=ApplyPlanResponse,
    summary="Preview carrying changes from another branch into this bill",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def plan_cherry_pick(
    boq_id: uuid.UUID,
    body: ApplyPlanRequest,
    user_id: CurrentUserId,
    session: SessionDep,
) -> ApplyPlanResponse:
    """What a cherry-pick from ``source_boq_id`` into this bill would write, conflicts marked."""
    await _verify_boq_access(session, boq_id, user_id)
    await _verify_boq_access(session, body.source_boq_id, user_id)
    return ApplyPlanResponse(**await BranchService(session).plan(body.source_boq_id, boq_id, body.keys))


@branch_router.post(
    "/boqs/{boq_id}/branches/cherry-pick/",
    response_model=ApplyResult,
    summary="Carry chosen changes from another branch into this bill",
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def cherry_pick(
    boq_id: uuid.UUID,
    body: CherryPickRequest,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> ApplyResult:
    """Apply the chosen positions; refuses with 409 while a conflict has no decision."""
    await _verify_boq_access(session, boq_id, user_id)
    await _verify_boq_access(session, body.source_boq_id, user_id)
    service = BranchService(session)
    if await service.branch_row(boq_id) is None:
        _require_merge(payload)
    result = await service.cherry_pick(
        body.source_boq_id,
        boq_id,
        keys=body.keys,
        resolutions=dict(body.resolutions),
        actor_id=_user_uuid(user_id),
    )
    return ApplyResult(**result)


@branch_router.post(
    "/boqs/{boq_id}/branch/merge/",
    response_model=ApplyResult,
    summary="Merge a branch back into its main estimate",
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def merge_branch(
    boq_id: uuid.UUID,
    body: MergeRequest,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> ApplyResult:
    """Snapshot main, apply every change of the branch, then lock the branch as merged."""
    await _verify_boq_access(session, boq_id, user_id)
    _require_merge(payload)
    if not body.confirm:
        raise _refuse(status.HTTP_400_BAD_REQUEST, "confirm_required")
    result = await BranchService(session).merge(
        boq_id,
        resolutions=dict(body.resolutions),
        include_markups=body.include_markups,
        actor_id=_user_uuid(user_id),
    )
    return ApplyResult(**result)


@branch_router.put(
    "/boqs/{boq_id}/branch/design-option/",
    response_model=BranchTreeResponse,
    summary="Link a design option to this branch",
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def link_design_option(
    boq_id: uuid.UUID,
    body: DesignOptionLinkBody,
    user_id: CurrentUserId,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> BranchTreeResponse:
    """Price a design option from this bill (or unlink it); the option is repriced by its own module."""
    await _verify_boq_access(session, boq_id, user_id)
    service = BranchService(session)
    await service.link_design_option(boq_id, body.option_id)
    return BranchTreeResponse(**await service.tree(boq_id), can_merge=can_merge(payload))

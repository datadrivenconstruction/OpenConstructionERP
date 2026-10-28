# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠FastAPI router for design-side site supervision.

Auto-mounted at ``/api/v1/site-supervision/``. Every endpoint is project-scoped
via :func:`app.dependencies.verify_project_access` - the same guard the
credentials and compliance-docs modules use - so a caller cannot see or mutate
supervision data on a project they lack access to, and a cross-project id
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
from app.modules.site_supervision import intl
from app.modules.site_supervision.schemas import (
    DISCIPLINES,
    ENTRY_CATEGORIES,
    ENTRY_STATUSES,
    VISIT_STATUSES,
    SupervisionEntryCreate,
    SupervisionEntryRefuse,
    SupervisionEntryResponse,
    SupervisionEntryUpdate,
    SupervisionVisitCreate,
    SupervisionVisitResponse,
    SupervisionVisitUpdate,
)
from app.modules.site_supervision.service import SupervisionService

router = APIRouter(tags=["site-supervision"])


def _get_service(session: SessionDep) -> SupervisionService:
    return SupervisionService(session)


# ── Meta ────────────────────────────────────────────────────────────────


@router.get(
    "/meta",
    dependencies=[Depends(RequirePermission("site_supervision.read"))],
)
async def get_meta(lang: LangDep) -> dict:
    """Expose the validated vocabularies with localized labels for the UI."""
    return {
        "disciplines": [{"code": c, "label": intl.describe_discipline(c, lang)} for c in DISCIPLINES],
        "visit_statuses": [{"code": s, "label": intl.describe_visit_status(s, lang)} for s in VISIT_STATUSES],
        "entry_categories": [{"code": c, "label": intl.describe_category(c, lang)} for c in ENTRY_CATEGORIES],
        "entry_statuses": [{"code": s, "label": intl.describe_entry_status(s, lang)} for s in ENTRY_STATUSES],
    }


# ── Visits: CRUD ────────────────────────────────────────────────────────


@router.get(
    "/visits/",
    response_model=list[SupervisionVisitResponse],
    dependencies=[Depends(RequirePermission("site_supervision.read"))],
)
async def list_visits(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    status_filter: str | None = Query(default=None, alias="status"),
    discipline: str | None = Query(default=None),
    service: SupervisionService = Depends(_get_service),
) -> list[SupervisionVisitResponse]:
    """List supervision visits for a project, optionally filtered."""
    await verify_project_access(project_id, user_id, session)
    items = await service.list_visits(project_id, status=status_filter, discipline=discipline)
    return [SupervisionVisitResponse.model_validate(i) for i in items]


@router.post(
    "/visits/",
    response_model=SupervisionVisitResponse,
    status_code=201,
)
async def create_visit(
    data: SupervisionVisitCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_supervision.create")),
    service: SupervisionService = Depends(_get_service),
) -> SupervisionVisitResponse:
    """Plan or record a supervision visit against a project."""
    await verify_project_access(data.project_id, user_id, session)
    visit = await service.create_visit(data, user_id=user_id)
    return SupervisionVisitResponse.model_validate(visit)


@router.get(
    "/visits/{visit_id}/",
    response_model=SupervisionVisitResponse,
    dependencies=[Depends(RequirePermission("site_supervision.read"))],
)
async def get_visit(
    visit_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: SupervisionService = Depends(_get_service),
) -> SupervisionVisitResponse:
    """Read a single supervision visit."""
    visit = await service.get_visit(visit_id)
    await verify_project_access(visit.project_id, user_id, session)
    return SupervisionVisitResponse.model_validate(visit)


@router.patch(
    "/visits/{visit_id}/",
    response_model=SupervisionVisitResponse,
)
async def update_visit(
    visit_id: uuid.UUID,
    data: SupervisionVisitUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_supervision.update")),
    service: SupervisionService = Depends(_get_service),
) -> SupervisionVisitResponse:
    """Patch a supervision visit."""
    existing = await service.get_visit(visit_id)
    await verify_project_access(existing.project_id, user_id, session)
    visit = await service.update_visit(visit_id, data, user_id=user_id)
    return SupervisionVisitResponse.model_validate(visit)


@router.delete(
    "/visits/{visit_id}/",
    status_code=204,
)
async def delete_visit(
    visit_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_supervision.delete")),
    service: SupervisionService = Depends(_get_service),
) -> None:
    """Delete a supervision visit (cascades to its entries)."""
    existing = await service.get_visit(visit_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_visit(visit_id)


# ── Visits: state machine ───────────────────────────────────────────────


@router.post(
    "/visits/{visit_id}/conduct",
    response_model=SupervisionVisitResponse,
)
async def conduct_visit(
    visit_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_supervision.update")),
    service: SupervisionService = Depends(_get_service),
) -> SupervisionVisitResponse:
    """Mark a planned visit as conducted (planned -> conducted)."""
    existing = await service.get_visit(visit_id)
    await verify_project_access(existing.project_id, user_id, session)
    visit = await service.conduct_visit(visit_id)
    return SupervisionVisitResponse.model_validate(visit)


@router.post(
    "/visits/{visit_id}/report",
    response_model=SupervisionVisitResponse,
)
async def report_visit(
    visit_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_supervision.update")),
    service: SupervisionService = Depends(_get_service),
) -> SupervisionVisitResponse:
    """Mark a conducted visit as reported (conducted -> reported)."""
    existing = await service.get_visit(visit_id)
    await verify_project_access(existing.project_id, user_id, session)
    visit = await service.report_visit(visit_id)
    return SupervisionVisitResponse.model_validate(visit)


@router.get(
    "/visits/{visit_id}/entries/",
    response_model=list[SupervisionEntryResponse],
    dependencies=[Depends(RequirePermission("site_supervision.read"))],
)
async def list_visit_entries(
    visit_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: SupervisionService = Depends(_get_service),
) -> list[SupervisionEntryResponse]:
    """List the observations raised on a visit."""
    visit = await service.get_visit(visit_id)
    await verify_project_access(visit.project_id, user_id, session)
    items = await service.list_entries_for_visit(visit_id)
    return [SupervisionEntryResponse.model_validate(i) for i in items]


@router.get(
    "/visits/{visit_id}/export",
    dependencies=[Depends(RequirePermission("site_supervision.read"))],
)
async def export_visit(
    visit_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: SupervisionService = Depends(_get_service),
) -> dict:
    """Export a visit and its entries as a neutral-keyed structured record.

    Ready to serialise to a supervision-log XML; the field names are
    jurisdiction-neutral.
    """
    visit = await service.get_visit(visit_id)
    await verify_project_access(visit.project_id, user_id, session)
    return await service.export_visit(visit_id)


# ── Entries: CRUD ───────────────────────────────────────────────────────


@router.post(
    "/entries/",
    response_model=SupervisionEntryResponse,
    status_code=201,
)
async def create_entry(
    data: SupervisionEntryCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_supervision.create")),
    service: SupervisionService = Depends(_get_service),
) -> SupervisionEntryResponse:
    """Raise an observation on a supervision visit."""
    visit = await service.get_visit(data.visit_id)
    await verify_project_access(visit.project_id, user_id, session)
    entry = await service.create_entry(data, user_id=user_id)
    return SupervisionEntryResponse.model_validate(entry)


@router.get(
    "/entries/{entry_id}/",
    response_model=SupervisionEntryResponse,
    dependencies=[Depends(RequirePermission("site_supervision.read"))],
)
async def get_entry(
    entry_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: SupervisionService = Depends(_get_service),
) -> SupervisionEntryResponse:
    """Read a single supervision entry."""
    entry = await service.get_entry(entry_id)
    await verify_project_access(entry.project_id, user_id, session)
    return SupervisionEntryResponse.model_validate(entry)


@router.patch(
    "/entries/{entry_id}/",
    response_model=SupervisionEntryResponse,
)
async def update_entry(
    entry_id: uuid.UUID,
    data: SupervisionEntryUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_supervision.update")),
    service: SupervisionService = Depends(_get_service),
) -> SupervisionEntryResponse:
    """Patch a supervision entry."""
    existing = await service.get_entry(entry_id)
    await verify_project_access(existing.project_id, user_id, session)
    entry = await service.update_entry(entry_id, data, user_id=user_id)
    return SupervisionEntryResponse.model_validate(entry)


@router.post(
    "/entries/{entry_id}/refuse",
    response_model=SupervisionEntryResponse,
)
async def refuse_entry(
    entry_id: uuid.UUID,
    data: SupervisionEntryRefuse,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_supervision.update")),
    service: SupervisionService = Depends(_get_service),
) -> SupervisionEntryResponse:
    """Record a motivated refusal on an entry (-> refused_motivated).

    The reason is required; a blank reason is rejected with 400.
    """
    existing = await service.get_entry(entry_id)
    await verify_project_access(existing.project_id, user_id, session)
    entry = await service.refuse_entry(entry_id, data.reason)
    return SupervisionEntryResponse.model_validate(entry)


@router.delete(
    "/entries/{entry_id}/",
    status_code=204,
)
async def delete_entry(
    entry_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("site_supervision.delete")),
    service: SupervisionService = Depends(_get_service),
) -> None:
    """Delete a supervision entry."""
    existing = await service.get_entry(entry_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_entry(entry_id)


# ── Analytics ───────────────────────────────────────────────────────────


@router.get(
    "/plan-vs-fact",
    dependencies=[Depends(RequirePermission("site_supervision.read"))],
)
async def plan_vs_fact(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    service: SupervisionService = Depends(_get_service),
) -> dict:
    """Planned-versus-conducted figures, overdue visits and completion ratio."""
    await verify_project_access(project_id, user_id, session)
    return await service.plan_vs_fact(project_id)


@router.get(
    "/hidden-works",
    dependencies=[Depends(RequirePermission("site_supervision.read"))],
)
async def hidden_works(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    service: SupervisionService = Depends(_get_service),
) -> list[dict]:
    """The hidden-works acceptance register for a project."""
    await verify_project_access(project_id, user_id, session)
    return await service.hidden_works_register(project_id)


@router.get(
    "/change-links",
    dependencies=[Depends(RequirePermission("site_supervision.read"))],
)
async def change_links(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    service: SupervisionService = Depends(_get_service),
) -> list[dict]:
    """Instructions and deviations that feed the change / MOC route."""
    await verify_project_access(project_id, user_id, session)
    return await service.change_sheet_links(project_id)


@router.get(
    "/plan-coverage",
    dependencies=[Depends(RequirePermission("site_supervision.read"))],
)
async def plan_coverage(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    service: SupervisionService = Depends(_get_service),
) -> dict:
    """Closeout plan-coverage check: planned visits with outcomes, hidden works accepted."""
    await verify_project_access(project_id, user_id, session)
    return await service.plan_coverage(project_id)


__all__ = ["router"]

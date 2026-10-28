# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠FastAPI router for the source-data (prerequisite documents) register.

Auto-mounted at ``/api/v1/source-data/``. Every endpoint is project-scoped via
:func:`app.dependencies.verify_project_access` - the same guard the credentials
and compliance-docs modules use - so a caller cannot see or mutate source data
on a project they lack access to, and a cross-project id surfaces as 404 (not
403) so the endpoint can't be turned into an id-existence oracle.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query

from app.dependencies import (
    CurrentUserId,
    LangDep,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.source_data import intl
from app.modules.source_data.schemas import (
    CHECKLIST_STATUSES,
    DOC_TYPES,
    DOCUMENT_STATUSES,
    ChecklistSummary,
    DefectiveInputsNotice,
    SourceChecklistItemCreate,
    SourceChecklistItemResponse,
    SourceChecklistItemUpdate,
    SourceDocumentCreate,
    SourceDocumentResponse,
    SourceDocumentUpdate,
)
from app.modules.source_data.service import SourceDataService

router = APIRouter(tags=["source_data"])


def _get_service(session: SessionDep) -> SourceDataService:
    return SourceDataService(session)


def _to_response(item: object) -> SourceDocumentResponse:
    """Build a document response with the computed ``days_until_expiry``.

    ``None`` for a perpetual document (no ``valid_until``); otherwise a signed
    day count - negative once expired.
    """
    valid_until = getattr(item, "valid_until", None)
    days_until_expiry: int | None = None
    if valid_until is not None:
        try:
            days_until_expiry = (valid_until - datetime.now(UTC).date()).days
        except TypeError:  # pragma: no cover - defensive
            days_until_expiry = None

    resp = SourceDocumentResponse.model_validate(item)
    return resp.model_copy(update={"days_until_expiry": days_until_expiry})


# ── Meta ────────────────────────────────────────────────────────────────


@router.get(
    "/meta",
    dependencies=[Depends(RequirePermission("source_data.read"))],
)
async def get_meta(lang: LangDep) -> dict:
    """Expose the validated vocabularies with localized labels for the UI.

    The frontend builds its type / status pickers from this payload so it never
    drifts from the server-side whitelists, and the labels come pre-translated
    for the requested locale (falling back to English).
    """
    return {
        "doc_types": [{"code": c, "label": intl.describe_type(c, lang)} for c in DOC_TYPES],
        "statuses": [{"code": s, "label": intl.describe_status(s, lang)} for s in DOCUMENT_STATUSES],
        "checklist_statuses": list(CHECKLIST_STATUSES),
    }


# ── Documents ───────────────────────────────────────────────────────────


@router.get(
    "/documents",
    response_model=list[SourceDocumentResponse],
    dependencies=[Depends(RequirePermission("source_data.read"))],
)
async def list_documents(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    status_filter: str | None = Query(default=None, alias="status"),
    doc_type: str | None = Query(default=None),
    service: SourceDataService = Depends(_get_service),
) -> list[SourceDocumentResponse]:
    """List source documents for a project, optionally filtered."""
    await verify_project_access(project_id, user_id, session)
    items = await service.list_documents(project_id, status=status_filter, doc_type=doc_type)
    return [_to_response(i) for i in items]


@router.get(
    "/expiring-soon",
    response_model=list[SourceDocumentResponse],
    dependencies=[Depends(RequirePermission("source_data.read"))],
)
async def list_expiring_soon(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    limit: int = Query(default=50, ge=1, le=200),
    service: SourceDataService = Depends(_get_service),
) -> list[SourceDocumentResponse]:
    """Documents already expired or due within their reminder window.

    Ascending by expiry - designed for the dashboard "source data to renew"
    widget.
    """
    await verify_project_access(project_id, user_id, session)
    items = await service.list_expiring_soon(project_id, limit=limit)
    return [_to_response(i) for i in items]


@router.get(
    "/blocking-schedule",
    response_model=list[SourceDocumentResponse],
    dependencies=[Depends(RequirePermission("source_data.read"))],
)
async def list_blocking_schedule(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    service: SourceDataService = Depends(_get_service),
) -> list[SourceDocumentResponse]:
    """Prerequisite documents that block the programme: flagged and expired."""
    await verify_project_access(project_id, user_id, session)
    items = await service.list_blocking_schedule(project_id)
    return [_to_response(i) for i in items]


@router.get(
    "/defective-inputs-notice",
    response_model=DefectiveInputsNotice,
    dependencies=[Depends(RequirePermission("source_data.read"))],
)
async def get_defective_inputs_notice(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    service: SourceDataService = Depends(_get_service),
) -> DefectiveInputsNotice:
    """Structured "defective or missing source data" payload for correspondence.

    Returns data only (missing prerequisites + expired documents + a summary);
    another module renders the actual letter.
    """
    await verify_project_access(project_id, user_id, session)
    return await service.defective_inputs_notice(project_id)


@router.post(
    "/documents",
    response_model=SourceDocumentResponse,
    status_code=201,
)
async def create_document(
    data: SourceDocumentCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("source_data.create")),
    service: SourceDataService = Depends(_get_service),
) -> SourceDocumentResponse:
    """Register a new prerequisite document against a project."""
    await verify_project_access(data.project_id, user_id, session)
    document = await service.create_document(data, user_id=user_id)
    return _to_response(document)


@router.get(
    "/documents/{document_id}",
    response_model=SourceDocumentResponse,
    dependencies=[Depends(RequirePermission("source_data.read"))],
)
async def get_document(
    document_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    service: SourceDataService = Depends(_get_service),
) -> SourceDocumentResponse:
    """Read a single source document."""
    document = await service.get_document(document_id)
    await verify_project_access(document.project_id, user_id, session)
    return _to_response(document)


@router.patch(
    "/documents/{document_id}",
    response_model=SourceDocumentResponse,
)
async def update_document(
    document_id: uuid.UUID,
    data: SourceDocumentUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("source_data.update")),
    service: SourceDataService = Depends(_get_service),
) -> SourceDocumentResponse:
    """Patch a document. Status is recomputed from the validity window."""
    existing = await service.get_document(document_id)
    await verify_project_access(existing.project_id, user_id, session)
    document = await service.update_document(document_id, data, user_id=user_id)
    return _to_response(document)


@router.post(
    "/documents/{document_id}/verify",
    response_model=SourceDocumentResponse,
)
async def verify_document(
    document_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("source_data.update")),
    service: SourceDataService = Depends(_get_service),
) -> SourceDocumentResponse:
    """Mark a document verified; the validity window still governs the status."""
    existing = await service.get_document(document_id)
    await verify_project_access(existing.project_id, user_id, session)
    document = await service.verify_document(document_id, user_id=user_id)
    return _to_response(document)


@router.delete(
    "/documents/{document_id}",
    status_code=204,
)
async def delete_document(
    document_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("source_data.delete")),
    service: SourceDataService = Depends(_get_service),
) -> None:
    """Delete a source document."""
    existing = await service.get_document(document_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_document(document_id)


# ── Checklist ───────────────────────────────────────────────────────────


@router.get(
    "/checklist/summary",
    response_model=ChecklistSummary,
    dependencies=[Depends(RequirePermission("source_data.read"))],
)
async def get_checklist_summary(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    service: SourceDataService = Depends(_get_service),
) -> ChecklistSummary:
    """Completeness roll-up of a project's required source-data checklist."""
    await verify_project_access(project_id, user_id, session)
    return await service.checklist_summary(project_id)


@router.get(
    "/checklist",
    response_model=list[SourceChecklistItemResponse],
    dependencies=[Depends(RequirePermission("source_data.read"))],
)
async def list_checklist(
    user_id: CurrentUserId,
    session: SessionDep,
    project_id: uuid.UUID = Query(...),
    service: SourceDataService = Depends(_get_service),
) -> list[SourceChecklistItemResponse]:
    """List the source-data checklist items for a project."""
    await verify_project_access(project_id, user_id, session)
    return await service.list_checklist(project_id)


@router.post(
    "/checklist",
    response_model=SourceChecklistItemResponse,
    status_code=201,
)
async def create_checklist_item(
    data: SourceChecklistItemCreate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("source_data.create")),
    service: SourceDataService = Depends(_get_service),
) -> SourceChecklistItemResponse:
    """Add a prerequisite to a project's source-data checklist."""
    await verify_project_access(data.project_id, user_id, session)
    return await service.create_checklist_item(data)


@router.patch(
    "/checklist/{item_id}",
    response_model=SourceChecklistItemResponse,
)
async def update_checklist_item(
    item_id: uuid.UUID,
    data: SourceChecklistItemUpdate,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("source_data.update")),
    service: SourceDataService = Depends(_get_service),
) -> SourceChecklistItemResponse:
    """Patch a checklist item (e.g. mark satisfied or waived)."""
    existing = await service.get_checklist_item(item_id)
    await verify_project_access(existing.project_id, user_id, session)
    return await service.update_checklist_item(item_id, data)


@router.delete(
    "/checklist/{item_id}",
    status_code=204,
)
async def delete_checklist_item(
    item_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    _perm: None = Depends(RequirePermission("source_data.delete")),
    service: SourceDataService = Depends(_get_service),
) -> None:
    """Delete a checklist item."""
    existing = await service.get_checklist_item(item_id)
    await verify_project_access(existing.project_id, user_id, session)
    await service.delete_checklist_item(item_id)


__all__ = ["router"]

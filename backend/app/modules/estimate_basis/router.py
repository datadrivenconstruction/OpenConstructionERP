# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Estimate-basis API routes.

Mounted at ``/api/v1/estimate-basis``. Drafts, stores, edits and exports the
basis-of-estimate for a project:

    GET  /classes                       - the AACE class table and its bands
    POST /generate                      - draft a fresh basis from the estimate
    GET  /projects/{project_id}         - list a project's basis documents
    GET  /documents/{document_id}       - fetch one document
    PUT  /documents/{document_id}       - save edits (inclusions/exclusions/...)
    GET  /documents/{document_id}/export - Markdown (or JSON) for the proposal

Reads need viewer access; generating and editing need editor access. Every route
additionally checks the caller may reach the underlying project (404 on both
missing and forbidden, so a project id is never an existence oracle).
"""

from __future__ import annotations

import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.content_disposition import attachment_disposition
from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    verify_project_access,
)
from app.modules.estimate_basis.models import EstimateBasis
from app.modules.estimate_basis.schemas import (
    EstimateBasisListResponse,
    EstimateBasisResponse,
    EstimateClassCatalog,
    GenerateRequest,
    UpdateRequest,
)
from app.modules.estimate_basis.service import EstimateBasisService

router = APIRouter()

_READ = Depends(RequirePermission("estimate_basis.read"))
_WRITE = Depends(RequirePermission("estimate_basis.write"))
_GENERATE = Depends(RequirePermission("estimate_basis.generate"))


def _coerce_uuid(value: str) -> uuid.UUID | None:
    """Best-effort parse of the JWT subject string into a UUID (for provenance)."""
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


async def _load_owned_document(
    document_id: uuid.UUID,
    user_id: str,
    session: AsyncSession,
) -> EstimateBasis:
    """Load a document and verify the caller may reach its project (else 404)."""
    service = EstimateBasisService(session)
    doc = await service.get_document(document_id)
    if doc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Basis of estimate not found")
    # 404 (not 403) on forbidden - same non-disclosure policy as the rest of the app.
    await verify_project_access(doc.project_id, user_id, session)
    return doc


@router.get("/classes", response_model=EstimateClassCatalog, dependencies=[_READ])
async def list_classes() -> EstimateClassCatalog:
    """List all registered estimate classification systems and their classes.

    Returns every class from every system (AACE 18R-97, Canadian CCA, etc.)
    so a client never hardcodes a standard's numbers. Each item carries a
    ``classification_system`` field for filtering by jurisdiction.
    """
    return EstimateBasisService.class_catalog()


@router.post("/generate", response_model=EstimateBasisResponse, dependencies=[_GENERATE])
async def generate(
    payload: GenerateRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> EstimateBasisResponse:
    """Draft and store a basis-of-estimate from a project's estimate contents."""
    await verify_project_access(payload.project_id, user_id, session)
    service = EstimateBasisService(session)
    doc = await service.generate(
        project_id=payload.project_id,
        boq_id=payload.boq_id,
        title=payload.title,
        currency=payload.currency,
        base_date=payload.base_date,
        created_by=_coerce_uuid(user_id),
    )
    return service.to_response(doc)


@router.get("/projects/{project_id}", response_model=EstimateBasisListResponse, dependencies=[_READ])
async def list_for_project(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> EstimateBasisListResponse:
    """List every basis-of-estimate drafted for a project, newest first."""
    await verify_project_access(project_id, user_id, session)
    service = EstimateBasisService(session)
    docs = await service.list_for_project(project_id)
    return EstimateBasisListResponse(
        project_id=str(project_id),
        items=[service.to_summary(d) for d in docs],
    )


@router.get("/documents/{document_id}", response_model=EstimateBasisResponse, dependencies=[_READ])
async def get_document(
    document_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
) -> EstimateBasisResponse:
    """Fetch one basis-of-estimate document."""
    doc = await _load_owned_document(document_id, user_id, session)
    return EstimateBasisService.to_response(doc)


@router.put("/documents/{document_id}", response_model=EstimateBasisResponse, dependencies=[_WRITE])
async def update_document(
    document_id: uuid.UUID,
    payload: UpdateRequest,
    session: SessionDep,
    user_id: CurrentUserId,
) -> EstimateBasisResponse:
    """Save user edits to a basis-of-estimate document."""
    doc = await _load_owned_document(document_id, user_id, session)
    service = EstimateBasisService(session)
    doc = await service.update_document(doc, payload)
    return service.to_response(doc)


@router.get("/documents/{document_id}/export", dependencies=[_READ])
async def export_document(
    document_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    fmt: str = Query(default="markdown", pattern="^(markdown|json)$", alias="format"),
) -> object:
    """Export the document to attach to a proposal.

    ``format=markdown`` (default) streams a readable Markdown file; ``format=json``
    returns the structured document for a downstream renderer.
    """
    doc = await _load_owned_document(document_id, user_id, session)
    if fmt == "json":
        return EstimateBasisService.to_response(doc)

    text = EstimateBasisService.render_markdown(doc)
    safe = (doc.title or "basis_of_estimate").replace("/", "-").replace(" ", "_")[:80]
    return StreamingResponse(
        io.BytesIO(text.encode("utf-8")),
        media_type="text/markdown",
        headers={"Content-Disposition": attachment_disposition(f"basis_of_estimate_{safe}.md")},
    )

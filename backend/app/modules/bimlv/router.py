# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BIM-LV container API routes (DIN SPEC 91350).

Endpoints:
    POST /projects/{project_id}/import   - Upload a container, materialize links
    GET  /boqs/{boq_id}/export           - Download a BOQ as a BIM-LV container
"""

import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response

from app.core.content_disposition import attachment_disposition
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.bimlv import service
from app.modules.bimlv.container import BimLvContainerError, read_container
from app.modules.bimlv.schemas import BimLvImportResponse, ModelReferenceOut
from app.modules.boq.models import BOQ

router = APIRouter(tags=["bimlv"])
logger = logging.getLogger(__name__)

# Hard ceiling on an uploaded container before it even reaches the codec's own
# per-member ceilings - keeps a hostile multi-GB upload from being buffered.
_MAX_UPLOAD_BYTES = 128 * 1024 * 1024


@router.post(
    "/projects/{project_id}/import",
    response_model=BimLvImportResponse,
    summary="Import a DIN SPEC 91350 BIM-LV container and materialize its links",
)
async def import_container(
    project_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    file: UploadFile = File(...),
    _perm: None = Depends(RequirePermission("bim.create")),
) -> BimLvImportResponse:
    """Upload a BIM-LV container and create BOQ<->BIM element links from it.

    The container's positions and BIM elements must already exist in the
    project (imported through the GAEB and BIM pipelines); this endpoint
    materializes the traceability links between them. Ordinals or GUIDs that do
    not resolve are reported back rather than dropped silently.
    """
    await verify_project_access(project_id, user_id, session)

    try:
        payload = await file.read()
    except Exception as exc:
        logger.exception("Unable to read BIM-LV container upload")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to read the uploaded container",
        ) from exc

    if len(payload) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Container upload exceeds the size limit",
        )

    try:
        parsed = read_container(payload)
    except BimLvContainerError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    result = await service.materialize_links(project_id, parsed, session, user_id=user_id)

    return BimLvImportResponse(
        created=result.created,
        skipped_existing=result.skipped_existing,
        matched_ordinals=result.matched_ordinals,
        total_ordinals=result.total_ordinals,
        unmatched_ordinals=result.unmatched_ordinals,
        unmatched_guids=result.unmatched_guids,
        position_count=len(parsed.positions),
        model_reference=ModelReferenceOut(
            filename=parsed.model_ref.filename,
            model_id=parsed.model_ref.model_id,
            ifc_schema=parsed.model_ref.schema,
            guid=parsed.model_ref.guid,
            checksum=parsed.model_ref.checksum,
        ),
        warnings=parsed.warnings,
    )


@router.get(
    "/boqs/{boq_id}/export",
    summary="Export a BOQ as a DIN SPEC 91350 BIM-LV container",
)
async def export_boq_container(
    boq_id: uuid.UUID,
    session: SessionDep,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("boq.read")),
) -> Response:
    """Download the BOQ (GAEB LV + BIM model reference + link table) as a
    BIM-LV container ZIP.
    """
    boq = await session.get(BOQ, boq_id)
    if boq is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOQ not found")
    await verify_project_access(boq.project_id, user_id, session)

    try:
        export = await service.export_container(boq_id, session)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BOQ not found") from exc

    return Response(
        content=export.data,
        media_type="application/zip",
        headers={"Content-Disposition": attachment_disposition(export.filename)},
    )

"""Routes for the details the estimate PDF prints about client, site and payment.

Included into the BOQ ``router`` so the routes mount under ``/api/v1/boq``:

    GET  /projects/{project_id}/pdf-details/   - the stored details
    PUT  /projects/{project_id}/pdf-details/   - replace them
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm.attributes import flag_modified

from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.boq.pdf_details import PdfDetails, merged_metadata, read_details
from app.modules.projects.models import Project

pdf_details_router = APIRouter(tags=["boq"])


async def _project(session: SessionDep, project_id: uuid.UUID, user_id: str) -> Project:
    await verify_project_access(project_id, user_id, session)
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@pdf_details_router.get(
    "/projects/{project_id}/pdf-details/",
    response_model=PdfDetails,
    summary="Details printed on the estimate PDF",
    dependencies=[Depends(RequirePermission("boq.read"))],
)
async def get_pdf_details(project_id: uuid.UUID, user_id: CurrentUserId, session: SessionDep) -> PdfDetails:
    """Client, site, payment terms and the columns left out of the printed estimate."""
    project = await _project(session, project_id, user_id)
    return read_details(project.metadata_)


@pdf_details_router.put(
    "/projects/{project_id}/pdf-details/",
    response_model=PdfDetails,
    summary="Set the details printed on the estimate PDF",
    dependencies=[Depends(RequirePermission("boq.update"))],
)
async def put_pdf_details(
    project_id: uuid.UUID, body: PdfDetails, user_id: CurrentUserId, session: SessionDep
) -> PdfDetails:
    """Replace the stored details; text is cleaned and unknown columns are dropped."""
    project = await _project(session, project_id, user_id)
    project.metadata_ = merged_metadata(project.metadata_, body)
    flag_modified(project, "metadata_")
    await session.flush()
    return body

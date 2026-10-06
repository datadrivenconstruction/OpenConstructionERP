# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Import a regional price list (prezzario regionale) as a cost catalogue.

The import screen works through background jobs, so a list of any size is
read and written without a request outlasting the proxy (``pricelist_jobs``):

    POST   /import/pricelist/uploads/                      -- store the upload, start its preview
    POST   /import/pricelist/uploads/{upload_id}/preview/  -- preview again with the user's corrections
    POST   /import/pricelist/uploads/{upload_id}/import/   -- create the catalogue and import the voci
    GET    /import/pricelist/jobs/{job_id}                 -- progress, then the result or the refusal
    DELETE /import/pricelist/uploads/{upload_id}/          -- the user cancelled

Two synchronous calls stay for API users with small lists, and answer the same
payloads and refusal codes:

    POST /import/pricelist/preview/  -- recognise the format and report what the list holds
    POST /import/pricelist/file/     -- create the catalogue and import the priced voci

Mounted by ``costs/router.py`` (the module loader mounts one router per module).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status

from app.dependencies import CurrentUserPayload, RequirePermission, SessionDep
from app.modules.costs import pricelist_jobs
from app.modules.costs.pricelist_import import (
    PriceListRefused,
    check_catalog_name,
    import_list,
    preview,
    with_free_suggestion,
)
from app.modules.costs.pricelists.containers import ContainerRefused
from app.modules.costs.pricelists.service import UploadPlan, plan_upload

router = APIRouter(tags=["costs"])

_CREATE = [Depends(RequirePermission("costs.create"))]


def _owner(user: dict[str, Any] | None) -> str:
    """The caller's user id, which owns the uploads and jobs they start."""
    try:
        return str(uuid.UUID(str((user or {}).get("sub"))))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated") from exc


def _plan(file: UploadFile) -> UploadPlan:
    try:
        return plan_upload(file.file, file.filename or "upload")
    except ContainerRefused as exc:
        raise PriceListRefused(exc.code, **exc.params).as_http() from exc


# ── Background flow (the import screen) ──────────────────────────────────


@router.post("/import/pricelist/uploads/", status_code=status.HTTP_202_ACCEPTED, dependencies=_CREATE)
async def upload_pricelist(
    user: CurrentUserPayload,
    file: UploadFile = File(..., description="A regional price list: XML, CSV, XLSX, JSON, or the ZIP as published"),
    region_code: str | None = Form(
        default=None, description="Region prefix (TOS, LOM, ...) when the file does not say"
    ),
    edition: str | None = Form(default=None, description="Edition year when the file does not say"),
) -> dict[str, Any]:
    """Store the upload and start reading it; poll ``jobs/{job_id}`` for the preview."""
    owner = _owner(user)
    try:
        upload_id, name = await pricelist_jobs.store_upload(file.file, file.filename or "upload", owner)
        key = await pricelist_jobs.find_upload(upload_id, owner)
    except PriceListRefused as exc:
        raise exc.as_http() from exc
    job = await pricelist_jobs.submit_preview(
        upload_id=upload_id, storage_key=key, file_name=name, owner_id=owner, region_code=region_code, edition=edition
    )
    return {"upload_id": upload_id, "job_id": str(job.id)}


@router.post(
    "/import/pricelist/uploads/{upload_id}/preview/", status_code=status.HTTP_202_ACCEPTED, dependencies=_CREATE
)
async def repreview_pricelist(
    upload_id: str,
    user: CurrentUserPayload,
    region_code: str | None = Form(default=None),
    edition: str | None = Form(default=None),
) -> dict[str, Any]:
    """Read the stored upload again with the region or edition the user corrected."""
    owner = _owner(user)
    try:
        key = await pricelist_jobs.find_upload(upload_id, owner)
    except PriceListRefused as exc:
        raise exc.as_http() from exc
    job = await pricelist_jobs.submit_preview(
        upload_id=upload_id,
        storage_key=key,
        file_name=key.rsplit("/", 1)[-1],
        owner_id=owner,
        region_code=region_code,
        edition=edition,
    )
    return {"upload_id": upload_id, "job_id": str(job.id)}


@router.post(
    "/import/pricelist/uploads/{upload_id}/import/", status_code=status.HTTP_202_ACCEPTED, dependencies=_CREATE
)
async def import_uploaded_pricelist(
    upload_id: str,
    user: CurrentUserPayload,
    catalog_name: str = Form(..., description='New catalogue name, e.g. "Toscana 2025 - Firenze"'),
    region_code: str | None = Form(default=None),
    edition: str | None = Form(default=None),
    expected_rows: int | None = Form(default=None, ge=0, description="Rows the preview counted, for progress"),
) -> dict[str, Any]:
    """Start importing the stored upload into a new catalogue; poll ``jobs/{job_id}`` for progress."""
    owner = _owner(user)
    try:
        name = check_catalog_name(catalog_name)
        key = await pricelist_jobs.find_upload(upload_id, owner)
    except PriceListRefused as exc:
        raise exc.as_http() from exc
    job = await pricelist_jobs.submit_import(
        upload_id=upload_id,
        storage_key=key,
        owner_id=owner,
        catalog_name=name,
        region_code=region_code,
        edition=edition,
        expected_rows=expected_rows,
    )
    return {"upload_id": upload_id, "job_id": str(job.id)}


@router.get("/import/pricelist/jobs/{job_id}", dependencies=_CREATE)
async def read_pricelist_job(job_id: uuid.UUID, user: CurrentUserPayload) -> dict[str, Any]:
    """Progress of one of the caller's preview or import jobs, then its result or the refusal.

    ``status`` is pending, started, success or failed. While running,
    ``stage`` names the step (``reading``, ``writing``), ``rows_read`` and
    ``imported`` count up, and ``progress_percent`` moves when the total is
    known. On success ``result`` holds the preview or the import result the
    synchronous endpoints answer; on failure ``error`` holds the refusal code
    and its parameters.
    """
    view = await pricelist_jobs.read_job(job_id, _owner(user))
    if view is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import job not found")
    return view


@router.delete("/import/pricelist/uploads/{upload_id}/", status_code=status.HTTP_204_NO_CONTENT, dependencies=_CREATE)
async def delete_uploaded_pricelist(upload_id: str, user: CurrentUserPayload) -> Response:
    """Forget an upload the user cancelled."""
    await pricelist_jobs.delete_upload(upload_id, _owner(user))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Synchronous calls (API users, small lists) ───────────────────────────


@router.post("/import/pricelist/preview/", dependencies=_CREATE)
async def preview_pricelist(
    _user: CurrentUserPayload,
    session: SessionDep,
    file: UploadFile = File(..., description="A regional price list: XML, CSV, XLSX, JSON, or the ZIP as published"),
    region_code: str | None = Form(
        default=None, description="Region prefix (TOS, LOM, ...) when the file does not say"
    ),
    edition: str | None = Form(default=None, description="Edition year when the file does not say"),
) -> dict[str, Any]:
    """Recognise the price list in an upload and report it without writing anything.

    The response names the format, region, edition, area, licence and
    attribution as the file (or the publisher's catalogue record) states them,
    with counts, the chapters, sample rows and the suggested catalogue name.
    ``warnings`` carries reason codes the UI translates: ``region_inferred``
    and ``region_not_detected`` ask the user to confirm or pick the region,
    ``broken_numbers`` says some cells could not be read as numbers and were
    left out rather than guessed.
    """
    plan = _plan(file)
    try:
        report = await asyncio.to_thread(preview, plan, region_code, edition)
    except PriceListRefused as exc:
        raise exc.as_http() from exc
    return await with_free_suggestion(session, report)


@router.post("/import/pricelist/file/", dependencies=_CREATE)
async def import_pricelist(
    user: CurrentUserPayload,
    session: SessionDep,
    file: UploadFile = File(..., description="The same upload the preview read"),
    catalog_name: str = Form(..., description='New catalogue name, e.g. "Toscana 2025 - Firenze"'),
    region_code: str | None = Form(default=None),
    edition: str | None = Form(default=None),
) -> dict[str, Any]:
    """Create a catalogue named by the user and import the list's priced voci into it.

    Every item carries the voce code as its ``voci`` classification, the
    Italian text, the normalised unit, the rate in euro, and under
    ``metadata.prezzario`` the region, edition, licence, attribution, chapter
    path and the labour, safety, overhead and profit shares the list states.
    Items with an analysis carry it as components that add up to the rate.
    """
    try:
        name = check_catalog_name(catalog_name)
        plan = _plan(file)
        try:
            owner: uuid.UUID | None = uuid.UUID(str((user or {}).get("sub")))
        except (ValueError, TypeError):
            owner = None
        return await import_list(
            session, plan, catalog_name=name, region_code=region_code, edition=edition, owner_id=owner
        )
    except PriceListRefused as exc:
        raise exc.as_http() from exc


__all__ = ["router"]

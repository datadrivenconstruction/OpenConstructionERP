"""ACAP module API routes."""

from __future__ import annotations

import logging
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi import File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.dependencies import get_current_user_payload
from app.modules.acap.authz import require_project_access, require_project_owner
from app.modules.acap.layout.schema import FloorPlan

logger = logging.getLogger(__name__)

router = APIRouter(tags=["acap"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe for the ACAP module. Unauthenticated."""
    return {"status": "ok", "module": "acap"}


# ── Layout generation ────────────────────────────────────────────────────────


class GenerateLayoutRequest(BaseModel):
    requirement_text: str
    kavling_width_m: float = Field(gt=0.0)
    kavling_length_m: float = Field(gt=0.0)
    jumlah_lantai: int = Field(default=1, ge=1)


class GenerateLayoutResponse(BaseModel):
    version: int
    plan: dict
    project_id: _uuid.UUID


async def get_session():
    """Yield an async database session (local copy to avoid import-order issues)."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@router.post("/projects/{project_id}/layout:generate")
async def generate_layout_endpoint(
    project_id: _uuid.UUID,
    body: GenerateLayoutRequest,
    session: AsyncSession = Depends(get_session),
    payload: dict = Depends(get_current_user_payload),
) -> GenerateLayoutResponse:
    """Generate a new floor-plan version for *project_id* via LLM.

    Each call creates a new version (does NOT overwrite older versions).
    The generated plan is validated against :mod:`app.modules.acap.layout.validator`.
    """
    await require_project_owner(session, project_id, payload)

    from app.modules.acap.layout.generator import LayoutGenerationError, generate_layout
    from app.modules.acap.models.floor_plan import FloorPlanRecord, next_version

    try:
        plan = await generate_layout(
            session=session,
            requirement_text=body.requirement_text,
            kavling_width_m=body.kavling_width_m,
            kavling_length_m=body.kavling_length_m,
            jumlah_lantai=body.jumlah_lantai,
            user_id=payload["sub"],
        )
    except LayoutGenerationError as e:
        status = 400 if e.attempts == 0 else 422
        raise HTTPException(
            status_code=status,
            detail={
                "detail": str(e),
                "reasons": e.reasons,
                "attempts": e.attempts,
            },
        ) from e

    # Persist
    version = await next_version(session, project_id)
    record = FloorPlanRecord(
        project_id=project_id,
        version=version,
        requirement_text=body.requirement_text,
        jumlah_lantai=body.jumlah_lantai,
        model=plan.generated_by,
        status="generated",
        plan_json=plan.model_dump(),
    )
    session.add(record)
    await session.flush()

    logger.info(
        "Generated layout v%d for project %s (model=%s)",
        version,
        project_id,
        plan.generated_by,
    )

    return GenerateLayoutResponse(
        version=version,
        plan=plan.model_dump(),
        project_id=project_id,
    )


# ── Layout editing ───────────────────────────────────────────────────────────


class LayoutGetResponse(BaseModel):
    version: int
    status: str
    plan: dict


class LayoutSaveResponse(BaseModel):
    version: int
    plan: dict


@router.get("/projects/{project_id}/layout")
async def get_latest_layout_endpoint(
    project_id: _uuid.UUID,
    session: AsyncSession = Depends(get_session),
    payload: dict = Depends(get_current_user_payload),
) -> LayoutGetResponse:
    """Return the latest (highest version) floor-plan for *project_id*."""
    await require_project_access(session, project_id, payload)

    from sqlalchemy import select

    from app.modules.acap.models.floor_plan import FloorPlanRecord

    stmt = (
        select(FloorPlanRecord)
        .where(FloorPlanRecord.project_id == project_id)
        .order_by(FloorPlanRecord.version.desc())
        .limit(1)
    )
    record = (await session.execute(stmt)).scalars().first()
    if record is None:
        raise HTTPException(status_code=404, detail="No layout for this project")

    return LayoutGetResponse(version=record.version, status=record.status, plan=record.plan_json)


@router.put("/projects/{project_id}/layout")
async def save_layout_endpoint(
    project_id: _uuid.UUID,
    body: FloorPlan,
    session: AsyncSession = Depends(get_session),
    payload: dict = Depends(get_current_user_payload),
) -> LayoutSaveResponse:
    """Persist an edited floor-plan as a NEW version (never overwrites older ones).

    Validated against :mod:`app.modules.acap.layout.validator` before saving.
    """
    await require_project_owner(session, project_id, payload)

    from app.modules.acap.layout.validator import LayoutValidationError, validate_plan
    from app.modules.acap.models.floor_plan import FloorPlanRecord, next_version

    try:
        validate_plan(body)
    except LayoutValidationError as e:
        raise HTTPException(
            status_code=422,
            detail={"detail": "Layout invalid", "reasons": e.reasons},
        ) from e

    version = await next_version(session, project_id)
    record = FloorPlanRecord(
        project_id=project_id,
        version=version,
        requirement_text=body.requirement_text,
        jumlah_lantai=body.jumlah_lantai,
        model=body.generated_by,
        status="edited",
        plan_json=body.model_dump(),
    )
    session.add(record)
    await session.flush()

    logger.info("Saved edited layout v%d for project %s", version, project_id)

    return LayoutSaveResponse(version=version, plan=body.model_dump())


# ── RAB (bill-of-quantities) generation ─────────────────────────────────────


class GenerateRabResponse(BaseModel):
    boq_id: _uuid.UUID
    grand_total: str
    subtotals_by_kategori: dict[str, str]
    lines: list[dict]
    price_missing_lines: list[dict]
    curated_lines: list[dict]
    not_covered: list[str]


@router.post("/projects/{project_id}/rab:generate")
async def generate_rab_endpoint(
    project_id: _uuid.UUID,
    session: AsyncSession = Depends(get_session),
    payload: dict = Depends(get_current_user_payload),
) -> GenerateRabResponse:
    """Generate + persist a deterministic RAB (bill of quantities) for *project_id*.

    Loads the latest saved FloorPlan, computes qty (pure geometry, see
    :mod:`app.modules.acap.takeoff`) x AHSP koefisien x Batam material price
    for the wall/finish scope (see :mod:`app.modules.acap.rab.generator`),
    and persists the result as a BOQ + Positions. NO LLM anywhere in this
    path — every number is deterministic; a missing Batam price is flagged
    (never guessed) and surfaced in ``price_missing_lines``.

    The persisted ``boq_id`` can be rendered immediately via the existing
    ``GET /boqs/{boq_id}/export/pdf/`` endpoint (no new PDF code needed here).
    """
    await require_project_owner(session, project_id, payload)

    from sqlalchemy import select

    from app.modules.acap.models.floor_plan import FloorPlanRecord
    from app.modules.acap.rab.generator import generate_rab, persist_rab

    stmt = (
        select(FloorPlanRecord)
        .where(FloorPlanRecord.project_id == project_id)
        .order_by(FloorPlanRecord.version.desc())
        .limit(1)
    )
    record = (await session.execute(stmt)).scalars().first()
    if record is None:
        raise HTTPException(status_code=404, detail="No layout for this project")

    plan = FloorPlan.model_validate(record.plan_json)
    rab_result = await generate_rab(session, plan, project_id)
    boq_id = await persist_rab(session, project_id, rab_result)

    def _line_summary(line: dict) -> dict:
        return {
            "kode": line["kode"],
            "uraian": line["uraian"],
            "unit": line["unit"],
            "quantity": str(line["quantity"]),
            "unit_rate": None if line["unit_rate"] is None else str(line["unit_rate"]),
            "total": None if line["total"] is None else str(line["total"]),
            "kategori": line["kategori"],
            "price_missing": line["price_missing"],
            "missing_resources": line["missing_resources"],
            "curated_resources": line.get("curated_resources", []),
        }

    return GenerateRabResponse(
        boq_id=boq_id,
        grand_total=str(rab_result.grand_total),
        subtotals_by_kategori={kategori: str(total) for kategori, total in rab_result.subtotals_by_kategori.items()},
        lines=[_line_summary(line) for line in rab_result.lines],
        price_missing_lines=[_line_summary(line) for line in rab_result.price_missing_lines],
        curated_lines=[_line_summary(line) for line in rab_result.curated_lines],
        not_covered=rab_result.not_covered,
    )


# ── Timeline (construction schedule) generation ─────────────────────────────


class GenerateTimelineResponse(BaseModel):
    total_days: int
    tasks: list[dict]
    stages: list[dict]
    not_covered: list[str]


@router.post("/projects/{project_id}/timeline:generate")
async def generate_timeline_endpoint(
    project_id: _uuid.UUID,
    session: AsyncSession = Depends(get_session),
    payload: dict = Depends(get_current_user_payload),
) -> GenerateTimelineResponse:
    """Generate a deterministic construction timeline (Gantt JSON) for *project_id*.

    Loads the latest saved FloorPlan and derives each work item's duration from
    the AHSP labour coefficients x the SAME take-off quantities as the RAB
    (see :mod:`app.modules.acap.timeline.generator`). NO LLM: durations and
    sequencing are fully deterministic.
    """
    await require_project_owner(session, project_id, payload)

    from sqlalchemy import select

    from app.modules.acap.models.floor_plan import FloorPlanRecord
    from app.modules.acap.timeline.generator import generate_timeline

    stmt = (
        select(FloorPlanRecord)
        .where(FloorPlanRecord.project_id == project_id)
        .order_by(FloorPlanRecord.version.desc())
        .limit(1)
    )
    record = (await session.execute(stmt)).scalars().first()
    if record is None:
        raise HTTPException(status_code=404, detail="No layout for this project")

    plan = FloorPlan.model_validate(record.plan_json)
    result = await generate_timeline(session, plan)

    def _task_json(task: dict) -> dict:
        return {
            "element": task["element"],
            "kode": task["kode"],
            "uraian": task["uraian"],
            "unit": task["unit"],
            "stage": task["stage"],
            "crew": task["crew"],
            "quantity": str(task["quantity"]),
            "labor_oh_per_unit": str(task["labor_oh_per_unit"]),
            "man_days": str(task["man_days"]),
            "duration_days": task["duration_days"],
            "start_day": task["start_day"],
            "end_day": task["end_day"],
            "depends_on": task["depends_on"],
        }

    return GenerateTimelineResponse(
        total_days=result.total_days,
        tasks=[_task_json(t) for t in result.tasks],
        stages=result.stages,
        not_covered=result.not_covered,
    )


_TIMELINE_CSV_HEADER = [
    "stage", "kode", "uraian", "unit", "quantity", "labor_oh_per_unit",
    "man_days", "crew", "duration_days", "start_day", "end_day", "depends_on",
]


@router.get("/projects/{project_id}/timeline.csv")
async def export_timeline_csv_endpoint(
    project_id: _uuid.UUID,
    session: AsyncSession = Depends(get_session),
    payload: dict = Depends(get_current_user_payload),
) -> Response:
    """Export the project's construction timeline as a downloadable CSV.

    Same deterministic schedule as ``timeline:generate``, one row per task in
    start-day order. Returns 404 if the project has no saved layout.
    """
    await require_project_access(session, project_id, payload)

    import csv
    import io

    from sqlalchemy import select

    from app.modules.acap.models.floor_plan import FloorPlanRecord
    from app.modules.acap.timeline.generator import generate_timeline

    stmt = (
        select(FloorPlanRecord)
        .where(FloorPlanRecord.project_id == project_id)
        .order_by(FloorPlanRecord.version.desc())
        .limit(1)
    )
    record = (await session.execute(stmt)).scalars().first()
    if record is None:
        raise HTTPException(status_code=404, detail="No layout for this project")

    plan = FloorPlan.model_validate(record.plan_json)
    result = await generate_timeline(session, plan)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_TIMELINE_CSV_HEADER)
    for task in sorted(result.tasks, key=lambda t: (t["start_day"], t["stage"])):
        writer.writerow([
            task["stage"], task["kode"], task["uraian"], task["unit"],
            task["quantity"], task["labor_oh_per_unit"], task["man_days"],
            task["crew"], task["duration_days"], task["start_day"], task["end_day"],
            "|".join(task["depends_on"]),
        ])

    filename = f"timeline-{project_id}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Visual render (floor plan -> image via GeminiGen) ───────────────────────


class RenderResponse(BaseModel):
    render_id: _uuid.UUID
    floor_plan_version: int
    status: str
    prompt: str
    storage_key: str | None = None
    source_url: str | None = None
    error_message: str | None = None


def _render_json(record) -> RenderResponse:
    return RenderResponse(
        render_id=record.id,
        floor_plan_version=record.floor_plan_version,
        status=record.status,
        prompt=record.prompt,
        storage_key=record.storage_key,
        source_url=record.source_url,
        error_message=record.error_message,
    )


@router.post("/projects/{project_id}/render:generate")
async def generate_render_endpoint(
    project_id: _uuid.UUID,
    session: AsyncSession = Depends(get_session),
    payload: dict = Depends(get_current_user_payload),
) -> RenderResponse:
    """Render the latest floor-plan to an image (GeminiGen) and persist it.

    KEY-GATED: returns 400 (not 500) when ``GEMINIGEN_API_KEY`` is unset — the
    integration is real but the service is simply not configured yet. The
    render is DECORATIVE and never feeds the RAB. A provider failure persists a
    ``failed`` RenderRecord and returns it (status=failed) rather than erroring.
    """
    # Authorize BEFORE the key-gate so a non-owner cannot probe whether the
    # render service is configured.
    await require_project_owner(session, project_id, payload)

    from sqlalchemy import select

    from app.modules.acap.models.floor_plan import FloorPlanRecord
    from app.modules.acap.render.client import render_service_configured
    from app.modules.acap.render.generator import generate_render

    if not render_service_configured():
        raise HTTPException(
            status_code=400,
            detail={
                "detail": "Render service not configured",
                "reason": "GEMINIGEN_API_KEY not set",
            },
        )

    stmt = (
        select(FloorPlanRecord)
        .where(FloorPlanRecord.project_id == project_id)
        .order_by(FloorPlanRecord.version.desc())
        .limit(1)
    )
    record = (await session.execute(stmt)).scalars().first()
    if record is None:
        raise HTTPException(status_code=404, detail="No layout for this project")

    plan = FloorPlan.model_validate(record.plan_json)
    render = await generate_render(session, project_id, plan, record.version)
    return _render_json(render)


@router.get("/projects/{project_id}/renders")
async def list_renders_endpoint(
    project_id: _uuid.UUID,
    session: AsyncSession = Depends(get_session),
    payload: dict = Depends(get_current_user_payload),
) -> list[RenderResponse]:
    """List a project's renders, newest first."""
    await require_project_access(session, project_id, payload)

    from sqlalchemy import select

    from app.modules.acap.models.render import RenderRecord

    stmt = (
        select(RenderRecord)
        .where(RenderRecord.project_id == project_id)
        .order_by(RenderRecord.created_at.desc())
    )
    records = (await session.execute(stmt)).scalars().all()
    return [_render_json(r) for r in records]


# ── Interior render (per-room via GeminiGen) ─────────────────────────────────


class InteriorGenerateRequest(BaseModel):
    room_name: str
    style: str


class InteriorRenderResponse(BaseModel):
    interior_id: _uuid.UUID
    room_name: str
    style: str
    status: str
    prompt: str
    storage_key: str | None = None
    source_url: str | None = None
    error_message: str | None = None


def _interior_render_json(record) -> InteriorRenderResponse:
    return InteriorRenderResponse(
        interior_id=record.id,
        room_name=record.room_name,
        style=record.style,
        status=record.status,
        prompt=record.prompt,
        storage_key=record.storage_key,
        source_url=record.source_url,
        error_message=record.error_message,
    )


@router.post("/projects/{project_id}/interior:generate")
async def generate_interior_endpoint(
    project_id: _uuid.UUID,
    body: InteriorGenerateRequest,
    session: AsyncSession = Depends(get_session),
    payload: dict = Depends(get_current_user_payload),
) -> InteriorRenderResponse:
    """Generate an interior render for a single room via GeminiGen.

    Loads the latest saved FloorPlan, builds a prompt per room+style, calls
    the external render service, downloads the result to object storage, and
    persists an ``InteriorRenderRecord``. KEY-GATED: returns 400 (not 500)
    when ``GEMINIGEN_API_KEY`` is unset.
    """
    await require_project_owner(session, project_id, payload)

    from sqlalchemy import select

    from app.modules.acap.interior.prompts import build_interior_prompt
    from app.modules.acap.models.floor_plan import FloorPlanRecord
    from app.modules.acap.models.interior_render import InteriorRenderRecord
    from app.modules.acap.render.client import (
        RenderNotConfiguredError,
        RenderServiceError,
        generate_render_image,
        render_service_configured,
    )

    if not render_service_configured():
        raise HTTPException(
            status_code=400,
            detail={
                "detail": "Render service not configured",
                "reason": "GEMINIGEN_API_KEY not set",
            },
        )

    stmt = (
        select(FloorPlanRecord)
        .where(FloorPlanRecord.project_id == project_id)
        .order_by(FloorPlanRecord.version.desc())
        .limit(1)
    )
    record = (await session.execute(stmt)).scalars().first()
    if record is None:
        raise HTTPException(status_code=404, detail="Generate a floor plan first")

    plan = FloorPlan.model_validate(record.plan_json)

    # Find room by name across all levels.
    found_room = None
    for level in plan.levels:
        for room in level.rooms:
            if room.name == body.room_name:
                found_room = (room, level.level)
                break
        if found_room:
            break
    if found_room is None:
        raise HTTPException(
            status_code=422,
            detail=f"Room '{body.room_name}' not found in layout",
        )

    room, room_level = found_room

    try:
        prompt = build_interior_prompt(
            room_name=room.name,
            room_type=room.type,
            area_m2=room.area_m2,
            style=body.style,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    # Persist pending record first.
    irecord = InteriorRenderRecord(
        project_id=project_id,
        floor_plan_version=record.version,
        room_name=body.room_name,
        style=body.style,
        prompt=prompt,
        model="nano-banana-pro",
        status="pending",
    )
    session.add(irecord)
    await session.flush()

    # Call external render service.
    import httpx

    from app.core.storage import get_storage_backend

    try:
        result = await generate_render_image(prompt)
        media_url = result.get("media_url")
        if not media_url:
            raise RenderServiceError("provider returned no media URL")

        async with httpx.AsyncClient(timeout=60.0) as dl_client:
            dl_resp = await dl_client.get(media_url)
            if dl_resp.status_code >= 400:
                raise RenderServiceError(
                    f"download: HTTP {dl_resp.status_code} fetching image"
                )
            image_bytes = dl_resp.content
            if len(image_bytes) < 1024:
                raise RenderServiceError(
                    f"download: image body too small ({len(image_bytes)} bytes)"
                )

        from uuid import uuid4

        storage = get_storage_backend()
        key = f"acap/interiors/{project_id}/{uuid4().hex}.png"
        await storage.put(key, image_bytes)

        irecord.provider_uuid = result.get("uuid")
        irecord.source_url = media_url
        irecord.storage_key = key
        irecord.status = "completed"
    except RenderServiceError as exc:
        irecord.status = "failed"
        irecord.error_message = str(exc)[:500]

    await session.flush()
    return _interior_render_json(irecord)


@router.get("/projects/{project_id}/interiors")
async def list_interiors_endpoint(
    project_id: _uuid.UUID,
    room_name: str | None = None,
    session: AsyncSession = Depends(get_session),
    payload: dict = Depends(get_current_user_payload),
) -> list[InteriorRenderResponse]:
    """List a project's interior renders, newest first.

    Optionally filter by ``room_name`` query parameter.
    """
    await require_project_access(session, project_id, payload)

    from sqlalchemy import select

    from app.modules.acap.models.interior_render import InteriorRenderRecord

    stmt = (
        select(InteriorRenderRecord)
        .where(InteriorRenderRecord.project_id == project_id)
    )
    if room_name:
        stmt = stmt.where(InteriorRenderRecord.room_name == room_name)
    stmt = stmt.order_by(InteriorRenderRecord.created_at.desc())

    records = (await session.execute(stmt)).scalars().all()
    return [_interior_render_json(r) for r in records]


# ── Plan-image upload (Vision extract source) ────────────────────────────────


_ALLOWED_PLAN_IMAGE_CONTENT_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "application/pdf": "pdf",
}
_MAX_PLAN_IMAGE_BYTES = 15 * 1024 * 1024  # 15 MiB


class PlanImageResponse(BaseModel):
    image_id: _uuid.UUID
    filename: str
    content_type: str
    size_bytes: int


@router.post("/projects/{project_id}/plan-images")
async def upload_plan_image_endpoint(
    project_id: _uuid.UUID,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    payload: dict = Depends(get_current_user_payload),
) -> PlanImageResponse:
    """Persist an uploaded floor-plan image to object storage + record its metadata.

    Designed as the input to the Gemini-vision extract step. SECURITY:
    content-type is allowlisted, size is capped at 15 MiB, the storage key is
    server-generated (client filename is NEVER trusted into the key path), and
    authz (project owner) is checked BEFORE any byte of the body is read.
    """
    await require_project_owner(session, project_id, payload)

    content_type = (file.content_type or "").lower()
    ext = _ALLOWED_PLAN_IMAGE_CONTENT_TYPES.get(content_type)
    if ext is None:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    # Reject before pulling the whole body into a single bytes object. Starlette
    # populates file.size from the parsed part; when it's absent (no
    # content-length) fall back to the post-read check below.
    # ponytail: parser still spools the part first; a true streaming cap needs
    # Starlette max_part_size at app config — upgrade there if abuse shows up.
    if file.size is not None and file.size > _MAX_PLAN_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 15 MiB)")

    data = await file.read()
    if len(data) > _MAX_PLAN_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 15 MiB)")

    # Import INSIDE the handler so tests can monkeypatch get_storage_backend.
    from app.core.storage import get_storage_backend
    from uuid import uuid4

    from app.modules.acap.models.plan_image import PlanImageRecord

    storage = get_storage_backend()
    key = f"acap/plan-images/{project_id}/{uuid4().hex}.{ext}"
    await storage.put(key, data)

    record = PlanImageRecord(
        project_id=project_id,
        filename=file.filename or "unnamed",
        content_type=content_type,
        size_bytes=len(data),
        storage_key=key,
        status="uploaded",
    )
    session.add(record)
    await session.flush()

    logger.info(
        "Uploaded plan image %s for project %s (%d bytes, %s)",
        record.id,
        project_id,
        len(data),
        content_type,
    )

    return PlanImageResponse(
        image_id=record.id,
        filename=record.filename,
        content_type=record.content_type,
        size_bytes=record.size_bytes,
    )


# ── Plan-image extraction (Gemini vision) ──────────────────────────────────


class ExtractResponse(BaseModel):
    draft_plan: dict
    valid: bool
    reasons: list[str]
    model: str


@router.post("/projects/{project_id}/plan-images/{image_id}/extract")
async def extract_plan_image_endpoint(
    project_id: _uuid.UUID,
    image_id: _uuid.UUID,
    session: AsyncSession = Depends(get_session),
    payload: dict = Depends(get_current_user_payload),
) -> ExtractResponse:
    """Extract a floor-plan from an uploaded plan image via Gemini vision.

    Key-gated: returns 400 (not 500) when ``GOOGLE_API_KEY`` is unset.
    The extract NEVER writes to ``oe_acap_floor_plan`` — the draft is returned
    to the caller for manual confirmation and optional save.
    """
    await require_project_owner(session, project_id, payload)

    from app.modules.acap.models.plan_image import PlanImageRecord
    from app.modules.acap.vision.client import (
        VisionNotConfiguredError,
        VisionServiceError,
        _model,
        extract_floor_plan,
        vision_service_configured,
    )
    from app.modules.acap.vision.extractor import build_draft_plan
    from app.core.storage import get_storage_backend

    if not vision_service_configured():
        raise HTTPException(
            status_code=400,
            detail={
                "detail": "Vision service not configured",
                "reason": "GOOGLE_API_KEY not set",
            },
        )

    from sqlalchemy import select

    stmt = select(PlanImageRecord).where(PlanImageRecord.id == image_id)
    record = (await session.execute(stmt)).scalars().first()
    if record is None or record.project_id != project_id:
        raise HTTPException(status_code=404, detail="Plan image not found")

    storage = get_storage_backend()
    try:
        image_bytes = await storage.get(record.storage_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Image data not found in storage")

    try:
        extraction = await extract_floor_plan(image_bytes, record.content_type)
    except VisionNotConfiguredError:
        raise HTTPException(
            status_code=400,
            detail={
                "detail": "Vision service not configured",
                "reason": "GOOGLE_API_KEY not set",
            },
        )
    except VisionServiceError as e:
        raise HTTPException(status_code=502, detail="Vision extraction failed")

    draft, valid, reasons = build_draft_plan(extraction)

    return ExtractResponse(
        draft_plan=draft,
        valid=valid,
        reasons=reasons,
        model=_model(),
    )

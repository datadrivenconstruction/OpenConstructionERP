# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Match Elements REST router.

Endpoints (auto-mounted at /api/v1/match_elements/ by the module loader):

    POST   /sessions                       Create session (auto-bind catalogue)
    GET    /sessions?project_id=...        List recent sessions for resume picker
    GET    /sessions/{id}                  Read one session
    PATCH  /sessions/{id}                  Update group_by / filters / archive / threshold
    POST   /sessions/{id}/touch            Bump last_active_at (cheap heartbeat)

    GET    /sessions/{id}/groups           Paginated list with summary counters
    GET    /sessions/{id}/group?group_key= Detailed group + matcher candidates
    POST   /sessions/{id}/groups/split     (Phase A.5b stub)
    POST   /sessions/{id}/groups/merge     (Phase A.5b stub)

    POST   /sessions/{id}/match            Run vector / lexical / resources matcher
    POST   /sessions/{id}/confirm          Confirm a candidate as the chosen match
    POST   /sessions/{id}/bulk-confirm     Confirm all suggested above threshold
    POST   /sessions/{id}/apply            Dry-run preview / write to BOQ
    POST   /sessions/{id}/no-match         Mark group TBD / RFQ / custom

    GET    /sessions/{id}/attributes       Drag-source list of group-by chip keys
    GET    /sessions/{id}/categories       IFC class counts (with translated labels)

    GET    /projects/{project_id}/bim-models  BIM model strip for the BIM tabs

    GET    /templates                      Tenant template library
    POST   /templates/lookup               Bulk signature lookup
    DELETE /templates/{id}                 Remove template
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUserId, SessionDep, verify_project_access
from app.modules.match_elements import pipeline, schemas
from app.modules.match_elements.analytics import compute_match_analytics
from app.modules.match_elements.excel_import import parse_boq_xlsx
from app.modules.match_elements.models import MatchPromptTemplate, MatchSession
from app.modules.match_elements.service import get_service

router = APIRouter()


def _u(s: str) -> uuid.UUID:
    return uuid.UUID(s)


async def _assert_session_access(
    db: AsyncSession,
    session_id: uuid.UUID,
    user_id: str,
) -> uuid.UUID:
    """Authorise a request that targets a specific MatchSession.

    Loads the row, raises 404 if missing, and delegates project-level
    ownership to ``verify_project_access`` (which also returns 404 on
    deny so we don't leak existence). Returns the session's project_id
    so callers can avoid a second lookup.
    """
    row = (
        await db.execute(
            select(MatchSession.project_id).where(MatchSession.id == session_id),
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Match session not found")
    project_id = row[0]
    await verify_project_access(project_id, user_id, db)
    return project_id


# ── Sessions ─────────────────────────────────────────────────────────────


@router.post("/sessions", response_model=schemas.SessionRead, status_code=201)
async def create_session(
    spec: schemas.SessionCreate,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.SessionRead:
    await verify_project_access(spec.project_id, current_user_id, session)
    try:
        return await get_service().create_session(
            session, spec, _u(current_user_id),
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.post(
    "/sessions/from-excel",
    response_model=schemas.SessionRead,
    status_code=201,
    summary="Create a BoQ match session by uploading an xlsx file",
)
async def create_session_from_excel(
    session: SessionDep,
    current_user_id: CurrentUserId,
    project_id: uuid.UUID = Form(...),
    file: UploadFile = File(..., description="Bill of Quantities .xlsx file"),
    name: str | None = Form(None),
    # Accepts a CWICR v3 region id ("DE_BERLIN", ...) or a legacy UUID —
    # the service layer routes each kind to its own storage slot. Was
    # ``uuid.UUID | None`` before, which 422'd every wizard submission.
    catalogue_id: str | None = Form(None),
    construction_stage: str | None = Form(None),
) -> schemas.SessionRead:
    """Upload an xlsx BoQ and create a match session in one round-trip.

    Implements MAPPING_PROCESS.md §4.1.5 — the Excel BoQ source. Column
    detection is multi-language (English/German/Russian/Spanish/Chinese
    /Japanese/Korean/Turkish/Polish/etc.); see
    :mod:`match_elements.excel_import` for the full alias table.
    Caller-side parsing is still supported via the regular
    ``POST /sessions`` endpoint with ``boq_rows`` populated — this route
    is the convenience path for end users.
    """
    await verify_project_access(project_id, current_user_id, session)

    filename = (file.filename or "").lower()
    if not filename.endswith(".xlsx"):
        raise HTTPException(
            status_code=400,
            detail=(
                "Only .xlsx files are supported. Save your BoQ as Excel "
                "(not .xls / .csv) and re-upload."
            ),
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        rows = parse_boq_xlsx(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not rows:
        raise HTTPException(
            status_code=400,
            detail=(
                "No valid BoQ rows found. Ensure your spreadsheet has a "
                "header row with at least a 'Description' column and at "
                "least one data row underneath."
            ),
        )

    spec = schemas.SessionCreate(
        project_id=project_id,
        source="boq",
        name=name or (file.filename or "BoQ Import"),
        catalogue_id=catalogue_id,
        construction_stage=construction_stage,  # type: ignore[arg-type]
        boq_rows=rows,
    )

    try:
        return await get_service().create_session(
            session, spec, _u(current_user_id),
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.get("/sessions", response_model=list[schemas.SessionSummary])
async def list_sessions(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
    include_archived: bool = False,
    limit: int = 50,
) -> list[schemas.SessionSummary]:
    await verify_project_access(project_id, current_user_id, session)
    try:
        return await get_service().list_sessions(
            session, project_id,
            include_archived=include_archived,
            limit=limit,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.get("/sessions/{session_id}", response_model=schemas.SessionRead)
async def get_session_endpoint(
    session_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.SessionRead:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().get_session(session, session_id)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.patch("/sessions/{session_id}", response_model=schemas.SessionRead)
async def update_session(
    session_id: uuid.UUID,
    patch: schemas.SessionUpdate,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.SessionRead:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().update_session(session, session_id, patch)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/touch", status_code=204)
async def touch_session(
    session_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> None:
    await _assert_session_access(session, session_id, current_user_id)
    await get_service().touch_session(session, session_id)


@router.get("/sessions/{session_id}/progress")
async def get_match_progress(
    session_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> dict[str, object]:
    """Lightweight progress poll for an in-flight or finished match run.

    Read-only — fetches from the process-local in-memory dict the
    match runner writes to. The wizard's MatchProgressCard polls this
    every ~800ms while the match is running and stops as soon as
    ``status`` flips to ``done`` or ``error``. Always 200 — an idle
    session returns a neutral payload so the FE never has to
    special-case 404 vs "no run yet".
    """
    await _assert_session_access(session, session_id, current_user_id)
    return await get_service().get_progress(session, session_id)


@router.post("/sessions/{session_id}/__debug_set_progress", include_in_schema=False)
async def debug_set_progress(
    session_id: uuid.UUID,
    payload: dict[str, object],
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> dict[str, str]:
    """Test-only hook to pre-seed the in-memory progress dict.

    Used by ``probe-match-progress-stages.mjs`` to capture the
    MatchProgressCard at each of the 5 stages even when the real
    match completes in <2s on the local backend's tiny text fixture.
    Hidden from the OpenAPI schema (``include_in_schema=False``)
    because it's not part of the public contract — the only legit
    caller is the QA probe.

    Safety: the same project-access check the real progress endpoint
    runs gates this one — a stranger can't poison someone else's
    session.
    """
    await _assert_session_access(session, session_id, current_user_id)
    from app.modules.match_elements.service import MatchElementsService  # noqa: PLC0415

    MatchElementsService._write_progress(
        session_id,
        stage=str(payload.get("stage", "init")),
        stage_idx=int(payload.get("stage_idx", 1) or 1),
        groups_done=int(payload.get("groups_done", 0) or 0),
        groups_total=int(payload.get("groups_total", 0) or 0),
        started_at=payload.get("started_at"),  # type: ignore[arg-type]
        status=str(payload.get("status", "running")),
        error=payload.get("error"),  # type: ignore[arg-type]
    )
    return {"ok": "set"}


# ── Groups ───────────────────────────────────────────────────────────────


@router.get(
    "/sessions/{session_id}/groups",
    response_model=schemas.GroupListResponse,
)
async def list_groups(
    session_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
    status: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> schemas.GroupListResponse:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().list_groups(
            session, session_id, status=status, limit=limit, offset=offset,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.get(
    "/sessions/{session_id}/group",
    response_model=schemas.GroupDetail,
)
async def get_group(
    session_id: uuid.UUID,
    group_key: str,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.GroupDetail:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().get_group_detail(
            session, session_id, group_key,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/groups/split",
    response_model=schemas.GroupDetail,
)
async def split_group(
    session_id: uuid.UUID,
    group_key: str,
    spec: schemas.GroupSplitRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.GroupDetail:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().split_group(
            session, session_id, group_key, spec,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/groups/merge",
    response_model=schemas.GroupDetail,
)
async def merge_groups(
    session_id: uuid.UUID,
    group_key: str,
    spec: schemas.GroupMergeRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.GroupDetail:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().merge_groups(
            session, session_id, group_key, spec,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


# ── Attributes / categories ─────────────────────────────────────────────


@router.get(
    "/sessions/{session_id}/attributes",
    response_model=list[schemas.AttributeKey],
)
async def list_attribute_keys(
    session_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> list[schemas.AttributeKey]:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().list_attribute_keys(session, session_id)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.get(
    "/sessions/{session_id}/categories",
    response_model=list[schemas.CategoryCount],
)
async def list_categories(
    session_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> list[schemas.CategoryCount]:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().list_categories(session, session_id)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


# ── BIM models for the BIM tab strip ─────────────────────────────────────


@router.get(
    "/projects/{project_id}/bim-models",
    response_model=list[schemas.BIMModelOption],
)
async def list_project_bim_models(
    project_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> list[schemas.BIMModelOption]:
    """BIM models attached to a project, ready-to-bind to a session.

    Mirrors the ``/api/v1/bim_hub/`` list shape, but returns only the
    fields the match-elements page renders (filename, format, status,
    counts, timestamps). Filters out errored/processing models so the
    user can't bind to a model that has nothing to match against.
    """
    await verify_project_access(project_id, current_user_id, session)
    from app.modules.bim_hub.models import BIMModel

    stmt = (
        select(BIMModel)
        .where(BIMModel.project_id == project_id)
        .order_by(BIMModel.created_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    out: list[schemas.BIMModelOption] = []
    for m in rows:
        out.append(
            schemas.BIMModelOption(
                id=m.id,
                name=m.name,
                model_format=m.model_format,
                element_count=int(m.element_count or 0),
                storey_count=int(m.storey_count or 0),
                status=m.status or "",
                created_at=m.created_at,
            )
        )
    return out


# ── Match / confirm / apply ──────────────────────────────────────────────


@router.post(
    "/sessions/{session_id}/match",
    response_model=list[schemas.GroupSummary],
)
async def run_match(
    session_id: uuid.UUID,
    spec: schemas.RunMatchRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> list[schemas.GroupSummary]:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().run_match(session, session_id, spec)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/confirm", response_model=schemas.GroupDetail,
)
async def confirm_match(
    session_id: uuid.UUID,
    spec: schemas.ConfirmMatchRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.GroupDetail:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().confirm(
            session, session_id, spec, _u(current_user_id),
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/bulk-confirm")
async def bulk_confirm(
    session_id: uuid.UUID,
    spec: schemas.BulkConfirmRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> dict[str, int]:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        n = await get_service().bulk_confirm(
            session, session_id, spec, _u(current_user_id),
        )
        return {"confirmed_count": n}
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/apply", response_model=schemas.ApplyToBoqResponse,
)
async def apply_to_boq(
    session_id: uuid.UUID,
    spec: schemas.ApplyToBoqRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.ApplyToBoqResponse:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().apply_to_boq(
            session, session_id, spec, _u(current_user_id),
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/no-match", response_model=schemas.GroupDetail,
)
async def no_match(
    session_id: uuid.UUID,
    spec: schemas.NoMatchRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.GroupDetail:
    await _assert_session_access(session, session_id, current_user_id)
    try:
        return await get_service().no_match(session, session_id, spec)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


# ── Templates (cross-project library) ────────────────────────────────────


@router.get("/templates", response_model=list[schemas.TemplateRead])
async def list_templates(
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> list[schemas.TemplateRead]:
    try:
        return await get_service().list_templates(session, tenant_id=None)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.post(
    "/templates/lookup", response_model=schemas.TemplateLookupResponse,
)
async def lookup_templates(
    spec: schemas.TemplateLookupRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.TemplateLookupResponse:
    try:
        return await get_service().lookup_templates(
            session, tenant_id=None, signatures=spec.signatures,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(
    template_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> None:
    try:
        await get_service().delete_template(session, template_id)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


# ── Visible pipeline (v3034 — 7-stage match wizard) ──────────────────────


@router.get(
    "/sessions/{session_id}/stages",
    response_model=schemas.StageListResponse,
)
async def list_pipeline_stages(
    session_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.StageListResponse:
    """Return the seven pipeline stages for a session in canonical order.

    Stages that have never run come back with status ``pending`` and
    empty inputs/output so the UI always renders a full timeline. The
    ``explainer`` / ``title`` / ``subtitle`` fields are the source of
    truth for the StageCard copy.
    """
    await _assert_session_access(session, session_id, current_user_id)
    await pipeline.ensure_system_prompts(session)
    stages = await pipeline.list_stages(session, session_id)
    return schemas.StageListResponse(
        session_id=session_id,
        stages=[schemas.StageState(**s) for s in stages],
    )


@router.post(
    "/sessions/{session_id}/stages/{stage_name}/run",
    response_model=schemas.RunStageResponse,
)
async def run_pipeline_stage(
    session_id: uuid.UUID,
    stage_name: str,
    spec: schemas.RunStageRequest,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.RunStageResponse:
    """Execute one stage and persist its state.

    Downstream stages that were ``done`` are marked ``stale`` so the UI
    shows the user which steps need re-running after a tweak. An empty
    body re-runs the stage with whatever knobs are already stored on it.
    """
    await _assert_session_access(session, session_id, current_user_id)
    if stage_name not in pipeline.STAGE_NAMES:
        raise HTTPException(
            status_code=404, detail=f"Unknown stage: {stage_name!r}",
        )
    try:
        result = await pipeline.run_stage(
            session,
            session_id,
            stage_name,
            inputs_override=spec.inputs,
            prompt_template_id=spec.prompt_template_id,
            llm_provider=spec.llm_provider,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return schemas.RunStageResponse(**result)


# ── Prompt templates (user-editable LLM prompts) ─────────────────────────


@router.get(
    "/prompt-templates",
    response_model=list[schemas.PromptTemplateRead],
)
async def list_prompt_templates(
    session: SessionDep,
    current_user_id: CurrentUserId,
    key: str | None = Query(None, max_length=64),
) -> list[schemas.PromptTemplateRead]:
    """List system + own prompt templates, optionally filtered by stage key.

    System prompts (``is_system=True``, ``created_by=NULL``) are visible
    to everyone; user prompts are visible only to their creator. The UI
    groups them under each stage's ``prompt_key``.
    """
    await pipeline.ensure_system_prompts(session)
    try:
        uid = uuid.UUID(current_user_id)
    except (ValueError, TypeError):
        uid = None
    stmt = select(MatchPromptTemplate).where(
        (MatchPromptTemplate.is_system.is_(True))
        | (MatchPromptTemplate.created_by == uid)
    )
    if key:
        stmt = stmt.where(MatchPromptTemplate.key == key)
    stmt = stmt.order_by(
        MatchPromptTemplate.key.asc(),
        MatchPromptTemplate.is_system.desc(),
        MatchPromptTemplate.version.desc(),
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [schemas.PromptTemplateRead.model_validate(r) for r in rows]


@router.get(
    "/prompt-templates/{template_id}",
    response_model=schemas.PromptTemplateRead,
)
async def get_prompt_template(
    template_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.PromptTemplateRead:
    row = await session.get(MatchPromptTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    if not row.is_system:
        try:
            uid = uuid.UUID(current_user_id)
        except (ValueError, TypeError):
            uid = None
        if row.created_by != uid:
            raise HTTPException(
                status_code=404, detail="Prompt template not found",
            )
    return schemas.PromptTemplateRead.model_validate(row)


@router.post(
    "/prompt-templates",
    response_model=schemas.PromptTemplateRead,
    status_code=201,
)
async def create_prompt_template(
    spec: schemas.PromptTemplateCreate,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.PromptTemplateRead:
    """Create a user-owned prompt — typically a fork of a system prompt.

    The ``key`` is validated against the known stage hooks so a typo
    can't orphan a prompt that no stage will ever resolve.
    """
    valid_keys = {
        m["prompt_key"]
        for m in pipeline.STAGE_META.values()
        if m["prompt_key"]
    }
    if spec.key not in valid_keys:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown prompt key {spec.key!r}. "
                f"Valid keys: {sorted(valid_keys)}"
            ),
        )
    try:
        uid: uuid.UUID | None = uuid.UUID(current_user_id)
    except (ValueError, TypeError):
        uid = None
    # Next version for this (key) owned by the user.
    existing = (
        await session.execute(
            select(MatchPromptTemplate.version)
            .where(
                MatchPromptTemplate.key == spec.key,
                MatchPromptTemplate.created_by == uid,
            )
            .order_by(MatchPromptTemplate.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    next_version = (existing or 0) + 1
    row = MatchPromptTemplate(
        key=spec.key,
        name=spec.name,
        description=spec.description,
        system_prompt=spec.system_prompt or "",
        user_template=spec.user_template,
        allowed_providers=spec.allowed_providers,
        version=next_version,
        is_system=False,
        created_by=uid,
        forked_from_id=spec.forked_from_id,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return schemas.PromptTemplateRead.model_validate(row)


@router.patch(
    "/prompt-templates/{template_id}",
    response_model=schemas.PromptTemplateRead,
)
async def update_prompt_template(
    template_id: uuid.UUID,
    patch: schemas.PromptTemplateUpdate,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> schemas.PromptTemplateRead:
    """Edit a user-owned prompt. System prompts are immutable — fork first."""
    row = await session.get(MatchPromptTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    if row.is_system:
        raise HTTPException(
            status_code=403,
            detail="System prompts are read-only — fork it first",
        )
    try:
        uid = uuid.UUID(current_user_id)
    except (ValueError, TypeError):
        uid = None
    if row.created_by != uid:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    data = patch.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(row, field, value)
    row.version = (row.version or 1) + 1
    await session.commit()
    await session.refresh(row)
    return schemas.PromptTemplateRead.model_validate(row)


@router.delete("/prompt-templates/{template_id}", status_code=204)
async def delete_prompt_template(
    template_id: uuid.UUID,
    session: SessionDep,
    current_user_id: CurrentUserId,
) -> None:
    row = await session.get(MatchPromptTemplate, template_id)
    if row is None:
        return
    if row.is_system:
        raise HTTPException(
            status_code=403, detail="System prompts cannot be deleted",
        )
    try:
        uid = uuid.UUID(current_user_id)
    except (ValueError, TypeError):
        uid = None
    if row.created_by != uid:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    await session.delete(row)
    await session.commit()


# ── Analytics (MAPPING_PROCESS.md §10) ───────────────────────────────────


@router.get("/analytics", response_model=schemas.AnalyticsResponse)
async def get_match_analytics(
    session: SessionDep,
    current_user_id: CurrentUserId,
    days: int = Query(7, ge=1, le=90),
    project_id: uuid.UUID | None = Query(None),
    catalog_id: str | None = Query(None, max_length=64),
) -> schemas.AnalyticsResponse:
    """Return aggregate match-quality metrics for the last ``days`` days.

    Pass ``project_id`` to scope to a single project (auth-checked the
    same way as other project routes); omit it for tenant-wide rollup
    (user must still be authenticated). ``catalog_id`` (e.g.
    ``cwicr_DE``) further narrows the window when diagnosing one
    catalogue's recall.

    Always 200 — empty windows return zero-counters with no alerts so
    the dashboard renders cleanly on a fresh deploy.
    """
    if project_id is not None:
        await verify_project_access(project_id, current_user_id, session)
    return await compute_match_analytics(
        session,
        days=days,
        project_id=project_id,
        catalog_id=catalog_id,
    )


# ── Qdrant supervisor (native binary, no Docker) ─────────────────────────


def _qdrant_health_to_dict(health: object) -> dict[str, object]:
    """Render a ``QdrantHealth`` dataclass as a JSON-safe dict.

    Frontend ``QdrantHealthCard`` consumes these fields verbatim; the
    shape is locked to the dataclass in ``qdrant_supervisor.py``.
    """
    return {
        "reachable": getattr(health, "reachable", False),
        "url": getattr(health, "url", None),
        "installed": getattr(health, "installed", False),
        "binary_path": getattr(health, "binary_path", None),
        "storage_dir": getattr(health, "storage_dir", ""),
        "spawn_attempted": getattr(health, "spawn_attempted", False),
        "message": getattr(health, "message", ""),
        "install_hint": getattr(health, "install_hint", ""),
        "download_url": getattr(health, "download_url", None),
    }


@router.get("/qdrant/health")
async def qdrant_health(_current_user_id: CurrentUserId) -> dict[str, object]:
    """Probe Qdrant and (if a local binary exists) auto-spawn it.

    Used by ``QdrantHealthCard`` on /match-elements to detect when the
    vector DB is down and surface a one-click install / refresh flow.
    Authentication is required so anonymous probes can't enumerate
    binary paths on disk.

    When the supervisor flips Qdrant from down→up (because the binary
    was already on disk and just needed to be spawned), we also drop
    the cached ``_qdrant_instance`` in ``app.core.vector`` so the rest
    of the backend's vector code paths (``/costs/vector/v3-status``,
    catalogue install, semantic search) recover without a process
    restart.
    """
    from app.config import get_settings
    from app.core.vector import reset_qdrant_client
    from app.modules.match_elements.qdrant_supervisor import ensure_qdrant_running

    settings = get_settings()
    health = ensure_qdrant_running(settings.qdrant_url, spawn_if_installed=True)
    if getattr(health, "reachable", False) and getattr(health, "spawn_attempted", False):
        # Spawning just succeeded → invalidate any cached "Qdrant not
        # reachable" state elsewhere in the process.
        reset_qdrant_client()
    return _qdrant_health_to_dict(health)


@router.post("/qdrant/install")
async def qdrant_install(_current_user_id: CurrentUserId) -> dict[str, object]:
    """Download the native Qdrant binary from GitHub Releases, then start it.

    Mirrors the converter-install pattern used by /takeoff and /bim:
    one-click, no Docker. The download is signed by Qdrant and stored
    under ``~/.openestimator/qdrant``. After install we re-probe so the
    response reflects the live binding state — front-end can branch on
    ``reachable`` to flip the card immediately.

    After a successful install we also drop the cached vector-client
    so ``/costs/vector/v3-status`` and the catalogue installer stop
    returning ``Qdrant not reachable`` for the rest of the process
    lifetime.
    """
    from app.config import get_settings
    from app.core.vector import reset_qdrant_client
    from app.modules.match_elements.qdrant_supervisor import (
        ensure_qdrant_running,
        install_qdrant_native,
    )

    settings = get_settings()
    try:
        install_qdrant_native(force=False)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    health = ensure_qdrant_running(settings.qdrant_url, spawn_if_installed=True)
    if getattr(health, "reachable", False):
        reset_qdrant_client()
    return _qdrant_health_to_dict(health)

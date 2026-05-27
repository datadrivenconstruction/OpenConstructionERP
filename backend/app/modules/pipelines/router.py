# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Pipeline Builder REST API.

Auto-mounted by the module loader at ``/api/v1/pipelines`` (kebab-case of
the ``pipelines`` directory). The wire contract is PINNED — the frontend
is built against it in parallel; do not deviate.

Endpoints:
    GET    /                       - List pipelines (optional ?project_id=)
    POST   /                       - Create pipeline
    GET    /{id}                   - Get one pipeline
    PUT    /{id}                   - Update pipeline (publish-gated)
    DELETE /{id}                   - Delete pipeline
    POST   /{id}/run               - Enqueue a run (JobRun)
    GET    /{id}/runs/             - List runs for a pipeline
    GET    /runs/{run_id}          - Run detail (+ per-node states)
    GET    /node-types/            - Node Capability Registry catalog
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.core.i18n import get_locale
from app.core.pipeline.executor import GraphValidationError
from app.core.pipeline.registry import list_node_specs
from app.core.validation.messages import translate
from app.dependencies import CurrentUserId, SessionDep, verify_project_access
from app.modules.pipelines.models import Pipeline
from app.modules.pipelines.schemas import (
    NodeTypeOut,
    PipelineCreate,
    PipelineDetail,
    PipelineSummary,
    PipelineUpdate,
    RunAccepted,
    RunDetail,
    RunRequest,
    RunSummary,
)
from app.modules.pipelines.service import PipelineService

router = APIRouter()


def _detail(p: Pipeline) -> PipelineDetail:
    return PipelineDetail(
        id=str(p.id),
        name=p.name,
        description=p.description,
        project_id=str(p.project_id) if p.project_id else None,
        is_published=p.is_published,
        graph=dict(p.graph or {}),
        policy=dict(p.policy or {}),
        version=p.version,
        updated_at=p.updated_at.isoformat() if p.updated_at else None,
    )


async def _load(service: PipelineService, pipeline_id: str, user_id: str) -> Pipeline:
    try:
        pid = uuid.UUID(pipeline_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found") from exc
    pipeline = await service.get_authorized(pid, user_id)
    if pipeline is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found")
    return pipeline


# ── Node type catalog ────────────────────────────────────────────────────
# Declared before /{id} so "node-types" is never captured as a pipeline id.


@router.get("/node-types/", response_model=list[NodeTypeOut])
async def list_node_types(_user: CurrentUserId) -> list[NodeTypeOut]:
    """‌⁠‍Return every registered node type (the palette catalog)."""
    return [NodeTypeOut(**spec.public_dict()) for spec in list_node_specs()]


# ── Run detail (declared before /{id} for the same reason) ───────────────


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: str, session: SessionDep, user_id: CurrentUserId) -> RunDetail:
    """‌⁠‍Return a run with its per-node states."""
    service = PipelineService(session)
    try:
        rid = uuid.UUID(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found") from exc
    run = await service.get_run_authorized(rid, user_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return RunDetail(**await service.run_read_model(run))


# ── Pipeline CRUD ────────────────────────────────────────────────────────


@router.get("/", response_model=list[PipelineSummary])
async def list_pipelines(
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: str | None = Query(default=None),
) -> list[PipelineSummary]:
    """List pipelines, optionally scoped to a project."""
    service = PipelineService(session)
    rows = await service.list(project_id=project_id, user_id=user_id)
    return [
        PipelineSummary(
            id=str(p.id),
            name=p.name,
            description=p.description,
            is_published=p.is_published,
            node_count=len((p.graph or {}).get("nodes") or []),
            updated_at=p.updated_at.isoformat() if p.updated_at else None,
        )
        for p in rows
    ]


@router.post("/", response_model=PipelineDetail, status_code=status.HTTP_201_CREATED)
async def create_pipeline(
    body: PipelineCreate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> PipelineDetail:
    """Create a new (unpublished) pipeline.

    When a ``project_id`` is supplied the caller MUST have access to that
    project — otherwise an authenticated user could bind a pipeline (and
    every future run + node-state output of that pipeline) to a project
    they do not own (cross-tenant write IDOR).
    """
    if body.project_id is not None:
        try:
            pid = uuid.UUID(str(body.project_id))
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=translate("errors.project_not_found", locale=get_locale()),
            ) from exc
        await verify_project_access(pid, user_id, session)
    service = PipelineService(session)
    pipeline = await service.create(
        name=body.name,
        description=body.description,
        project_id=body.project_id,
        graph=body.graph.model_dump(),
        policy=body.policy,
        created_by=user_id,
    )
    return _detail(pipeline)


@router.get("/{pipeline_id}", response_model=PipelineDetail)
async def get_pipeline(pipeline_id: str, session: SessionDep, user_id: CurrentUserId) -> PipelineDetail:
    """Fetch a single pipeline by id."""
    service = PipelineService(session)
    return _detail(await _load(service, pipeline_id, user_id))


@router.put("/{pipeline_id}", response_model=PipelineDetail)
async def update_pipeline(
    pipeline_id: str,
    body: PipelineUpdate,
    session: SessionDep,
    user_id: CurrentUserId,
) -> PipelineDetail:
    """Patch a pipeline. Publishing is gated by the structural rule."""
    service = PipelineService(session)
    pipeline = await _load(service, pipeline_id, user_id)
    try:
        updated = await service.update(
            pipeline,
            name=body.name,
            description=body.description,
            graph=body.graph.model_dump() if body.graph is not None else None,
            policy=body.policy,
            is_published=body.is_published,
        )
    except GraphValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _detail(updated)


@router.delete("/{pipeline_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pipeline(pipeline_id: str, session: SessionDep, user_id: CurrentUserId) -> None:
    """Delete a pipeline (cascades to its runs + node states)."""
    service = PipelineService(session)
    pipeline = await _load(service, pipeline_id, user_id)
    await service.delete(pipeline)


# ── Runs ─────────────────────────────────────────────────────────────────


@router.post("/{pipeline_id}/run", response_model=RunAccepted)
async def run_pipeline(
    pipeline_id: str,
    body: RunRequest,  # noqa: ARG001 — accepted for the pinned contract.
    session: SessionDep,
    user_id: CurrentUserId,
) -> RunAccepted:
    """Validate, snapshot and enqueue a run as a JobRun."""
    service = PipelineService(session)
    pipeline = await _load(service, pipeline_id, user_id)
    try:
        run, job = await service.submit_run(
            pipeline,
            trigger={"type": "manual", "actor_id": user_id},
            actor_id=user_id,
        )
    except GraphValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return RunAccepted(
        run_id=str(run.id),
        job_run_id=str(job.id) if job is not None else None,
        status=job.status if job is not None else "pending",
    )


@router.get("/{pipeline_id}/runs/", response_model=list[RunSummary])
async def list_runs(pipeline_id: str, session: SessionDep, user_id: CurrentUserId) -> list[RunSummary]:
    """List every run of a pipeline, newest first."""
    service = PipelineService(session)
    pipeline = await _load(service, pipeline_id, user_id)
    runs = await service.list_runs(pipeline.id)
    return [RunSummary(**await service.run_summary(r)) for r in runs]

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project agent catalogue API (under ``/api/v1/ai-agents/catalogue``).

* ``GET  /projects/{project_id}``                       - agents, settings, kill switch.
* ``PUT  /projects/{project_id}/agents/{agent}``        - enable / configure (manager).
* ``PUT  /projects/{project_id}/halt``                  - kill switch (manager).
* ``POST /projects/{project_id}/agents/{agent}/run``    - run, returns the draft.
* ``GET  /projects/{project_id}/drafts``                - drafts to review.
* ``POST /projects/{project_id}/drafts/{id}/review``    - accept / reject (editor).
* ``GET  /projects/{project_id}/runs``                  - run history.
* ``GET  /projects/{project_id}/validation``            - ``ai_agent_drafts`` rule results.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.validation.engine import validation_engine
from app.dependencies import CurrentUserPayload, RequirePermission, SessionDep, verify_project_access
from app.modules.ai_agents.catalogue import CATALOGUE, DEFAULT_REVIEW_AFTER_DAYS
from app.modules.ai_agents.catalogue_service import CatalogueError, CatalogueService
from app.modules.ai_agents.validators import AI_AGENT_DRAFTS_RULE_SET

router = APIRouter(prefix="/catalogue", tags=["ai_agents_catalogue"])

_ERROR_STATUS = {
    "unknown_agent": 404,
    "not_found": 404,
    "halted": 423,
    "disabled": 409,
    "already_reviewed": 409,
    "missing_inputs": 422,
    "invalid_decision": 422,
    "invalid_date": 422,
}


class AgentConfigIn(BaseModel):
    """Enable / configure one catalogue agent on a project."""

    enabled: bool | None = None
    config: dict[str, Any] | None = None
    max_tokens_per_run: int | None = Field(default=None, ge=500, le=200_000)


class HaltIn(BaseModel):
    """Project kill switch."""

    halted: bool
    reason: str = Field(default="", max_length=500)


class RunIn(BaseModel):
    """Inputs for one catalogue run."""

    inputs: dict[str, Any] = Field(default_factory=dict)
    use_ai: bool = True


class ReviewIn(BaseModel):
    """A human decision on a draft."""

    decision: Literal["accepted", "rejected"]
    note: str | None = Field(default=None, max_length=4000)
    apply: bool = False
    edits: dict[str, Any] | None = None


class DraftOut(BaseModel):
    """A draft produced by a catalogue agent."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    run_id: uuid.UUID | None
    agent_name: str
    draft_kind: str
    title: str
    payload: dict[str, Any]
    confidence: float
    sources: list[dict[str, Any]]
    status: str
    created_by: uuid.UUID
    reviewed_by: uuid.UUID | None
    reviewed_at: str | None
    review_note: str | None
    applied_record_id: str | None
    created_at: datetime | None = None


class RunOut(BaseModel):
    """One catalogue run (audit row)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_name: str
    status: str
    failure_reason: str | None
    trigger_source: str
    user_id: uuid.UUID
    total_tokens: int
    iterations: int
    final_output: str | None
    started_at: str | None
    finished_at: str | None


class DraftListResponse(BaseModel):
    items: list[DraftOut]
    total: int
    offset: int = 0
    limit: int = 100


class RunListResponse(BaseModel):
    items: list[RunOut]
    total: int
    offset: int = 0
    limit: int = 50


class RunResult(BaseModel):
    """A run and the draft it produced (none when the run failed)."""

    run: RunOut
    draft: DraftOut | None


def _identity(payload: dict) -> tuple[uuid.UUID, str]:
    try:
        return uuid.UUID(str(payload.get("sub"))), str(payload.get("role") or "viewer")
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user") from exc


def _raise(exc: CatalogueError) -> NoReturn:
    raise HTTPException(status_code=_ERROR_STATUS.get(exc.code, 400), detail={"code": exc.code, "detail": str(exc)})


@router.get("/projects/{project_id}", dependencies=[Depends(RequirePermission("ai_agents.read"))])
async def get_catalogue(project_id: uuid.UUID, payload: CurrentUserPayload, session: SessionDep) -> dict[str, Any]:
    """Catalogue agents with this project's settings and the kill switch."""
    user_id, _ = _identity(payload)
    await verify_project_access(project_id, str(user_id), session)
    return await CatalogueService(session).catalogue(project_id)


@router.put(
    "/projects/{project_id}/agents/{agent_name}",
    dependencies=[Depends(RequirePermission("ai_agents.configure"))],
)
async def configure_agent(
    project_id: uuid.UUID,
    agent_name: str,
    body: AgentConfigIn,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> dict[str, Any]:
    """Enable, disable or configure one agent on the project."""
    user_id, _ = _identity(payload)
    await verify_project_access(project_id, str(user_id), session)
    service = CatalogueService(session)
    try:
        await service.configure(
            project_id,
            agent_name,
            user_id=user_id,
            enabled=body.enabled,
            config=body.config,
            max_tokens_per_run=body.max_tokens_per_run,
        )
    except CatalogueError as exc:
        _raise(exc)
    return await service.catalogue(project_id)


@router.put("/projects/{project_id}/halt", dependencies=[Depends(RequirePermission("ai_agents.configure"))])
async def set_halt(
    project_id: uuid.UUID,
    body: HaltIn,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> dict[str, Any]:
    """Stop (or allow again) every catalogue agent on the project."""
    user_id, _ = _identity(payload)
    await verify_project_access(project_id, str(user_id), session)
    service = CatalogueService(session)
    await service.set_halt(project_id, halted=body.halted, reason=body.reason, user_id=user_id)
    return await service.catalogue(project_id)


@router.post(
    "/projects/{project_id}/agents/{agent_name}/run",
    response_model=RunResult,
    dependencies=[Depends(RequirePermission("ai_agents.run"))],
)
async def run_agent(
    project_id: uuid.UUID,
    agent_name: str,
    body: RunIn,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> RunResult:
    """Run one catalogue agent; the result is a draft waiting for review."""
    user_id, role = _identity(payload)
    await verify_project_access(project_id, str(user_id), session)
    try:
        run, draft = await CatalogueService(session).run(
            project_id=project_id,
            agent_name=agent_name,
            inputs=body.inputs,
            user_id=user_id,
            role=role,
            use_ai=body.use_ai,
        )
    except CatalogueError as exc:
        _raise(exc)
    return RunResult(run=RunOut.model_validate(run), draft=DraftOut.model_validate(draft) if draft else None)


@router.get(
    "/projects/{project_id}/drafts",
    response_model=DraftListResponse,
    dependencies=[Depends(RequirePermission("ai_agents.read"))],
)
async def list_drafts(
    project_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    draft_status: str | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> DraftListResponse:
    """Drafts on the project, newest first."""
    user_id, _ = _identity(payload)
    await verify_project_access(project_id, str(user_id), session)
    rows, total = await CatalogueService(session).drafts_page(project_id, draft_status, offset=offset, limit=limit)
    return DraftListResponse(items=[DraftOut.model_validate(d) for d in rows], total=total, offset=offset, limit=limit)


@router.post(
    "/projects/{project_id}/drafts/{draft_id}/review",
    response_model=DraftOut,
    dependencies=[Depends(RequirePermission("ai_agents.review"))],
)
async def review_draft(
    project_id: uuid.UUID,
    draft_id: uuid.UUID,
    body: ReviewIn,
    payload: CurrentUserPayload,
    session: SessionDep,
) -> DraftOut:
    """Accept or reject a draft (accepting an RFI draft can create the RFI)."""
    user_id, _ = _identity(payload)
    await verify_project_access(project_id, str(user_id), session)
    try:
        draft = await CatalogueService(session).review(
            draft_id,
            project_id=project_id,
            decision=body.decision,
            user_id=user_id,
            note=body.note,
            apply=body.apply,
            edits=body.edits,
        )
    except CatalogueError as exc:
        _raise(exc)
    return DraftOut.model_validate(draft)


@router.get(
    "/projects/{project_id}/runs",
    response_model=RunListResponse,
    dependencies=[Depends(RequirePermission("ai_agents.read"))],
)
async def run_history(
    project_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
) -> RunListResponse:
    """Catalogue runs on the project, newest first."""
    user_id, _ = _identity(payload)
    await verify_project_access(project_id, str(user_id), session)
    rows, total = await CatalogueService(session).history_page(project_id, offset=offset, limit=limit)
    return RunListResponse(items=[RunOut.model_validate(r) for r in rows], total=total, offset=offset, limit=limit)


@router.get("/projects/{project_id}/validation", dependencies=[Depends(RequirePermission("ai_agents.read"))])
async def validate_drafts(
    project_id: uuid.UUID,
    payload: CurrentUserPayload,
    session: SessionDep,
    locale: str = Query(default="en", max_length=12),
) -> dict[str, Any]:
    """Run the ``ai_agent_drafts`` rule set over this project's pending drafts."""
    user_id, _ = _identity(payload)
    await verify_project_access(project_id, str(user_id), session)
    service = CatalogueService(session)
    configs = {a["name"]: a["config"] for a in (await service.catalogue(project_id))["agents"]}
    drafts = [
        {
            "id": str(d.id),
            "title": d.title,
            "status": d.status,
            "agent_name": d.agent_name,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "review_after_days": (configs.get(d.agent_name) or {}).get("review_after_days", DEFAULT_REVIEW_AFTER_DAYS),
        }
        for d in await service.drafts(project_id, "pending")
        if d.agent_name in CATALOGUE
    ]
    report = await validation_engine.validate(
        data={"drafts": drafts},
        rule_sets=[AI_AGENT_DRAFTS_RULE_SET],
        target_type="ai_agent_drafts",
        target_id=str(project_id),
        project_id=str(project_id),
        metadata={"locale": locale},
    )
    return {
        "checked": len(drafts),
        "findings": [
            {"rule_id": r.rule_id, "severity": str(r.severity), "message": r.message, "draft_id": r.element_ref}
            for r in report.results
            if not r.passed and not r.is_engine_error
        ],
    }

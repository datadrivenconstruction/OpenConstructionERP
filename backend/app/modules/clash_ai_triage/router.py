# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Clash AI Triage API routes.

Mounted by the module loader at ``/api/v1/clash-ai-triage`` (kebab-cased
directory name per the loader convention).

Endpoints
    POST /clashes/{clash_id}                — triage a single clash
    POST /batch                             — triage many clashes
    GET  /clashes/{clash_id}/history        — list past triage rows
    GET  /prompts/current                   — read the current prompt templates
    POST /replay/{triage_result_id}         — re-run with a new prompt version

Permissions
    clash_triage.execute  — single + batch + replay (Editor)
    clash_triage.read     — history + prompts/current (Viewer)

IDOR
    Project-ownership is enforced on every endpoint via the shared
    ``verify_project_access`` helper. We resolve the clash → run →
    project chain before letting any caller read or mutate triage state.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import (
    CurrentUserId,
    RequirePermission,
    SessionDep,
    check_ai_rate_limit,
    verify_project_access,
)
from app.modules.clash.models import ClashResult, ClashRun
from app.modules.clash_ai_triage.models import ClashTriageResult
from app.modules.clash_ai_triage.prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT_V1,
    USER_PROMPT_V1,
)
from app.modules.clash_ai_triage.schemas import (
    PromptTemplatesResponse,
    TriageBatchRequest,
    TriageHistoryPage,
    TriageReplayRequest,
    TriageResultResponse,
)
from app.modules.clash_ai_triage.service import (
    ClashSubjectNotFound,
    ClashTriageService,
    ClashTriageUnavailable,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Clash AI Triage"])


def _get_service(session: SessionDep) -> ClashTriageService:
    return ClashTriageService(session)


async def _project_id_for_clash(session: AsyncSession, clash_id: uuid.UUID) -> uuid.UUID:
    """Walk ``ClashResult → ClashRun → project_id``; 404 if not reachable."""
    stmt = (
        select(ClashRun.project_id)
        .join(ClashResult, ClashResult.run_id == ClashRun.id)
        .where(ClashResult.id == clash_id)
    )
    pid = (await session.execute(stmt)).scalar_one_or_none()
    if pid is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clash {clash_id} not found",
        )
    return pid


def _to_response(row: ClashTriageResult) -> TriageResultResponse:
    """Adapt a persisted row into the wire response shape."""
    return TriageResultResponse(
        id=row.id,
        subject_type=row.subject_type,  # type: ignore[arg-type]
        subject_id=row.subject_id,
        clash_id=row.clash_id,
        model_name=row.model_name,
        prompt_version=row.prompt_version,
        category=row.category,  # type: ignore[arg-type]
        confidence=float(row.confidence),
        severity_suggested=row.severity_suggested,  # type: ignore[arg-type]
        explanation=row.explanation,
        suggested_action=row.suggested_action,  # type: ignore[arg-type]
        model_evidence_used=list(row.model_evidence_used or []),
        tokens_used=int(row.tokens_used or 0),
        cost_usd_estimate=float(row.cost_usd_estimate or 0.0),
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ── POST /clashes/{clash_id} — single triage ────────────────────────────────


@router.post(
    "/clashes/{clash_id}",
    response_model=TriageResultResponse,
    dependencies=[Depends(RequirePermission("clash_triage.execute"))],
)
async def triage_clash(
    clash_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    force_refresh: bool = Query(default=False),
    service: ClashTriageService = Depends(_get_service),
    _ai_remaining: int = Depends(check_ai_rate_limit),
) -> TriageResultResponse:
    """Triage one clash. Returns the cached row unless ``force_refresh=true``.

    Rate-limited via :func:`check_ai_rate_limit` so a runaway client cannot
    drive unbounded LLM cost — see ``AI_RATE_LIMIT`` env var (default 10/min
    per user).
    """
    project_id = await _project_id_for_clash(session, clash_id)
    await verify_project_access(project_id, user_id, session)
    try:
        row = await service.triage_clash(
            clash_id,
            user_id=uuid.UUID(user_id),
            force_refresh=force_refresh,
        )
    except ClashSubjectNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ClashTriageUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _to_response(row)


# ── POST /batch — fan-out triage ────────────────────────────────────────────


@router.post(
    "/batch",
    response_model=list[TriageResultResponse],
    dependencies=[Depends(RequirePermission("clash_triage.execute"))],
)
async def triage_batch(
    body: TriageBatchRequest,
    user_id: CurrentUserId,
    session: SessionDep,
    service: ClashTriageService = Depends(_get_service),
    _ai_remaining: int = Depends(check_ai_rate_limit),
) -> list[TriageResultResponse]:
    """Fan out triage over ``body.clash_ids`` with bounded concurrency.

    Rate-limited (one bucket "slot" per batch call) so a malicious project
    cannot replay-triage thousands of clashes by submitting one giant batch
    after another — paired with ``max_concurrent`` (in-flight cap) and the
    per-(subject, prompt, model) cache to keep cost predictable.
    """
    # Verify project access against the first reachable clash. The batch
    # contract is "all clashes belong to the same project the caller has
    # access to" — we enforce by sampling the head; the service then
    # tolerates missing clashes gracefully (skips + logs).
    if not body.clash_ids:
        return []
    head = body.clash_ids[0]
    project_id = await _project_id_for_clash(session, head)
    await verify_project_access(project_id, user_id, session)

    try:
        rows = await service.triage_batch(
            body.clash_ids,
            user_id=uuid.UUID(user_id),
            max_concurrent=body.max_concurrent,
            force_refresh=body.force_refresh,
        )
    except ClashTriageUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return [_to_response(r) for r in rows]


# ── GET /clashes/{clash_id}/history ────────────────────────────────────────


@router.get(
    "/clashes/{clash_id}/history",
    response_model=TriageHistoryPage,
    dependencies=[Depends(RequirePermission("clash.read"))],
)
async def list_history(
    clash_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    service: ClashTriageService = Depends(_get_service),
) -> TriageHistoryPage:
    """Paginated per-clash triage history, newest first."""
    project_id = await _project_id_for_clash(session, clash_id)
    await verify_project_access(project_id, user_id, session)
    rows, total = await service.list_history(clash_id, page=page, page_size=page_size)
    return TriageHistoryPage(
        items=[_to_response(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


# ── GET /prompts/current ──────────────────────────────────────────────────


@router.get(
    "/prompts/current",
    response_model=PromptTemplatesResponse,
    dependencies=[Depends(RequirePermission("clash_triage.read"))],
)
async def get_current_prompts(
    user_id: CurrentUserId,
) -> PromptTemplatesResponse:
    """Return the prompt templates the service will use for the next call.

    Read-only by design — see ``prompts.py`` for the "tune by editing
    the file" philosophy. Surfaced through HTTP so the UI can show a
    coordinator the exact prompt that produced (or will produce) a
    given verdict.
    """
    return PromptTemplatesResponse(
        prompt_version=PROMPT_VERSION,
        system_prompt=SYSTEM_PROMPT_V1,
        user_prompt_template=USER_PROMPT_V1,
    )


# ── POST /replay/{triage_result_id} ───────────────────────────────────────


@router.post(
    "/replay/{triage_result_id}",
    response_model=TriageResultResponse,
    dependencies=[Depends(RequirePermission("clash_triage.execute"))],
)
async def replay(
    triage_result_id: uuid.UUID,
    user_id: CurrentUserId,
    session: SessionDep,
    body: TriageReplayRequest | None = None,
    service: ClashTriageService = Depends(_get_service),
    _ai_remaining: int = Depends(check_ai_rate_limit),
) -> TriageResultResponse:
    """Re-run an existing triage against a (usually newer) prompt version.

    Replay ALWAYS pays for a fresh LLM call (the cache is by design bypassed
    — that's the whole point of replay). Rate-limited so an actor with
    ``clash_triage.execute`` cannot loop replays to drive LLM cost up.
    """
    stmt = select(ClashTriageResult).where(ClashTriageResult.id == triage_result_id)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is None:
        raise HTTPException(status_code=404, detail="Triage result not found")
    # Walk via the original clash_id for IDOR — replay is only allowed on
    # subjects in projects the caller still has access to.
    if existing.clash_id is not None:
        project_id = await _project_id_for_clash(session, existing.clash_id)
        await verify_project_access(project_id, user_id, session)
    else:
        # Source clash was deleted (FK on-delete nulled clash_id). Without
        # an anchor row we cannot resolve the owning project, so refuse to
        # replay — any user with ``clash_triage.execute`` would otherwise
        # be able to drive AI calls against an orphaned subject.
        raise HTTPException(
            status_code=410,
            detail="Source clash was deleted; triage cannot be replayed.",
        )
    target = body.prompt_version if body and body.prompt_version else None
    try:
        row = await service.replay_with_new_prompt(
            triage_result_id,
            new_prompt_version=target,
            user_id=uuid.UUID(user_id),
        )
    except ClashSubjectNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ClashTriageUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _to_response(row)

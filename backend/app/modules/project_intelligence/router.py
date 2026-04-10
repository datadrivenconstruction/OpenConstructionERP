"""Project Intelligence API routes.

Endpoints:
    GET  /score/?project_id=X          — Project score with gaps and achievements
    GET  /state/?project_id=X          — Full project state snapshot
    GET  /summary/?project_id=X        — Combined state + score
    POST /recommendations/             — AI recommendations (or rule-based fallback)
    POST /chat/                        — Ask a question about the project
    POST /explain-gap/                 — Explain a specific gap
    POST /actions/{action_id}/         — Execute an action
    GET  /actions/?project_id=X        — List available actions
"""

import logging
import time
import uuid
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.project_intelligence.actions import (
    execute_action,
    get_available_actions,
)
from app.modules.project_intelligence.advisor import (
    answer_question as ai_answer_question,
    explain_gap as ai_explain_gap,
    generate_recommendations,
)
from app.modules.project_intelligence.collector import collect_project_state
from app.modules.project_intelligence.schemas import (
    ActionDefinitionResponse,
    ActionResponse,
    AchievementResponse,
    ChatRequest,
    CriticalGapResponse,
    ExplainGapRequest,
    ProjectScoreResponse,
    ProjectStateResponse,
    ProjectSummaryResponse,
    RecommendationRequest,
)
from app.modules.project_intelligence.scorer import compute_score

router = APIRouter(tags=["Project Intelligence"])
logger = logging.getLogger(__name__)


# ── IDOR protection ───────────────────────────────────────────────────────


async def _verify_project_access(
    session: AsyncSession,
    project_id: uuid.UUID | str,
    user_id: str | None,
) -> None:
    """Verify the current user owns (or is admin on) the referenced project.

    Every project_intelligence endpoint must call this before touching
    collector / scorer / advisor — those helpers trust the project_id
    and will happily return cross-tenant data otherwise.
    Mirrors ``erp_chat.tools._require_project_access``.
    """
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    try:
        pid = project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(str(project_id))
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid project_id",
        )

    try:
        from app.modules.projects.repository import ProjectRepository
        from app.modules.users.repository import UserRepository

        proj_repo = ProjectRepository(session)
        project = await proj_repo.get_by_id(pid)
        if project is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {pid} not found",
            )

        # Admin bypass
        try:
            user_repo = UserRepository(session)
            user = await user_repo.get_by_id(user_id)
            if user is not None and getattr(user, "role", "") == "admin":
                return
        except Exception:  # noqa: BLE001 — best-effort admin check
            pass

        if str(getattr(project, "owner_id", "")) != str(user_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: you do not own this project",
            )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Project Intelligence access check failed for %s: %s", project_id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authorization check failed",
        )


# ── Simple in-memory cache (keyed by user + project to avoid leakage) ─────

_state_cache: dict[tuple[str, str], tuple[float, Any]] = {}
CACHE_TTL_SECONDS = 300  # 5 minutes


def _cache_key(user_id: str | None, project_id: str) -> tuple[str, str]:
    """Per-user cache key — prevents cross-user state leaks."""
    return (str(user_id or "anon"), project_id)


def _get_cached_state(user_id: str | None, project_id: str) -> Any | None:
    """Return cached state if still valid."""
    entry = _state_cache.get(_cache_key(user_id, project_id))
    if entry and (time.time() - entry[0]) < CACHE_TTL_SECONDS:
        return entry[1]
    return None


def _set_cached_state(user_id: str | None, project_id: str, state: Any) -> None:
    """Cache a project state for the given user."""
    _state_cache[_cache_key(user_id, project_id)] = (time.time(), state)


def _invalidate_cache(user_id: str | None, project_id: str) -> None:
    """Remove a project from cache for the given user."""
    _state_cache.pop(_cache_key(user_id, project_id), None)


# ── Helper to collect + optionally cache ──────────────────────────────────


async def _get_state(
    session: SessionDep,
    user_id: str | None,
    project_id: str,
    refresh: bool = False,
) -> Any:
    """Get project state, using cache unless refresh is requested."""
    if not refresh:
        cached = _get_cached_state(user_id, project_id)
        if cached is not None:
            return cached

    state = await collect_project_state(session, project_id)
    _set_cached_state(user_id, project_id, state)
    return state


# ── GET /score/ ───────────────────────────────────────────────────────────


@router.get(
    "/score/",
    response_model=ProjectScoreResponse,
    dependencies=[Depends(RequirePermission("project_intelligence.read"))],
)
async def get_score(
    project_id: uuid.UUID = Query(...),
    refresh: bool = Query(False),
    session: SessionDep = None,  # type: ignore[assignment]
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> ProjectScoreResponse:
    """Compute and return the project intelligence score."""
    await _verify_project_access(session, project_id, user_id)
    state = await _get_state(session, user_id, str(project_id), refresh=refresh)
    score = compute_score(state)

    return ProjectScoreResponse(
        overall=score.overall,
        overall_grade=score.overall_grade,
        domain_scores=score.domain_scores,
        critical_gaps=[
            CriticalGapResponse(**asdict(g)) for g in score.critical_gaps
        ],
        achievements=[
            AchievementResponse(**asdict(a)) for a in score.achievements
        ],
    )


# ── GET /state/ ───────────────────────────────────────────────────────────


@router.get(
    "/state/",
    response_model=ProjectStateResponse,
    dependencies=[Depends(RequirePermission("project_intelligence.read"))],
)
async def get_state(
    project_id: uuid.UUID = Query(...),
    refresh: bool = Query(False),
    session: SessionDep = None,  # type: ignore[assignment]
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> ProjectStateResponse:
    """Return full project state snapshot."""
    await _verify_project_access(session, project_id, user_id)
    state = await _get_state(session, user_id, str(project_id), refresh=refresh)
    return ProjectStateResponse(**asdict(state))


# ── GET /summary/ ─────────────────────────────────────────────────────────


@router.get(
    "/summary/",
    response_model=ProjectSummaryResponse,
    dependencies=[Depends(RequirePermission("project_intelligence.read"))],
)
async def get_summary(
    project_id: uuid.UUID = Query(...),
    refresh: bool = Query(False),
    session: SessionDep = None,  # type: ignore[assignment]
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> ProjectSummaryResponse:
    """Return combined state + score for the project."""
    await _verify_project_access(session, project_id, user_id)
    state = await _get_state(session, user_id, str(project_id), refresh=refresh)
    score = compute_score(state)

    return ProjectSummaryResponse(
        state=ProjectStateResponse(**asdict(state)),
        score=ProjectScoreResponse(
            overall=score.overall,
            overall_grade=score.overall_grade,
            domain_scores=score.domain_scores,
            critical_gaps=[
                CriticalGapResponse(**asdict(g)) for g in score.critical_gaps
            ],
            achievements=[
                AchievementResponse(**asdict(a)) for a in score.achievements
            ],
        ),
    )


# ── POST /recommendations/ ───────────────────────────────────────────────


@router.post(
    "/recommendations/",
    dependencies=[Depends(RequirePermission("project_intelligence.read"))],
)
async def get_recommendations(
    body: RecommendationRequest,
    project_id: uuid.UUID = Query(...),
    session: SessionDep = None,  # type: ignore[assignment]
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Generate AI recommendations for the project."""
    await _verify_project_access(session, project_id, user_id)
    state = await _get_state(session, user_id, str(project_id))
    score = compute_score(state)

    text = await generate_recommendations(
        session=session,
        state=state,
        score=score,
        role=body.role,
        language=body.language,
    )

    return {"text": text, "role": body.role, "language": body.language}


# ── POST /chat/ ───────────────────────────────────────────────────────────


@router.post(
    "/chat/",
    dependencies=[Depends(RequirePermission("project_intelligence.read"))],
)
async def chat(
    body: ChatRequest,
    project_id: uuid.UUID = Query(...),
    session: SessionDep = None,  # type: ignore[assignment]
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Answer a question about the project."""
    await _verify_project_access(session, project_id, user_id)
    state = await _get_state(session, user_id, str(project_id))
    score = compute_score(state)

    text = await ai_answer_question(
        session=session,
        state=state,
        score=score,
        question=body.question,
        role=body.role,
        language=body.language,
    )

    return {"text": text, "question": body.question}


# ── POST /explain-gap/ ───────────────────────────────────────────────────


@router.post(
    "/explain-gap/",
    dependencies=[Depends(RequirePermission("project_intelligence.read"))],
)
async def explain_gap(
    body: ExplainGapRequest,
    project_id: uuid.UUID = Query(...),
    session: SessionDep = None,  # type: ignore[assignment]
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Explain a specific gap in detail."""
    await _verify_project_access(session, project_id, user_id)
    state = await _get_state(session, user_id, str(project_id))
    score = compute_score(state)

    # Find the gap by ID
    target_gap = None
    for gap in score.critical_gaps:
        if gap.id == body.gap_id:
            target_gap = gap
            break

    if not target_gap:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Gap '{body.gap_id}' not found for this project",
        )

    text = await ai_explain_gap(
        session=session,
        gap=target_gap,
        state=state,
        language=body.language,
    )

    return {"text": text, "gap_id": body.gap_id}


# ── POST /actions/{action_id}/ ───────────────────────────────────────────


@router.post(
    "/actions/{action_id}/",
    response_model=ActionResponse,
    dependencies=[Depends(RequirePermission("project_intelligence.create"))],
)
async def run_action(
    action_id: str,
    project_id: uuid.UUID = Query(...),
    session: SessionDep = None,  # type: ignore[assignment]
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> ActionResponse:
    """Execute a project intelligence action."""
    await _verify_project_access(session, project_id, user_id)
    result = await execute_action(session, action_id, str(project_id))

    # Invalidate cache after action
    _invalidate_cache(user_id, str(project_id))

    return ActionResponse(
        success=result.success,
        message=result.message,
        redirect_url=result.redirect_url,
        data=result.data,
    )


# ── GET /actions/ ─────────────────────────────────────────────────────────


@router.get(
    "/actions/",
    response_model=list[ActionDefinitionResponse],
    dependencies=[Depends(RequirePermission("project_intelligence.read"))],
)
async def list_actions(
    project_id: uuid.UUID = Query(...),
    session: SessionDep = None,  # type: ignore[assignment]
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> list[ActionDefinitionResponse]:
    """List available actions for this project's current gaps."""
    await _verify_project_access(session, project_id, user_id)
    state = await _get_state(session, user_id, str(project_id))
    score = compute_score(state)

    action_ids = [g.action_id for g in score.critical_gaps if g.action_id]
    actions_data = get_available_actions(action_ids)

    return [ActionDefinitionResponse(**a) for a in actions_data]

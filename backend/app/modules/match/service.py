# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""HTTP-facing service layer — keeps the router thin.

Loads the acting user's AISettings (so the translation cascade and
rerank tier can use their key) and verifies project ownership before
delegating to :mod:`app.core.match_service`.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.match_service import (
    ElementEnvelope,
    MatchCandidate,
    MatchResponse,
    build_envelope,
    match_envelope,
    record_feedback,
)

logger = logging.getLogger(__name__)


async def _load_ai_settings(db: AsyncSession, user_id: str | None) -> Any:
    """Fetch the user's AISettings row, or ``None`` when unavailable.

    AISettings powers the translation LLM and the rerank LLM. If the
    user has no row, both tiers degrade gracefully (translation falls
    through to fallback, rerank skips).
    """
    if not user_id:
        return None
    try:
        from sqlalchemy import select

        from app.modules.ai.models import AISettings

        stmt = select(AISettings).where(AISettings.user_id == uuid.UUID(user_id))
        return (await db.execute(stmt)).scalar_one_or_none()
    except Exception as exc:  # pragma: no cover — AI module optional
        logger.debug("ai_settings load skipped: %s", exc)
        return None


async def _verify_project_access(
    db: AsyncSession,
    project_id: uuid.UUID,
    user_id: str,
    role: str = "",
) -> None:
    """Raise 403/404 if the acting user can't see this project."""
    from app.modules.projects.repository import ProjectRepository

    repo = ProjectRepository(db)
    project = await repo.get_by_id(project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    if role == "admin":
        return
    if str(project.owner_id) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this project",
        )


async def run_match_for_element(
    *,
    db: AsyncSession,
    project_id: uuid.UUID,
    user_id: str,
    user_role: str,
    source: str,
    raw_element_data: dict[str, Any],
    top_k: int = 10,
    use_reranker: bool = False,
) -> MatchResponse:
    """Build envelope, verify access, run the matcher."""
    await _verify_project_access(db, project_id, user_id, user_role)
    envelope = build_envelope(source, raw_element_data)
    ai_settings = await _load_ai_settings(db, user_id)
    return await match_envelope(
        envelope,
        project_id=project_id,
        top_k=top_k,
        use_reranker=use_reranker,
        db=db,
        ai_settings=ai_settings,
    )


async def submit_feedback(
    *,
    db: AsyncSession,
    project_id: uuid.UUID,
    user_id: str,
    user_role: str,
    element_envelope: ElementEnvelope,
    accepted_candidate: MatchCandidate | None,
    rejected_candidates: list[MatchCandidate],
    user_chose_code: str | None,
) -> None:
    """Authorize and persist a feedback event."""
    await _verify_project_access(db, project_id, user_id, user_role)
    await record_feedback(
        db=db,
        project_id=project_id,
        element_envelope=element_envelope,
        accepted_candidate=accepted_candidate,
        rejected_candidates=rejected_candidates,
        user_chose_code=user_chose_code,
        user_id=user_id,
    )

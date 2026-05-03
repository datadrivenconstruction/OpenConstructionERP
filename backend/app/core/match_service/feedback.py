# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Match feedback loop — captures user confirmations for offline tuning.

Every time the user accepts, rejects, or hand-overrides a match
suggestion the router calls :func:`record_feedback`. The captured
``AuditEntry`` carries the full envelope, the top candidates we
showed, and what the user actually picked — enough signal to retrain
boost weights and augment the golden set.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_log
from app.core.match_service.envelope import ElementEnvelope, MatchCandidate

logger = logging.getLogger(__name__)


def _candidate_payload(candidate: MatchCandidate) -> dict[str, Any]:
    """Compact dict for audit storage — drops fields a downstream
    re-ranker can recompute from ``code`` (description, currency, etc.)
    while keeping the score / boost trail."""
    return {
        "code": candidate.code,
        "score": round(float(candidate.score), 4),
        "vector_score": round(float(candidate.vector_score), 4),
        "boosts_applied": dict(candidate.boosts_applied or {}),
        "confidence_band": candidate.confidence_band,
    }


async def record_feedback(
    *,
    db: AsyncSession,
    project_id: uuid.UUID | str,
    element_envelope: ElementEnvelope,
    accepted_candidate: MatchCandidate | None,
    rejected_candidates: list[MatchCandidate] | None = None,
    user_chose_code: str | None = None,
    user_id: str | None = None,
) -> None:
    """Persist one feedback event for the matcher's training corpus.

    Args:
        db: Async session.
        project_id: Project the match was scoped to.
        element_envelope: The envelope the matcher saw.
        accepted_candidate: The candidate the user accepted (if any).
        rejected_candidates: Candidates the user explicitly rejected.
        user_chose_code: Free-form code the user typed in instead — set
            when the user disagreed with every suggestion and went
            manual.
        user_id: Acting user UUID for audit attribution.

    Returns:
        ``None`` — failures are logged at debug level and swallowed so
        feedback collection never blocks the user-facing flow.
    """
    project_str = str(project_id)
    rejected = rejected_candidates or []

    payload: dict[str, Any] = {
        "envelope": element_envelope.model_dump(mode="json"),
        "accepted": _candidate_payload(accepted_candidate) if accepted_candidate else None,
        "rejected": [_candidate_payload(c) for c in rejected],
        "user_chose_code": user_chose_code,
    }

    try:
        await audit_log(
            db,
            action="match_feedback",
            entity_type="match_feedback",
            entity_id=project_str,
            user_id=user_id,
            details=payload,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("match feedback audit_log skipped: %s", exc)

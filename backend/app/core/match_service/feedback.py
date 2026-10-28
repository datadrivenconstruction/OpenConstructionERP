# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Match feedback loop - captures user confirmations for offline tuning.

Every time the user accepts, rejects, or hand-overrides a match
suggestion the router calls :func:`record_feedback`. The captured
``AuditEntry`` carries the full envelope, the top candidates we
showed, and what the user actually picked - enough signal to retrain
boost weights and augment the golden set.

Capture is not the whole story: an acceptance is also the signal the
matcher's prior-pick logic learns from. So alongside the audit row we
best-effort stamp the accepted code onto the matching search-log row
(``MatchSearchLog.picked_rate_code`` / ``picked_rank``), which is the
read model the ranker's prior-pick boost and the exact-repeat
short-circuit consult next time the same line comes round.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_log
from app.core.match_service.envelope import ElementEnvelope, MatchCandidate

logger = logging.getLogger(__name__)

# How many recent unpicked search-log rows to scan when attributing a
# confirmation back to the search that produced it. A confirmation almost
# always follows its search immediately, so the newest matching row is the
# right one; the cap keeps the scan bounded on a busy project.
_FEEDBACK_SCAN_LIMIT: int = 25


def _candidate_payload(candidate: MatchCandidate) -> dict[str, Any]:
    """Compact dict for audit storage - drops fields a downstream
    re-ranker can recompute from ``code`` (description, currency, etc.)
    while keeping the score / boost trail."""
    return {
        "code": candidate.code,
        "score": round(float(candidate.score), 4),
        "vector_score": round(float(candidate.vector_score), 4),
        "boosts_applied": dict(candidate.boosts_applied or {}),
        "confidence_band": candidate.confidence_band,
    }


def _picked_rank_for_code(candidate_codes: list[Any] | None, code: str) -> int | None:
    """1-based rank of ``code`` within a search-log row's shown codes.

    Returns ``None`` when the code isn't in the list (the accepted rate
    wasn't one of the suggestions for that row, so it isn't the row this
    confirmation belongs to). Pure and DB-free so the attribution logic is
    unit-testable without a database.
    """
    if not code or not candidate_codes:
        return None
    target = str(code).strip()
    if not target:
        return None
    for idx, raw in enumerate(candidate_codes, start=1):
        if str(raw).strip() == target:
            return idx
    return None


async def _feed_pick_to_search_log(
    db: AsyncSession,
    *,
    project_id: uuid.UUID | str,
    picked_code: str,
) -> None:
    """Stamp an acceptance onto the search-log row that suggested it.

    Backfills ``picked_rate_code`` / ``picked_rank`` / ``picked_at`` on the
    most recent not-yet-picked ``MatchSearchLog`` row for this project
    whose recorded candidate list contained ``picked_code``. That row's
    ``candidate_codes`` are written by the ranker at search time, so a
    match found there is a reliable attribution. This is the capture ->
    read-model bridge for the learning loop; it is idempotent (skips rows
    already stamped) and best-effort (the caller swallows failures so
    feedback never blocks the user flow).
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.modules.match_elements.models import MatchSearchLog  # noqa: PLC0415

    try:
        pid = project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(str(project_id))
    except (TypeError, ValueError):
        return

    stmt = (
        select(MatchSearchLog)
        .where(
            MatchSearchLog.project_id == pid,
            MatchSearchLog.picked_rate_code.is_(None),
        )
        .order_by(MatchSearchLog.created_at.desc())
        .limit(_FEEDBACK_SCAN_LIMIT)
    )
    rows = (await db.execute(stmt)).scalars().all()
    for row in rows:
        codes = (row.metadata_ or {}).get("candidate_codes")
        if not isinstance(codes, list):
            continue
        rank = _picked_rank_for_code(codes, picked_code)
        if rank is not None:
            row.picked_rate_code = picked_code
            row.picked_rank = rank
            row.picked_at = datetime.now(UTC)
            return


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
        user_chose_code: Free-form code the user typed in instead - set
            when the user disagreed with every suggestion and went
            manual.
        user_id: Acting user UUID for audit attribution.

    Returns:
        ``None`` - failures are logged at debug level and swallowed so
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
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("match feedback audit_log skipped: %s", exc)

    # Feed the read model the matcher learns from: an accepted code (or a
    # hand-typed override) becomes the pick on the search-log row that
    # suggested it, so the next match for the same line can surface it.
    # Capture-only side effect - never let it break the user flow.
    picked_code = (accepted_candidate.code if accepted_candidate else None) or user_chose_code
    if picked_code:
        try:
            await _feed_pick_to_search_log(db, project_id=project_id, picked_code=str(picked_code))
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("match feedback read-model feed skipped: %s", exc)

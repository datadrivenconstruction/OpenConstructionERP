# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Match service — element-to-CWICR vector matcher.

Public API:

    * :func:`match_element` — eval-harness entrypoint:
        ``async (element_info: dict, top_k: int) -> list[dict]``.
        Wraps ``build_envelope`` + ``rank``. Each returned dict
        carries at minimum ``code`` and ``unit_rate`` (the eval
        contract).
    * :func:`match_envelope` — when the caller already built an
        :class:`ElementEnvelope` (typically the router).
    * :func:`record_feedback` — persist user confirmation/rejection
        for offline boost-weight tuning.

Source extractors live under ``extractors/`` and self-register via
:data:`extractors.EXTRACTORS`.

Boost rules live under ``boosts/`` and self-register via
:data:`boosts.BOOSTS`.

Configuration knobs live in :mod:`config`.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.match_service.determinism import (
    enter_deterministic_mode,
    stabilize_response,
)
from app.core.match_service.envelope import (
    ElementEnvelope,
    MatchCandidate,
    MatchRequest,
    MatchResponse,
    SourceType,
)
from app.core.match_service.extractors import EXTRACTORS, build_envelope
from app.core.match_service.feedback import record_feedback
from app.core.match_service.ranker_qdrant import rank as _rank_qdrant
from app.database import async_session_factory

logger = logging.getLogger(__name__)


def _select_ranker():
    """Return the ranker callable.

    Historically toggled between LanceDB and Qdrant via
    ``settings.match_backend``; the LanceDB path was removed in v3 so
    this now always returns the Qdrant ranker. Kept as a function (not
    inlined) so test code that monkeypatched the selector still works.
    """
    return _rank_qdrant


# Backwards-compat: the legacy public name ``rank`` still resolves to
# the active (Qdrant) ranker so importers outside the package keep
# working without a code change.
rank = _rank_qdrant


async def match_envelope(
    envelope: ElementEnvelope,
    *,
    project_id: uuid.UUID | str,
    top_k: int = 10,
    use_reranker: bool = False,
    db: AsyncSession | None = None,
    ai_settings: Any = None,
) -> MatchResponse:
    """‌⁠‍Run the matcher on a pre-built envelope.

    Args:
        envelope: The element envelope to match.
        project_id: Project scope (drives ``MatchProjectSettings``).
        top_k: Maximum number of candidates to return.
        use_reranker: Toggle the optional LLM rerank tier.
        db: Optional session to reuse. If ``None``, the matcher opens
            its own short-lived session against ``async_session_factory``.
        ai_settings: Optional AISettings for the LLM tiers (translation
            cascade + reranker).

    Returns:
        :class:`MatchResponse` (always — never raises for normal input).
    """
    project_uuid = project_id if isinstance(project_id, uuid.UUID) else uuid.UUID(str(project_id))
    request = MatchRequest(
        envelope=envelope,
        project_id=project_uuid,
        top_k=top_k,
        use_reranker=use_reranker,
    )

    # OE_MATCH_DETERMINISTIC=1 pins RNGs + forces BGE batch_size=1 so
    # the bench harness can compare runs without run-to-run variance
    # drowning out the signal. No-op in production (default off). The
    # call is idempotent so cost is amortised across the process — only
    # the first match request pays the seed/patch overhead.
    enter_deterministic_mode()

    rank_fn = _select_ranker()

    if db is not None:
        response = await rank_fn(request, db=db, ai_settings=ai_settings)
        return stabilize_response(response)

    async with async_session_factory() as session:
        try:
            response = await rank_fn(request, db=session, ai_settings=ai_settings)
            await session.commit()
            return stabilize_response(response)
        except Exception:
            await session.rollback()
            raise


async def match_element(
    element_info: dict[str, Any],
    top_k: int = 10,
    *,
    source: str | None = None,
    project_id: uuid.UUID | str | None = None,
    use_reranker: bool = False,
    db: AsyncSession | None = None,
    ai_settings: Any = None,
) -> list[dict[str, Any]]:
    """‌⁠‍Eval-harness contract: ``async (element_info, top_k) -> list[dict]``.

    The harness signature passes only positional ``element_info`` and
    ``top_k`` — every other argument is keyword-only with a sensible
    default so the call surface stays simple for that runner.

    Source resolution:
        * Explicit ``source`` keyword if provided.
        * ``element_info["source"]`` otherwise.
        * Falls back to ``"bim"`` (the most common case in our golden
          set).

    Project resolution:
        * Explicit ``project_id`` keyword if provided.
        * ``element_info["project_id"]`` otherwise.
        * Falls back to a sentinel UUID so the matcher can still build
          settings — this keeps the eval harness independent of a real
          DB row.

    Returns:
        List of candidate dicts. Each dict has the full
        :class:`MatchCandidate` shape (the harness only needs ``code``
        and ``unit_rate``, but we send everything so the same response
        is reusable in non-eval calls).
    """
    raw = dict(element_info or {})
    raw_source = source or raw.get("source") or "bim"
    raw_project = project_id or raw.get("project_id")

    # Allow the harness's flat ``element_info`` shape (with keys like
    # ``category``, ``material``, ``thickness_m`` straight at the root)
    # to flow through the BIM extractor. Properties live alongside
    # quantities in the harness golden set, so we promote material into
    # ``properties`` here when we can.
    if raw_source == "bim" and "properties" not in raw:
        promoted = {
            k: v
            for k, v in raw.items()
            if k in {"material", "fire_rating", "finish", "u_value", "thermal_conductivity_w_mk", "insulation"}
        }
        if promoted:
            raw = {**raw, "properties": promoted}

    envelope = build_envelope(str(raw_source), raw)

    project_uuid: uuid.UUID
    if raw_project is None:
        # Sentinel — generates a row on first call inside the test DB.
        project_uuid = uuid.UUID("00000000-0000-0000-0000-000000000000")
    elif isinstance(raw_project, uuid.UUID):
        project_uuid = raw_project
    else:
        try:
            project_uuid = uuid.UUID(str(raw_project))
        except (TypeError, ValueError):
            project_uuid = uuid.UUID("00000000-0000-0000-0000-000000000000")

    response = await match_envelope(
        envelope,
        project_id=project_uuid,
        top_k=top_k,
        use_reranker=use_reranker,
        db=db,
        ai_settings=ai_settings,
    )
    return [c.model_dump() for c in response.candidates]


__all__ = [
    "EXTRACTORS",
    "ElementEnvelope",
    "MatchCandidate",
    "MatchRequest",
    "MatchResponse",
    "SourceType",
    "build_envelope",
    "match_element",
    "match_envelope",
    "rank",
    "record_feedback",
]

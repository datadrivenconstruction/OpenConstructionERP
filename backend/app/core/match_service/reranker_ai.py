# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""LLM rerank tier — opt-in, cost-capped, gracefully degrades.

When ``MatchRequest.use_reranker=True`` the ranker calls
:func:`rerank_top_k` to ask an LLM to re-score the top candidates by
"best-match-quality" and return per-candidate reasoning the UI can show.

Why this is opt-in:
    * Costs ~$0.005 - $0.02 per request (depending on provider).
    * Adds 1-3s of latency.
    * The boost-only ranking is already strong (>0.7 top-1 on golden).

So we keep this off by default. Power users with cost budgets and a
willingness to wait can switch it on for tricky elements.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.match_service.config import (
    RERANK_MAX_COST_USD,
    RERANK_MAX_TOKENS,
    RERANK_MODEL_HINT,
    RERANK_TOP_K,
)
from app.core.match_service.envelope import (
    ElementEnvelope,
    MatchCandidate,
    confidence_band_for,
)

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = (
    "You are a senior construction estimator. You see a building element "
    "and a shortlist of CWICR cost-database candidates. Reorder the "
    "shortlist by the best fit for the element, considering material, "
    "dimension, classification, and unit of measure. Output a JSON list "
    "of objects with keys: code, score (0.0-1.0), reasoning (one short "
    "sentence). The output list must contain every input code exactly "
    "once, in the new ranked order."
)


def _build_user_prompt(envelope: ElementEnvelope, candidates: list[MatchCandidate]) -> str:
    """Render the rerank prompt body — element + shortlist as JSON."""
    element_payload: dict[str, Any] = {
        "category": envelope.category,
        "description": envelope.description,
        "properties": envelope.properties,
        "quantities": envelope.quantities,
        "unit_hint": envelope.unit_hint,
        "classifier_hint": envelope.classifier_hint,
    }
    candidate_payloads: list[dict[str, Any]] = []
    for c in candidates:
        candidate_payloads.append({
            "code": c.code,
            "description": c.description,
            "unit": c.unit,
            "unit_rate": c.unit_rate,
            "currency": c.currency,
            "vector_score": round(c.vector_score, 4),
            "boosted_score": round(c.score, 4),
            "classification": c.classification,
        })

    return (
        "ELEMENT:\n"
        + json.dumps(element_payload, ensure_ascii=False, indent=2)
        + "\n\nCANDIDATES:\n"
        + json.dumps(candidate_payloads, ensure_ascii=False, indent=2)
        + "\n\nReturn JSON only — no prose, no markdown."
    )


def _parse_rerank_response(raw: str) -> list[dict[str, Any]]:
    """Best-effort parse of the LLM rerank output.

    Returns an empty list on any failure — callers must treat that as
    "rerank gave us nothing useful, keep the boosted ranking".
    """
    try:
        from app.modules.ai.ai_client import extract_json  # noqa: PLC0415
    except ImportError:  # pragma: no cover — defensive
        return []
    parsed = extract_json(raw)
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        # Sometimes LLMs wrap the list in {"candidates": [...]}
        for key in ("candidates", "ranked", "results"):
            if isinstance(parsed.get(key), list):
                return [item for item in parsed[key] if isinstance(item, dict)]
    return []


def _estimate_cost_usd(tokens: int) -> float:
    """Rough USD cost for ``tokens`` input+output (Claude Sonnet pricing).

    Anthropic Sonnet input is ~$3 / Mtok, output ~$15 / Mtok. We don't
    know the input/output split here, so we charge at a midpoint of
    $9 / Mtok. Used purely for the cost-cap sanity check; the response
    surfaces the real cost when the AI client returns it.
    """
    return (tokens / 1_000_000.0) * 9.0


async def rerank_top_k(
    candidates: list[MatchCandidate],
    envelope: ElementEnvelope,
    *,
    k: int = RERANK_TOP_K,
    ai_settings: Any = None,
) -> tuple[list[MatchCandidate], float]:
    """Re-rank the top-``k`` candidates with an LLM.

    Returns ``(ranked_candidates, cost_usd)``. On any failure (no API
    key, network error, malformed response, or projected cost over the
    cap) returns ``(input_unchanged, 0.0)`` — never raises.
    """
    if not candidates:
        return candidates, 0.0

    head = candidates[:k]
    tail = candidates[k:]

    # Cheap upfront cost gate — refuse if even the empty payload would
    # exceed the cap. Real cost reported by the AI client is checked
    # again after the call.
    if _estimate_cost_usd(RERANK_MAX_TOKENS) > RERANK_MAX_COST_USD:
        logger.debug("rerank skipped: estimated cost exceeds cap")
        return candidates, 0.0

    if ai_settings is None:
        return candidates, 0.0

    try:
        from app.modules.ai.ai_client import call_ai, resolve_provider_and_key
    except ImportError:  # pragma: no cover — defensive
        return candidates, 0.0

    try:
        provider, api_key = resolve_provider_and_key(
            ai_settings, preferred_model=RERANK_MODEL_HINT,
        )
    except ValueError:
        return candidates, 0.0

    prompt = _build_user_prompt(envelope, head)

    try:
        raw, tokens = await call_ai(
            provider=provider,
            api_key=api_key,
            system=_SYSTEM_PROMPT,
            prompt=prompt,
            max_tokens=RERANK_MAX_TOKENS,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("rerank LLM call failed: %s", exc)
        return candidates, 0.0

    cost = _estimate_cost_usd(tokens)
    if cost > RERANK_MAX_COST_USD:
        logger.debug("rerank cost %.4f exceeded cap %.4f — discarding result", cost, RERANK_MAX_COST_USD)
        return candidates, 0.0

    parsed = _parse_rerank_response(raw)
    if not parsed:
        return candidates, cost

    by_code: dict[str, MatchCandidate] = {c.code: c for c in head}
    reordered: list[MatchCandidate] = []
    for entry in parsed:
        code = str(entry.get("code", ""))
        if code not in by_code:
            continue
        cand = by_code.pop(code)
        new_score_raw = entry.get("score")
        try:
            new_score = float(new_score_raw) if new_score_raw is not None else cand.score
        except (TypeError, ValueError):
            new_score = cand.score
        cand = cand.model_copy(update={
            "score": max(0.0, min(1.0, new_score)),
            "confidence_band": confidence_band_for(max(0.0, min(1.0, new_score))),
            "reasoning": str(entry.get("reasoning") or "")[:500] or None,
        })
        reordered.append(cand)

    # Append any candidates the LLM forgot to mention so the response
    # still contains the full top-k.
    reordered.extend(by_code.values())
    reordered.sort(key=lambda c: c.score, reverse=True)
    return reordered + tail, cost

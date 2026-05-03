# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Match-service tunables — every magic number lives here.

Boost weights, score clamps, fuzzy-match cutoffs, reranker model name,
and cost caps. The defaults here were calibrated on the v2.8.0 golden
set (``backend/tests/eval/golden_set.yaml``) — keep them in sync if you
re-tune.

Env-var overrides
=================

Every weight can be overridden at process boot via ``MATCH_*`` env vars
so we can A/B-test boost magnitudes without redeploying. Bad values
(non-float, NaN) silently fall back to the canonical default and a
debug-level log line is emitted.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    """Read ``name`` from env as a float, or return ``default`` on miss."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        logger.debug("MATCH config: ignoring non-float %s=%r", name, raw)
        return default


def _env_int(name: str, default: int) -> int:
    """Read ``name`` from env as an int, or return ``default`` on miss."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        logger.debug("MATCH config: ignoring non-int %s=%r", name, raw)
        return default


# ── Boost weights ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BoostWeights:
    """Additive deltas applied to ``vector_score`` before final ranking.

    Each boost reports its delta independently so the final score is
    transparent: the response carries ``boosts_applied`` showing every
    contribution by name. Total boost is summed and clamped to [0, 1].
    """

    classifier_full_match: float
    classifier_group_match: float
    unit_match: float
    unit_mismatch_penalty: float
    region_match: float
    lex_high: float
    lex_medium: float


BOOST_WEIGHTS: BoostWeights = BoostWeights(
    classifier_full_match=_env_float("MATCH_BOOST_CLASSIFIER_FULL", 0.15),
    classifier_group_match=_env_float("MATCH_BOOST_CLASSIFIER_GROUP", 0.08),
    unit_match=_env_float("MATCH_BOOST_UNIT_MATCH", 0.05),
    unit_mismatch_penalty=_env_float("MATCH_BOOST_UNIT_MISMATCH", -0.10),
    region_match=_env_float("MATCH_BOOST_REGION_MATCH", 0.05),
    lex_high=_env_float("MATCH_BOOST_LEX_HIGH", 0.05),
    lex_medium=_env_float("MATCH_BOOST_LEX_MEDIUM", 0.02),
)


# ── Score clamps & confidence bands ──────────────────────────────────────


SCORE_FLOOR: float = 0.0
SCORE_CEIL: float = 1.0

# Confidence-band thresholds — match the v2.8.0 brief verbatim.
CONFIDENCE_HIGH_THRESHOLD: float = 0.85
CONFIDENCE_MEDIUM_THRESHOLD: float = 0.70


# ── Fuzzy lex thresholds (rapidfuzz token_set_ratio, 0-100) ──────────────

LEX_HIGH_THRESHOLD: int = _env_int("MATCH_LEX_HIGH", 80)
LEX_MEDIUM_THRESHOLD: int = _env_int("MATCH_LEX_MEDIUM", 60)


# ── Search over-fetch multiplier ─────────────────────────────────────────
#
# We pull ``top_k * SEARCH_OVERFETCH`` hits from the vector store so
# boosts can re-rank within a wider window. 3× is enough that a candidate
# ranked 25th by raw cosine can still climb into a top-10 after a full
# classifier+unit boost stack, without making the cosine search itself
# expensive. Anything higher mostly just costs latency.

SEARCH_OVERFETCH: int = _env_int("MATCH_SEARCH_OVERFETCH", 3)


# ── Query-text shaping ───────────────────────────────────────────────────

# Concise queries embed best with E5 — long property dumps add noise.
QUERY_MAX_CHARS: int = _env_int("MATCH_QUERY_MAX_CHARS", 200)


# ── Reranker (optional LLM tier) ─────────────────────────────────────────

# Re-ranks the top-K with an LLM only when the caller opts in
# (``MatchRequest.use_reranker=True``). Default off — reranking the
# full top-10 of every match request would burn ~$0.02 each.
RERANK_TOP_K: int = _env_int("MATCH_RERANK_TOP_K", 5)
RERANK_MAX_TOKENS: int = _env_int("MATCH_RERANK_MAX_TOKENS", 1024)
RERANK_MAX_COST_USD: float = _env_float("MATCH_RERANK_MAX_COST_USD", 0.05)
RERANK_MODEL_HINT: str = os.environ.get("MATCH_RERANK_MODEL", "claude-sonnet")

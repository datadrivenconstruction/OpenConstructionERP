# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Match-service tunables — every magic number lives here.

Boost weights, score clamps, fuzzy-match cutoffs, reranker model name,
and cost caps. The defaults here were calibrated on the v2.8.0 golden
set (``backend/tests/eval/golden_set.yaml``) — keep them in sync if you
re-tune.

v3 — bands re-pinned for BGE-M3 (2026-05-10): ``CONFIDENCE_HIGH`` 0.85
→ 0.78, ``CONFIDENCE_MEDIUM`` 0.70 → 0.62, ``AUTO_CONFIRM_DEFAULT``
0.95 → 0.88. The BGE-M3 RRF score distribution sits ~5–8 points lower
than the e5-small + LanceDB cosine the v2.8.0 numbers were tuned on.

Env-var overrides
=================

Every weight can be overridden at process boot via ``MATCH_*`` env vars
so we can A/B-test boost magnitudes without redeploying. Bad values
(non-float, NaN) silently fall back to the canonical default and a
debug-level log line is emitted.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    """‌⁠‍Read ``name`` from env as a float, or return ``default`` on miss."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        logger.debug("MATCH config: ignoring non-float %s=%r", name, raw)
        return default


def _env_int(name: str, default: int) -> int:
    """‌⁠‍Read ``name`` from env as an int, or return ``default`` on miss."""
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
    rare_token_per_hit: float
    rare_token_cap: float


BOOST_WEIGHTS: BoostWeights = BoostWeights(
    classifier_full_match=_env_float("MATCH_BOOST_CLASSIFIER_FULL", 0.15),
    classifier_group_match=_env_float("MATCH_BOOST_CLASSIFIER_GROUP", 0.08),
    unit_match=_env_float("MATCH_BOOST_UNIT_MATCH", 0.05),
    unit_mismatch_penalty=_env_float("MATCH_BOOST_UNIT_MISMATCH", -0.10),
    region_match=_env_float("MATCH_BOOST_REGION_MATCH", 0.05),
    lex_high=_env_float("MATCH_BOOST_LEX_HIGH", 0.05),
    lex_medium=_env_float("MATCH_BOOST_LEX_MEDIUM", 0.02),
    # Distinctive technical tokens (concrete grades, pipe nominals, steel
    # profiles) embed poorly in multilingual semantic space. Reward
    # verbatim overlap to repair the recall loss without touching the
    # encoder.
    rare_token_per_hit=_env_float("MATCH_BOOST_RARE_TOKEN_PER_HIT", 0.06),
    rare_token_cap=_env_float("MATCH_BOOST_RARE_TOKEN_CAP", 0.15),
)


# ── Score clamps & confidence bands ──────────────────────────────────────


SCORE_FLOOR: float = 0.0
SCORE_CEIL: float = 1.0

# Confidence-band thresholds — pinned for BGE-M3 + Qdrant RRF as of
# 2026-05-10. The earlier defaults (HIGH=0.85 / MEDIUM=0.70) were
# calibrated against e5-small + LanceDB cosine; BGE-M3's RRF-fused
# score distribution sits roughly 5-8 points lower for the same
# semantic neighborhood, so v3 lowers HIGH→0.78 and MEDIUM→0.62.
# Both are env-overridable so operators can re-calibrate after a
# fresh golden-set run (or future model swap) without a code deploy.
CONFIDENCE_HIGH_THRESHOLD: float = _env_float("MATCH_CONFIDENCE_HIGH", 0.78)
CONFIDENCE_MEDIUM_THRESHOLD: float = _env_float("MATCH_CONFIDENCE_MEDIUM", 0.62)

# Default auto-confirm threshold for new MatchSessions. Each session can
# override per-project via the API; this is the factory default. A
# session-scoped slider is still the right UX for per-project trust
# calibration — this constant only changes what new sessions inherit.
# v3: lowered 0.95 → 0.88 because a 0.95 BGE-M3 RRF score is essentially
# a perfect match. We want auto-confirm to catch HIGH-band hits (≥0.78
# under the re-calibrated thresholds), so 0.88 sits comfortably above
# HIGH while still letting strong-but-not-perfect candidates through.
DEFAULT_AUTO_CONFIRM_THRESHOLD: float = _env_float("MATCH_AUTO_CONFIRM_DEFAULT", 0.88)


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


# ── BGE local cross-encoder reranker ─────────────────────────────────────
#
# When :mod:`reranker_bge` is enabled, the top-``RERANK_BGE_TOP_K``
# candidates from the bi-encoder + RRF fusion are re-scored by a local
# cross-encoder (BAAI/bge-reranker-v2-m3 by default). Free, fast,
# multilingual. See :mod:`reranker_bge` for the lifecycle and graceful
# degradation behaviour.

RERANK_BGE_TOP_K: int = _env_int("MATCH_RERANK_BGE_TOP_K", 10)
RERANK_BGE_MODEL_NAME: str = os.environ.get("MATCH_RERANK_BGE_MODEL", "BAAI/bge-reranker-v2-m3")
# fp16 saves ~50% VRAM on GPU but is a no-op on CPU; default off so the
# CPU-only VPS path stays bit-identical regardless of env.
RERANK_BGE_USE_FP16: bool = os.environ.get("MATCH_RERANK_BGE_FP16", "0") in ("1", "true", "True")


# ── Profile-driven thresholds (T3.1 / T3.2 / T3.3) ───────────────────────
#
# T3.1: confidence-band thresholds are calibrated for BGE-M3 + Qdrant RRF.
#       Other encoders (e5-small, bge-small) and the Sonnet reranker have
#       different score distributions and need their own bands.
# T3.2: boost weights are tuned to v3 DIN-276; per-standard tuning will
#       layer on top later. For now the API surface exists as a stub.
# T3.3: lex-fuzz thresholds (RapidFuzz token_set_ratio) are language-
#       blind by default but inflectional languages (PL/RU/FI/TR/...) need
#       a lower cutoff to compensate for declension noise.
#
# Profile files live under ``data/match/`` so operators can hot-swap them
# without a code deploy. Missing or malformed files fall back to the
# existing module-level constants so the import path keeps working in
# minimal/dev installs that don't ship the data tree.

# Repo layout: ``<root>/backend/app/core/match_service/config.py`` → 5 up
# = repo root. Then ``data/match/...``.
_PROFILE_DIR: Path = Path(__file__).resolve().parents[4] / "data" / "match"
_ENCODER_PROFILE_PATH: Path = _PROFILE_DIR / "encoder_profiles.json"
_LEX_PROFILE_PATH: Path = _PROFILE_DIR / "lex_thresholds.json"


@lru_cache(maxsize=1)
def _load_encoder_profiles_raw() -> dict[str, Any]:
    """‌⁠‍Read ``encoder_profiles.json`` once, cache for process lifetime.

    Returns an empty dict on any I/O or parse error so callers can fall
    back to the canonical constants without raising.
    """
    try:
        with _ENCODER_PROFILE_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            logger.debug("MATCH config: encoder_profiles.json root is not an object — ignoring")
            return {}
        return data
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("MATCH config: encoder_profiles.json unreadable (%s)", exc)
        return {}


@lru_cache(maxsize=1)
def _load_lex_profiles_raw() -> dict[str, Any]:
    """‌⁠‍Read ``lex_thresholds.json`` once, cache for process lifetime."""
    try:
        with _LEX_PROFILE_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            logger.debug("MATCH config: lex_thresholds.json root is not an object — ignoring")
            return {}
        return data
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("MATCH config: lex_thresholds.json unreadable (%s)", exc)
        return {}


def _load_encoder_profile(model_id: str | None) -> dict[str, float]:
    """‌⁠‍Return the encoder profile dict for ``model_id`` or {}.

    Lookup order: explicit ``model_id`` → file's ``default`` key →
    empty dict (caller falls back to canonical constants).
    """
    raw = _load_encoder_profiles_raw()
    if not raw:
        return {}
    profiles = raw.get("profiles") or {}
    if not isinstance(profiles, dict):
        return {}

    # 1. Exact match.
    if model_id and model_id in profiles:
        prof = profiles.get(model_id)
        if isinstance(prof, dict):
            return prof

    # 2. Default key from the file.
    default_key = raw.get("default")
    if isinstance(default_key, str) and default_key in profiles:
        prof = profiles.get(default_key)
        if isinstance(prof, dict):
            return prof

    return {}


def _load_lex_thresholds_for(lang: str) -> dict[str, int]:
    """‌⁠‍Return the lex-threshold dict for ``lang`` or the file default."""
    raw = _load_lex_profiles_raw()
    if not raw:
        return {}
    languages = raw.get("languages") or {}
    if isinstance(languages, dict) and lang:
        prof = languages.get(lang)
        if isinstance(prof, dict):
            return prof
    default_prof = raw.get("default")
    if isinstance(default_prof, dict):
        return default_prof
    return {}


def confidence_thresholds_for_model(
    model_id: str | None,
) -> tuple[float, float, float]:
    """‌⁠‍Resolve ``(high, medium, low)`` confidence bands for ``model_id``.

    Falls back to the canonical ``CONFIDENCE_HIGH_THRESHOLD`` /
    ``CONFIDENCE_MEDIUM_THRESHOLD`` constants (and ``0.40`` for low)
    when the profile file is missing or the model is unknown — so legacy
    call sites keep working unchanged.
    """
    prof = _load_encoder_profile(model_id)
    try:
        high = float(prof.get("high", CONFIDENCE_HIGH_THRESHOLD))
    except (TypeError, ValueError):
        high = CONFIDENCE_HIGH_THRESHOLD
    try:
        medium = float(prof.get("medium", CONFIDENCE_MEDIUM_THRESHOLD))
    except (TypeError, ValueError):
        medium = CONFIDENCE_MEDIUM_THRESHOLD
    try:
        low = float(prof.get("low", 0.40))
    except (TypeError, ValueError):
        low = 0.40
    return (high, medium, low)


def lex_thresholds_for_language(lang: str | None) -> tuple[int, int]:
    """‌⁠‍Resolve ``(high, medium)`` lex thresholds for ``lang``.

    Falls back to ``LEX_HIGH_THRESHOLD`` / ``LEX_MEDIUM_THRESHOLD`` so
    callers that don't pass a language (or pass an unknown one) keep the
    historical behaviour.
    """
    prof = _load_lex_thresholds_for((lang or "").lower())
    try:
        high = int(prof.get("high", LEX_HIGH_THRESHOLD))
    except (TypeError, ValueError):
        high = LEX_HIGH_THRESHOLD
    try:
        medium = int(prof.get("medium", LEX_MEDIUM_THRESHOLD))
    except (TypeError, ValueError):
        medium = LEX_MEDIUM_THRESHOLD
    return (high, medium)


def boost_weights_for_standard(standard: str | None) -> dict[str, float]:
    """‌⁠‍Resolve boost weights for a classification ``standard``.

    Stub for T3.2 — currently returns the canonical ``BOOST_WEIGHTS`` as
    a plain dict regardless of ``standard``. The API surface lets future
    per-standard tuning (DIN 276 vs. NRM vs. MasterFormat) layer in
    without changing the ranker call sites.
    """
    # ``standard`` intentionally ignored for now — see T3.2 in
    # MATCH_HARDCODE_REGISTRY.md.
    del standard
    return asdict(BOOST_WEIGHTS)

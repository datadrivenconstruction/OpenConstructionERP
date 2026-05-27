# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Local BGE cross-encoder rerank tier — free, fast, gracefully degrades.

The bi-encoder + RRF fusion path in :mod:`qdrant_adapter` is fast but
noisy at the boundary between rank 1 and rank 5: the top candidates
have very similar fused scores so small lexical differences (concrete
grade ``C30/37`` vs ``C25/30``) get smoothed out. A cross-encoder
re-scores ``(query, candidate)`` pairs *together* through one transformer
forward pass — substantially better at fine discrimination.

Where this differs from :mod:`reranker_ai`:

* No API cost — runs locally on CPU (or GPU when present).
* No latency budget tradeoff — INT8 ONNX BGE-reranker-v2-m3 reranks
  10 pairs in ~200 ms on a typical VPS, well under the user-facing
  budget.
* No external dependency at import time — :func:`rerank` lazy-imports
  ``FlagEmbedding.FlagReranker`` and falls through cleanly when the
  ``[semantic]`` extra is missing.

The bge variant is **not** opt-in like the LLM reranker — it runs on
every match request once enabled in settings. The opt-out is via
``settings.match_use_bge_reranker = False`` for installs where the
extra disk footprint (~568 MB FP32, ~140 MB INT8) is too much.

Model selection follows :data:`RERANK_BGE_MODEL_NAME` from
:mod:`config`. Default is ``BAAI/bge-reranker-v2-m3`` — multilingual
across 100+ languages, MIT-licensed, same author as ``bge-m3`` so
cross-encoder ↔ bi-encoder are trained on the same corpus.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.match_service.config import confidence_thresholds_for_model
from app.core.match_service.envelope import (
    ConfidenceBand,
    ElementEnvelope,
    MatchCandidate,
    confidence_band_for,
)

# BGE cross-encoder shares its score distribution with the bge-m3 family
# the bi-encoder uses, so we re-use that profile key. Operators who swap
# the cross-encoder for a different model can override via env or by
# editing data/match/encoder_profiles.json.
_BGE_PROFILE_KEY: str = "bge-m3"


def _dynamic_band_for_bge(
    score: float,
    *,
    hard_filters_matched: int = 0,
    classification_confidence: str | None = None,
) -> ConfidenceBand:
    """Confidence band keyed off the BGE encoder profile.

    Falls back to the canonical :func:`confidence_band_for` whenever the
    profile resolves to the global constants (the helper is a no-op then),
    so legacy tests that pin behaviour against the env-overridable
    constants stay green.
    """
    try:
        high, medium, _ = confidence_thresholds_for_model(_BGE_PROFILE_KEY)
    except Exception:
        return confidence_band_for(
            score,
            hard_filters_matched=hard_filters_matched,
            classification_confidence=classification_confidence,
        )

    cls = (classification_confidence or "").strip().lower()
    cls_offset = -0.02 if cls == "high" else 0.03 if cls == "low" else 0.0

    high_floor = high + cls_offset
    medium_floor = medium + cls_offset
    if hard_filters_matched >= 3:
        high_floor = min(high_floor, (high * 0.96) + cls_offset)
    if hard_filters_matched >= 1:
        medium_floor = min(medium_floor, (medium * 0.97) + cls_offset)

    if score >= high_floor:
        return "high"
    if score >= medium_floor:
        return "medium"
    return "low"


logger = logging.getLogger(__name__)


# Cached reranker instance — the model is large enough that re-loading
# it per-request would dominate latency. None until first successful
# load; ``False`` after a load failure to short-circuit subsequent
# attempts (no point retrying on every match).
_RERANKER: Any = None


def _get_reranker() -> Any:
    """Lazy-load and cache the FlagReranker model.

    Returns the cached reranker instance, or ``None`` if the
    ``[semantic]`` extra isn't installed / the model couldn't be
    fetched. Subsequent calls after a failure return ``None`` cheaply
    without re-attempting the import.
    """
    global _RERANKER
    if _RERANKER is False:
        return None
    if _RERANKER is not None:
        return _RERANKER

    try:
        from FlagEmbedding import FlagReranker  # type: ignore[import-not-found]
    except ImportError:
        logger.info("reranker_bge: FlagEmbedding not installed — rerank disabled")
        _RERANKER = False
        return None

    from app.config import get_settings

    settings = get_settings()
    model_name = getattr(settings, "rerank_bge_model_name", "BAAI/bge-reranker-v2-m3")
    use_fp16 = bool(getattr(settings, "rerank_bge_use_fp16", False))

    try:
        _RERANKER = FlagReranker(model_name, use_fp16=use_fp16)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("reranker_bge: model load failed (%s) — rerank disabled", exc)
        _RERANKER = False
        return None
    return _RERANKER


def _build_query_text(envelope: ElementEnvelope) -> str:
    """Render the envelope into a single query string for the cross-encoder.

    Mirrors the ``core_query`` from :func:`query_builder.build_search_plan`
    so the reranker sees the same semantic signal the bi-encoder did.
    Kept narrow on purpose — the cross-encoder benefits from a short
    focused query, not a noisy concatenation.
    """
    parts: list[str] = []
    if envelope.category:
        parts.append(str(envelope.category))
    if envelope.description:
        parts.append(str(envelope.description))
    if envelope.material_class:
        parts.append(str(envelope.material_class))
    if envelope.nominal_size_mm:
        parts.append(f"{envelope.nominal_size_mm}mm")
    if envelope.unit_hint:
        parts.append(str(envelope.unit_hint))
    return " ".join(p.strip() for p in parts if p.strip())


def _build_candidate_text(candidate: MatchCandidate) -> str:
    """Render the candidate into the cross-encoder's "passage" half.

    Cross-encoders score (query, passage) jointly so the passage must
    carry the discriminating signal — code, description, unit. Skip
    fields the bi-encoder already scored (vector_score) since the
    cross-encoder isn't operating on the embedding.

    Defensive fallback for snapshot-only installs: when ``description``
    is empty (parquet missing, payload synthesis already attempted and
    yielded nothing) we fold classification IDs + region into the
    passage so the cross-encoder has at least the categorical anchor
    instead of just an opaque rate_code. Without this the BGE score
    collapses to ≈ 0 for every candidate and the ranker effectively
    flattens — same UX as a metadata-only fallback even when the
    bi-encoder hit was genuinely good.
    """
    parts: list[str] = []
    if candidate.code:
        parts.append(str(candidate.code))
    if candidate.description:
        parts.append(str(candidate.description))
    if candidate.unit:
        parts.append(f"unit {candidate.unit}")
    if not candidate.description:
        for std in ("din276", "nrm", "masterformat"):
            cls = candidate.classification.get(std) if candidate.classification else None
            if cls:
                parts.append(f"{std} {cls}")
        if candidate.region_code:
            parts.append(f"region {candidate.region_code}")
    return " ".join(p.strip() for p in parts if p.strip())


def _normalize_bge_scores(raw_scores: list[float]) -> list[float]:
    """Map FlagReranker logits onto the [0,1] band the rest of the system expects.

    BGE-reranker outputs unbounded logits, typically in the range
    [-10, +10]. Apply a sigmoid so downstream :func:`confidence_band_for`
    can compare them against the existing thresholds without rescaling.
    """
    import math

    return [1.0 / (1.0 + math.exp(-s)) for s in raw_scores]


def is_available() -> bool:
    """Return ``True`` when the BGE reranker can be invoked.

    Cheap probe — calls :func:`_get_reranker` and observes the cache
    state. Intended for callers that want to gate UI ("rerank with BGE"
    toggle) on actual availability rather than a settings flag alone.
    """
    return _get_reranker() is not None


def rerank(
    candidates: list[MatchCandidate],
    envelope: ElementEnvelope,
    *,
    k: int | None = None,
    hard_filters_matched: int = 0,
    classification_confidence_by_code: dict[str, str] | None = None,
) -> list[MatchCandidate]:
    """Re-score the top-``k`` candidates with the local BGE cross-encoder.

    Mutates score + confidence_band on each reranked candidate; never
    re-orders the tail beyond the top-``k`` slice (the bi-encoder is
    trustworthy enough past rank 10 that re-ordering would just churn).

    On any failure path — model not loaded, single empty candidate,
    encoding error — returns the input list unchanged. The caller is
    expected to treat the return value as a possibly-no-op transform.

    ``hard_filters_matched`` and ``classification_confidence_by_code``
    are forwarded into :func:`confidence_band_for` so the v3-P9 §6.4
    band derivation factors in the SearchPlan tightness.
    """

    if not candidates:
        return candidates

    reranker = _get_reranker()
    if reranker is None:
        return candidates

    head_size = k if k is not None else min(len(candidates), 10)
    head = candidates[:head_size]
    tail = candidates[head_size:]

    query = _build_query_text(envelope)
    pairs: list[tuple[str, str]] = [(query, _build_candidate_text(c)) for c in head]
    if not query or not all(text for _, text in pairs):
        return candidates

    try:
        raw_scores = reranker.compute_score(pairs)
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("reranker_bge: compute_score failed (%s)", exc)
        return candidates

    if not isinstance(raw_scores, list):
        # FlagReranker returns a float for a single pair; coerce.
        raw_scores = [float(raw_scores)]
    raw_scores = [float(s) for s in raw_scores]
    normalized = _normalize_bge_scores(raw_scores)

    # Blend factor — how much weight to give the BGE rerank vs the
    # prior (fused vector + boosts) score. On payload-only snapshots
    # the catalogue descriptions are templated (e.g.
    # "Electrical equipment — IfcLightFixture — Commissioning —
    # MasterFormat 26 20 00") and BGE finds little signal beyond the
    # generic category prefix — its sigmoid logits collapse to the
    # 0.003-0.05 band even for objectively-correct matches. A naive
    # score replacement then drags every correct hit down to that
    # band, killing the confidence story for downstream UI/auto-link.
    #
    # The blend below treats BGE as a *reordering* signal, not a
    # *score replacement*: 60% prior + 40% BGE preserves the vector
    # confidence while still letting BGE break ties between top-k
    # candidates. Reranker still drives the final sort order (so
    # candidate at position 1 after rerank is the one BGE thinks is
    # best) — only the displayed/stored score is preserved.
    _BGE_BLEND_WEIGHT: float = 0.4

    by_code = classification_confidence_by_code or {}
    # Pair each head candidate with its BGE signal so we can sort by
    # BGE (re-ordering authority) but display the blended score.
    indexed: list[tuple[float, float, MatchCandidate]] = []
    for cand, new_score in zip(head, normalized, strict=False):
        clamped = max(0.0, min(1.0, new_score))
        prior = float(cand.score)
        # Blend: prior_score * (1 - w) + bge_score * w. When
        # ``bge_score`` is much lower than prior (the templated-passage
        # cliff), we keep most of the prior. When BGE is much higher
        # (rare — usually means the prior was over-cautious), we move
        # closer to BGE's reading.
        blended = prior * (1.0 - _BGE_BLEND_WEIGHT) + clamped * _BGE_BLEND_WEIGHT
        blended = max(0.0, min(1.0, blended))
        indexed.append((clamped, blended, cand))

    # Sort the head by BGE first (reorder authority), tie-break by
    # blended (preserves prior signal when BGE is flat), then by code
    # for determinism.
    indexed.sort(key=lambda t: (-t[0], -t[1], t[2].code))

    reranked: list[MatchCandidate] = []
    for clamped, blended, cand in indexed:
        prior = float(cand.score)
        band = _dynamic_band_for_bge(
            blended,
            hard_filters_matched=hard_filters_matched,
            classification_confidence=by_code.get(cand.code),
        )
        reranked.append(
            cand.model_copy(
                update={
                    # ``score`` is what the UI shows + what auto-link
                    # gates on; keep it on the same scale as the
                    # pre-rerank vector path so a 0.85 auto-link
                    # threshold means the same thing across reranked
                    # and non-reranked responses.
                    "score": blended,
                    "confidence_band": band,
                    "boosts_applied": {
                        **cand.boosts_applied,
                        # Track both the raw BGE signal and the
                        # blended delta so the explainability panel
                        # can show "BGE rerank pushed this up by X".
                        "bge_rerank_raw": clamped,
                        "bge_rerank_delta": blended - prior,
                    },
                }
            )
        )

    # Head was already sorted by BGE-then-blended-then-code in
    # ``indexed.sort`` above (BGE preserves the cross-encoder's
    # ordering authority; blended + code tie-break for determinism).
    # Avoid the trailing ``reranked.sort(key=score)`` that the
    # pre-blend implementation did — once we blend with the prior, the
    # blended score is no longer monotone in BGE rank, so re-sorting
    # by it would undo the BGE reordering and collapse back to
    # vector-only ranking. We keep the BGE order from indexed.sort
    # and let the caller's final ``candidates.sort`` (in
    # ``ranker_qdrant.rank``) deal with global ordering.
    return reranked + tail


__all__ = ["is_available", "rerank"]

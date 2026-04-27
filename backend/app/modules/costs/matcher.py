# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""CWICR cost-item matcher (T12).

Given a free-form BOQ position description, return the top-K most relevant
:class:`CostItem` rows from the active cost database, with a 0..1 confidence
score per result. Used by the BOQ editor's "Apply CWICR rate" affordance.

Modes
-----
* ``lexical`` (default, always available)
    rapidfuzz-based fuzzy match against ``description`` + localized
    descriptions, plus small additive bonuses for unit-of-measure match
    and language hint hit.
* ``semantic``
    Optional path. Tries to import :mod:`qdrant_client` and
    :mod:`sentence_transformers` lazily. If either dependency is missing
    (the ``[semantic]`` extra is not installed) we log once at WARNING
    and fall back to lexical without raising. The matcher must always
    return *something* — the BOQ editor depends on it.
* ``hybrid``
    Both lexical and semantic scores are computed, blended as
    ``0.6 * lexical + 0.4 * semantic`` (the lexical channel is more
    reliable in pure-lexical fallback scenarios).

Pure-lexical mode is the documented contract — every test in this
module's unit suite exercises it without any optional deps installed.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costs.models import CostItem

logger = logging.getLogger(__name__)


# ── Constants ──────────────────────────────────────────────────────────────


_DEFAULT_TOP_K = 10
_MAX_TOP_K = 50
_CANDIDATE_CAP = 400
"""Hard cap on rows pulled from DB before fuzzy ranking. Keeps the
P95 latency bounded on a 55 000-row CWICR table."""

_LEXICAL_WEIGHT_HYBRID = 0.6
_SEMANTIC_WEIGHT_HYBRID = 0.4

_UNIT_BONUS = 0.10
"""Score boost when the candidate's ``unit`` exactly matches the request
unit. Capped well below 1.0 so it can only nudge ordering — not flip a
clearly-irrelevant row to the top."""

_LANG_BONUS = 0.05
"""Score boost when the candidate has a localized description in the
requested language. Smaller than the unit bonus because language hits
are common in multilingual CWICR data and shouldn't dominate."""


# ── Public API types ───────────────────────────────────────────────────────


class MatchResult(BaseModel):
    """One ranked match for a BOQ-position → CWICR query.

    The frontend renders these as rows in the CwicrMatchPanel; clicking
    "Apply" pushes ``unit_rate`` + ``cost_item_id`` onto the active BOQ
    position (and stores ``code`` in metadata for traceability).
    """

    model_config = ConfigDict(from_attributes=False)

    cost_item_id: str = Field(..., description="UUID of the matched CostItem")
    code: str = Field(..., description="CWICR rate code")
    description: str = Field(..., description="Human-readable description")
    unit: str = Field(..., description="Unit of measurement (m, m2, m3, ...)")
    unit_rate: float = Field(..., description="Numeric unit rate (0 if unparseable)")
    currency: str = Field(default="EUR", description="ISO 4217 currency code")
    score: float = Field(
        ..., ge=0.0, le=1.0, description="Relevance score 0..1 (higher = better)"
    )
    source: str = Field(
        default="lexical",
        description="Which matching channel produced this result: lexical | semantic | hybrid",
    )


@dataclass
class _Candidate:
    """Internal candidate row before scoring (avoids re-reading SQLAlchemy attrs)."""

    item: CostItem
    lexical: float = 0.0
    semantic: float = 0.0


class _SemanticDepsMissing(RuntimeError):
    """Raised internally when qdrant / sentence-transformers cannot be imported."""


# Sentinel — log the missing-deps warning at most once per process.
_warned_missing_semantic_deps = False


# ── Public matcher entry point ─────────────────────────────────────────────


async def match_cwicr_items(
    session: AsyncSession,
    query: str,
    *,
    unit: str | None = None,
    lang: str | None = None,
    top_k: int = _DEFAULT_TOP_K,
    semantic: bool = False,
    mode: str = "lexical",
    region: str | None = None,
    source: str = "cwicr",
) -> list[MatchResult]:
    """Return up to ``top_k`` :class:`MatchResult` rows ranked by relevance.

    Parameters
    ----------
    session
        Live :class:`AsyncSession` used to load candidates.
    query
        Free-form description text. Empty / whitespace-only → empty list
        (no point scoring nothing — saves a DB hit).
    unit
        Optional unit hint (``m3``, ``kg``, ...). Exact matches get a
        small additive bonus.
    lang
        Optional ISO-639-1 hint (``en``, ``de``, ``ru``, ...). Items whose
        ``descriptions`` dict has the matching key get a small bonus.
    top_k
        Maximum rows to return. Clamped to ``[1, 50]``.
    semantic
        Compatibility flag — if True and ``mode='lexical'`` we promote
        to ``hybrid`` (the legacy router uses ``semantic=True``).
    mode
        ``lexical`` (default), ``semantic``, or ``hybrid``.
    region
        Optional region filter (e.g. ``DE_BERLIN``). Forwarded to the SQL.
    source
        Filter by ``CostItem.source``. Defaults to ``cwicr`` (the open
        cost database). Pass ``None`` to disable the filter.
    """
    q = (query or "").strip()
    if not q:
        return []

    top_k = max(1, min(int(top_k or _DEFAULT_TOP_K), _MAX_TOP_K))

    # Promote mode if the legacy ``semantic=True`` flag was passed.
    effective_mode = mode
    if semantic and effective_mode == "lexical":
        effective_mode = "hybrid"

    # ── Load candidates (lexical OR-ILIKE prefilter) ─────────────────────
    candidates = await _load_candidates(
        session, q, region=region, source=source, cap=_CANDIDATE_CAP
    )
    if not candidates:
        return []

    # ── Score candidates ────────────────────────────────────────────────
    scored = _score_lexical(candidates, query=q, unit=unit, lang=lang)

    use_semantic = effective_mode in {"semantic", "hybrid"}
    semantic_ok = False
    if use_semantic:
        semantic_ok = _score_semantic(scored, query=q)

    if effective_mode == "semantic" and not semantic_ok:
        # Caller asked for semantic-only but deps unavailable → degrade
        # to lexical instead of returning an empty list. The result is
        # still useful, just less semantically aware.
        effective_mode = "lexical"

    # Combine into final score per candidate.
    final: list[tuple[float, str, _Candidate]] = []
    for cand in scored:
        if effective_mode == "lexical" or not semantic_ok:
            score = cand.lexical
            channel = "lexical"
        elif effective_mode == "semantic":
            score = cand.semantic
            channel = "semantic"
        else:  # hybrid
            score = (
                _LEXICAL_WEIGHT_HYBRID * cand.lexical
                + _SEMANTIC_WEIGHT_HYBRID * cand.semantic
            )
            channel = "hybrid"
        if score <= 0.0:
            continue
        final.append((score, channel, cand))

    # Sort by score desc, then by code asc for stable output.
    final.sort(key=lambda t: (-t[0], t[2].item.code))

    return [
        _to_match_result(cand.item, score=score, channel=channel)
        for score, channel, cand in final[:top_k]
    ]


# ── Position-driven entry point ────────────────────────────────────────────


async def match_cwicr_for_position(
    session: AsyncSession,
    position_id: uuid.UUID,
    *,
    top_k: int = _DEFAULT_TOP_K,
    mode: str = "lexical",
    lang: str | None = None,
    region: str | None = None,
) -> list[MatchResult]:
    """Look up a :class:`Position` and run the matcher on its description.

    Returns an empty list if the position exists but has no description.
    Raises :class:`LookupError` if the position is not found — the router
    converts that into a 404.
    """
    # Local import to avoid a hard circular dep between costs ↔ boq.
    from app.modules.boq.models import Position

    pos = await session.get(Position, position_id)
    if pos is None:
        raise LookupError(f"Position {position_id} not found")

    return await match_cwicr_items(
        session,
        pos.description or "",
        unit=pos.unit or None,
        lang=lang,
        top_k=top_k,
        mode=mode,
        region=region,
    )


# ── Candidate loading ──────────────────────────────────────────────────────


async def _load_candidates(
    session: AsyncSession,
    query: str,
    *,
    region: str | None,
    source: str | None,
    cap: int,
) -> list[_Candidate]:
    """Pull a bounded candidate window via OR-ILIKE on description + code."""
    tokens = _query_tokens(query)
    base = select(CostItem).where(CostItem.is_active.is_(True))
    if region:
        base = base.where(CostItem.region == region)
    if source:
        base = base.where(CostItem.source == source)

    conditions: list[Any] = []
    for tok in tokens:
        if len(tok) < 3:
            continue
        pattern = f"%{tok}%"
        conditions.append(CostItem.description.ilike(pattern))
        conditions.append(CostItem.code.ilike(pattern))

    if conditions:
        base = base.where(or_(*conditions))
    # If no usable tokens (single-char query, etc.) we still do a bounded
    # scan rather than returning empty — caller may still want a unit-only
    # filter to surface something.

    stmt = base.limit(cap)
    result = await session.execute(stmt)
    rows: list[CostItem] = list(result.scalars().all())
    return [_Candidate(item=r) for r in rows]


def _query_tokens(query: str) -> list[str]:
    """Split a query into lower-case alphanumeric tokens, dedup, len>=3."""
    import re

    raw = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) >= 3]
    seen: set[str] = set()
    out: list[str] = []
    for t in raw:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


# ── Lexical scoring ────────────────────────────────────────────────────────


def _score_lexical(
    candidates: list[_Candidate],
    *,
    query: str,
    unit: str | None,
    lang: str | None,
) -> list[_Candidate]:
    """Compute ``cand.lexical`` (0..1) for every candidate.

    Uses :func:`rapidfuzz.fuzz.token_set_ratio` against the candidate's
    description (and any localized description in the request lang). The
    raw 0..100 ratio is normalized to 0..1, then we apply small additive
    bonuses for unit-of-measure match and lang-key presence — both
    capped so the final score never exceeds 1.0.
    """
    try:
        from rapidfuzz import fuzz
    except ImportError:  # pragma: no cover — rapidfuzz is a base dep
        # Without rapidfuzz we have no lexical signal at all. Be honest
        # about it: return zero scores rather than fabricating values.
        for c in candidates:
            c.lexical = 0.0
        return candidates

    q = query.strip().lower()
    unit_norm = (unit or "").strip().lower() or None
    lang_norm = (lang or "").strip().lower() or None

    for c in candidates:
        item = c.item
        # Best ratio over: primary description + any localized variants.
        descs = [item.description or ""]
        if isinstance(item.descriptions, dict):
            for v in item.descriptions.values():
                if isinstance(v, str) and v:
                    descs.append(v)
        # Token-set-ratio is order-insensitive and tolerant of extra
        # words on either side — exactly the right shape for matching
        # short BOQ descriptions against verbose CWICR rate descriptions.
        best = 0.0
        for d in descs:
            r = float(fuzz.token_set_ratio(q, d.lower()))
            if r > best:
                best = r
        # Also score against the code so codes like "C30/37" still win
        # when the user types "c30 37". Capped lower than description
        # because codes are sparse signal.
        code_ratio = float(fuzz.token_set_ratio(q, (item.code or "").lower())) * 0.6
        raw = max(best, code_ratio) / 100.0  # Normalize 0..1.

        bonus = 0.0
        if unit_norm and (item.unit or "").strip().lower() == unit_norm:
            bonus += _UNIT_BONUS
        if lang_norm and isinstance(item.descriptions, dict):
            if lang_norm in {k.lower() for k in item.descriptions if isinstance(k, str)}:
                bonus += _LANG_BONUS

        c.lexical = max(0.0, min(1.0, raw + bonus))

    return candidates


# ── Semantic scoring (optional) ────────────────────────────────────────────


def _score_semantic(candidates: list[_Candidate], *, query: str) -> bool:
    """Populate ``cand.semantic`` via Qdrant + sentence-transformers.

    Returns ``True`` if semantic scoring succeeded, ``False`` if any
    optional dependency is missing or the call fails. On failure, we
    leave ``cand.semantic`` at 0.0 — callers in lexical/hybrid mode
    will simply use the lexical channel.
    """
    global _warned_missing_semantic_deps

    try:
        encoder = _load_sentence_encoder()
    except _SemanticDepsMissing as exc:
        if not _warned_missing_semantic_deps:
            logger.warning(
                "CWICR matcher: semantic mode requested but optional deps "
                "missing (%s) — falling back to lexical. Install the "
                "[semantic] extra to enable.",
                exc,
            )
            _warned_missing_semantic_deps = True
        return False
    except Exception:  # pragma: no cover - defensive
        logger.exception("CWICR matcher: semantic encoder failed to load")
        return False

    try:
        # Encode query once.
        q_vec = encoder([query])[0]
        # Encode all candidate descriptions in one batch.
        descs = [(c.item.description or "") for c in candidates]
        if not any(descs):
            return False
        d_vecs = encoder(descs)
        for c, d_vec in zip(candidates, d_vecs, strict=True):
            sim = _cosine(q_vec, d_vec)
            # cosine on normalized embeddings ∈ [-1, 1]; clamp to [0,1]
            # since negative similarity is uninformative for ranking.
            c.semantic = max(0.0, min(1.0, sim))
    except Exception:  # pragma: no cover - defensive
        logger.exception("CWICR matcher: semantic scoring failed")
        return False
    return True


def _load_sentence_encoder() -> Any:
    """Lazily build a callable ``texts -> list[list[float]]`` encoder.

    Tries (in order):
      1. The shared :func:`app.core.vector.encode_texts` helper if it's
         available — that's the production path because it reuses the
         already-warmed model and respects deployment-side configuration.
      2. ``sentence_transformers.SentenceTransformer`` directly — only
         used when ``app.core.vector`` doesn't expose the helper, e.g.
         in an isolated unit test.

    Raises :class:`_SemanticDepsMissing` when neither path is reachable.
    """
    # Path 1 — production helper.
    try:
        from app.core.vector import encode_texts
    except Exception:
        encode_texts = None  # type: ignore[assignment]

    if callable(encode_texts):
        return encode_texts

    # Path 2 — direct sentence-transformers.
    try:
        from sentence_transformers import SentenceTransformer  # noqa: F401
    except ImportError as exc:
        raise _SemanticDepsMissing(f"sentence_transformers unavailable: {exc}") from exc

    try:
        import qdrant_client  # noqa: F401  (kept as a marker dep)
    except ImportError as exc:
        # qdrant_client is logically optional for pure local encoding,
        # but the spec requires both to be present before we trust the
        # semantic channel.
        raise _SemanticDepsMissing(f"qdrant_client unavailable: {exc}") from exc

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")

    def _encode(texts: list[str]) -> list[list[float]]:
        return model.encode(texts, convert_to_numpy=True, show_progress_bar=False).tolist()

    return _encode


def _cosine(a: list[float] | Any, b: list[float] | Any) -> float:
    """Cosine similarity between two equal-length vectors. NumPy-free."""
    # Allow ndarray / list — cast both sides to list-of-floats.
    av = list(a) if not hasattr(a, "tolist") else a.tolist()
    bv = list(b) if not hasattr(b, "tolist") else b.tolist()
    if len(av) != len(bv) or not av:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(av, bv, strict=True):
        x = float(x)
        y = float(y)
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return float(dot / ((na**0.5) * (nb**0.5)))


# ── Result construction ────────────────────────────────────────────────────


def _to_match_result(
    item: CostItem, *, score: float, channel: str
) -> MatchResult:
    """Coerce a SQLAlchemy :class:`CostItem` into a public MatchResult."""
    try:
        rate_val = float(item.rate)
    except (TypeError, ValueError):
        rate_val = 0.0
    return MatchResult(
        cost_item_id=str(item.id),
        code=item.code or "",
        description=item.description or "",
        unit=item.unit or "",
        unit_rate=rate_val,
        currency=item.currency or "EUR",
        score=round(min(max(score, 0.0), 1.0), 4),
        source=channel,
    )


__all__ = [
    "MatchResult",
    "match_cwicr_for_position",
    "match_cwicr_items",
]

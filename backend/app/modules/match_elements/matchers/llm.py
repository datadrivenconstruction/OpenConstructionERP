# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍LLM matcher - AI re-rank over a vector-prefiltered candidate shortlist.

The match-elements service calls this when the user picks ``method="llm"``
on a group. Rather than asking the LLM to invent CWICR codes from thin
air (which hallucinates non-existent rates), this matcher follows the
"AI-augmented, human-confirmed" principle in two bounded steps:

1. **Recall** - the existing :class:`VectorMatcher` produces a shortlist
   of real catalogue rows for the group's envelope (dense + sparse fuse
   in Qdrant). These are guaranteed-valid candidates with real codes,
   units, and rates.
2. **Precision** - the shortlist (description + unit only, no rates) is
   handed to the LLM, which picks the best match and assigns a 0..1
   confidence. The LLM can only *choose among and re-order* the
   shortlist; it can never fabricate a code. We then reorder the real
   :class:`MatchCandidate` objects accordingly and stamp the LLM's
   confidence as the new score.

Honest degradation
------------------
When no AI provider key is configured (the common single-tenant case
before the user adds a key in Settings > AI), the matcher does NOT raise
and does NOT return a misleading empty result. It falls back to the
vector candidates unchanged, tags each with a ``boosts_applied`` note
(``llm_unavailable``) and logs a single warning. The user still gets the
deterministic vector ranking; the only thing missing is the AI re-order.
This is the most honest behaviour: the feature works, just without the
optional AI tier, exactly like the BGE reranker degrades when the
cross-encoder weights are absent.

Token budget
------------
Only the top :data:`_SHORTLIST_SIZE` candidates are sent, and only their
``code`` / ``description`` / ``unit`` (never the rate - price must not
bias a *relevance* judgement). The prompt asks for a compact JSON array,
capped at ``max_tokens=600``. One LLM round-trip per group; the service
already batches by capping ``max_groups`` per run.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.match_service.envelope import (
    ElementEnvelope,
    MatchCandidate,
    confidence_band_for,
)
from app.modules.match_elements.matchers.vector import VectorMatcher

logger = logging.getLogger(__name__)

# How many vector candidates to expose to the LLM. Twelve is enough to
# capture the right answer in the shortlist (vector recall@10 ~ 0.97 per
# the MAPPING_PROCESS bench) while keeping the prompt small.
_SHORTLIST_SIZE = 12

# Upper bound on response tokens - a ranked index list plus short
# reasoning fits comfortably; caps the per-group cost.
_MAX_TOKENS = 600

_SYSTEM_PROMPT = (
    "You are a senior construction cost estimator. You are given one "
    "source element (from a BIM model, a drawing, or a bill of "
    "quantities) and a numbered shortlist of candidate cost-catalogue "
    "positions. Choose which candidates best describe the same work, "
    "best first. Judge relevance only - descriptions and units, not "
    "price. Reply with ONLY a JSON array, no prose."
)


def _build_prompt(envelope: ElementEnvelope, candidates: list[MatchCandidate]) -> str:
    """‌⁠‍Render the source element + numbered shortlist into a user prompt.

    The candidate rate is deliberately omitted - a relevance judgement
    must not be swayed by how cheap or expensive a row is.
    """
    lines: list[str] = []
    lines.append("SOURCE ELEMENT")
    if envelope.category:
        lines.append(f"  category: {envelope.category}")
    if envelope.description:
        lines.append(f"  description: {envelope.description}")
    if envelope.unit_hint:
        lines.append(f"  expected unit: {envelope.unit_hint}")
    if envelope.material_class:
        lines.append(f"  material: {envelope.material_class}")

    lines.append("")
    lines.append("CANDIDATE POSITIONS")
    for idx, cand in enumerate(candidates):
        desc = (cand.description or "").strip().replace("\n", " ")[:200]
        unit = (cand.unit or "").strip()
        unit_suffix = f"  [{unit}]" if unit else ""
        lines.append(f"  {idx}. {desc}{unit_suffix}")

    lines.append("")
    lines.append(
        "Reply with a JSON array of objects, best match first, of the form "
        '[{"index": <candidate number>, "confidence": <0..1>, '
        '"reason": "<short why>"}]. Include only candidates that genuinely '
        "match (omit irrelevant ones). If none match, reply []."
    )
    return "\n".join(lines)


def _parse_ranking(raw: str, n_candidates: int) -> list[tuple[int, float, str]]:
    """‌⁠‍Parse the LLM JSON ranking into ``[(index, confidence, reason)]``.

    Tolerates code fences / surrounding prose via the shared
    :func:`extract_json` helper. Drops out-of-range indices and
    de-duplicates so a malformed response can never crash the matcher or
    point at a candidate that does not exist.
    """
    from app.modules.ai.ai_client import extract_json

    parsed = extract_json(raw)
    if not isinstance(parsed, list):
        return []

    out: list[tuple[int, float, str]] = []
    seen: set[int] = set()
    for item in parsed:
        if not isinstance(item, dict):
            continue
        idx_raw = item.get("index")
        try:
            idx = int(idx_raw)
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx >= n_candidates or idx in seen:
            continue
        seen.add(idx)
        try:
            conf = float(item.get("confidence"))
        except (TypeError, ValueError):
            conf = 0.0
        conf = max(0.0, min(1.0, conf))
        reason = str(item.get("reason") or "").strip()[:300]
        out.append((idx, conf, reason))
    return out


class LLMMatcher:
    """AI re-rank over a vector-prefiltered shortlist. See module docstring."""

    name = "llm"

    def __init__(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID | None = None,
        model_override: str | None = None,
    ) -> None:
        self.session = session
        self._vector = VectorMatcher(session)
        # Whose AI key to re-rank with. Bring-your-own-AI: the re-rank uses
        # the requesting user's own provider key, never another tenant's.
        self.user_id = user_id
        # Optional per-run model/provider hint (e.g. "gpt-4o", "claude-opus").
        # Steers which of the user's configured providers does the re-rank.
        self.model_override = model_override

    async def _resolve_ai(self) -> tuple[str, str, str | None] | None:
        """Resolve ``(provider, api_key, model)`` or ``None`` when unset.

        Scoped to ``self.user_id`` so the AI re-rank always runs on the
        requesting user's own provider key (bring-your-own-AI), never on
        whichever tenant happened to save a key first.
        ``resolve_provider_key_model`` also reaches into env vars /
        config.json when the user's row has no key, so a single-tenant
        deploy that keeps its key in the environment still works with
        ``user_id`` set. Every failure path returns ``None`` so the caller
        degrades to the deterministic vector ranking.
        """
        try:
            from app.modules.ai.ai_client import resolve_provider_key_model
            from app.modules.ai.repository import AISettingsRepository
        except ImportError as exc:
            logger.warning("LLMMatcher: AI module not available: %s", exc)
            return None

        settings = None
        if self.user_id is not None:
            try:
                settings = await AISettingsRepository(self.session).get_by_user_id(self.user_id)
            except Exception as exc:  # noqa: BLE001 - AI is best-effort
                logger.warning("LLMMatcher: AISettings lookup failed: %s", exc)
                settings = None

        try:
            provider, api_key, model = resolve_provider_key_model(settings, self.model_override)
        except ValueError:
            # No usable key for this user (and none in env/config).
            return None
        if provider and (api_key or provider in ("ollama", "vllm")):
            return provider, api_key, model
        return None

    def _degrade(
        self,
        candidates: list[MatchCandidate],
        note: str,
    ) -> list[MatchCandidate]:
        """Return the vector candidates unchanged, tagged with ``note``.

        Used whenever the AI tier is unavailable or fails - the user keeps
        the deterministic vector ranking instead of a 501 or an empty list.
        """
        for cand in candidates:
            boosts = dict(cand.boosts_applied)
            boosts[note] = 1.0
            cand.boosts_applied = boosts
        return candidates

    async def rank(
        self,
        *,
        envelope: ElementEnvelope,
        project_id: uuid.UUID,
        catalogue_id: uuid.UUID | None = None,
        top_k: int = 10,
    ) -> list[MatchCandidate]:
        # ── 1. Recall: vector shortlist of real catalogue rows ───────────
        shortlist = await self._vector.rank(
            envelope=envelope,
            project_id=project_id,
            catalogue_id=catalogue_id,
            top_k=max(top_k, _SHORTLIST_SIZE),
        )
        if not shortlist:
            return []
        shortlist = shortlist[:_SHORTLIST_SIZE]

        # ── 2. Resolve the AI provider - degrade if none ─────────────────
        resolved = await self._resolve_ai()
        if resolved is None:
            logger.info(
                "LLMMatcher: no AI provider configured - returning vector ranking unchanged (project=%s).",
                project_id,
            )
            return self._degrade(shortlist, "llm_unavailable")[:top_k]
        provider, api_key, model = resolved

        # ── 3. Precision: ask the LLM to re-rank the shortlist ───────────
        from app.modules.ai.ai_client import call_ai

        prompt = _build_prompt(envelope, shortlist)
        try:
            raw_response, _tokens = await call_ai(
                provider=provider,
                api_key=api_key,
                system=_SYSTEM_PROMPT,
                prompt=prompt,
                model=model,
                max_tokens=_MAX_TOKENS,
            )
        except Exception as exc:  # noqa: BLE001 - AI is best-effort
            logger.warning(
                "LLMMatcher: AI call failed (%s) - returning vector ranking: %s",
                provider,
                exc,
            )
            return self._degrade(shortlist, "llm_error")[:top_k]

        ranking = _parse_ranking(raw_response or "", len(shortlist))
        if not ranking:
            # The model returned nothing usable (or judged none relevant).
            # Fall back to the vector ranking rather than dropping the
            # group entirely - the deterministic result is still useful.
            logger.info(
                "LLMMatcher: LLM returned no usable ranking - keeping vector order (project=%s).",
                project_id,
            )
            return self._degrade(shortlist, "llm_no_pick")[:top_k]

        # ── 4. Reorder the real candidates by the LLM's judgement ────────
        out: list[MatchCandidate] = []
        for idx, conf, reason in ranking:
            cand = shortlist[idx]
            # Preserve the vector evidence; overlay the LLM's verdict.
            cand.vector_score = cand.score
            cand.score = conf
            cand.confidence_band = confidence_band_for(conf)
            cand.source = "llm"
            cand.reasoning = reason or cand.reasoning
            boosts = dict(cand.boosts_applied)
            boosts["llm_rerank"] = conf
            cand.boosts_applied = boosts
            out.append(cand)

        return out[:top_k]


__all__ = ["LLMMatcher"]

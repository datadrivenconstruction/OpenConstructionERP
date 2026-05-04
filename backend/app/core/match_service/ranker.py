# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Core ranker — translation → vector search → boost stack → ranked output.

Pipeline (no LLM):

    1. Load ``MatchProjectSettings`` for the project.
    2. Build a concise query string from the envelope.
    3. Translate to the project's catalogue language if needed.
    4. Vector-search CWICR (over-fetch by ``SEARCH_OVERFETCH``).
    5. Convert each hit into a :class:`MatchCandidate` (raw vector_score).
    6. Run every boost in :data:`BOOSTS`, sum into final ``score``.
    7. Sort, slice to ``top_k``, set confidence band, derive auto-link.

The reranker tier (LLM) is bolted on after step 7 only when
``request.use_reranker=True``.
"""

from __future__ import annotations

import logging
import time
import uuid
from types import SimpleNamespace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.match_service.boosts import apply_boosts
from app.core.match_service.config import (
    QUERY_MAX_CHARS,
    SCORE_CEIL,
    SCORE_FLOOR,
    SEARCH_OVERFETCH,
)
from app.core.match_service.envelope import (
    ElementEnvelope,
    MatchCandidate,
    MatchRequest,
    MatchResponse,
    MatchStatus,
    confidence_band_for,
)
from app.core.translation import TranslationResult, translate
from app.modules.costs import vector_adapter as cost_vector
from app.modules.projects.service import get_or_create_match_settings

logger = logging.getLogger(__name__)


# ── Catalogue → ISO-639 language ─────────────────────────────────────────
#
# Maps every CWICR catalogue ID we know about to the language its
# descriptions are written in. This is the *target* language for the
# translation cascade — an English BIM element name is rewritten into,
# say, Russian before searching the RU_STPETERSBURG catalogue. Missing
# keys fall back to ``"en"`` so a freshly-onboarded catalogue still
# searches; the worst case is one less translation pass, not a crash.
_CATALOG_LANGUAGE: dict[str, str] = {
    "RU_STPETERSBURG": "ru",
    "BG_SOFIA":        "bg",
    "DE_BERLIN":       "de",
    "USA_USD":         "en",
    "UK_GBP":          "en",
    "ENG_TORONTO":     "en",
    "AU_SYDNEY":       "en",
    "NZ_AUCKLAND":     "en",
    "ZA_JOHANNESBURG": "en",
    "FR_PARIS":        "fr",
    "SP_BARCELONA":    "es",
    "MX_MEXICOCITY":   "es",
    "PT_SAOPAULO":     "pt",
    "IT_ROME":         "it",
    "NL_AMSTERDAM":    "nl",
    "PL_WARSAW":       "pl",
    "CS_PRAGUE":       "cs",
    "HR_ZAGREB":       "hr",
    "RO_BUCHAREST":    "ro",
    "SV_STOCKHOLM":    "sv",
    "TR_ISTANBUL":     "tr",
    "AR_DUBAI":        "ar",
    "ZH_SHANGHAI":     "zh",
    "JA_TOKYO":        "ja",
    "KO_SEOUL":        "ko",
    "HI_MUMBAI":       "hi",
    "ID_JAKARTA":      "id",
    "TH_BANGKOK":      "th",
    "VI_HANOI":        "vi",
    "NG_LAGOS":        "en",
}


async def _resolve_catalog_status(
    db,
    catalog_id: str | None,
) -> tuple[MatchStatus, int, int]:
    """Resolve the ``catalog_id`` to a structured (status, count, vec) tuple.

    Returns:
        ``("ok", sql_count, vector_count)``           — catalogue ready to search.
        ``("no_catalog_selected", 0, 0)``             — settings.cost_database_id is null.
        ``("no_catalogs_loaded", 0, 0)``              — no catalogue loaded at all.
        ``("catalog_not_vectorized", sql_count, 0)``  — picked, loaded, no vectors.

    The match endpoint short-circuits on every non-``ok`` status with an
    empty candidate list and the matching status code so the UI can
    render an explicit empty state instead of a misleading no-results.
    """
    from sqlalchemy import func, select  # noqa: PLC0415

    from app.modules.costs.models import CostItem  # noqa: PLC0415

    if not catalog_id:
        # Decide between "no catalog selected" vs "nothing loaded at all"
        # so the UI can offer the right CTA. One COUNT roundtrip — cheap.
        try:
            total_loaded = (
                await db.execute(
                    select(func.count(CostItem.id)).where(CostItem.is_active.is_(True))
                )
            ).scalar() or 0
        except Exception:
            total_loaded = 0
        if total_loaded == 0:
            return "no_catalogs_loaded", 0, 0
        return "no_catalog_selected", 0, 0

    try:
        sql_count = (
            await db.execute(
                select(func.count(CostItem.id))
                .where(CostItem.is_active.is_(True))
                .where(CostItem.region == catalog_id)
            )
        ).scalar() or 0
    except Exception as exc:
        logger.warning("match_service: catalog count failed for %s: %s", catalog_id, exc)
        sql_count = 0

    if sql_count == 0:
        # Picked id doesn't exist in the SQL table. If *other* catalogues
        # are loaded, fall back to ``no_catalog_selected`` so the UI shows
        # the picker bar (the user can recover with one click) — never
        # claim "no catalogues loaded" while RU/BG/etc are sitting right
        # there. Only return ``no_catalogs_loaded`` when truly empty.
        try:
            total_loaded = (
                await db.execute(
                    select(func.count(CostItem.id)).where(CostItem.is_active.is_(True))
                )
            ).scalar() or 0
        except Exception:
            total_loaded = 0
        if total_loaded == 0:
            return "no_catalogs_loaded", 0, 0
        return "no_catalog_selected", 0, 0

    try:
        from app.core.vector import vector_count_with_payload_substring  # noqa: PLC0415
        from app.core.vector_index import COLLECTION_COSTS  # noqa: PLC0415
        vec_count = vector_count_with_payload_substring(COLLECTION_COSTS, catalog_id)
    except Exception:
        vec_count = 0

    if vec_count == 0:
        return "catalog_not_vectorized", int(sql_count), 0
    return "ok", int(sql_count), int(vec_count)


# ── Query construction ───────────────────────────────────────────────────


def _format_props(props: dict[str, Any], limit: int = 6) -> str:
    """Stringify the most useful properties into a short ``key:value`` blob.

    Embedding noise grows fast with token count, so we cap at ``limit``
    properties chosen by a stable order — material first (it's the
    biggest semantic signal), then everything else alphabetically.
    """
    if not props:
        return ""
    ordered: list[tuple[str, Any]] = []
    for priority_key in ("material", "fire_rating", "finish", "type", "grade"):
        if priority_key in props:
            ordered.append((priority_key, props[priority_key]))
    for key in sorted(props):
        if key in {p[0] for p in ordered}:
            continue
        ordered.append((key, props[key]))
        if len(ordered) >= limit:
            break

    parts: list[str] = []
    for key, value in ordered[:limit]:
        if value in (None, "", []):
            continue
        parts.append(f"{key}:{value}")
    return " ".join(parts)


def build_query_text(envelope: ElementEnvelope) -> str:
    """Concatenate ``category description {props}`` and clamp to a max length.

    The cap is a ranking-quality choice: E5 short queries embed more
    discriminatively than long ones; once you pass ~200 chars the
    extra tokens dilute the dominant signal.
    """
    parts = [
        envelope.category.strip(),
        envelope.description.strip(),
        _format_props(envelope.properties),
    ]
    raw = " ".join(p for p in parts if p)
    if len(raw) > QUERY_MAX_CHARS:
        raw = raw[:QUERY_MAX_CHARS].rstrip()
    return raw


# ── Vector hit → MatchCandidate ──────────────────────────────────────────


def _hit_to_candidate(hit: dict[str, Any]) -> MatchCandidate:
    """Map a raw vector-search hit into a :class:`MatchCandidate`."""
    payload = hit.get("payload") or {}
    classification: dict[str, str] = {}
    for cls in ("din276", "nrm", "masterformat"):
        value = payload.get(f"classification_{cls}")
        if value:
            classification[cls] = str(value)

    raw_score = float(hit.get("score", 0.0))
    return MatchCandidate(
        code=str(payload.get("code", "") or hit.get("id", "")),
        description=str(payload.get("description", "")),
        unit=str(payload.get("unit", "")),
        unit_rate=float(payload.get("unit_cost", 0.0)),
        currency=str(payload.get("currency", "")),
        score=raw_score,
        vector_score=raw_score,
        boosts_applied={},
        confidence_band=confidence_band_for(raw_score),
        region_code=str(payload.get("region_code", "")),
        source=str(payload.get("source", "")),
        language=str(payload.get("language", "")),
        classification=classification,
    )


# ── Translation step ─────────────────────────────────────────────────────


async def _maybe_translate(
    envelope: ElementEnvelope,
    target_language: str,
    *,
    user_settings: Any = None,
) -> tuple[ElementEnvelope, TranslationResult | None]:
    """Translate envelope text into ``target_language`` if needed.

    Returns the (possibly mutated) envelope and a :class:`TranslationResult`
    when a translation actually fired. The translation is one-way: only
    the description is rewritten — quantities and properties stay
    language-agnostic.

    A ``fallback`` tier result is treated like "no translation
    available": the search still happens against the original text. The
    short-circuit when ``source_lang == target_language`` is handled
    inside ``translate()`` itself, but we add an extra cheap guard here
    to avoid even constructing the cache.
    """
    src = (envelope.source_lang or "").lower()
    tgt = (target_language or "").lower()
    if not src or not tgt or src == tgt:
        return envelope, None
    if not envelope.description:
        return envelope, None

    result = await translate(
        envelope.description,
        source_lang=src,
        target_lang=tgt,
        user_settings=user_settings,
    )
    # Only mutate the envelope's description if the cascade actually
    # produced a translation — otherwise we'd be embedding the
    # original text again under a misleading "translated" label.
    if result.tier_used.value != "fallback" and result.translated:
        envelope = envelope.model_copy(update={"description": result.translated})
    return envelope, result


# ── Core entrypoint ──────────────────────────────────────────────────────


async def rank(
    req: MatchRequest,
    *,
    db: AsyncSession,
    ai_settings: Any = None,
) -> MatchResponse:
    """Run the full match pipeline. Never raises for normal input.

    Args:
        req: Inbound :class:`MatchRequest`.
        db: Async session — used to fetch project match settings.
        ai_settings: Optional ``AISettings`` row for the LLM translation
            tier. ``None`` is fine — the cascade falls through to fallback.

    Returns:
        :class:`MatchResponse` with ranked candidates, the translation
        outcome (if any), and the auto-link target (if the project's
        threshold was crossed and auto-link is enabled).
    """
    started = time.perf_counter()
    cost_usd = 0.0

    project_uuid: uuid.UUID = (
        req.project_id
        if isinstance(req.project_id, uuid.UUID)
        else uuid.UUID(str(req.project_id))
    )
    # Project may not exist (eval harness sentinel UUID, deleted project,
    # or a caller passing a placeholder). Falling through with a
    # transient defaults object lets the matcher still produce ranked
    # candidates instead of bubbling a FK IntegrityError.
    try:
        settings = await get_or_create_match_settings(db, project_uuid)
    except Exception as exc:
        logger.info(
            "match_service: project %s has no settings row (%s); using transient defaults",
            project_uuid,
            type(exc).__name__,
        )
        try:
            await db.rollback()
        except Exception:  # pragma: no cover — rollback may fail on closed session
            pass
        settings = SimpleNamespace(
            project_id=project_uuid,
            target_language="en",
            classifier="none",
            auto_link_threshold=0.85,
            auto_link_enabled=False,
            mode="manual",
            sources_enabled=["bim", "pdf", "dwg", "photo"],
        )

    # Attach project context for boosts that need the project (region etc.).
    # Hot path: under concurrent match load this used to issue one
    # ``ProjectRepository.get_by_id`` per request — a serialised SELECT
    # round-trip. Boosts only read ``settings.project.region`` so we
    # cache the region string with a 60s TTL and synthesise a tiny
    # ``project``-shaped object for the boost layer to consume.
    project_region: str | None = None
    try:
        from app.core.match_service.region_cache import region_for

        project_region = await region_for(db, project_uuid)
    except Exception:
        # Cache layer is best-effort — boosts that need a region simply
        # skip when it's unavailable.
        pass
    settings_with_project: Any = settings
    try:
        settings.project = SimpleNamespace(  # type: ignore[attr-defined]
            id=project_uuid,
            region=project_region,
        )
    except Exception:
        pass

    envelope = req.envelope

    # ── Catalogue binding (v2.8.2) ───────────────────────────────────
    # Match runs against ONE explicitly-selected CWICR catalogue. No
    # auto-pick from ``project.region`` — those are coarse tags
    # (DACH/EU/US) while catalogue ids are city-level (DE_BERLIN). When
    # ``cost_database_id`` is null we surface a structured error envelope
    # so the UI can render an explicit picker; the same applies when the
    # picked catalogue is empty or has no vectors yet.
    catalog_id: str | None = (
        getattr(settings, "cost_database_id", None) or None
    )
    catalog_status, catalog_count, catalog_vec = await _resolve_catalog_status(
        db, catalog_id,
    )
    if catalog_status != "ok":
        return MatchResponse(
            request=req,
            candidates=[],
            translation_used=None,
            auto_linked=None,
            took_ms=int((time.perf_counter() - started) * 1000),
            cost_usd=cost_usd,
            status=catalog_status,
            catalog_id=catalog_id,
            catalog_count=catalog_count,
            catalog_vectorized_count=catalog_vec,
        )

    # ── Translation (γ) ──────────────────────────────────────────────
    # Translate the envelope into the *catalogue's* dominant language.
    # The project's configured ``target_language`` is ignored on this
    # path — it would only matter if the project switches catalogues
    # mid-flow, in which case the new catalogue's language wins.
    target_language = _CATALOG_LANGUAGE.get(catalog_id or "", "en")
    translated_envelope, translation_used = await _maybe_translate(
        envelope, target_language, user_settings=ai_settings,
    )
    if translation_used and translation_used.cost_usd:
        cost_usd += float(translation_used.cost_usd or 0.0)

    # ── Vector search (α) ────────────────────────────────────────────
    query_text = build_query_text(translated_envelope)
    if not query_text:
        return MatchResponse(
            request=req,
            candidates=[],
            translation_used=translation_used,
            auto_linked=None,
            took_ms=int((time.perf_counter() - started) * 1000),
            cost_usd=cost_usd,
            status="ok",
            catalog_id=catalog_id,
            catalog_count=catalog_count,
            catalog_vectorized_count=catalog_vec,
        )

    fetch = max(req.top_k, req.top_k * SEARCH_OVERFETCH)
    try:
        # Region filter pins the search to the user's chosen catalogue.
        # Language filter is intentionally NOT passed: the LanceDB
        # collection only stores the catalogue's native language and
        # we already ensured ``catalog_id`` is loaded — passing
        # ``language`` would just risk filtering out valid hits when
        # the language-tag column is sparse on legacy fixtures.
        hits = await cost_vector.search(
            query_text,
            limit=fetch,
            region=catalog_id,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("match_service: vector search failed: %s", exc)
        hits = []

    # ── Boost stack (β) ──────────────────────────────────────────────
    candidates: list[MatchCandidate] = []
    for hit in hits:
        candidate = _hit_to_candidate(hit)
        deltas = apply_boosts(translated_envelope, candidate, settings_with_project)
        if deltas:
            candidate.boosts_applied = deltas
            adjusted = candidate.vector_score + sum(deltas.values())
            candidate.score = max(SCORE_FLOOR, min(SCORE_CEIL, adjusted))
        else:
            candidate.score = candidate.vector_score
        candidate.confidence_band = confidence_band_for(candidate.score)
        candidates.append(candidate)

    # Secondary sort key on ``code`` so ties are deterministic across
    # reruns. LanceDB doesn't guarantee stable order on score ties, so
    # without this auto-link could flip between equally-good candidates.
    # ``reverse=True`` on score, ascending lex on code (negate via
    # tuple form: lower code wins on tie).
    candidates.sort(key=lambda c: (-c.score, c.code))
    candidates = candidates[: req.top_k]

    # ── Reranker (ε) ─────────────────────────────────────────────────
    if req.use_reranker and candidates:
        try:
            from app.core.match_service.reranker_ai import rerank_top_k

            candidates, rerank_cost = await rerank_top_k(
                candidates, translated_envelope, ai_settings=ai_settings,
            )
            cost_usd += float(rerank_cost or 0.0)
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("match_service: rerank skipped: %s", exc)

    # ── Auto-link gate ───────────────────────────────────────────────
    auto_linked = None
    if (
        candidates
        and bool(getattr(settings, "auto_link_enabled", False))
        and candidates[0].score >= float(settings.auto_link_threshold or 1.0)
    ):
        auto_linked = candidates[0]

    return MatchResponse(
        request=req,
        candidates=candidates,
        translation_used=translation_used,
        auto_linked=auto_linked,
        took_ms=int((time.perf_counter() - started) * 1000),
        cost_usd=cost_usd,
        status="ok",
        catalog_id=catalog_id,
        catalog_count=catalog_count,
        catalog_vectorized_count=catalog_vec,
    )

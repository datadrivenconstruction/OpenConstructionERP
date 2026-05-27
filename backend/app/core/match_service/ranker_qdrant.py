# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Qdrant-backed ranker — replacement for the legacy LanceDB ranker.

Pipeline (no LLM by default, BGE-M3 multilingual covers cross-lang):

    1. Load ``MatchProjectSettings`` for the project.
    2. Resolve catalogue binding (which CWICR collection + parquet pair).
    3. Build a structured query via :func:`query_builder.build_query`:
       CORE text + native filters + optional resources_query.
    4. One-shot hybrid search through :func:`qdrant_adapter.search`
       (dense + sparse + resources fused via Qdrant native RRF).
    5. Attach 84-column parquet data via
       :func:`qdrant_adapter.lookup_full_rows`.
    6. Convert each hit → :class:`MatchCandidate`.
    7. Apply the **narrow** boost stack (classifier + unit + region only —
       lex and rare_token are dropped: sparse RRF in Qdrant subsumes them).
    8. Sort, slice to ``top_k``, set confidence band, derive auto-link.

The legacy :mod:`app.core.match_service.ranker` keeps working unchanged
during Phase 2-4 so we can A/B compare under live load. Phase 5 deletes
``ranker.py`` and renames this module into its place.

Translation cascade is intentionally OFF by default — BGE-M3 multilingual
covers most cross-lang recall and the cascade adds 50-200 ms p50. Flip
``MatchProjectSettings.translate_query=True`` per project to re-enable.
"""

from __future__ import annotations

import logging
import os
import re
import time
import uuid
from types import SimpleNamespace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.match_service.boosts import classifier as boost_classifier
from app.core.match_service.boosts import region as boost_region
from app.core.match_service.boosts import unit as boost_unit
from app.core.match_service.config import (
    SCORE_CEIL,
    SCORE_FLOOR,
    SEARCH_OVERFETCH,
    confidence_thresholds_for_model,
)
from app.core.match_service.envelope import (
    ConfidenceBand,
    ElementEnvelope,
    MatchCandidate,
    MatchRequest,
    MatchResponse,
    MatchStatus,
    confidence_band_for,
)
from app.core.match_service.region_language import language_for as _language_for_catalog
from app.core.translation import TranslationResult, translate
from app.modules.costs.qdrant_adapter import (
    QdrantHit,
    country_to_collection,
    lookup_full_rows,
    substitute_abstract_parents,
)
from app.modules.costs.qdrant_adapter import (
    search_by_filter as qdrant_search_by_filter,
)
from app.modules.costs.qdrant_adapter import (
    search_with_fallback as qdrant_search_with_fallback,
)
from app.modules.costs.query_builder import build_search_plan
from app.modules.projects.service import get_or_create_match_settings

logger = logging.getLogger(__name__)


# Narrow boost stack — see module docstring for the reasoning. Order
# follows "most explainable first" so the API response's
# ``boosts_applied`` dict is human-readable.
_BOOSTS = (
    boost_classifier.boost,
    boost_unit.boost,
    boost_region.boost,
)


def _active_encoder_id() -> str | None:
    """‌⁠‍Resolve the active encoder model id for confidence-band calibration.

    The encoder id keys ``data/match/encoder_profiles.json`` so a
    deployment that swapped to e5-small or the Sonnet rerank tier gets
    matching score bands without a code deploy. Returns ``None`` on any
    failure so :func:`confidence_thresholds_for_model` falls back to the
    canonical ``CONFIDENCE_*_THRESHOLD`` constants.
    """
    # Env var overrides the bound setting so operators can A/B without a
    # config push — matches the env-override pattern used everywhere
    # else in match_service/config.py.
    env_val = os.environ.get("MATCH_EMBEDDING_MODEL")
    if env_val:
        return str(env_val).split("/")[-1].lower()
    try:
        from app.config import get_settings

        s = get_settings()
        model = getattr(s, "cwicr_embedding_model", None) or getattr(
            s,
            "embedding_model_name",
            None,
        )
        if model:
            # encoder_profiles.json keys are short labels ("bge-m3",
            # "e5-small") while settings hold the full HuggingFace path
            # ("BAAI/bge-m3"). Normalise by stripping the org prefix and
            # lower-casing — keeps the profile file canonical.
            short = str(model).split("/")[-1].lower()
            return short
    except Exception:
        return None
    return None


def _dynamic_confidence_band(
    score: float,
    *,
    encoder_id: str | None = None,
    hard_filters_matched: int = 0,
    classification_confidence: str | None = None,
) -> ConfidenceBand:
    """‌⁠‍Confidence band keyed off per-encoder profile thresholds.

    Wraps :func:`confidence_band_for` so existing hard-filter / classification
    bonus logic stays in one place. When the encoder profile resolves
    cleanly we use its ``(high, medium)`` floors; otherwise fall back to
    the canonical constants the legacy helper consults.
    """
    try:
        high, medium, _ = confidence_thresholds_for_model(encoder_id)
    except Exception:
        return confidence_band_for(
            score,
            hard_filters_matched=hard_filters_matched,
            classification_confidence=classification_confidence,
        )

    # Apply the same v3 §6.4 derivation as the canonical helper, but
    # against the profile-derived floors.
    cls = (classification_confidence or "").strip().lower()
    cls_offset = -0.02 if cls == "high" else 0.03 if cls == "low" else 0.0

    high_floor = high + cls_offset
    medium_floor = medium + cls_offset

    # The bonus floors mirror envelope._HARD_FILTER_*_BONUS_FLOOR but
    # scaled relative to the profile defaults — operators retuning bands
    # for a different encoder shouldn't have to also retune the bonus
    # floors. 0.96× HIGH ≈ original 0.75/0.78 ratio for BGE-M3.
    if hard_filters_matched >= 3:
        high_floor = min(high_floor, (high * 0.96) + cls_offset)
    if hard_filters_matched >= 1:
        medium_floor = min(medium_floor, (medium * 0.97) + cls_offset)

    if score >= high_floor:
        return "high"
    if score >= medium_floor:
        return "medium"
    return "low"


# ── Catalogue resolution ─────────────────────────────────────────────────


# Short-TTL cache for ``_resolve_catalog_status`` keyed by catalog_id. The
# resolver does an SQL COUNT against ``oe_costs_item`` (which on the dev
# SQLite carries 100k+ rows without an index on ``region``) plus a Qdrant
# ``get_collection`` round-trip — each pair takes ~2–7 s. ``run_match``
# calls into the ranker once per group, so a 15-group match was paying
# this cost 15× even though the answer doesn't change across the 30 s the
# match itself takes. Cache invalidates after 30 s so a fresh
# ``alembic upgrade`` / catalogue install / vectorise still gets picked up
# without a backend restart.
_CATALOG_STATUS_CACHE_TTL_SEC: float = 30.0
_catalog_status_cache: dict[str | None, tuple[float, tuple[MatchStatus, int, int]]] = {}


async def _resolve_catalog_status(
    db: AsyncSession,
    catalog_id: str | None,
) -> tuple[MatchStatus, int, int]:
    """Resolve catalog → (status, sql_count, qdrant_vector_count).

    Mirrors the legacy ranker's status taxonomy so the UI's empty-state
    rendering doesn't need to change. The vector count comes from
    Qdrant collection info instead of the legacy LanceDB table.

    A failure to reach Qdrant (collection missing, embedded store
    uninitialised, server unreachable) collapses to
    ``"catalog_not_vectorized"`` so the UI surfaces a clear next step.
    """

    # Short-TTL process-local cache — see ``_CATALOG_STATUS_CACHE_TTL_SEC``.
    # Each ``run_match`` iterates groups and calls into ``rank`` per-group;
    # without this every group repeats the SQL COUNT + Qdrant probe even
    # though the catalogue state doesn't change between groups.
    now = time.perf_counter()
    cached = _catalog_status_cache.get(catalog_id)
    if cached is not None and now - cached[0] < _CATALOG_STATUS_CACHE_TTL_SEC:
        return cached[1]

    from sqlalchemy import func, select

    from app.modules.costs.models import CostItem

    if not catalog_id:
        try:
            total_loaded = (
                await db.execute(select(func.count(CostItem.id)).where(CostItem.is_active.is_(True)))
            ).scalar() or 0
        except Exception:
            total_loaded = 0
        result: tuple[MatchStatus, int, int] = (
            ("no_catalogs_loaded", 0, 0) if total_loaded == 0 else ("no_catalog_selected", 0, 0)
        )
        _catalog_status_cache[catalog_id] = (now, result)
        return result

    try:
        sql_count = (
            await db.execute(
                select(func.count(CostItem.id)).where(CostItem.is_active.is_(True)).where(CostItem.region == catalog_id)
            )
        ).scalar() or 0
    except Exception as exc:
        logger.warning("ranker_qdrant: catalog count failed for %s: %s", catalog_id, exc)
        sql_count = 0

    # SQL count is informational, not gating. Under v3 the canonical
    # source is Qdrant — the SQL ``oe_costs_item`` table only carries
    # rows when the operator imported a CWICR CSV/parquet, which is
    # optional once the v3 snapshot is loaded. The language-fallback
    # bindings minted by ``auto_bind`` Pass 1b (``US`` for English,
    # ``DE`` for German, etc.) intentionally have ``sql_count == 0``
    # while pointing at a populated CWICR collection. Probe Qdrant
    # first; only fall through to "no catalogue" when BOTH stores are
    # empty.
    vec_count = await _qdrant_vector_count(catalog_id)
    if vec_count > 0:
        result = ("ok", int(sql_count), int(vec_count))
        _catalog_status_cache[catalog_id] = (now, result)
        return result

    if sql_count == 0:
        try:
            total_loaded = (
                await db.execute(select(func.count(CostItem.id)).where(CostItem.is_active.is_(True)))
            ).scalar() or 0
        except Exception:
            total_loaded = 0
        result = ("no_catalogs_loaded", 0, 0) if total_loaded == 0 else ("no_catalog_selected", 0, 0)
        _catalog_status_cache[catalog_id] = (now, result)
        return result

    result = ("catalog_not_vectorized", int(sql_count), 0)
    _catalog_status_cache[catalog_id] = (now, result)
    return result


async def _qdrant_vector_count(catalog_id: str) -> int:
    """Return the number of points in the catalogue's Qdrant collection.

    Returns 0 (rather than raising) when Qdrant is unreachable so the
    catalogue resolver can collapse onto ``catalog_not_vectorized`` and
    the UI can render the right CTA.

    Falls back to the versionless name (``cwicr_ru``) when the configured
    versioned name (``cwicr_ru_v3``) is missing — covers dev installs
    that ingested before the v3 rename without forcing every operator
    to flip ``CWICR_COLLECTION_VERSION``.
    """

    try:
        from app.modules.costs.qdrant_adapter import _get_client

        client = _get_client()
        collection = country_to_collection(catalog_id)
        try:
            info = client.get_collection(collection)
        except Exception:
            # Strip the ``_v?`` suffix and try again. Same logic the
            # search adapter would benefit from — exposed via the
            # public helper below.
            base = collection.rsplit("_v", 1)[0] if "_v" in collection else collection
            if base != collection:
                info = client.get_collection(base)
            else:
                raise
        return int(getattr(info, "points_count", None) or getattr(info, "vectors_count", 0) or 0)
    except Exception as exc:
        logger.debug("ranker_qdrant: collection count for %s failed: %s", catalog_id, exc)
        return 0


# ── Translation step (optional, off by default) ──────────────────────────


async def _maybe_translate(
    envelope: ElementEnvelope,
    target_language: str,
    *,
    user_settings: Any = None,
    enabled: bool = False,
) -> tuple[ElementEnvelope, TranslationResult | None]:
    """Translate envelope into ``target_language`` only when explicitly enabled.

    BGE-M3 multilingual handles most cross-lang recall natively, so the
    cascade is opt-in per project. When ``enabled=False``, this helper
    is a no-op and saves the 50-200 ms a translation tier would cost.
    """

    if not enabled:
        return envelope, None
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
    if result.tier_used.value != "fallback" and result.translated:
        envelope = envelope.model_copy(update={"description": result.translated})
    return envelope, result


# ── Payload-derived fallbacks (snapshot-only installs) ───────────────────
#
# When the DDC v3 snapshot is the only source installed (no CWICR CSV /
# parquet sideload), the SQL ``oe_costs_item`` table is empty for the
# snapshot's region and ``lookup_full_rows`` returns nothing. The
# Qdrant payload alone has to drive description / currency on the
# candidate — otherwise the BGE cross-encoder collapses score to ≈ 0
# because the passage text is just an opaque rate_code, and the user
# sees blank descriptions plus a zero score even when the vector hit
# was semantically perfect.
#
# These helpers synthesise the missing fields from the snapshot's
# categorical metadata. ``unit_rate`` is INTENTIONALLY left at 0.0 when
# the parquet is missing — the operator's load-bearing number must
# never be fabricated.

_COUNTRY_DEFAULT_CURRENCY: dict[str, str] = {
    # North America
    "US": "USD",
    "USA": "USD",
    "CA": "CAD",
    "MX": "MXN",
    # Central & South America
    "BR": "BRL",
    "AR": "ARS",
    "CL": "CLP",
    "CO": "COP",
    "PE": "PEN",
    "UY": "UYU",
    "VE": "VES",
    "BO": "BOB",
    "PY": "PYG",
    "EC": "USD",
    "GT": "GTQ",
    "DO": "DOP",
    "CR": "CRC",
    "PA": "PAB",
    # Western & Northern Europe (Eurozone first, then non-EUR)
    "DE": "EUR",
    "FR": "EUR",
    "IT": "EUR",
    "ES": "EUR",
    "PT": "EUR",
    "NL": "EUR",
    "BE": "EUR",
    "AT": "EUR",
    "IE": "EUR",
    "FI": "EUR",
    "GR": "EUR",
    "LU": "EUR",
    "MT": "EUR",
    "CY": "EUR",
    "SK": "EUR",
    "SI": "EUR",
    "EE": "EUR",
    "LV": "EUR",
    "LT": "EUR",
    "GB": "GBP",
    "UK": "GBP",
    "CH": "CHF",
    "NO": "NOK",
    "SE": "SEK",
    "DK": "DKK",
    "IS": "ISK",
    "LI": "CHF",
    # Eastern Europe / CIS
    "PL": "PLN",
    "CZ": "CZK",
    "HU": "HUF",
    "RO": "RON",
    "BG": "BGN",
    "HR": "EUR",
    "RS": "RSD",
    "UA": "UAH",
    "RU": "RUB",
    "BY": "BYN",
    "MD": "MDL",
    "AL": "ALL",
    "MK": "MKD",
    "BA": "BAM",
    # Middle East & North Africa
    "AE": "AED",
    "SA": "SAR",
    "QA": "QAR",
    "KW": "KWD",
    "BH": "BHD",
    "OM": "OMR",
    "IL": "ILS",
    "TR": "TRY",
    "EG": "EGP",
    "MA": "MAD",
    "DZ": "DZD",
    "TN": "TND",
    "JO": "JOD",
    "LB": "LBP",
    "IR": "IRR",
    "IQ": "IQD",
    # Sub-Saharan Africa
    "ZA": "ZAR",
    "NG": "NGN",
    "KE": "KES",
    "GH": "GHS",
    "ET": "ETB",
    "TZ": "TZS",
    "UG": "UGX",
    "RW": "RWF",
    "CI": "XOF",
    "SN": "XOF",
    "CM": "XAF",
    "AO": "AOA",
    "MZ": "MZN",
    "ZM": "ZMW",
    "ZW": "ZWL",
    "BW": "BWP",
    "MU": "MUR",
    "NA": "NAD",
    # Asia-Pacific
    "CN": "CNY",
    "HK": "HKD",
    "TW": "TWD",
    "JP": "JPY",
    "KR": "KRW",
    "SG": "SGD",
    "MY": "MYR",
    "TH": "THB",
    "ID": "IDR",
    "PH": "PHP",
    "VN": "VND",
    "IN": "INR",
    "BD": "BDT",
    "PK": "PKR",
    "LK": "LKR",
    "NP": "NPR",
    "MN": "MNT",
    "KZ": "KZT",
    "UZ": "UZS",
    "AZ": "AZN",
    "GE": "GEL",
    "AM": "AMD",
    # Oceania
    "AU": "AUD",
    "NZ": "NZD",
    "FJ": "FJD",
    "PG": "PGK",
}


def _description_from_payload(payload: dict[str, Any]) -> str:
    """Synthesise a candidate description from snapshot categorical fields.

    Used as the fallback when neither the parquet row nor the Qdrant
    payload's ``description`` carry usable text. The DDC v3 snapshot
    indexes a handful of categorical columns
    (``collection_name`` / ``material_class`` / ``ifc_class`` /
    ``category_type`` / ``masterformat_division``) that, concatenated,
    read as a human-grade "what this rate is" line — good enough to
    surface in the candidate list AND for the BGE cross-encoder to
    score against.

    Empty / None inputs are skipped so a sparse payload doesn't produce
    em-dash spam. ``category_type`` is title-cased so an ALL-CAPS
    snapshot value (``"REPAIR AND CONSTRUCTION WORKS"``) reads as
    sentence case in the UI. ``masterformat_division`` is prefixed with
    its label so the human reader knows what the digits mean.

    Returns an empty string when no categorical field is populated.
    """
    parts: list[str] = []
    collection = (payload.get("collection_name") or "").strip()
    if collection:
        parts.append(collection)
    material = (payload.get("material_class") or "").strip()
    if material:
        parts.append(material)
    ifc_class = (payload.get("ifc_class") or "").strip()
    if ifc_class:
        parts.append(ifc_class)
    category_type = (payload.get("category_type") or "").strip()
    if category_type:
        parts.append(category_type.title())
    masterformat = (payload.get("masterformat_division") or "").strip()
    if masterformat:
        parts.append(f"MasterFormat {masterformat}")
    return " — ".join(parts)


# ── Hit → candidate ──────────────────────────────────────────────────────


def _hit_to_candidate(
    hit: QdrantHit,
    full_row: dict[str, Any] | None,
) -> MatchCandidate:
    """Map a Qdrant hit + parquet row → :class:`MatchCandidate`.

    Payload is intentionally minimal so we lean on the parquet row for
    description / unit / unit_cost / classification fields. The Qdrant
    score (RRF fused) is treated as the raw vector_score that the
    boost stack adjusts on top.

    Snapshot-only installs surface here with ``full_row=None`` — when
    that happens we synthesise description from the snapshot's
    categorical fields via :func:`_description_from_payload` and fill
    currency from the country head via :data:`_COUNTRY_DEFAULT_CURRENCY`.
    ``unit_rate`` STAYS 0.0 in that case — fabricating the operator's
    load-bearing number would be worse than surfacing an empty rate.
    """

    payload = hit.payload or {}
    full = full_row or {}

    # Classification: the parquet may carry several mappings. Also
    # surface ``masterformat_division`` from the Qdrant payload — the
    # v3 snapshot indexes that field directly and it's the only
    # classification a snapshot-only install can provide.
    classification: dict[str, str] = {}
    for cls_key, parquet_key in (
        ("din276", "classification_din276"),
        ("nrm", "classification_nrm"),
        ("masterformat", "classification_masterformat"),
    ):
        v = full.get(parquet_key) or payload.get(parquet_key)
        if v:
            classification[cls_key] = str(v)
    # Snapshot-only fallback for masterformat from the indexed payload.
    if "masterformat" not in classification:
        mf = payload.get("masterformat_division")
        if mf:
            classification["masterformat"] = str(mf)

    raw_score = float(hit.score)
    rate_code = hit.rate_code

    # Description / unit / cost prefer the parquet (richer) and fall
    # back to whatever the Qdrant payload happened to carry. When both
    # are missing, synthesise from the snapshot's categorical fields so
    # the BGE cross-encoder has SOMETHING to score against and the UI
    # surfaces a human-readable line instead of just an opaque code.
    description = str(full.get("description") or payload.get("description") or "")
    if not description:
        description = _description_from_payload(payload)
    unit = str(full.get("rate_unit") or payload.get("rate_unit") or "")
    unit_rate = float(
        full.get("total_cost_per_position") or full.get("unit_cost") or payload.get("unit_cost", 0.0) or 0.0
    )
    currency = str(full.get("currency") or payload.get("currency") or "")
    region_code = str(full.get("country") or payload.get("country") or hit.country)
    # Snapshot-only fallback: derive currency from the country head when
    # neither parquet nor payload provided it. Unknown country codes
    # leave currency empty so the UI can flag the gap rather than
    # surfacing a wrong default.
    if not currency and region_code:
        currency = _COUNTRY_DEFAULT_CURRENCY.get(region_code.strip().upper(), "")

    return MatchCandidate(
        id=rate_code or None,
        code=rate_code,
        description=description,
        unit=unit,
        unit_rate=unit_rate,
        currency=currency,
        score=raw_score,
        vector_score=raw_score,
        boosts_applied={},
        confidence_band=_dynamic_confidence_band(
            raw_score,
            encoder_id=_active_encoder_id(),
        ),
        region_code=region_code,
        source=str(payload.get("source") or "cwicr"),
        language=str(full.get("language") or payload.get("language") or ""),
        classification=classification,
    )


def _apply_narrow_boosts(
    envelope: ElementEnvelope,
    candidate: MatchCandidate,
    settings: Any,
) -> dict[str, float]:
    """Run the narrow Qdrant-era boost stack — classifier + unit + region.

    rare_token and lex_* boosts are intentionally NOT called: the
    sparse channel in the Qdrant RRF fusion already accounts for
    verbatim term hits, so layering rare_token on top double-counts and
    inflates ties.
    """

    out: dict[str, float] = {}
    for fn in _BOOSTS:
        try:
            delta = fn(envelope, candidate, settings)
        except Exception:
            continue
        if delta:
            out.update(delta)
    return out


def _apply_soft_boosts(
    hit: QdrantHit,
    full_row: dict[str, Any] | None,
    soft_boosts: list[tuple[str, Any, float]],
) -> tuple[float, dict[str, float]]:
    """Apply v3 SearchPlan soft boosts to one candidate's RRF score.

    Per MAPPING_PROCESS.md §4.6, soft boosts are multiplicative on the
    RRF score: when ``hit.payload[field] == value`` the score gets
    multiplied by the boost factor. The full parquet row is consulted
    as a fallback because the Qdrant payload is intentionally minimal
    in v3 (only filter columns) — fields like ``ost_category`` or
    ``material_class`` may live only in the parquet.

    Returns the adjusted score and a per-boost breakdown for the UI's
    explainability panel (``MatchCandidate.boosts_applied``). The
    breakdown is the *delta* (boost-1) so the dashboard can render
    "ost_category +50%" rather than "1.5".
    """

    if not soft_boosts:
        return float(hit.score), {}

    payload = hit.payload or {}
    full = full_row or {}

    score = float(hit.score)
    deltas: dict[str, float] = {}
    for field_key, expected, boost in soft_boosts:
        actual = payload.get(field_key)
        if actual is None:
            actual = full.get(field_key)
        if actual is None:
            continue
        # Numeric soft boosts (e.g. nominal_size_mm) tolerate ±10%
        # on either side so a 220mm-wall rate still picks up the
        # 200mm boost. String boosts are exact-match.
        matched = False
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            if expected and abs(actual - expected) / max(expected, 1) <= 0.10:
                matched = True
        elif str(actual) == str(expected):
            matched = True
        if matched:
            score *= boost
            deltas[f"soft_{field_key}"] = float(boost) - 1.0
    return score, deltas


# ── Encoder-free metadata scorer ─────────────────────────────────────────
#
# When the encoder is offline (broken HF cache, [semantic] extra missing,
# slow first cold download), the dense+sparse fusion path returns nothing
# and the user sees a blank result. The function below produces a
# deterministic ranking from payload signals alone so the matcher still
# returns plausible candidates, just with lower confidence.
#
# Score is a weighted sum of four components in [0, 1]:
#
#   * lexical (0.45): Jaccard overlap on tokenised text — element
#     description/material/type vs catalogue collection_name/category_type.
#     Generic IFC stems (Ifc, Wall, Door, Slab) are excluded so common
#     IFC noise doesn't dominate.
#   * unit_dim (0.25): matching coarse unit family (volume/area/length/
#     mass/count/time). Hard signal — a wall (m³) shouldn't compete
#     with flooring (m²) for top slots.
#   * region (0.15): catalogue ``country`` payload matches the project
#     region two-letter prefix.
#   * material (0.15): catalogue ``material_class`` overlaps element
#     material token (concrete ↔ ReinforcedConcrete, brick ↔ Brick).
#
# The weights are deliberately modest so a perfect metadata match
# scores around 1.0 but never gets auto-confirmed without human review.
# A future vector run on the same envelope will overwrite the score.

_GENERIC_TOKEN_STOP = frozenset(
    {
        "ifc",
        "wall",
        "door",
        "window",
        "slab",
        "beam",
        "column",
        "stair",
        "space",
        "covering",
        "pipe",
        "duct",
        "fitting",
        "element",
        "type",
        "standard",
        "case",
        "and",
        "or",
        "of",
        "the",
        "a",
        "an",
        "with",
        "is",
        "as",
        "for",
    }
)


def _tokenise(text: str | None) -> set[str]:
    if not text:
        return set()
    raw = re.sub(r"[^\w]+", " ", str(text).lower())
    return {t for t in raw.split() if len(t) >= 2 and t not in _GENERIC_TOKEN_STOP}


def _unit_family(unit: str | None) -> str | None:
    if not unit:
        return None
    u = str(unit).strip().lower()
    if u in {"m3", "m³", "cy", "cbm", "cum"}:
        return "volume"
    if u in {"m2", "m²", "sm", "sf", "sqm", "sqft"}:
        return "area"
    if u in {"m", "lm", "lf", "lfm", "rm"}:
        return "length"
    if u in {"kg", "t", "ton", "tonne", "tn"}:
        return "mass"
    if u in {"pcs", "ea", "stk", "nr", "no", "u", "stck"}:
        return "count"
    if u in {"h", "hr", "hour"}:
        return "time"
    return None


def _score_payload_against_envelope(
    payload: dict[str, Any],
    *,
    envelope: ElementEnvelope,
    project_region: str | None,
) -> tuple[float, dict[str, float]]:
    """Score a catalogue payload against the envelope without a vector.

    Returns ``(score, breakdown)`` so the caller can surface why a row
    ranked where it did. Score is normalised to [0, 1].
    """

    env_text_parts = [
        envelope.description or "",
        envelope.category or "",
        getattr(envelope, "ost_category", "") or "",
        " ".join(str(v) for v in (envelope.properties or {}).values()),
    ]
    env_tokens = _tokenise(" ".join(env_text_parts))

    pay_text = " ".join(
        str(payload.get(k) or "") for k in ("collection_name", "category_type", "ost_category", "material_class")
    )
    pay_tokens = _tokenise(pay_text)

    if env_tokens and pay_tokens:
        intersection = env_tokens & pay_tokens
        union = env_tokens | pay_tokens
        lexical = len(intersection) / len(union) if union else 0.0
    else:
        lexical = 0.0

    env_unit_family = _unit_family(envelope.unit_hint)
    pay_unit_family = (payload.get("unit_type") or "").strip().lower() or None
    if pay_unit_family is None:
        pay_unit_family = _unit_family(payload.get("rate_unit"))
    unit_score = 1.0 if (env_unit_family and pay_unit_family and env_unit_family == pay_unit_family) else 0.0

    region_score = 0.0
    if project_region:
        pay_country = str(payload.get("country") or "").upper()
        proj_head = project_region.upper()[:2]
        if pay_country and pay_country.startswith(proj_head):
            region_score = 1.0

    env_material = (envelope.properties or {}).get("material") if envelope.properties else None
    material_score = 0.0
    if env_material:
        env_mat_tokens = _tokenise(str(env_material))
        pay_mat_tokens = _tokenise(payload.get("material_class"))
        if env_mat_tokens and pay_mat_tokens and (env_mat_tokens & pay_mat_tokens):
            material_score = 1.0

    score = 0.45 * lexical + 0.25 * unit_score + 0.15 * region_score + 0.15 * material_score

    return score, {
        "lexical": round(lexical, 3),
        "unit": round(unit_score, 3),
        "region": round(region_score, 3),
        "material": round(material_score, 3),
    }


async def _metadata_only_candidates(
    *,
    envelope: ElementEnvelope,
    catalog_id: str | None,
    hard_filters: dict[str, Any],
    project_region: str | None,
    top_k: int,
    fetch: int,
) -> list[QdrantHit]:
    """Encoder-free candidate fetch + score.

    Pulls up to ``fetch`` rows from Qdrant by hard filter (IFC class +
    is_abstract=False is the bedrock), then scores each by metadata
    signals. Falls back to no-filter scroll if the strict filter set
    under-returns — this catches the case where the catalogue's
    ``ifc_class`` payload has gaps. Returns top-``top_k`` hits sorted by
    metadata score descending.
    """

    if not catalog_id:
        return []

    # Strict filter first, then relax to bedrock if it under-returns.
    relax_ladder: list[dict[str, Any]] = [
        hard_filters,
        {k: v for k, v in hard_filters.items() if k in {"ifc_class", "ost_category", "is_abstract"}},
        {"is_abstract": False},
    ]
    seen_codes: set[str] = set()
    raw_hits: list[QdrantHit] = []
    for f in relax_ladder:
        try:
            tier_hits = await qdrant_search_by_filter(
                country=catalog_id,
                filters=f,
                limit=fetch,
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("metadata fallback: scroll tier failed: %s", exc)
            tier_hits = []
        for h in tier_hits:
            if h.rate_code in seen_codes:
                continue
            seen_codes.add(h.rate_code)
            raw_hits.append(h)
        if len(raw_hits) >= fetch:
            break

    if not raw_hits:
        return []

    scored: list[tuple[float, dict[str, float], QdrantHit]] = []
    for h in raw_hits:
        score, breakdown = _score_payload_against_envelope(
            h.payload or {},
            envelope=envelope,
            project_region=project_region,
        )
        scored.append((score, breakdown, h))

    # Deterministic tie-break on rate_code (see determinism.py): the
    # metadata-only score quantises to coarse bands (0.0 / 0.225 / 0.45
    # / 0.675 / 0.9 with the default weights) so equal-score ties are
    # the norm, not the exception. Pin them by lex order.
    scored.sort(key=lambda t: (-t[0], t[2].rate_code))
    out: list[QdrantHit] = []
    for score, breakdown, h in scored[:top_k]:
        # Annotate payload so downstream UI/log can show why this ranked.
        new_payload = dict(h.payload or {})
        new_payload["_match_breakdown"] = breakdown
        new_payload["_match_method"] = "metadata"
        out.append(
            QdrantHit(
                rate_code=h.rate_code,
                country=h.country,
                score=score,
                payload=new_payload,
            )
        )
    return out


# ── Core entrypoint ──────────────────────────────────────────────────────


async def rank(
    req: MatchRequest,
    *,
    db: AsyncSession,
    ai_settings: Any = None,
) -> MatchResponse:
    """Run the full Qdrant-backed match pipeline. Never raises for normal input.

    Drop-in alternative to :func:`app.core.match_service.ranker.rank` —
    same request and response shapes, different vector backend.
    """

    started = time.perf_counter()
    cost_usd = 0.0

    project_uuid: uuid.UUID = (
        req.project_id if isinstance(req.project_id, uuid.UUID) else uuid.UUID(str(req.project_id))
    )
    try:
        settings = await get_or_create_match_settings(db, project_uuid)
    except Exception as exc:
        logger.info(
            "ranker_qdrant: project %s has no settings row (%s); using transient defaults",
            project_uuid,
            type(exc).__name__,
        )
        try:
            await db.rollback()
        except Exception:
            pass
        # Pull defaults from the canonical constants — env-overridable
        # via MATCH_DEFAULT_TARGET_LANGUAGE / MATCH_DEFAULT_AUTO_LINK_THRESHOLD.
        # Without this hop a non-English deployment whose project's
        # settings row was missing would fall back to English-only
        # ranking and a 0.85 auto-link cutoff regardless of the
        # tenant's calibration.
        from app.modules.projects.models import (  # noqa: PLC0415
            MATCH_DEFAULT_AUTO_LINK_ENABLED,
            MATCH_DEFAULT_AUTO_LINK_THRESHOLD,
            MATCH_DEFAULT_CLASSIFIER,
            MATCH_DEFAULT_MODE,
            MATCH_DEFAULT_SOURCES,
            MATCH_DEFAULT_TARGET_LANGUAGE,
        )

        settings = SimpleNamespace(
            project_id=project_uuid,
            target_language=MATCH_DEFAULT_TARGET_LANGUAGE,
            classifier=MATCH_DEFAULT_CLASSIFIER,
            auto_link_threshold=MATCH_DEFAULT_AUTO_LINK_THRESHOLD,
            auto_link_enabled=MATCH_DEFAULT_AUTO_LINK_ENABLED,
            mode=MATCH_DEFAULT_MODE,
            sources_enabled=list(MATCH_DEFAULT_SOURCES),
            translate_query=False,
        )

    # Project context for boosts (region etc.).
    project_region: str | None = None
    try:
        from app.core.match_service.region_cache import region_for

        project_region = await region_for(db, project_uuid)
    except Exception:
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

    # ── Catalogue binding ────────────────────────────────────────────
    catalog_id: str | None = getattr(settings, "cost_database_id", None) or None
    catalog_status, catalog_count, catalog_vec = await _resolve_catalog_status(db, catalog_id)
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

    # ── exact_code short-circuit (MAPPING_PROCESS.md §4.1.5) ─────────
    # When the upstream extractor populated ``envelope.exact_code``
    # (today: BoQ row with an explicit ``Code`` column, tomorrow: any
    # source that knows the rate verbatim) we bypass the Qdrant fan-out
    # entirely and pull the rate from parquet. Saves ~25-50 ms + the
    # full reranker stack and guarantees the operator-supplied code
    # wins over whatever the encoder thinks is "close enough".
    #
    # When the code isn't in the bound catalogue (stale code, wrong
    # catalogue, typo), the helper returns None and we fall through to
    # the normal vector path — degrade, never fail.
    if envelope.exact_code:
        short_resp = await _try_exact_code_short_circuit(
            envelope=envelope,
            req=req,
            catalog_id=catalog_id,
            catalog_count=catalog_count,
            catalog_vec=catalog_vec,
            cost_usd=cost_usd,
            started=started,
        )
        if short_resp is not None:
            return short_resp
        logger.warning(
            "ranker_qdrant: exact_code %r not in catalogue %r — falling back to vector search",
            envelope.exact_code,
            catalog_id,
        )

    # ── Translation (optional) ───────────────────────────────────────
    target_language = _language_for_catalog(catalog_id)
    translate_enabled = bool(getattr(settings, "translate_query", False))
    translated_envelope, translation_used = await _maybe_translate(
        envelope,
        target_language,
        user_settings=ai_settings,
        enabled=translate_enabled,
    )
    if translation_used and translation_used.cost_usd:
        cost_usd += float(translation_used.cost_usd or 0.0)

    # ── Build structured v3 SearchPlan ───────────────────────────────
    # ``catalog_id`` lets the planner suppress hard filters the bound
    # CWICR collection doesn't actually carry (e.g. ``ifc_class`` on the
    # DDC v3 snapshots) instead of pinning a field that would zero out
    # the result set at every relax tier.
    plan = build_search_plan(translated_envelope, catalog_id=catalog_id)
    if not plan.dense_query:
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

    # ── Vector search (hardened: relax-tier fallback + abstract sub) ─
    # ``search_with_fallback`` walks the §5.2 relax ladder if the full
    # hard-filter set under-returns. ``tier_used`` is logged so the
    # planned v3-P10 ``match_search_log`` can correlate filter-set
    # tightness with downstream confirmation rate.
    tier_used = 0
    try:
        hits, tier_used = await qdrant_search_with_fallback(
            country=catalog_id,
            limit=fetch,
            **plan.search_kwargs,
        )
        if hits:
            hits = await substitute_abstract_parents(
                country=catalog_id,
                core_query=plan.search_kwargs["core_query"],
                hits=hits,
            )
        if tier_used > 0:
            logger.debug(
                "ranker_qdrant: search fell back to relax tier %d (%d hits)",
                tier_used,
                len(hits),
            )
    except RuntimeError as exc:
        # Encoder offline ([semantic] extra missing, broken HF cache,
        # Qdrant unreachable). Don't blank the result — fall through to
        # an encoder-free metadata path so the user still gets a ranked
        # candidate list from payload signals (IFC class filter +
        # lexical + region + unit + material). Confidence will be lower
        # than the hybrid path but ordering is meaningful.
        logger.warning("ranker_qdrant: search degraded (%s) — using metadata fallback", exc)
        try:
            hits = await _metadata_only_candidates(
                envelope=translated_envelope,
                catalog_id=catalog_id,
                hard_filters=plan.hard_filters,
                project_region=project_region,
                top_k=req.top_k,
                fetch=max(fetch, 50),
            )
        except Exception as fallback_exc:  # pragma: no cover — defensive
            logger.warning(
                "ranker_qdrant: metadata fallback also failed (%s)",
                fallback_exc,
            )
            hits = []
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("ranker_qdrant: vector search failed: %s", exc)
        hits = []

    # Encoder ran but came back empty (e.g. dense returned nothing
    # because the element description is too sparse, or the relax
    # ladder exhausted without a hit). Try the metadata path once more
    # so the user gets *some* ranked output rather than a blank page.
    if not hits:
        try:
            fallback_hits = await _metadata_only_candidates(
                envelope=translated_envelope,
                catalog_id=catalog_id,
                hard_filters=plan.hard_filters,
                project_region=project_region,
                top_k=req.top_k,
                fetch=max(fetch, 50),
            )
            if fallback_hits:
                logger.info(
                    "ranker_qdrant: vector miss — metadata fallback returned %d hits",
                    len(fallback_hits),
                )
                hits = fallback_hits
        except Exception as fb_exc:  # pragma: no cover — defensive
            logger.debug("ranker_qdrant: metadata fallback skipped: %s", fb_exc)

    # ── Attach 84-column parquet data ────────────────────────────────
    full_rows: dict[str, dict[str, Any]] = {}
    if hits:
        try:
            rows = await lookup_full_rows(
                country=catalog_id,
                rate_codes=[h.rate_code for h in hits],
            )
            full_rows = {str(r.get("rate_code")): r for r in rows}
        except Exception as exc:  # pragma: no cover — parquet missing is OK
            logger.debug("ranker_qdrant: parquet lookup failed (%s); using payload only", exc)

    # ── Magnet-candidate suppressor (opt-in, env-gated) ───────────────
    # v3 payload-only snapshots breed a small set of "magnet" candidates
    # the cross-encoder is drawn to regardless of query topic. Drop /
    # penalise them here so the BGE rerank below sees a cleaner pool.
    # Off by default (``OE_MATCH_MAGNET_FILTER=1`` to enable). Touching
    # only the tail of the post-Qdrant code path keeps the parallel
    # snapshot-enrichment agent's edits orthogonal to this hook.
    if hits:
        try:
            from app.core.match_service.boosts import magnet_filter

            hits = magnet_filter.apply_to_hits(
                translated_envelope,
                hits,
                full_rows=full_rows,
                query_id=str(getattr(req, "request_id", None) or project_uuid),
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("ranker_qdrant: magnet_filter skipped: %s", exc)

    # ── Apply v3 soft boosts BEFORE the candidate cast ───────────────
    # The soft boosts are multiplicative on the raw RRF score (per
    # §4.6) so we tweak ``hit.score`` first, then let
    # ``_hit_to_candidate`` carry the boosted value into ``vector_score``.
    # ``_apply_narrow_boosts`` runs on top with additive deltas — the
    # two stacks are intentionally orthogonal: soft boosts say "this
    # rate matches the source's structural classifier", narrow boosts
    # say "this rate matches the unit / region / DIN trade".
    soft_deltas_by_code: dict[str, dict[str, float]] = {}
    for hit in hits:
        adjusted, soft_deltas = _apply_soft_boosts(
            hit,
            full_rows.get(hit.rate_code),
            plan.soft_boosts,
        )
        hit.score = adjusted
        if soft_deltas:
            soft_deltas_by_code[hit.rate_code] = soft_deltas

    # ── Convert + narrow boost stack ─────────────────────────────────
    candidates: list[MatchCandidate] = []
    for hit in hits:
        candidate = _hit_to_candidate(hit, full_rows.get(hit.rate_code))
        soft_deltas = soft_deltas_by_code.get(hit.rate_code, {})
        narrow_deltas = _apply_narrow_boosts(
            translated_envelope,
            candidate,
            settings_with_project,
        )
        merged_deltas: dict[str, float] = {**soft_deltas, **narrow_deltas}
        if merged_deltas:
            candidate.boosts_applied = merged_deltas
            adjusted = candidate.vector_score + sum(narrow_deltas.values())
            candidate.score = max(SCORE_FLOOR, min(SCORE_CEIL, adjusted))
        else:
            candidate.score = candidate.vector_score
        # v3-P9 §6.4: derive confidence with hard-filter density and
        # the candidate's classification_confidence stamp. Encoder-aware
        # band floors come from data/match/encoder_profiles.json so a
        # cutover from BGE-M3 to a different encoder doesn't silently
        # mis-classify candidates.
        hard_filter_count = len(plan.hard_filters)
        candidate.confidence_band = _dynamic_confidence_band(
            candidate.score,
            encoder_id=_active_encoder_id(),
            hard_filters_matched=hard_filter_count,
            classification_confidence=(
                full_rows.get(hit.rate_code, {}).get("classification_confidence")
                or hit.payload.get("classification_confidence")
            ),
        )
        candidates.append(candidate)

    # Deterministic tie-break on rate_code.
    candidates.sort(key=lambda c: (-c.score, c.code))
    candidates = candidates[: req.top_k]

    # ── v3-P9: local BGE cross-encoder rerank (free, fast, optional) ─
    # Default-on when ``[semantic]`` extra is installed. Gracefully no-op
    # when the model isn't available, so the same code path runs whether
    # or not the operator has provisioned the reranker.
    if candidates and bool(getattr(settings, "match_use_bge_reranker", True)):
        try:
            from app.core.match_service.reranker_bge import rerank as bge_rerank

            classification_confidence_by_code: dict[str, str] = {}
            for c in candidates:
                row = full_rows.get(c.code) or {}
                cc = row.get("classification_confidence")
                if cc:
                    classification_confidence_by_code[c.code] = str(cc)
            candidates = bge_rerank(
                candidates,
                translated_envelope,
                hard_filters_matched=len(plan.hard_filters),
                classification_confidence_by_code=classification_confidence_by_code,
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("ranker_qdrant: BGE rerank skipped: %s", exc)

    # ── Optional LLM reranker (cost-gated, opt-in per request) ────────
    if req.use_reranker and candidates:
        try:
            from app.core.match_service.reranker_ai import rerank_top_k

            candidates, rerank_cost = await rerank_top_k(
                candidates,
                translated_envelope,
                ai_settings=ai_settings,
            )
            cost_usd += float(rerank_cost or 0.0)
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("ranker_qdrant: rerank skipped: %s", exc)

    # ── Auto-link gate ───────────────────────────────────────────────
    auto_linked: MatchCandidate | None = None
    if (
        candidates
        and bool(getattr(settings, "auto_link_enabled", False))
        and candidates[0].score >= float(settings.auto_link_threshold or 1.0)
    ):
        auto_linked = candidates[0]

    took_ms = int((time.perf_counter() - started) * 1000)

    # ── v3-P10: write the analytics row (best-effort, never raises) ──
    # Logging failures must not break the match request — wrap in
    # try/except. The session is committed inside the helper so the
    # caller's session lifecycle is unaffected.
    try:
        await _write_search_log(
            project_id=req.project_id,
            catalog_id=catalog_id,
            collection_name=country_to_collection(catalog_id),
            plan=plan,
            candidates=candidates,
            tier_used=tier_used,
            took_ms=took_ms,
            status="ok",
            bge_used=bool(candidates and getattr(settings, "match_use_bge_reranker", True)),
            llm_used=bool(req.use_reranker and candidates),
            envelope=envelope,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("ranker_qdrant: search log skipped: %s", exc)

    return MatchResponse(
        request=req,
        candidates=candidates,
        translation_used=translation_used,
        auto_linked=auto_linked,
        took_ms=took_ms,
        cost_usd=cost_usd,
        status="ok",
        catalog_id=catalog_id,
        catalog_count=catalog_count,
        catalog_vectorized_count=catalog_vec,
    )


async def _write_search_log(
    *,
    project_id: Any,
    catalog_id: str,
    collection_name: str,
    plan: Any,
    candidates: list[MatchCandidate],
    tier_used: int,
    took_ms: int,
    status: str,
    bge_used: bool,
    llm_used: bool,
    envelope: ElementEnvelope | None = None,
    session_id: Any | None = None,
    group_id: Any | None = None,
) -> None:
    """Best-effort INSERT into ``oe_match_elements_search_log``.

    Uses an independent SQLAlchemy session so failures here can't
    poison the caller's transaction. Truncates ``core_query`` to the
    column's max length defensively (the model declares 2000 chars but
    SearchPlan can produce longer strings for noisy envelopes).

    ``plan`` may be ``None`` for paths that bypass the SearchPlan (e.g.,
    the §4.1.5 exact_code short-circuit) — in that case ``core_query``,
    ``hard_filters`` and ``soft_boosts`` collapse to empty defaults so
    the log row still INSERTs cleanly.

    v2936 additions:
        * ``envelope``    — when supplied, ``source_type`` / ``ifc_class``
                            land as top-level columns so analytics can
                            filter without a 3-table JOIN.
        * ``catalog_id`` head (e.g. ``"DE"`` for ``"DE_BERLIN"``) lands
                            in the new ``country`` column for the same
                            reason.
        * ``metadata.candidate_codes`` carries the top-N rate_codes so
                            ``MatchService.confirm()`` can later derive
                            ``picked_rank`` without a re-search — the
                            candidates fall out of memory after the
                            response is returned to the user.
    """

    from app.database import async_session_factory
    from app.modules.costs.qdrant_adapter import country_filter_for
    from app.modules.match_elements.models import MatchSearchLog

    top = candidates[0] if candidates else None
    core_query = ""
    hard_filters: dict[str, Any] = {}
    soft_boosts: list[dict[str, Any]] = []
    if plan is not None:
        core_query = (getattr(plan, "dense_query", "") or "")[:2000]
        hard_filters = dict(getattr(plan, "hard_filters", None) or {})
        soft_boosts = [{"key": k, "value": v, "weight": w} for k, v, w in (getattr(plan, "soft_boosts", None) or [])]

    # Envelope-derived analytics columns. Source/IFC are read-only on
    # the envelope; country is the region head pinned for the search
    # so MX_MEXICO and ES_MADRID land as ``MX`` and ``ES`` respectively
    # (the v3 ES collection mixes regions, see qdrant_adapter docstring).
    source_type: str | None = None
    ifc_class: str | None = None
    if envelope is not None:
        source_type = getattr(envelope, "source", "") or None
        ifc_class = getattr(envelope, "ifc_class", "") or None
    country = country_filter_for(catalog_id) or (catalog_id.split("_", 1)[0] if catalog_id else None)

    # Carry the top-N rate_codes through to the log row so ``confirm``
    # can compute picked_rank without another search. Truncate to the
    # candidate cap + cast for JSON safety.
    candidate_codes = [str(c.code) for c in candidates[:50] if c.code]
    metadata: dict[str, Any] = {"candidate_codes": candidate_codes}

    async with async_session_factory() as session:
        log_row = MatchSearchLog(
            project_id=project_id,
            session_id=session_id,
            group_id=group_id,
            catalog_id=catalog_id or None,
            collection_name=collection_name or None,
            core_query=core_query or None,
            hard_filters=hard_filters,
            soft_boosts=soft_boosts,
            hits_count=len(candidates),
            relax_tier_used=int(tier_used or 0),
            top_score=float(top.score) if top else None,
            top_confidence_band=top.confidence_band if top else None,
            bge_rerank_used=bge_used,
            llm_rerank_used=llm_used,
            took_ms=int(took_ms),
            status=status,
            source_type=source_type,
            ifc_class=ifc_class,
            country=country,
            metadata_=metadata,
        )
        session.add(log_row)
        await session.commit()


# ─────────────────────────────────────────────────────────────────────
#  exact_code short-circuit (MAPPING_PROCESS.md §4.1.5)
# ─────────────────────────────────────────────────────────────────────


# Sentinel for ``relax_tier_used`` on the search log — distinguishes
# the §4.1.5 short-circuit from tier 0 (full filter set, no relaxation
# needed) without needing a separate column. Negative values are
# reserved for non-tier paths in the analytics query.
_EXACT_CODE_TIER_SENTINEL: int = -1


def _build_exact_candidate(
    *,
    rate_code: str,
    row: dict[str, Any],
    catalog_id: str | None,
) -> MatchCandidate:
    """Materialise a high-confidence MatchCandidate from a single parquet row.

    Used by :func:`_try_exact_code_short_circuit`. Score is pinned at
    1.0 and confidence at HIGH because the source supplied a verbatim
    rate code — there is nothing to rank against. ``boosts_applied``
    is stamped with ``exact_code`` so the audit trail and the UI can
    surface "matched by source-supplied code, not by similarity".
    """

    description = row.get("rate_original_name") or row.get("rate_final_name") or row.get("description") or ""
    unit = row.get("rate_unit") or row.get("unit") or ""
    raw_rate = row.get("rate_total") or row.get("unit_rate") or row.get("rate") or 0.0
    try:
        unit_rate = float(raw_rate)
    except (TypeError, ValueError):
        unit_rate = 0.0
    currency = row.get("currency") or row.get("rate_currency") or row.get("ccy") or ""
    region = row.get("country") or row.get("region") or catalog_id or ""

    classification: dict[str, str] = {}
    for key in ("classification_din276", "classification_masterformat", "classification_nrm"):
        v = row.get(key)
        if v:
            classification[key.removeprefix("classification_")] = str(v)

    return MatchCandidate(
        id=None,
        code=rate_code,
        description=str(description),
        unit=str(unit),
        unit_rate=unit_rate,
        currency=str(currency),
        score=1.0,
        vector_score=1.0,
        boosts_applied={"exact_code": 1.0},
        confidence_band="high",
        reasoning=("Direct match by rate_code from source (e.g., BoQ Code column)."),
        region_code=str(region),
        source="exact_code",
        language=str(row.get("language") or ""),
        classification=classification,
    )


async def _try_exact_code_short_circuit(
    *,
    envelope: ElementEnvelope,
    req: MatchRequest,
    catalog_id: str | None,
    catalog_count: int,
    catalog_vec: int,
    cost_usd: float,
    started: float,
) -> MatchResponse | None:
    """Bypass Qdrant when the source carries an explicit rate_code.

    Returns a fully-formed :class:`MatchResponse` with one HIGH-band
    candidate when the code is found in ``catalog_id``'s parquet.
    Returns ``None`` when:

    * ``envelope.exact_code`` is empty (caller is responsible for
      checking, but we double-check defensively),
    * ``catalog_id`` isn't bound (no parquet to query),
    * ``lookup_full_rows`` doesn't return a matching row (stale code,
      wrong catalogue, typo) — the caller falls through to the normal
      vector path which still has a chance to surface the right rate.

    Auto-link policy: an exact-code hit is unconditionally auto-linked
    when ``settings.auto_link_enabled`` is on, regardless of the
    threshold — the source declared the answer, no policy override
    needed.
    """

    code = (envelope.exact_code or "").strip()
    if not code or not catalog_id:
        return None

    try:
        rows = await lookup_full_rows(country=catalog_id, rate_codes=[code])
    except Exception as exc:  # pragma: no cover — parquet missing is OK
        logger.debug(
            "ranker_qdrant: exact_code parquet lookup failed for %r: %s",
            code,
            exc,
        )
        return None

    if not rows:
        return None

    # Prefer the row whose rate_code matches verbatim (parquet may
    # return adjacent rows on ambiguous filter), fall back to first.
    matching = next(
        (r for r in rows if str(r.get("rate_code") or "").strip() == code),
        rows[0],
    )

    candidate = _build_exact_candidate(
        rate_code=code,
        row=matching,
        catalog_id=catalog_id,
    )
    auto_linked: MatchCandidate | None = candidate

    took_ms = int((time.perf_counter() - started) * 1000)

    # Log the short-circuit so analytics can audit "how often does the
    # source already know the answer". tier_used = -1 (sentinel)
    # distinguishes from the relax-tier ladder; status = "exact_code"
    # makes filtering trivial (``WHERE status = 'exact_code'``).
    try:
        await _write_search_log(
            project_id=req.project_id,
            catalog_id=catalog_id,
            collection_name=country_to_collection(catalog_id),
            plan=None,
            candidates=[candidate],
            tier_used=_EXACT_CODE_TIER_SENTINEL,
            took_ms=took_ms,
            status="exact_code",
            bge_used=False,
            llm_used=False,
            envelope=envelope,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("ranker_qdrant: search log skipped (exact_code): %s", exc)

    return MatchResponse(
        request=req,
        candidates=[candidate],
        translation_used=None,
        auto_linked=auto_linked,
        took_ms=took_ms,
        cost_usd=cost_usd,
        status="ok",
        catalog_id=catalog_id,
        catalog_count=catalog_count,
        catalog_vectorized_count=catalog_vec,
    )


__all__ = ["rank"]

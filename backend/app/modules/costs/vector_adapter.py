"""‌⁠‍Cost-catalog vector adapter — feeds the ``oe_cost_items`` collection.

Each :class:`~app.modules.costs.models.CostItem` row is embedded with the
multilingual-e5-small model so element→catalog matching can recall the
right cost item across the nine languages CWICR ships with (en, de, ru,
lt, fr, es, it, pl, pt — plus any other locale a tenant adds via the
``descriptions`` JSON column).

Why this adapter is not just another :class:`EmbeddingAdapter`
=============================================================

The shared multi-collection helpers in :mod:`app.core.vector_index`
encode every text with the *same* string, regardless of whether it's
being indexed (a "passage") or queried (a short "query"). E5 is
asymmetric — recall drops by ~50 % if you skip the
``passage:`` / ``query:`` prefix convention. So this adapter:

* implements ``to_text`` / ``to_payload`` like every other adapter — it
  still satisfies the :class:`EmbeddingAdapter` protocol, so the
  ``index_one`` / ``search_collection`` framework can be used by callers
  that don't care about the optimal recall (e.g. unified search);
* additionally exposes :func:`upsert`, :func:`delete`, :func:`search`
  and :func:`reindex_all` helpers that wrap the embedding step and
  inject the right prefix at encode time.

All heavy imports (``lancedb``, ``fastembed``, ``sentence_transformers``)
are deferred to the function body — this module is safe to import even
when the optional ``[vector]`` / ``[semantic]`` extras are missing, and
the app keeps booting normally; only the cost-vector feature degrades.

Storage shape
=============

The underlying LanceDB / Qdrant table uses the existing generic
collection schema (``id, vector, text, tenant_id, project_id, module,
payload``).  All cost-specific columns the brief calls out
(``description``, ``unit``, ``unit_cost``, ``currency``, ``region_code``,
``source``, ``language``, ``classification_din276`` /
``_nrm`` / ``_masterformat``) are JSON-encoded into the ``payload``
field — the same pattern every other module uses.  Adding a column to
the LanceDB schema would require a destructive migration; JSON keeps
the schema stable while the surface API is unchanged for callers.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.core.vector_index import COLLECTION_COSTS
from app.modules.costs.models import CostItem

logger = logging.getLogger(__name__)


# ── Language derivation ──────────────────────────────────────────────────
#
# CWICR catalogues ship one regional file per locale; the parquet rows
# don't carry an explicit ``language`` field but the country prefix on
# the region code lets us derive the dominant locale unambiguously for
# the supported set.  Anything outside the table falls back to ``en``
# so search ranking still works on rows whose language we couldn't
# infer (we just lose a small amount of cross-lingual signal).
#
# The lookup table lives in :mod:`app.core.match_service.region_language`
# so the costs adapter and the match-service ranker stay in sync — the
# two used to drift (``UK_GBP`` vs ``GB_LONDON``, ``CS_PRAGUE`` vs
# ``CZ_PRAGUE``, etc.), which silently broke the translation cascade
# for any catalogue id that lived in only one of the two tables.

from app.core.match_service.region_language import language_for as _language_for_region


def _language_for(item: CostItem) -> str:
    """‌⁠‍Best-effort ISO-639-1 language code for a cost item.

    Resolution order:
        1. Explicit ``metadata['language']`` (operator override).
        2. Region prefix lookup via the unified ``language_for`` helper.
        3. ``"en"`` fallback so the column is never empty.
    """
    metadata = getattr(item, "metadata_", None) or {}
    if isinstance(metadata, dict):
        explicit = metadata.get("language")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip().lower()
    return _language_for_region(item.region)


# ── E5 prefix convention ─────────────────────────────────────────────────
#
# The intfloat/multilingual-e5-* family is asymmetric: documents stored
# in the index must be encoded with ``passage: <text>`` and queries with
# ``query: <text>``. Skipping this halves recall on multi-language sets.
# The shared embedder in :mod:`app.core.vector` does not know about the
# convention — it just encodes whatever string we hand it — so we apply
# the prefix at the boundary here.

_PASSAGE_PREFIX = "passage: "
_QUERY_PREFIX = "query: "


# ── SQL lexical fallback ────────────────────────────────────────────────
#
# LanceDB ``oe_cost_items`` is rebuilt off-line via the admin reindex
# endpoint or the startup auto-backfill. Until that completes, the
# collection may be empty (fresh install) or contain stale test fixtures
# (legacy seed). To avoid serving fixtures or empty results to end
# users, ``search()`` falls back to a SQL ``ILIKE`` lookup over the
# real :class:`CostItem` rows — slower than vector search and lower
# recall, but guaranteed to return real CWICR codes + descriptions.
#
# The fallback fires when:
#   * the LanceDB hit list is empty, OR
#   * every payload in the hit list looks like a test fixture
#     (id starts with ``TEST-`` or code matches ``^[A-Z][0-9]{3}$``).
#
# Once the reindex completes the LanceDB hits become richer than the
# fixtures and the fallback is skipped automatically.

_FIXTURE_CODE_RE = None  # lazy compile on first use


def _looks_like_fixture(payload: dict[str, Any]) -> bool:
    """‌⁠‍Heuristic: is this LanceDB hit a test fixture, not real CWICR?

    Earlier versions used a generic ``^[A-Z]\\d{3}$`` regex that silently
    dropped legitimate short CWICR codes (``M001``, ``B100``, ``S420``)
    from BYO catalogues — they look like test fixtures but aren't. The
    filter now only catches markers a real catalogue would NEVER use:
    the explicit ``TEST-<hex>`` prefix and the legacy ``"desc "`` /
    ``"Test concrete C30/37"`` description fixtures from older test
    suites. Anything else passes through.
    """
    global _FIXTURE_CODE_RE
    if _FIXTURE_CODE_RE is None:
        import re

        _FIXTURE_CODE_RE = re.compile(r"^TEST-[a-f0-9]{6,}$")
    code = str(payload.get("code", "") or "")
    if code and _FIXTURE_CODE_RE.match(code):
        return True
    desc = str(payload.get("description", "") or "")
    if desc.startswith("desc ") or desc == "Test concrete C30/37":
        return True
    return False


async def _sql_lexical_search(
    query: str,
    *,
    limit: int,
    region: str | None,
    language: str | None,
) -> list[dict[str, Any]]:
    """ILIKE fallback over the real :class:`CostItem` SQL table.

    Splits the query into tokens, picks the 4 longest discriminative
    ones, and matches any of them in the description. Score is the
    fraction of tokens hit (0.0–0.6) so vector hits always outrank a
    lexical fallback when both are available.

    The ``language`` filter is permissive: if the strict filter yields
    zero results, it is dropped on the second pass — the fallback's
    purpose is to surface *some* real CWICR rows even when the project's
    target language doesn't match what the catalogue ships (the real
    catalogue is RU + BG today; English projects would otherwise get
    empty results until the operator imports an EN catalogue).
    """
    text = (query or "").strip()
    if not text:
        return []
    try:
        from sqlalchemy import or_, select  # noqa: PLC0415

        from app.database import async_session_factory  # noqa: PLC0415
        from app.modules.costs.models import CostItem  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug("cost-vector lexical: SQL imports failed: %s", exc)
        return []

    # Strip punctuation so a query like "Roof Metal Panels, sheet" doesn't
    # produce the literal token "panels," — ILIKE %panels,% would only
    # match descriptions containing the trailing comma. Caller is
    # responsible for handing us a query in the *catalogue's* language;
    # this is a narrow lexical search, not a translator.
    import re  # noqa: PLC0415

    cleaned = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    tokens = sorted(
        {t.lower() for t in cleaned.split() if len(t) >= 3},
        key=len,
        reverse=True,
    )[:6]
    if not tokens:
        return []

    try:
        async with async_session_factory() as session:
            stmt = select(CostItem).where(CostItem.is_active.is_(True))
            if region:
                stmt = stmt.where(CostItem.region == region)
            stmt = stmt.where(or_(*[CostItem.description.ilike(f"%{t}%") for t in tokens]))
            # Over-fetch so the in-Python token-coverage score has a real
            # chance to surface descriptions that match *several* tokens,
            # not just whatever PK-ordered first row matches one. The
            # cap keeps the round-trip bounded.
            stmt = stmt.limit(max(limit * 30, 200))
            rows = list((await session.execute(stmt)).scalars().all())
    except Exception as exc:
        logger.debug("cost-vector lexical: query failed: %s", exc)
        return []

    def _row_to_hit_with_count(
        row: CostItem,
        hits_count: int,
        total_tokens: int,
    ) -> dict[str, Any]:
        # Score band 0.3 - 0.6 — always below typical vector hits (≥0.7),
        # so the lexical fallback never fights a real vector candidate.
        denom = max(1, total_tokens)
        score = 0.3 + 0.3 * (hits_count / denom)
        row_lang = _language_for_region(row.region)
        payload: dict[str, Any] = {
            "code": row.code or "",
            "description": row.description or "",
            "unit": row.unit or "",
            "unit_cost": float(row.rate or 0.0),
            "currency": row.currency or "",
            "region_code": row.region or "",
            "source": row.source or "cwicr",
            "language": row_lang,
        }
        return {
            "id": str(row.id),
            "score": round(score, 3),
            "text": row.description or "",
            "payload": payload,
        }

    out: list[dict[str, Any]] = []
    for row in rows:
        desc_lower = (row.description or "").lower()
        hits = sum(1 for t in tokens if t in desc_lower)
        if hits == 0:
            continue
        out.append(_row_to_hit_with_count(row, hits, len(tokens)))

    out.sort(key=lambda h: -h["score"])
    logger.info(
        "cost-vector lexical: query=%r tokens=%d region=%s returning=%d/%d",
        text[:80],
        len(tokens),
        region or "any",
        min(len(out), limit),
        len(out),
    )
    return out[:limit]


# ── Adapter ──────────────────────────────────────────────────────────────


class CostItemVectorAdapter:
    """Embed CWICR / RSMeans / custom cost items into the unified store.

    Implements :class:`~app.core.vector_index.EmbeddingAdapter` so the
    generic helpers can use this adapter for cross-collection unified
    search.  Add ``upsert`` / ``delete`` / ``search`` / ``reindex_all``
    on top to apply the E5 ``passage:`` / ``query:`` prefix at the right
    boundary — that's the only reason we don't just plug into
    ``vector_index.index_one`` directly.
    """

    collection_name: str = COLLECTION_COSTS
    module_name: str = "costs"

    # ── EmbeddingAdapter protocol ────────────────────────────────────

    def to_text(self, row: CostItem) -> str:
        """Build the canonical text that gets embedded.

        Format mandated by the design brief:
            ``{description} | {classifier_codes} | {unit}``

        ``classifier_codes`` is the comma-joined list of ``classification``
        values (DIN 276 / NRM / MasterFormat / OmniClass / …).  Empty
        fields are dropped so we never embed dangling pipe separators.

        Note: the ``passage:`` prefix is **not** applied here — callers
        going through the shared ``index_one`` helper would otherwise
        leak the prefix into ``text`` payloads where it shouldn't appear.
        The prefix is added by :func:`upsert` / :func:`reindex_all` at
        encode time, immediately before passing to the embedder.
        """
        parts: list[str] = []
        if row.description:
            parts.append(str(row.description).strip())
        codes = self._classifier_codes(row)
        if codes:
            parts.append(codes)
        if row.unit:
            parts.append(str(row.unit).strip())
        return " | ".join(p for p in parts if p)

    def to_payload(self, row: CostItem) -> dict[str, Any]:
        """Light metadata returned with every search hit so the BOQ
        match UI can render a cost-item card without a Postgres roundtrip.

        Mirrors the columns the brief calls out:
            id, description, unit, unit_cost, currency, region_code,
            source, language, classification_din276, classification_nrm,
            classification_masterformat
        """
        classification = row.classification or {}
        if not isinstance(classification, dict):
            classification = {}
        return {
            "title": (row.description or "")[:160],
            "id": str(row.id) if getattr(row, "id", None) else "",
            "code": row.code or "",
            "description": (row.description or "")[:500],
            "unit": row.unit or "",
            "unit_cost": self._coerce_rate(row.rate),
            "currency": row.currency or "",
            "region_code": row.region or "",
            "source": row.source or "",
            "language": _language_for(row),
            "classification_din276": str(classification.get("din276") or ""),
            "classification_nrm": str(classification.get("nrm") or ""),
            "classification_masterformat": str(classification.get("masterformat") or ""),
        }

    def project_id_of(self, row: CostItem) -> str | None:
        """Cost items are tenant-global, never per-project — return None."""
        _ = row  # interface symmetry
        return None

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _coerce_rate(rate: Any) -> float:
        """Convert the string-encoded ``rate`` column to a float.

        Returns ``0.0`` for unparseable values so the payload schema
        stays stable; downstream rendering can decide how to flag the
        anomaly.
        """
        if rate is None:
            return 0.0
        if isinstance(rate, (int, float)):
            return float(rate)
        try:
            return float(str(rate))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _classifier_codes(row: CostItem) -> str:
        """Comma-join classification dict values into one segment.

        DIN 276 / NRM / MasterFormat / OmniClass are typically short
        strings ("330", "2.6.1", "03 30 00"). We sort by key for stable
        embedding output — the same row always produces the same vector,
        even if the JSON column was written by a different code path
        with unstable key order.
        """
        classification = row.classification or {}
        if not isinstance(classification, dict):
            return ""
        ordered = sorted((k, v) for k, v in classification.items() if v not in (None, ""))
        return ", ".join(f"{k}:{v}" for k, v in ordered)


# Singleton instance — adapters are stateless so one shared object is fine.
cost_item_vector_adapter = CostItemVectorAdapter()


# ── Lazy-loaded backend probe ────────────────────────────────────────────


def _vector_available() -> bool:
    """Return True iff the configured vector backend is importable.

    Probes the python package matching ``settings.vector_backend`` — so
    ``qdrant`` installs (``[semantic]`` extra) need ``qdrant_client``,
    ``lancedb`` installs (``[vector]`` extra) need ``lancedb``. Older
    versions hardcoded the lancedb probe, which made every cost upsert
    silently no-op on the default qdrant backend — see issue #162.
    """
    try:
        import importlib.util  # noqa: PLC0415

        from app.config import get_settings  # noqa: PLC0415

        backend = (get_settings().vector_backend or "qdrant").strip().lower()
        module = "qdrant_client" if backend == "qdrant" else "lancedb"
        if importlib.util.find_spec(module) is None:
            return False
    except Exception:
        return False
    return True


def _warn_missing_backend(operation: str) -> None:
    """Single rate-limited log line when a vector op is skipped."""
    logger.info(
        "cost-vector adapter: skipping %s — install the [vector] extra "
        "(`pip install openconstructionerp[vector]`) to enable cost "
        "semantic indexing.",
        operation,
    )


# ── Public write API ─────────────────────────────────────────────────────


async def upsert(rows: list[CostItem]) -> int:
    """Embed and upsert one or more cost items into ``oe_cost_items``.

    Each text is prefixed with ``passage: `` before encoding so the E5
    asymmetric encoder produces document-side embeddings.  Returns the
    number of rows successfully indexed.  Never raises — every failure
    funnels through the logger so the caller (typically a CRUD path or
    an event handler) can stay one-line.
    """
    if not rows:
        return 0
    if not _vector_available():
        _warn_missing_backend("upsert")
        return 0

    adapter = cost_item_vector_adapter

    texts: list[str] = []
    keepers: list[CostItem] = []
    for row in rows:
        if getattr(row, "id", None) is None:
            continue
        text = adapter.to_text(row)
        if not text:
            continue
        texts.append(_PASSAGE_PREFIX + text)
        keepers.append(row)
    if not texts:
        return 0

    try:
        from app.core.vector import encode_texts_async  # noqa: PLC0415

        vectors = await encode_texts_async(texts)
    except Exception as exc:
        logger.warning("cost-vector upsert: encode failed (%d rows): %s", len(texts), exc)
        return 0
    if not vectors or len(vectors) != len(keepers):
        logger.warning(
            "cost-vector upsert: encoder returned %d vectors for %d texts",
            len(vectors) if vectors else 0,
            len(texts),
        )
        return 0

    items: list[dict[str, Any]] = []
    for row, raw_text, vec in zip(keepers, texts, vectors, strict=True):
        payload = adapter.to_payload(row)
        items.append(
            {
                "id": str(row.id),
                "vector": vec,
                # Strip the prefix back off for the stored ``text`` column
                # — the prefix is only meaningful at encode time, leaving
                # it on disk would pollute snippet rendering.
                "text": raw_text.removeprefix(_PASSAGE_PREFIX),
                "tenant_id": "",
                "project_id": "",
                "module": adapter.module_name,
                "payload": json.dumps(payload, ensure_ascii=False, default=str),
            }
        )

    try:
        from app.core.vector import vector_index_collection  # noqa: PLC0415

        return vector_index_collection(adapter.collection_name, items)
    except Exception as exc:
        logger.warning("cost-vector upsert: store failed (%d rows): %s", len(items), exc)
        return 0


async def delete(item_ids: list[Any]) -> int:
    """Remove cost items from the vector store by id.  Idempotent."""
    if not item_ids:
        return 0
    if not _vector_available():
        _warn_missing_backend("delete")
        return 0
    cleaned = [str(i) for i in item_ids if i is not None]
    if not cleaned:
        return 0
    try:
        from app.core.vector import vector_delete_collection  # noqa: PLC0415

        return vector_delete_collection(COLLECTION_COSTS, cleaned)
    except Exception as exc:
        logger.warning("cost-vector delete: store failed (%d ids): %s", len(cleaned), exc)
        return 0


# ── Public read API ──────────────────────────────────────────────────────


async def search(
    query: str,
    *,
    limit: int = 10,
    region: str | None = None,
    language: str | None = None,
    source: str | None = None,
    din276_kg_prefix: str | None = None,
    project_currency: str | None = None,
) -> list[dict[str, Any]]:
    """Semantic search inside ``oe_cost_items``.

    The query string is prefixed with ``query: `` before encoding (the
    E5 asymmetric counterpart to the ``passage:`` prefix used during
    indexing).  Optional ``region`` / ``language`` / ``source`` filters
    are post-applied to hits — the underlying generic LanceDB schema
    only filters on tenant_id / project_id natively, so we filter the
    payload in Python after retrieval.

    ``din276_kg_prefix`` adds a trade-aware pre-filter on the leading
    digits of ``payload.classification_din276``. A 2-digit prefix (e.g.
    ``"33"`` for walls) keeps siblings within the same DIN 276 main
    cost group while excluding unrelated trades (e.g. MEP "44" hits
    competing for top-K slots against a structural envelope). The filter
    auto-disables when the catalogue is unclassified — i.e. fewer than
    ~20% of hits carry any DIN 276 value — so BYO catalogues without
    DIN 276 metadata still surface results.

    Returns hits sorted by similarity (highest first), shaped as
    ``{"id", "score", "payload": {...}, "text"}``.  Empty list on any
    failure path so callers can keep the call site one-line.
    """
    text = (query or "").strip()
    if not text:
        return []
    # Fast SQL fallback when the optional [vector] extra is missing — the
    # cost-vector feature degrades but real CWICR rows still surface.
    if not _vector_available():
        _warn_missing_backend("search")
        return await _sql_lexical_search(
            query,
            limit=limit,
            region=region,
            language=language,
        )

    try:
        from app.core.vector import (  # noqa: PLC0415
            encode_texts_async,
            vector_search_collection,
        )

        vectors = await encode_texts_async([_QUERY_PREFIX + text])
    except Exception as exc:
        # Encoder unavailable (model load failed, fastembed/sentence-transformers
        # missing wheels, GPU OOM, etc.) — fall straight through to lexical
        # so the user still sees real CWICR codes/descriptions instead of an
        # empty pane while ops fixes the encoder backend.
        logger.info("cost-vector search: encode failed (%s); using SQL fallback", exc)
        return await _sql_lexical_search(
            query,
            limit=limit,
            region=region,
            language=language,
        )
    if not vectors:
        return await _sql_lexical_search(
            query,
            limit=limit,
            region=region,
            language=language,
        )

    # Pull a wider window when payload-side filters are active so we
    # still have ``limit`` results after filtering — capped at 5x the
    # request to keep the round-trip cheap.
    any_filter = bool(region or language or source or din276_kg_prefix)
    fetch = limit if not any_filter else min(limit * 5, 250)
    try:
        raw_hits = vector_search_collection(
            COLLECTION_COSTS,
            vectors[0],
            project_id=None,
            tenant_id=None,
            limit=fetch,
        )
    except Exception as exc:
        logger.debug("cost-vector search: store failed: %s", exc)
        return []

    # Decode payloads once so we can probe DIN 276 coverage before
    # committing to the trade-aware pre-filter.
    decoded: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for raw in raw_hits:
        payload_raw = raw.get("payload")
        payload: dict[str, Any]
        if isinstance(payload_raw, dict):
            payload = payload_raw
        elif isinstance(payload_raw, str) and payload_raw:
            try:
                decoded_payload = json.loads(payload_raw)
                payload = decoded_payload if isinstance(decoded_payload, dict) else {}
            except Exception:
                payload = {}
        else:
            payload = {}
        decoded.append((raw, payload))

    # Auto-disable the DIN 276 pre-filter when the catalogue isn't
    # classified — a BYO catalogue without DIN 276 codes would otherwise
    # silently filter to zero results. Threshold is intentionally
    # permissive (20%) so partial classification still benefits from the
    # filter.
    active_din_prefix = din276_kg_prefix
    if active_din_prefix and decoded:
        classified = sum(1 for (_r, pl) in decoded if str(pl.get("classification_din276") or "").strip())
        if classified < max(3, int(len(decoded) * 0.20)):
            active_din_prefix = None

    out: list[dict[str, Any]] = []
    fixture_count = 0
    for raw, payload in decoded:
        if _looks_like_fixture(payload):
            fixture_count += 1
            continue

        if region and payload.get("region_code", "") != region:
            continue
        if language and payload.get("language", "") != language:
            continue
        if source and payload.get("source", "") != source:
            continue
        if active_din_prefix:
            kg = str(payload.get("classification_din276") or "")
            if not kg.startswith(active_din_prefix):
                continue
        # Currency-aware post-filter (universality fix). When the caller
        # knows the project's currency, drop hits whose currency disagrees
        # so a USD project doesn't see EUR rates ranked into the top-K.
        # Empty / null payload currency is treated as "compatible" so
        # legacy rows without a currency stamp still surface.
        if project_currency:
            payload_ccy = str(payload.get("currency") or "").strip().upper()
            if payload_ccy and payload_ccy != project_currency.upper():
                continue

        out.append(
            {
                "id": str(raw.get("id", "")),
                "score": float(raw.get("score", 0.0)),
                "text": str(raw.get("text", "")),
                "payload": payload,
            }
        )
        if len(out) >= limit:
            break

    # Trip the SQL lexical fallback when LanceDB returned nothing or
    # only fixtures — this is what real CWICR users see today, before
    # the admin reindex completes.
    if not out:
        if fixture_count:
            logger.info(
                "cost-vector search: %d fixture hits filtered, falling back to SQL lexical",
                fixture_count,
            )
        sql_hits = await _sql_lexical_search(
            query,
            limit=limit,
            region=region,
            language=language,
        )
        return sql_hits

    return out


# ── Reindex / backfill ───────────────────────────────────────────────────


async def reindex_all(rows: list[CostItem], *, batch_size: int = 500) -> dict[str, Any]:
    """Re-embed every supplied row in batches.

    Designed for the admin reindex endpoint and the startup auto-backfill
    hook.  Returns a summary dict ``{"indexed": int, "took_ms": int,
    "collection": str}`` matching the admin API contract.
    """
    started = time.monotonic()
    if not rows:
        return {
            "indexed": 0,
            "took_ms": 0,
            "collection": COLLECTION_COSTS,
        }
    if not _vector_available():
        _warn_missing_backend("reindex_all")
        return {
            "indexed": 0,
            "took_ms": int((time.monotonic() - started) * 1000),
            "collection": COLLECTION_COSTS,
        }

    indexed = 0
    for start in range(0, len(rows), max(1, batch_size)):
        chunk = rows[start : start + batch_size]
        indexed += await upsert(chunk)

    return {
        "indexed": indexed,
        "took_ms": int((time.monotonic() - started) * 1000),
        "collection": COLLECTION_COSTS,
    }


async def collection_count() -> int:
    """Number of cost items currently indexed (0 on any failure)."""
    if not _vector_available():
        return 0
    try:
        from app.core.vector import vector_count_collection  # noqa: PLC0415

        return int(vector_count_collection(COLLECTION_COSTS) or 0)
    except Exception:
        return 0


# ── Catalog-language detection ───────────────────────────────────────────
#
# The match service needs to know what language the *catalogue* ships in
# so it can translate the user's query before searching. Project settings
# default ``target_language`` to "en", but a tenant's catalogue may be
# RU + BG (CWICR ships per-region, with descriptions in the regional
# language). Without this hook, an English BIM-element name never matches
# Russian descriptions and the Match panel stays empty.
#
# The lookup is one ``GROUP BY region`` SELECT; we cache the answer for
# 5 minutes per process. Catalogues don't shift language mid-session, so
# the staleness window is generous.

_catalog_lang_cache: tuple[str | None, float] | None = None
_CATALOG_LANG_TTL = 300.0  # 5 minutes


async def catalog_dominant_language() -> str | None:
    """Return the ISO-639 code most catalogue rows are written in.

    ``None`` when the catalogue is empty or the lookup fails — callers
    should treat ``None`` as "skip the catalogue-language override and
    keep the project's configured target_language".

    Pure read, idempotent, cached. Safe to call from the hot match path.
    """
    global _catalog_lang_cache
    now = time.monotonic()
    if _catalog_lang_cache is not None:
        lang, expires = _catalog_lang_cache
        if now < expires:
            return lang

    try:
        from sqlalchemy import func, select  # noqa: PLC0415

        from app.database import async_session_factory  # noqa: PLC0415
        from app.modules.costs.models import CostItem  # noqa: PLC0415
    except Exception:  # pragma: no cover — defensive
        return None

    try:
        async with async_session_factory() as session:
            stmt = (
                select(CostItem.region, func.count().label("c"))
                .where(CostItem.is_active.is_(True))
                .group_by(CostItem.region)
                .order_by(func.count().desc())
                .limit(8)
            )
            rows = list((await session.execute(stmt)).all())
    except Exception as exc:
        logger.debug("catalog_dominant_language: query failed: %s", exc)
        _catalog_lang_cache = (None, now + 60.0)  # short TTL on failure
        return None

    by_lang: dict[str, int] = {}
    for region, count in rows:
        lang = _language_for_region(region)
        by_lang[lang] = by_lang.get(lang, 0) + int(count or 0)
    if not by_lang:
        _catalog_lang_cache = (None, now + _CATALOG_LANG_TTL)
        return None
    dominant = max(by_lang.items(), key=lambda kv: kv[1])[0]
    _catalog_lang_cache = (dominant, now + _CATALOG_LANG_TTL)
    return dominant


def clear_catalog_language_cache() -> None:
    """Reset the catalog-language TTL cache. Tests + import path use this."""
    global _catalog_lang_cache
    _catalog_lang_cache = None

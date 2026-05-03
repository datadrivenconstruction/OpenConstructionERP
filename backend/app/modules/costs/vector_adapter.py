"""Cost-catalog vector adapter — feeds the ``oe_cost_items`` collection.

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

_REGION_LANGUAGE: dict[str, str] = {
    # German-speaking
    "DE_BERLIN": "de",
    "DE_MUNICH": "de",
    "DE_HAMBURG": "de",
    "AT_VIENNA": "de",
    "CH_ZURICH": "de",
    # Romance
    "FR_PARIS": "fr",
    "ES_MADRID": "es",
    "IT_ROME": "it",
    "PT_LISBON": "pt",
    "PT_SAOPAULO": "pt",
    "BR_SAOPAULO": "pt",
    # English / Anglophone
    "GB_LONDON": "en",
    "IE_DUBLIN": "en",
    "USA_USD": "en",
    "USA_NEWYORK": "en",
    "CA_TORONTO": "en",
    "AU_SYDNEY": "en",
    "NZ_AUCKLAND": "en",
    "ZA_JOHANNESBURG": "en",
    # Slavic / CIS
    "PL_WARSAW": "pl",
    "CZ_PRAGUE": "cs",
    "RO_BUCHAREST": "ro",
    "RU_STPETERSBURG": "ru",
    "RU_MOSCOW": "ru",
    "BG_SOFIA": "bg",
    "LT_VILNIUS": "lt",
    # Benelux
    "NL_AMSTERDAM": "nl",
    "BE_BRUSSELS": "nl",
    # Asia / MENA
    "CN_SHANGHAI": "zh",
    "JP_TOKYO": "ja",
    "IN_MUMBAI": "en",
    "AE_DUBAI": "ar",
    "SA_RIYADH": "ar",
    "TR_ISTANBUL": "tr",
    # LatAm
    "MX_MEXICO": "es",
    "AR_BUENOSAIRES": "es",
}


def _language_for(item: CostItem) -> str:
    """Best-effort ISO-639-1 language code for a cost item.

    Resolution order:
        1. Explicit ``metadata['language']`` (operator override).
        2. Region prefix lookup in :data:`_REGION_LANGUAGE`.
        3. ``"en"`` fallback so the column is never empty.
    """
    metadata = getattr(item, "metadata_", None) or {}
    if isinstance(metadata, dict):
        explicit = metadata.get("language")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip().lower()
    region = (item.region or "").strip().upper()
    if region and region in _REGION_LANGUAGE:
        return _REGION_LANGUAGE[region]
    return "en"


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
            "classification_masterformat": str(
                classification.get("masterformat") or ""
            ),
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
        ordered = sorted(
            (k, v) for k, v in classification.items() if v not in (None, "")
        )
        return ", ".join(f"{k}:{v}" for k, v in ordered)


# Singleton instance — adapters are stateless so one shared object is fine.
cost_item_vector_adapter = CostItemVectorAdapter()


# ── Lazy-loaded backend probe ────────────────────────────────────────────


def _vector_available() -> bool:
    """Return True iff the optional vector backend is importable.

    Lazy: the import is attempted once per call, but the answer is
    cached cheaply by Python's import machinery so repeated calls cost
    nothing.  Used as a guard at the top of every public helper so the
    cost API path stays fast even on installs without the
    ``[vector]`` extra.
    """
    try:
        import importlib.util  # noqa: PLC0415

        if importlib.util.find_spec("lancedb") is None:
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
) -> list[dict[str, Any]]:
    """Semantic search inside ``oe_cost_items``.

    The query string is prefixed with ``query: `` before encoding (the
    E5 asymmetric counterpart to the ``passage:`` prefix used during
    indexing).  Optional ``region`` / ``language`` / ``source`` filters
    are post-applied to hits — the underlying generic LanceDB schema
    only filters on tenant_id / project_id natively, so we filter the
    payload in Python after retrieval.

    Returns hits sorted by similarity (highest first), shaped as
    ``{"id", "score", "payload": {...}, "text"}``.  Empty list on any
    failure path so callers can keep the call site one-line.
    """
    text = (query or "").strip()
    if not text:
        return []
    if not _vector_available():
        _warn_missing_backend("search")
        return []

    try:
        from app.core.vector import (  # noqa: PLC0415
            encode_texts_async,
            vector_search_collection,
        )

        vectors = await encode_texts_async([_QUERY_PREFIX + text])
    except Exception as exc:
        logger.debug("cost-vector search: encode failed: %s", exc)
        return []
    if not vectors:
        return []

    # Pull a wider window when payload-side filters are active so we
    # still have ``limit`` results after filtering — capped at 5x the
    # request to keep the round-trip cheap.
    fetch = limit if not (region or language or source) else min(limit * 5, 250)
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

    out: list[dict[str, Any]] = []
    for raw in raw_hits:
        payload_raw = raw.get("payload")
        payload: dict[str, Any]
        if isinstance(payload_raw, dict):
            payload = payload_raw
        elif isinstance(payload_raw, str) and payload_raw:
            try:
                decoded = json.loads(payload_raw)
                payload = decoded if isinstance(decoded, dict) else {}
            except Exception:
                payload = {}
        else:
            payload = {}

        if region and payload.get("region_code", "") != region:
            continue
        if language and payload.get("language", "") != language:
            continue
        if source and payload.get("source", "") != source:
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

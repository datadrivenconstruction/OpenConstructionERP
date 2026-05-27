# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍CWICR Qdrant adapter — 30-collection multilingual cost-rate search.

Replaces the legacy ``vector_adapter`` (LanceDB + e5-small + 384-dim) for
the ``/match-elements`` path. The new pipeline holds rate vectors in
30 per-language Qdrant collections (``cwicr_<lang>``), each point
carrying three named vectors:

* ``dense``     — 1024-dim BAAI/bge-m3 of the full rate description.
* ``sparse``    — BM25-like inverted vector for verbatim term hits
                  (concrete grades, pipe nominals, bolt sizes, etc).
* ``resources`` — 1024-dim bge-m3 of the rate's top-12 unique resources.

The Qdrant payload is intentionally minimal — only keys plus filter
columns (``rate_code``, ``country``, ``department_code``, ``is_abstract``,
``rate_unit``, ``mass_*``). Heavy fields (prices, labor lines, full
resource list, budget sums — 84 columns total) are read on demand from
``<region>_workitems_costs_resources_DDC_CWICR.parquet`` via
:mod:`app.modules.costs.parquet_lookup`. Keeping the vector store narrow
keeps embedded-Qdrant disk usage manageable and lets the parquet column
set evolve without re-vectorising.

Contract
--------

This module exposes two async helpers:

* :func:`search` — one-shot hybrid search that fans out
  ``dense`` + ``sparse`` (+ optional ``resources``) prefetches and fuses
  them with Reciprocal Rank Fusion natively in the Qdrant Query API.
* :func:`lookup_full_rows` — proxy onto :mod:`parquet_lookup` so the
  ranker can stay on a single ``qdrant_adapter`` import.

Heavy imports (``qdrant_client``, ``FlagEmbedding``) are deferred to the
function body. The module is safe to import even when the optional
``[semantic]`` extra is missing — only the CWICR Qdrant path degrades,
the rest of the app keeps booting.

Deployment
----------

Two modes are supported:

* **Server** (recommended for production and for DDC's pre-built
  catalogues) — ``settings.cwicr_qdrant_url`` points at a real Qdrant
  server (Docker compose ships ``qdrant/qdrant:v1.12.5`` on ports
  6333/6334). This is the **only** mode that can ingest the v3
  snapshots DDC publishes (``*_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot``)
  via :meth:`QdrantClient.recover_snapshot`. Verified 2026-05-09: the
  embedded path errors with ``NotImplementedError: Snapshots are not
  supported in the local Qdrant``, see v3 plan §5 risk note.
* **Embedded** (development / smoke) — ``settings.cwicr_qdrant_path``
  spawns an in-process simulation via ``QdrantClient(path=...)``.
  Suitable when the caller vectorises rates locally with BGE-M3 and
  upserts them point-by-point. **Cannot** ingest DDC snapshots.

The adapter prefers ``url`` over ``path`` when both are configured.
``settings.cwicr_qdrant_path`` defaults to ``~/.openestimator/qdrant_cwicr/``.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


# ── Public types ─────────────────────────────────────────────────────────


@dataclass
class QdrantHit:
    """‌⁠‍One result from :func:`search`.

    ``score`` is the RRF-fused score from Qdrant Query API, not a raw
    cosine similarity. Use for relative ranking only — absolute values
    are not comparable across queries.
    """

    rate_code: str
    country: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)


# ── Country → collection mapping ─────────────────────────────────────────
#
# Per MAPPING_PROCESS.md v3 (§2.1, §6.1) the 30 production CWICR
# collections are named ``cwicr_{LANG}_v3`` where ``LANG`` is the
# ISO-639-1 language code of the rates inside. One collection per
# language — Mexico, Spain and Argentina catalogues all live in
# ``cwicr_es_v3`` because BGE-M3 multilingual benefits from same-language
# clustering, and per-country narrowing is done via the ``country``
# payload predicate (see :func:`country_filter_for`).
#
# Pre-v3 (LanceDB era) we used ``cwicr_<country>`` with a hand-rolled
# remap table for USA→us / GB→uk. The v3 layout makes the remap
# unnecessary — :func:`region_language.language_for` already returns
# ``"en"`` for both USA_USD and GB_LONDON, so they correctly land in
# ``cwicr_en_v3`` together.
#
# Schema version is overridable via ``settings.cwicr_collection_version``
# so the application can flip to a future ``v4`` index without a code
# change. Empty string strips the suffix entirely for legacy installs
# that vectorised before the v3 cutover.


def _collection_version_suffix() -> str:
    """‌⁠‍Return the configured ``_<ver>`` suffix or empty for legacy installs.

    Reads ``settings.cwicr_collection_version`` lazily so test monkeypatching
    of the env var after import still takes effect. The leading underscore
    is added here to keep the f-string at the callsite readable.
    """

    version = (getattr(get_settings(), "cwicr_collection_version", "") or "").strip()
    return f"_{version}" if version else ""


# Process-local cache of the CWICR collection names Qdrant actually
# holds. Populated lazily by :func:`_available_cwicr_collections`; a
# short TTL keeps a freshly-ingested catalogue discoverable without a
# backend restart while still sparing every match call a list_collections
# round-trip.
_AVAILABLE_CWICR_TTL_SEC = 30.0
_available_cwicr_cache: tuple[float, frozenset[str]] | None = None


def _available_cwicr_collections() -> frozenset[str]:
    """Return the set of ``cwicr_*`` collection names present in Qdrant.

    Cached for :data:`_AVAILABLE_CWICR_TTL_SEC`. Returns an empty set
    (never raises) when Qdrant is unreachable so callers fall back to
    the naive language-derived name and the existing
    ``catalog_not_vectorized`` empty-state still fires correctly.
    """

    global _available_cwicr_cache
    import time as _t  # noqa: PLC0415

    # Pure-routing escape hatch. When the probe is disabled the function
    # behaves as if Qdrant were unreachable (empty set) so
    # :func:`country_to_collection` returns the naive language-derived
    # name verbatim — no network I/O, fully deterministic. Required for
    # deterministic bench runs and the routing-contract unit tests, which
    # otherwise silently fail whenever the dev/CI host happens to have a
    # sparsely-populated live Qdrant (only ``cwicr_en_v3`` present →
    # every non-English region falls back to English).
    if not getattr(get_settings(), "cwicr_collection_probe", True):
        return frozenset()

    now = _t.perf_counter()
    if _available_cwicr_cache is not None and now - _available_cwicr_cache[0] < _AVAILABLE_CWICR_TTL_SEC:
        return _available_cwicr_cache[1]

    names: set[str] = set()
    try:
        client = _get_client()
        cols = client.get_collections()
        for c in getattr(cols, "collections", None) or []:
            name = getattr(c, "name", "") or ""
            if name.startswith("cwicr_"):
                names.add(name)
    except Exception as exc:  # noqa: BLE001 — degrade, never fail
        logger.debug("qdrant_adapter: list cwicr collections failed: %s", exc)
        names = set()

    result = frozenset(names)
    _available_cwicr_cache = (now, result)
    return result


def _pick_fallback_cwicr(want: str, available: frozenset[str]) -> str | None:
    """Choose the best present CWICR collection when ``want`` is absent.

    BGE-M3 is multilingual, so an English (or any populated) CWICR
    collection still yields real cross-language candidates — far better
    than the hard ``catalog_not_vectorized`` empty result a missing
    per-language collection used to produce. Preference order:

    1. Same language family ignoring the ``_enriched`` / ``_v?`` tail
       (e.g. ``cwicr_pt_v3`` → ``cwicr_pt`` if only the unversioned
       name was ingested).
    2. English (``cwicr_en*``) — the densest, broadest catalogue and
       the one CWICR always ships.
    3. Any remaining populated CWICR collection (deterministic by
       sorted name so the choice is stable across calls/processes).
    """

    if not available:
        return None

    # 1. versionless / suffix-stripped sibling of the requested name.
    stem = want
    for tail in ("_enriched",):
        if stem.endswith(tail):
            stem = stem[: -len(tail)]
    base = stem.rsplit("_v", 1)[0] if "_v" in stem else stem
    siblings = sorted(n for n in available if n == base or n.rsplit("_v", 1)[0] == base)
    if siblings:
        return siblings[0]

    # 2. English collection (prefer enriched, then plain).
    english = sorted(n for n in available if n.startswith("cwicr_en"))
    if english:
        non_enriched = [n for n in english if not n.endswith("_enriched")]
        return (non_enriched or english)[0]

    # 3. Any remaining populated CWICR collection.
    rest = sorted(n for n in available if not n.endswith("_enriched"))
    return (rest or sorted(available))[0]


def country_to_collection(country: str | None) -> str:
    """Return the Qdrant collection name for a region/country code.

    The collection key is the **language** of the rates, not the
    country. Multiple regions sharing a language (DE_BERLIN, AT_VIENNA,
    CH_ZURICH) all resolve to the same collection (``cwicr_de_v3``).
    Per-country filtering happens via the ``country`` payload field —
    see :func:`country_filter_for`.

    Accepts both bare country codes (``"DE"``) and full region ids
    (``"DE_BERLIN"``, ``"USA_USD"``, ``"MX_MEXICO"``).

    Returns ``cwicr_en_v3`` when the input is empty or unrecognised so
    a misconfigured catalogue still hits a real collection rather than
    erroring out.

    Language-fallback (the /match-elements "nothing happens" fix)
    -------------------------------------------------------------
    When the language-derived collection (e.g. ``cwicr_pt_v3`` for a
    Brazil/Portugal project) is **not present** in Qdrant but other
    CWICR collections are, this returns the best available one rather
    than a dead name. BGE-M3 is multilingual so an English catalogue
    still returns real candidates — the prior behaviour silently short-
    circuited every BIM-vs-cost match to ``catalog_not_vectorized`` and
    the wizard rendered an empty result. The pick is consistent across
    the vector-count probe and the search itself because both route
    through this single function. The probe is best-effort: if Qdrant
    is unreachable the naive name is returned unchanged so the existing
    down-state empty UI still fires.

    Enriched-collection routing
    ---------------------------
    When ``OE_MATCH_USE_ENRICHED=1`` is set in the environment, the
    returned name is suffixed with ``_enriched`` (e.g.,
    ``cwicr_en_v3_enriched``). This lets operators A/B against a
    description-rich enrichment built by
    ``scripts/build_enriched_snapshot.py`` without touching the
    canonical snapshot. Falls back to the unsuffixed name automatically
    when the enriched collection isn't present — see
    :func:`_collection_vectors` which empty-caches missing collections.
    """

    from app.core.match_service.region_language import language_for

    lang = language_for(country)
    base = f"cwicr_{lang}{_collection_version_suffix()}"
    use_enriched = os.environ.get("OE_MATCH_USE_ENRICHED", "").strip() in (
        "1",
        "true",
        "True",
    )
    want = f"{base}_enriched" if use_enriched else base

    available = _available_cwicr_collections()
    if not available:
        # Qdrant unreachable / no cwicr_* collections discoverable —
        # keep the historical behaviour so the down-state UI is unchanged.
        return want
    if want in available:
        return want
    # Enriched requested but only the plain collection exists → use it.
    if use_enriched and base in available:
        return base
    fallback = _pick_fallback_cwicr(want, available)
    if fallback is not None:
        logger.info(
            "qdrant_adapter: collection %r absent for region %r — falling back to %r (multilingual BGE-M3 recall)",
            want,
            country,
            fallback,
        )
        return fallback
    return want


# Region-id heads DDC ships that differ from the 2-letter ISO-3166
# alpha-2 code its snapshot writes into the ``country`` payload. Keep
# in lockstep with the catalogue files DDC actually publishes — a new
# 3-letter/language-style head means a new entry here, not a code
# branch. 2-letter heads (DE, MX, BR, AT, CH, RU…) pass through
# unchanged via ``dict.get(head, head)``.
_REGION_HEAD_ALIASES: dict[str, str] = {
    "USA": "US",
    "GBR": "GB",
    "ENG": "CA",  # Canadian-English catalogue file DDC ships
}


def country_filter_for(country: str | None) -> str | None:
    """Return the ISO-3166 head of a region id for the ``country`` payload.

    A v3 language collection (``cwicr_es_v3``) carries rates from every
    Spanish-speaking region (ES, MX, AR). When the caller picked one
    specific catalogue (``MX_MEXICO``), the head ``"MX"`` should be
    pinned as a Qdrant payload filter so the search only sees Mexican
    rates. When the caller passed nothing or just a bare two-letter
    code (``"ES"`` meaning "search the whole Spanish collection"),
    return ``None`` so all countries within the language stay
    reachable.

    Distinguishing rule: a region id (``"DE_BERLIN"``, ``"USA_USD"``)
    pins; a bare country/language code (``"DE"``, ``"ES"``, ``"USA"``)
    does not. The underscore is the explicit signal that the caller
    meant a specific catalogue, not a language-wide search.

    3-letter / language-style head remap
    ------------------------------------
    Some catalogue region ids DDC ships use a 3-letter or
    language-style head (``USA_USD``, ``GBR_LONDON``, ``ENG_TORONTO``)
    while the snapshot's ``country`` payload is the 2-letter ISO-3166
    alpha-2 code DDC writes during vectorisation (``"US"``, ``"GB"``,
    ``"CA"``). Pinning the raw head (``"USA"``) would match **zero**
    rows in such a snapshot and silently exclude every rate for that
    region. The alias table mirrors the heads DDC actually ships, so
    the filter aligns with the snapshot rather than second-guessing it.
    """

    if not country or not country.strip():
        return None
    raw = country.strip().upper()
    if "_" not in raw:
        # Bare code (``DE``, ``USA``, ``RU``) — language-wide intent.
        return None

    # Language-fallback guard (the /match-elements "nothing happens" fix,
    # part 3). When the project's native language collection is absent
    # and :func:`country_to_collection` substituted a different-language
    # CWICR collection (e.g. ``PT_SAOPAULO`` → ``cwicr_en_v3`` which
    # holds only ``country="US"`` rows), pinning the original region's
    # head (``"PT"``) as a payload filter matches **zero** points and
    # silently eliminates every candidate — exactly the symptom the user
    # reported. Detect the fallback by comparing the collection the
    # native language *would* select against the one actually resolved;
    # when they differ, the fallback collection's country domain is not
    # the project's, so don't pin a country at all (let the multilingual
    # encoder rank the whole collection).
    if _language_fallback_active(raw):
        return None

    head = raw.split("_", 1)[0]
    head = _REGION_HEAD_ALIASES.get(head, head)
    return head or None


def _language_fallback_active(country: str) -> bool:
    """True when ``country`` resolves to a substituted (fallback) collection.

    Compares the *naive* language-derived collection name (what the
    region would map to if its own collection existed) with what
    :func:`country_to_collection` actually returns after the
    availability probe. A mismatch means a cross-language fallback was
    taken and country-payload pinning would be wrong.

    Best-effort: any failure (Qdrant down, import hiccup) returns
    ``False`` so the historical pinning behaviour is preserved when we
    can't prove a fallback happened.
    """

    try:
        from app.core.match_service.region_language import language_for

        lang = language_for(country)
        naive = f"cwicr_{lang}{_collection_version_suffix()}"
        if os.environ.get("OE_MATCH_USE_ENRICHED", "").strip() in (
            "1",
            "true",
            "True",
        ):
            naive = f"{naive}_enriched"
        resolved = country_to_collection(country)
        # Treat enriched/plain of the same language as "not a fallback".
        return resolved.rsplit("_v", 1)[0].removesuffix("_enriched") != naive.rsplit("_v", 1)[0].removesuffix(
            "_enriched"
        )
    except Exception:  # noqa: BLE001 — degrade to legacy pinning
        return False


# ── Lazy singletons (heavy deps deferred) ────────────────────────────────


_client: Any = None  # qdrant_client.QdrantClient
_encoder: Any = None  # FlagEmbedding.BGEM3FlagModel
# Single-flight guard for the (heavy, ~2 GB) encoder load so a burst of
# concurrent first /match requests can't race into a half-initialised
# model. Re-entrant not required — the load body never re-acquires it.
_ENCODER_LOAD_LOCK = threading.Lock()

# Per-collection capability cache — maps collection name to the set of
# named-vector keys the collection actually exposes (``dense`` /
# ``sparse`` / ``resources`` for fully-featured local catalogues; just
# ``dense`` + ``sparse`` for the DDC v3 snapshots). Populated on first
# ``search()`` against a given collection and consulted before issuing
# a ``Prefetch(using=…)`` so we never ask Qdrant for a vector the
# collection doesn't carry — that would 404 the whole query and force
# the ranker into the metadata-only fallback.
_collection_vectors_cache: dict[str, frozenset[str]] = {}


def _get_client() -> Any:
    """Lazy-init a QdrantClient pointed at the configured store.

    Prefers ``cwicr_qdrant_url`` when set (shared/server mode), falls
    back to embedded ``cwicr_qdrant_path``. Raises :class:`RuntimeError`
    when neither is reachable so the caller can surface a 503 to the
    user instead of a confusing AttributeError.
    """

    global _client
    if _client is not None:
        return _client

    try:
        from qdrant_client import QdrantClient
    except ImportError as exc:  # pragma: no cover — optional [semantic] extra
        raise RuntimeError(
            "qdrant-client is not installed; install the [semantic] extra: pip install openconstructionerp[semantic]"
        ) from exc

    s = get_settings()
    url = getattr(s, "cwicr_qdrant_url", None)
    if url:
        logger.info("CWICR Qdrant: connecting to URL %s", url)
        _client = QdrantClient(url=url)
        return _client

    path = getattr(s, "cwicr_qdrant_path", "") or os.path.expanduser("~/.openestimator/qdrant_cwicr")
    Path(path).mkdir(parents=True, exist_ok=True)
    logger.info("CWICR Qdrant: opening embedded store at %s", path)
    _client = QdrantClient(path=path)
    return _client


def _get_encoder() -> Any:
    """Lazy-init the BGE-M3 encoder (FP32 or INT8 ONNX).

    Returns a ``BGEM3FlagModel`` whose ``.encode()`` produces both dense
    and sparse representations in one forward pass. INT8 ONNX path
    (``gpahal/bge-m3-onnx-int8``) is the VPS default — ~700 MB on disk,
    near-FP32 recall on AVX512_VNNI hardware.

    Failure mode: when the model can't load (offline install, missing
    optional extras, broken HF cache) the singleton is stamped with
    ``False`` so subsequent calls short-circuit instead of paying the
    full multi-second download/retry on every match request. Mirrors
    the pattern :mod:`reranker_bge` uses. The caller raises so /match
    can surface ``catalog_not_vectorized`` instead of hanging.
    """

    global _encoder
    # ``False`` = HARD unavailable (the [semantic] extra isn't installed)
    # — there is no point retrying within this process. A *load* failure
    # (broken HF cache entry, OOM during a concurrent first-call race,
    # transient disk error) must NOT poison the process: it used to
    # stamp ``False`` permanently which silently turned every later
    # /match-elements run into a zero-candidate result even after the
    # underlying cause cleared. Such failures now raise WITHOUT stamping
    # ``False`` so the very next match retries the load.
    if _encoder is False:
        raise RuntimeError(
            "CWICR encoder unavailable: the [semantic] extra is not "
            "installed. Run: pip install openconstructionerp[semantic]"
        )
    if _encoder is not None:
        return _encoder

    # Serialise concurrent first-load attempts. Under the async server
    # the first /match request fans out across the threadpool; two
    # coroutines racing into ``BGEM3FlagModel(...)`` simultaneously was a
    # real source of half-initialised loads that then stuck. The lock
    # makes the load effectively single-flight; the double-check below
    # means the loser of the race just returns the winner's encoder.
    with _ENCODER_LOAD_LOCK:
        if _encoder is False:
            raise RuntimeError(
                "CWICR encoder unavailable: the [semantic] extra is not "
                "installed. Run: pip install openconstructionerp[semantic]"
            )
        if _encoder is not None:
            return _encoder

        try:
            from FlagEmbedding import BGEM3FlagModel
        except ImportError as exc:  # pragma: no cover
            _encoder = False  # genuinely missing package → hard-disable
            raise RuntimeError(
                "FlagEmbedding is not installed; install the [semantic] "
                "extra: pip install openconstructionerp[semantic]"
            ) from exc
        return _load_encoder_locked(BGEM3FlagModel)


def _load_encoder_locked(BGEM3FlagModel: Any) -> Any:  # noqa: N803
    """Inner load body — runs while holding :data:`_ENCODER_LOAD_LOCK`."""

    global _encoder

    s = get_settings()
    fp32_model = getattr(s, "cwicr_embedding_model", "BAAI/bge-m3") or "BAAI/bge-m3"
    use_int8 = getattr(s, "cwicr_embedding_int8", True)

    # Build the load plan. The INT8 ONNX checkpoint ships under a
    # separate HF repo (``gpahal/bge-m3-onnx-int8``) that contains ONLY
    # ``model_quantized.onnx`` — no ``pytorch_model.bin`` /
    # ``model.safetensors``. Some FlagEmbedding builds can't bootstrap
    # ``BGEM3FlagModel`` from an ONNX-only repo and raise
    # ``Error no file named pytorch_model.bin ...``. That used to stamp
    # the singleton ``False`` permanently, which silently turned EVERY
    # /match-elements vector run into a zero-candidate result (the
    # user-visible "match does nothing" bug). So: try INT8 first when
    # configured, but ALWAYS fall back to the canonical FP32
    # ``BAAI/bge-m3`` checkpoint before giving up. FP32 BGE-M3 is the
    # exact model the CWICR v3 collections were embedded with, so recall
    # is unaffected — only a little slower/heavier than INT8.
    attempts: list[tuple[str, bool]] = []
    if use_int8:
        attempts.append(("gpahal/bge-m3-onnx-int8", True))
    attempts.append((fp32_model, False))

    last_exc: Exception | None = None
    for model_id, is_int8 in attempts:
        logger.info("CWICR encoder: loading %s (int8=%s)", model_id, is_int8)
        try:
            _encoder = BGEM3FlagModel(model_id, use_fp16=not is_int8)
            if last_exc is not None:
                logger.warning(
                    "CWICR encoder: recovered on FP32 fallback %s after INT8 load failed (%s)",
                    model_id,
                    last_exc,
                )
            return _encoder
        except Exception as exc:  # noqa: BLE001 — try the next plan entry
            last_exc = exc
            logger.warning(
                "CWICR encoder: load of %s failed (%s) — %s",
                model_id,
                exc,
                "trying FP32 fallback" if is_int8 else "no more fallbacks",
            )

    # Every attempt failed. Do NOT stamp ``_encoder = False`` here — a
    # load failure is treated as transient/retryable (broken cache that
    # may get repaired, a concurrent-load race, transient OOM). The next
    # match call re-enters and retries the full plan. Only the
    # missing-package path above hard-disables the encoder.
    raise RuntimeError(f"CWICR encoder load failed: {last_exc}") from last_exc


def _encode(texts: list[str], *, with_resources: bool = False) -> dict[str, Any]:
    """Run BGE-M3 once and return dense + sparse vectors per input.

    Returns ``{"dense": list[list[float]], "sparse": list[SparseVector]}``
    where ``SparseVector`` is the qdrant_client native struct so the
    Query API accepts it as-is.
    """

    encoder = _get_encoder()
    out = encoder.encode(
        texts,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    # ``out["lexical_weights"]`` is a list of dict[token_id -> weight].
    from qdrant_client.http.models import SparseVector

    sparse_vectors: list[SparseVector] = []
    for weight_map in out["lexical_weights"]:
        # Qdrant SparseVector expects parallel index/value lists.
        # Token ids are stringified ints from FlagEmbedding — cast back.
        indices = [int(k) for k in weight_map]
        values = [float(v) for v in weight_map.values()]
        sparse_vectors.append(SparseVector(indices=indices, values=values))

    return {
        "dense": [list(map(float, v)) for v in out["dense_vecs"]],
        "sparse": sparse_vectors,
    }


# ── Per-collection capability discovery ──────────────────────────────────


def _collection_vectors(collection_name: str) -> frozenset[str]:
    """Return the set of named-vector keys a collection exposes.

    Cached per-process via :data:`_collection_vectors_cache` so the
    ``client.get_collection`` round-trip happens at most once per
    collection per backend boot. Unknown / unreachable collections
    resolve to an empty frozenset so the caller's "is the resources
    vector present?" probe degrades cleanly to "no" instead of raising.

    Used by :func:`search` to skip the ``resources`` prefetch when the
    target collection only carries ``dense`` + ``sparse`` (DDC v3
    snapshot shape). Without this, every match call against a snapshot
    install issued a ``Prefetch(using="resources", …)`` that Qdrant
    answered with a 404, forcing the ranker into the metadata-only
    fallback path (score ≈ 0.0002, opaque rate codes — see
    :doc:`memory/match_elements_three_filter_bugs`).
    """
    cached = _collection_vectors_cache.get(collection_name)
    if cached is not None:
        return cached

    try:
        client = _get_client()
        info = client.get_collection(collection_name)
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug(
            "qdrant_adapter: get_collection(%s) failed for capability probe: %s",
            collection_name,
            exc,
        )
        _collection_vectors_cache[collection_name] = frozenset()
        return _collection_vectors_cache[collection_name]

    # qdrant_client surfaces named vectors through
    # ``config.params.vectors`` (dict for multi-vector schemas) and
    # ``config.params.sparse_vectors`` for the sparse half. Both are
    # mappings keyed by the vector name; we union their keys so callers
    # can probe either kind via the same interface.
    names: set[str] = set()
    try:
        params = info.config.params  # type: ignore[union-attr]
        vectors = getattr(params, "vectors", None)
        if isinstance(vectors, dict):
            names.update(vectors.keys())
        elif vectors is not None:
            # Single unnamed vector — pre-multivector schema. Treat as
            # the canonical ``dense`` channel.
            names.add("dense")
        sparse = getattr(params, "sparse_vectors", None)
        if isinstance(sparse, dict):
            names.update(sparse.keys())
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug(
            "qdrant_adapter: capability extraction failed for %s: %s",
            collection_name,
            exc,
        )

    result = frozenset(names)
    _collection_vectors_cache[collection_name] = result
    return result


# Per-collection payload-key cache. Maps a collection name to the union
# of payload keys observed across a small sample of its points. Used to
# gate fragile hard filters (``ifc_class`` et al.) so they're only
# pinned when the bound collection actually carries that field — the
# DDC v3 CWICR snapshots (``cwicr_en_v3`` …) do NOT have an
# ``ifc_class`` payload, so pinning it eliminated every BIM-vs-cost
# candidate (the user-reported "/match-elements does nothing").
_collection_payload_keys_cache: dict[str, frozenset[str]] = {}


def collection_payload_keys(collection_name: str) -> frozenset[str]:
    """Return payload keys observed in a sample of ``collection_name``.

    Samples up to 32 points via a single ``scroll`` (no vector pulled)
    and unions their payload keys. Cached per-process. Returns an empty
    frozenset on any failure so callers treat "unknown schema" as "field
    absent" and degrade by *not* pinning the fragile filter — which is
    the safe direction (broader recall, never an empty result).
    """

    cached = _collection_payload_keys_cache.get(collection_name)
    if cached is not None:
        return cached

    keys: set[str] = set()
    try:
        client = _get_client()
        points, _ = client.scroll(
            collection_name=collection_name,
            limit=32,
            with_payload=True,
            with_vectors=False,
        )
        for p in points or []:
            pl = getattr(p, "payload", None) or {}
            keys.update(pl.keys())
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug(
            "qdrant_adapter: payload-key probe for %s failed: %s",
            collection_name,
            exc,
        )
        keys = set()

    result = frozenset(keys)
    _collection_payload_keys_cache[collection_name] = result
    return result


def collection_has_payload_field(country: str | None, field: str) -> bool:
    """True when the catalogue bound to ``country`` carries ``field``.

    Resolves the region → collection (honouring the language-fallback
    substitution) and probes that collection's sampled payload schema.
    Conservative: returns ``False`` when the schema can't be determined
    so the caller drops the fragile hard filter instead of pinning a
    field that would zero out the result set.
    """

    try:
        collection = country_to_collection(country)
    except Exception:  # noqa: BLE001
        return False
    return field in collection_payload_keys(collection)


def _qdrant_collection_points(collection_name: str) -> int:
    """Return the point count of ``collection_name`` (0 on any failure).

    Tries the exact name, then the ``_v?``-stripped base (covers dev
    installs that ingested before the v3 rename). Never raises — callers
    use this only as a "does this catalogue actually have data" signal,
    so an unreachable Qdrant collapses to 0 and the legacy SQL-only
    behaviour is preserved by the caller.
    """

    try:
        client = _get_client()
        try:
            info = client.get_collection(collection_name)
        except Exception:
            base = collection_name.rsplit("_v", 1)[0] if "_v" in collection_name else collection_name
            if base == collection_name:
                return 0
            info = client.get_collection(base)
        return int(getattr(info, "points_count", None) or getattr(info, "vectors_count", 0) or 0)
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug(
            "qdrant_adapter: point count for %s failed: %s",
            collection_name,
            exc,
        )
        return 0


# ── Public API ───────────────────────────────────────────────────────────


def _build_filter(filters: dict[str, Any]) -> Any | None:
    """Translate the adapter's filter contract to a qdrant_client Filter.

    Recognises the 29 indexed payload fields documented in
    MAPPING_PROCESS.md §2.2. Each key on the input dict translates to
    a Qdrant ``must`` predicate; lists / tuples / sets become ``MatchAny``
    (OR-of-values), scalars become ``MatchValue`` (exact match).
    Booleans are coerced to ``bool()`` so a stray "true"/"1" string
    doesn't accidentally pin to a literal-string predicate.

    Recognised keys (all optional — callers pass only what they need):

    * Boolean flags (Pset-derived): ``is_abstract``, ``is_external``,
      ``is_loadbearing``, ``is_structural``, ``is_machine``,
      ``is_material``, ``is_finishing``, ``is_temporary``,
      ``is_compound``.
    * IFC / OST classification: ``ifc_class``, ``ifc_predefined_type``,
      ``ost_category``, ``applies_to_ifc_classes``.
    * CSI / DIN: ``masterformat_division``, ``csi_division_2``,
      ``department_code``, ``subsection_code``.
    * Categorisation: ``category_type``, ``collection_name``,
      ``construction_stage``, ``uniformat_group``,
      ``classification_confidence``, ``equipment_class``.
    * Physical: ``unit_type``, ``unit_dim``, ``rate_unit``,
      ``nominal_size_mm``, ``material_class``, ``installation_method``.
    * Metadata: ``country``, ``rate_code``.

    Returns ``None`` when the filter dict is empty so the caller can
    omit it from the Query API call.
    """

    if not filters:
        return None

    from qdrant_client.http.models import (
        FieldCondition,
        Filter,
        MatchAny,
        MatchValue,
    )

    must: list[FieldCondition] = []

    # Boolean flags — coerced to ``bool()`` so polluted inputs
    # ("true" / "1" / 0.0) don't sneak through as type-mismatched
    # MatchValue predicates that Qdrant would reject silently.
    _BOOL_KEYS = (
        "is_abstract",
        "is_external",
        "is_loadbearing",
        "is_structural",
        "is_machine",
        "is_material",
        "is_finishing",
        "is_temporary",
        "is_compound",
    )
    for key in _BOOL_KEYS:
        if key in filters and filters[key] is not None:
            must.append(
                FieldCondition(
                    key=key,
                    match=MatchValue(value=bool(filters[key])),
                )
            )

    # Scalar / list-of-scalar fields. Order matches the v3 §2.2 listing
    # so the next maintainer can compare visually with MAPPING_PROCESS.md.
    _SCALAR_KEYS = (
        "country",
        "ifc_class",
        "ifc_predefined_type",
        "ost_category",
        "applies_to_ifc_classes",
        "masterformat_division",
        "csi_division_2",
        "category_type",
        "collection_name",
        "department_code",
        "subsection_code",
        "unit_type",
        "unit_dim",
        "rate_unit",
        "material_class",
        "installation_method",
        "construction_stage",
        "uniformat_group",
        "equipment_class",
        "classification_confidence",
        "rate_code",
        "nominal_size_mm",
    )
    for key in _SCALAR_KEYS:
        val = filters.get(key)
        if val is None:
            continue
        if isinstance(val, list | tuple | set):
            must.append(FieldCondition(key=key, match=MatchAny(any=list(val))))
        else:
            must.append(FieldCondition(key=key, match=MatchValue(value=val)))

    if not must:
        return None
    return Filter(must=must)


async def search(
    *,
    country: str,
    core_query: str,
    resources_query: str | None = None,
    filters: dict[str, Any] | None = None,
    limit: int = 30,
    prefetch_limit: int = 50,
) -> list[QdrantHit]:
    """Hybrid CWICR search across dense + sparse (+ optional resources).

    One Qdrant call, three prefetches, RRF fusion native to the Query
    API. Returns up to ``limit`` :class:`QdrantHit` rows ranked by the
    fused score, payload-only. Call :func:`lookup_full_rows` afterwards
    to attach the 84-column parquet data.

    ``country`` is the region or country code passed to
    :func:`country_to_collection`. ``filters`` follows the contract in
    :func:`_build_filter`.
    """

    collection = country_to_collection(country)
    # v3: a single language collection holds rates from multiple
    # countries. Auto-pin the country payload predicate when the
    # caller passed a specific region id; respect any explicit
    # ``country`` already in ``filters`` so callers can override the
    # auto-pin (e.g. cross-language search where they want all the
    # German rates regardless of region).
    merged_filters: dict[str, Any] = dict(filters or {})
    if "country" not in merged_filters:
        auto_country = country_filter_for(country)
        if auto_country:
            merged_filters["country"] = auto_country
    qdrant_filter = _build_filter(merged_filters)

    # Probe the collection's named-vector set BEFORE encoding the
    # resources query. The DDC v3 snapshot ships only ``dense`` +
    # ``sparse`` — issuing a ``Prefetch(using="resources", …)`` against
    # such a collection 404s the entire query API call and the ranker
    # falls through to metadata-only (score ≈ 0). Skipping the encode
    # when the vector isn't there saves a BGE-M3 forward pass on every
    # match request against a snapshot install.
    vectors_available = _collection_vectors(collection)
    use_resources = bool(resources_query and (not vectors_available or "resources" in vectors_available))
    if resources_query and not use_resources:
        logger.debug(
            "qdrant_adapter: collection %s has no 'resources' named vector (available=%s); skipping resources prefetch",
            collection,
            sorted(vectors_available) if vectors_available else "unknown",
        )

    # Encode both queries in one forward pass when resources_query is set
    # AND the collection actually carries the resources named vector.
    texts = [core_query]
    if use_resources:
        texts.append(resources_query)  # type: ignore[arg-type]
    encoded = _encode(texts)
    core_dense = encoded["dense"][0]
    core_sparse = encoded["sparse"][0]
    res_dense = encoded["dense"][1] if use_resources else None

    from qdrant_client.http.models import (
        Fusion,
        FusionQuery,
        Prefetch,
    )

    prefetch: list[Prefetch] = [
        Prefetch(
            query=core_dense,
            using="dense",
            filter=qdrant_filter,
            limit=prefetch_limit,
        ),
        Prefetch(
            query=core_sparse,
            using="sparse",
            filter=qdrant_filter,
            limit=prefetch_limit,
        ),
    ]
    if res_dense is not None:
        prefetch.append(
            Prefetch(
                query=res_dense,
                using="resources",
                filter=qdrant_filter,
                limit=prefetch_limit,
            )
        )

    client = _get_client()
    try:
        response = client.query_points(
            collection_name=collection,
            prefetch=prefetch,
            query=FusionQuery(fusion=Fusion.RRF),
            with_payload=True,
            with_vectors=False,
            limit=limit,
        )
    except Exception:
        # Dev installs that ingested CWICR before the v3 collection
        # rename keep the bare ``cwicr_<lang>`` collection. Strip the
        # ``_v?`` tail and retry once so a stale ``CWICR_COLLECTION_VERSION``
        # doesn't break search on those hosts.
        base = collection.rsplit("_v", 1)[0] if "_v" in collection else collection
        if base == collection:
            raise
        response = client.query_points(
            collection_name=base,
            prefetch=prefetch,
            query=FusionQuery(fusion=Fusion.RRF),
            with_payload=True,
            with_vectors=False,
            limit=limit,
        )

    hits: list[QdrantHit] = []
    for point in response.points:
        payload = point.payload or {}
        rate_code = str(payload.get("rate_code") or point.id)
        hits.append(
            QdrantHit(
                rate_code=rate_code,
                country=str(payload.get("country", country)),
                score=float(point.score or 0.0),
                payload=dict(payload),
            )
        )
    return hits


async def lookup_full_rows(
    *,
    country: str,
    rate_codes: list[str],
) -> list[dict[str, Any]]:
    """Attach the 84-column parquet data to a list of rate codes.

    Thin proxy onto :mod:`app.modules.costs.parquet_lookup` so the
    ranker stays on a single ``qdrant_adapter`` import. Returns rows in
    the same order as ``rate_codes`` — codes that don't match in the
    parquet are dropped silently (the caller can re-correlate by
    ``rate_code`` if order matters).
    """

    from app.modules.costs.parquet_lookup import lookup_rows

    return await lookup_rows(country=country, rate_codes=rate_codes)


async def search_by_filter(
    *,
    country: str,
    filters: dict[str, Any] | None = None,
    limit: int = 100,
) -> list[QdrantHit]:
    """Filter-only fetch — no vector encoding, no fusion.

    Pulls candidates by Qdrant payload filter using the scroll API. The
    rows come back with ``score=0.0`` because there is no vector query
    to score against; the caller is expected to score them using
    metadata signals (lexical overlap, region match, unit family,
    material match, classification).

    This is the encoder-free path. When the BGE-M3 / sentence-transformers
    encoder is offline (broken HF cache, missing extras, slow first cold
    download), the hybrid :func:`search` raises; the ranker falls
    through to this function so the user still gets a deterministic
    candidate set ranked on payload signals instead of a blank list.

    Falls back to the versionless collection name on lookup failure,
    same logic as :func:`search` (covers dev installs that ingested
    pre-v3 without flipping ``CWICR_COLLECTION_VERSION``).
    """

    collection = country_to_collection(country)
    merged_filters: dict[str, Any] = dict(filters or {})
    if "country" not in merged_filters:
        auto_country = country_filter_for(country)
        if auto_country:
            merged_filters["country"] = auto_country
    qdrant_filter = _build_filter(merged_filters)

    client = _get_client()
    try:
        points, _ = client.scroll(
            collection_name=collection,
            scroll_filter=qdrant_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
    except Exception:
        base = collection.rsplit("_v", 1)[0] if "_v" in collection else collection
        if base == collection:
            return []
        try:
            points, _ = client.scroll(
                collection_name=base,
                scroll_filter=qdrant_filter,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("search_by_filter: scroll failed for %s / %s: %s", collection, base, exc)
            return []

    hits: list[QdrantHit] = []
    for point in points:
        payload = point.payload or {}
        rate_code = str(payload.get("rate_code") or point.id)
        hits.append(
            QdrantHit(
                rate_code=rate_code,
                country=str(payload.get("country", country)),
                score=0.0,
                payload=payload,
            )
        )
    return hits


# ── v3-P7: Search hardening ──────────────────────────────────────────────
#
# A naive ``search()`` against the indexed CWICR collections will under-
# return when the SearchPlan emits too many hard filters at once. The
# fallback ladder, dedup pass, and abstract-substitution step below turn
# the raw Qdrant call into a robust top-K builder for the ranker.
#
# Per MAPPING_PROCESS.md v3 §5.2 the relaxation order trades the most
# specific signals first (``ifc_predefined_type``, ``construction_stage``)
# and keeps the bedrock predicates (``country``, ``unit_dim``,
# ``ifc_class``, ``is_abstract=False``) until last — those define the
# "this rate is in the right ballpark" baseline. The Pset booleans are
# dropped together because they are highly correlated and dropping just
# one rarely opens a meaningful new candidate set.

# Filter keys removed at each tier — earlier tiers preserve more
# specificity, later tiers progressively strip down to the bedrock.
# A ``None`` entry means "no relaxation" (final tier yields the full
# original filter set).
_RELAX_TIERS: tuple[tuple[str, ...], ...] = (
    (),  # tier 0 — full filter set
    ("ifc_predefined_type",),  # tier 1 — drop subtype
    ("ifc_predefined_type", "construction_stage"),  # tier 2 — drop stage too
    (
        "ifc_predefined_type",
        "construction_stage",
        "is_external",
        "is_loadbearing",
        "is_structural",
    ),  # tier 3 — drop Psets
    (
        "ifc_predefined_type",
        "construction_stage",
        "is_external",
        "is_loadbearing",
        "is_structural",
        "department_code",
        "subsection_code",
    ),  # tier 4 — drop trade bucket
    (
        "ifc_predefined_type",
        "construction_stage",
        "is_external",
        "is_loadbearing",
        "is_structural",
        "department_code",
        "subsection_code",
        "unit_dim",
    ),  # tier 5 — drop unit dim
)


# Defensive unit-dim aliasing for sources that haven't migrated to the
# canonical ``unit_dim`` enum (m, m2, m3, kg, pcs, lsum). The values
# here are the *canonical* form returned to the ranker so downstream
# boost / dedup logic can rely on a single representation.
_UNIT_DIM_ALIASES: dict[str, str] = {
    "m³": "m3",
    "м³": "m3",
    "cubic_meter": "m3",
    "cubic_metre": "m3",
    "m²": "m2",
    "м²": "m2",
    "square_meter": "m2",
    "square_metre": "m2",
    "m": "m",
    "м": "m",
    "linear_meter": "m",
    "linear_metre": "m",
    "kg": "kg",
    "кг": "kg",
    "kilogram": "kg",
    "t": "t",
    "ton": "t",
    "tonne": "t",
    "tonnes": "t",
    "т": "t",
    "pcs": "pcs",
    "шт": "pcs",
    "piece": "pcs",
    "pieces": "pcs",
    "stk": "pcs",
    "lsum": "lsum",
    "ls": "lsum",
    "lump_sum": "lsum",
}


def _normalise_unit_dim(value: str | None) -> str | None:
    """Return the canonical ``unit_dim`` form or ``None`` for empty input.

    Lookup is case-insensitive and tolerant of typographic variants
    (``m³`` vs ``m3``, Cyrillic ``м²``). Unknown values are returned
    verbatim — the parquet/Qdrant payload may use a vendor-specific
    unit that the alias table doesn't yet know, and we'd rather pin
    that filter than silently drop it.
    """

    if value is None:
        return None
    raw = str(value).strip().lower()
    if not raw:
        return None
    return _UNIT_DIM_ALIASES.get(raw, raw)


def _dedup_hits(hits: list[QdrantHit]) -> list[QdrantHit]:
    """Drop duplicate ``rate_code`` rows, keeping the highest score.

    Duplicates surface in two situations:

    1. Cross-language fan-out (planned for v3-P8 ``base_code`` rollup) —
       the same rate code appears in DE+EN+RU collections and we want
       only the top-scoring representative.
    2. Defensive coding for collections that accidentally hold both an
       abstract section header and an alias row keyed by the same
       ``rate_code`` (a known pre-v3 data quality issue).

    Order is preserved: the first occurrence wins, so the caller's
    sort order is respected.
    """

    seen: set[str] = set()
    out: list[QdrantHit] = []
    for h in hits:
        if h.rate_code in seen:
            continue
        seen.add(h.rate_code)
        out.append(h)
    return out


def _filters_after_relax(filters: dict[str, Any] | None, drop_keys: tuple[str, ...]) -> dict[str, Any]:
    """Return a shallow copy of ``filters`` with ``drop_keys`` removed.

    Used by :func:`search_with_fallback` to walk the relax ladder
    without mutating the caller's dict — pure-function semantics make
    the tier sequence trivially testable.
    """

    if not filters:
        return {}
    return {k: v for k, v in filters.items() if k not in drop_keys}


# ── v3-P8: Cross-language identity via base_code() ────────────────────────
#
# A CWICR rate code carries optional metadata suffixes:
#
#     03.330.10.de.m3
#     │  │   │  │  └─ unit suffix (one of canonical _UNIT_DIM_ALIASES values)
#     │  │   │  └──── language suffix (ISO-639-1 from REGION_LANGUAGE)
#     │  │   └─────── item ordinal
#     │  └─────────── subsection
#     └────────────── department
#
# The "base code" strips up to two trailing dotted segments where each
# segment is either a known language tag or a canonical unit_dim. This
# lets the ranker dedup the same logical rate across language collections
# (a German wall rate and its English translation share the same base
# code even though they live in different Qdrant collections).
#
# Codes without recognisable suffixes pass through unchanged so non-CWICR
# catalogues — BR SINAPI numeric codes, vendor-specific BYO rates — are
# never accidentally truncated.


def _canonical_unit_dims() -> set[str]:
    """Return the canonical unit_dim set used as suffix sentinels.

    Built from :data:`_UNIT_DIM_ALIASES` *values* (the canonical forms),
    not keys (the alias spellings). Computed lazily so the module import
    stays cheap.
    """
    return set(_UNIT_DIM_ALIASES.values())


def _known_language_tags() -> set[str]:
    """Return ISO-639-1 tags known to :mod:`region_language`.

    Pulls from REGION_LANGUAGE values + bare-country override values so
    every language we route a collection to is recognised as a valid
    suffix sentinel. Imported lazily to keep this adapter independent of
    region_language at import time (circular-import insurance).
    """
    from app.core.match_service.region_language import (
        _BARE_COUNTRY_OVERRIDES,
        REGION_LANGUAGE,
    )

    return set(REGION_LANGUAGE.values()) | set(_BARE_COUNTRY_OVERRIDES.values())


def base_code(rate_code: str | None) -> str:
    """Strip ``.{lang}`` and ``.{unit}`` suffixes for cross-language dedup.

    Walks the dotted segments from the right end and removes a segment
    iff it matches a known language tag or canonical unit_dim. Stops at
    the first non-matching segment so the structural prefix
    (``department.subsection.item``) is preserved verbatim.

    Examples (using the canonical unit set m/m2/m3/kg/t/pcs/lsum and the
    full REGION_LANGUAGE language set)::

        base_code("03.330.10.de.m3")  → "03.330.10"
        base_code("03.330.10.m3.de")  → "03.330.10"        # order-agnostic
        base_code("03.330.10.de")     → "03.330.10"        # only lang
        base_code("03.330.10.m3")     → "03.330.10"        # only unit
        base_code("03.330.10")        → "03.330.10"        # bare prefix
        base_code("87437")            → "87437"            # SINAPI numeric
        base_code("CUSTOM-XYZ")       → "CUSTOM-XYZ"       # BYO vendor code
        base_code("03.330.10.xx.yy")  → "03.330.10.xx.yy"  # unknown suffixes

    Returns the empty string for a falsy input — callers feed ``payload
    .get("rate_code")`` directly without a None-check.
    """

    if not rate_code:
        return ""

    sentinels = _canonical_unit_dims() | _known_language_tags()
    parts = str(rate_code).split(".")

    # Strip up to TWO suffix segments — one lang, one unit (or two of
    # the same kind, defensively, e.g. ``.de.de`` from a buggy seed).
    # Stop at the first non-sentinel so structural codes survive.
    stripped = 0
    while stripped < 2 and len(parts) > 1 and parts[-1].lower() in sentinels:
        parts.pop()
        stripped += 1

    return ".".join(parts)


def _dedup_hits_by_base_code(hits: list[QdrantHit]) -> list[QdrantHit]:
    """Cross-language dedup: keep the highest-score representative per base code.

    Cross-language fan-out (querying ``cwicr_de_v3`` AND ``cwicr_en_v3``
    for a translation-aware project) surfaces the same logical rate
    twice. This collapses them keeping the version that scored highest
    in RRF — typically the one whose collection's language matches the
    user's query language, which is the desired UX.

    Differs from :func:`_dedup_hits` by grouping on ``base_code`` rather
    than the full ``rate_code``: ``03.330.10.de.m3`` and
    ``03.330.10.en.m3`` map to the same key ``03.330.10``.

    First-seen-highest-scored wins — assumes the input is sorted by
    score descending (RRF output already is).
    """

    seen_bases: dict[str, QdrantHit] = {}
    for h in hits:
        key = base_code(h.rate_code) or h.rate_code
        existing = seen_bases.get(key)
        if existing is None or h.score > existing.score:
            seen_bases[key] = h

    # Preserve original input order among the survivors so the caller's
    # RRF rank is respected (not re-sorted).
    seen: set[int] = set()
    out: list[QdrantHit] = []
    for h in hits:
        key = base_code(h.rate_code) or h.rate_code
        if id(seen_bases[key]) in seen:
            continue
        if seen_bases[key] is h:
            seen.add(id(h))
            out.append(h)
    return out


async def cross_language_search(
    *,
    primary_country: str,
    additional_countries: list[str],
    core_query: str,
    resources_query: str | None = None,
    filters: dict[str, Any] | None = None,
    limit: int = 30,
    prefetch_limit: int = 50,
) -> list[QdrantHit]:
    """Fan-out :func:`search` across multiple language collections, dedup by base code.

    The primary country's collection is queried first so its rates anchor
    the result list — if a base code is shared between primary and
    additional collections, the primary-language version wins (assuming
    its score is competitive; the dedup is highest-score-wins).

    ``additional_countries`` is a list of region/country codes to also
    probe. Empty list (default) is equivalent to a single :func:`search`
    call against ``primary_country``.

    The fan-out is parallelised — one ``asyncio.gather`` so total latency
    is dominated by the slowest collection, not the sum.

    Returns up to ``limit`` deduped hits. Results across collections
    aren't re-ranked: the primary collection's ranking is preserved
    until the additional collections contribute genuinely new bases.
    """

    import asyncio

    countries = [primary_country, *additional_countries]
    # De-dup the country list itself — a caller might pass DE_BERLIN
    # twice or include the primary in additional by mistake. Preserve
    # order so the primary stays first.
    seen_countries: set[str] = set()
    unique_countries: list[str] = []
    for c in countries:
        coll = country_to_collection(c) if c else ""
        if coll and coll not in seen_countries:
            seen_countries.add(coll)
            unique_countries.append(c)

    if not unique_countries:
        return []

    coros = [
        search(
            country=c,
            core_query=core_query,
            resources_query=resources_query,
            filters=filters,
            limit=limit,
            prefetch_limit=prefetch_limit,
        )
        for c in unique_countries
    ]
    results = await asyncio.gather(*coros, return_exceptions=True)

    merged: list[QdrantHit] = []
    for c, res in zip(unique_countries, results, strict=False):
        if isinstance(res, Exception):
            logger.debug("cross_language_search: %s failed (%s)", c, res)
            continue
        merged.extend(res)

    deduped = _dedup_hits_by_base_code(merged)
    return deduped[:limit]


def _enumerate_target_codes(base: str, target_country: str) -> list[str]:
    """Enumerate plausible ``rate_code`` variants for ``base`` in ``target_country``.

    Used by :func:`cross_lang_lookup` to translate a rate code from one
    language collection to its sibling in another. The CWICR encoder
    appends ``.{lang}`` and / or ``.{unit}`` suffixes when it materialises
    per-language code variants — but the suffix order, presence, and
    cardinality vary across regions and snapshot vintages. Rather than
    hard-code one shape we enumerate every plausible permutation and let
    Qdrant's ``MatchAny`` resolve it in a single round-trip.

    The output is bounded: 1 (bare) + 1 (lang) + N units + N (lang.unit) +
    N (unit.lang) ≤ 2 + 3·|units|. With the canonical 7-element unit set
    that's at most 23 variants — well within Qdrant's payload-match cap.
    """

    from app.core.match_service.region_language import language_for

    target_lang = (language_for(target_country) or "").lower()
    units = sorted(_canonical_unit_dims())

    out: list[str] = [base]
    if target_lang:
        out.append(f"{base}.{target_lang}")
    for u in units:
        out.append(f"{base}.{u}")
        if target_lang:
            out.append(f"{base}.{target_lang}.{u}")
            out.append(f"{base}.{u}.{target_lang}")
    return out


async def cross_lang_lookup(
    *,
    source_rate_code: str,
    target_country: str,
) -> str | None:
    """Translate a rate_code into the ``target_country``'s language variant.

    Implements MAPPING_PROCESS.md §6.2 "точный подход" (exact approach):
    when a project's documentation is in EN but the estimate must be in
    RU rates, we want the *same* logical rate as a RU code with RU
    prices, not just a multilingual fan-out (which would surface the EN
    rate dressed in RU clothing).

    Algorithm:

    1. Strip ``.{lang}.{unit}`` suffixes from ``source_rate_code`` via
       :func:`base_code`. ``"03.330.10.en.m3"`` → ``"03.330.10"``.
    2. Enumerate plausible target-language variants
       (:func:`_enumerate_target_codes`).
    3. Single Qdrant scroll on ``country_to_collection(target_country)``
       with ``MatchAny`` on ``rate_code`` — at most one round-trip.
    4. When the target language collection mixes regions (ES collection
       carries ES + MX + AR), narrow further with the
       :func:`country_filter_for` predicate so the lookup honours the
       caller's region pin.

    Returns the matching ``rate_code`` string when found, else ``None``.
    Defensive: degrades to ``None`` on any Qdrant error / missing extras
    rather than raising, so the caller can fall back to semantic search.

    Examples::

        await cross_lang_lookup(
            source_rate_code="03.330.10.en.m3",
            target_country="RU_MOSCOW",
        )
        # → "03.330.10.ru.m3"  (or whatever the RU snapshot uses)

        await cross_lang_lookup(
            source_rate_code="FER46-01-001",
            target_country="DE_BERLIN",
        )
        # → None  (FER codes have no DE counterpart)
    """

    if not source_rate_code or not target_country:
        return None

    base = base_code(source_rate_code)
    if not base:
        return None

    coll = country_to_collection(target_country)
    if not coll:
        return None

    candidates = _enumerate_target_codes(base, target_country)

    try:
        from qdrant_client.http.models import (  # noqa: PLC0415
            FieldCondition,
            Filter,
            MatchAny,
            MatchValue,
        )

        client = _get_client()
        must: list[FieldCondition] = [
            FieldCondition(key="rate_code", match=MatchAny(any=candidates)),
        ]
        country_pin = country_filter_for(target_country)
        if country_pin:
            must.append(
                FieldCondition(key="country", match=MatchValue(value=country_pin)),
            )

        # Sync qdrant_client.scroll — mirrors the pattern used by
        # :func:`search` (see ``client.query_points`` callsite).
        points, _next = client.scroll(
            collection_name=coll,
            scroll_filter=Filter(must=must),
            limit=1,
            with_payload=["rate_code"],
            with_vectors=False,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.debug(
            "cross_lang_lookup: %r → %s lookup failed: %s",
            source_rate_code,
            target_country,
            exc,
        )
        return None

    if not points:
        return None

    found = str(points[0].payload.get("rate_code") or "").strip()
    return found or None


async def search_with_fallback(
    *,
    country: str,
    core_query: str,
    resources_query: str | None = None,
    filters: dict[str, Any] | None = None,
    limit: int = 30,
    prefetch_limit: int = 50,
    min_results: int | None = None,
) -> tuple[list[QdrantHit], int]:
    """Hardened :func:`search` with relax-tier fallback and dedup.

    Walks :data:`_RELAX_TIERS` until the result set has at least
    ``min_results`` hits or the bedrock filters are reached. Returns
    ``(hits, tier_used)`` so the caller can log which tier earned the
    candidates — useful for v3-P10 analytics on filter-set tightness.

    ``min_results`` defaults to ``max(1, limit // 4)`` — i.e., we try
    to keep at least a quarter of the requested limit. Setting it to
    ``limit`` forces full relaxation; setting it to ``0`` disables
    fallback entirely (single tier-0 call).
    """

    threshold = min_results if min_results is not None else max(1, limit // 4)
    last_hits: list[QdrantHit] = []
    last_tier = 0
    for tier_idx, drop_keys in enumerate(_RELAX_TIERS):
        relaxed = _filters_after_relax(filters, drop_keys)
        hits = await search(
            country=country,
            core_query=core_query,
            resources_query=resources_query,
            filters=relaxed,
            limit=limit,
            prefetch_limit=prefetch_limit,
        )
        deduped = _dedup_hits(hits)
        last_hits = deduped
        last_tier = tier_idx
        if len(deduped) >= threshold:
            if tier_idx > 0:
                logger.info(
                    "qdrant_adapter: relaxed to tier %d (dropped %s) for %d hits",
                    tier_idx,
                    drop_keys,
                    len(deduped),
                )
            return deduped, tier_idx
    return last_hits, last_tier


async def substitute_abstract_parents(
    *,
    country: str,
    core_query: str,
    hits: list[QdrantHit],
    max_substitutions: int = 2,
    children_per_parent: int = 3,
) -> list[QdrantHit]:
    """Replace ``is_abstract=True`` rows with concrete children.

    Section headers (e.g., DIN 276 KG-330 "Außenwände") are valuable
    semantically — the dense vector hits them when the query is broad —
    but worthless as cost rates because they have no unit price. v3
    indexes them with ``is_abstract=True`` so the ranker can spot them
    and issue a narrow follow-up search constrained to the same
    ``department_code`` / ``subsection_code`` with ``is_abstract=False``.

    Only the top ``max_substitutions`` abstract hits trigger follow-ups
    so the latency cost stays bounded (each follow-up is one Qdrant
    Query API call). Concrete children are spliced in at the abstract
    parent's original rank position; their order among themselves is
    the RRF order returned by the follow-up call.

    Hits without an abstract row pass through unchanged.
    """

    if not hits:
        return hits

    out: list[QdrantHit] = []
    substitutions_done = 0
    seen_codes: set[str] = {h.rate_code for h in hits if not h.payload.get("is_abstract")}

    for hit in hits:
        if not hit.payload.get("is_abstract"):
            out.append(hit)
            continue
        if substitutions_done >= max_substitutions:
            # Past the budget — keep the abstract as-is so the caller
            # at least knows there's a section-header candidate.
            out.append(hit)
            continue

        # Build a follow-up filter that pins the same trade bucket but
        # excludes the section header. ``subsection_code`` is preferred
        # when present (more specific); fall back to ``department_code``.
        sub_filters: dict[str, Any] = {"is_abstract": False}
        sub_code = hit.payload.get("subsection_code")
        dept_code = hit.payload.get("department_code")
        if sub_code:
            sub_filters["subsection_code"] = sub_code
        elif dept_code:
            sub_filters["department_code"] = dept_code
        else:
            # No trade bucket to narrow on → keep the abstract as-is.
            out.append(hit)
            continue

        try:
            children = await search(
                country=country,
                core_query=core_query,
                filters=sub_filters,
                limit=children_per_parent,
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("substitute_abstract_parents: follow-up failed (%s)", exc)
            out.append(hit)
            continue

        added_any = False
        for child in children:
            if child.rate_code in seen_codes:
                continue
            seen_codes.add(child.rate_code)
            out.append(child)
            added_any = True

        if not added_any:
            # Children were all dupes of existing concrete hits — keep
            # the abstract so the caller can decide what to do.
            out.append(hit)
        substitutions_done += 1

    return out


__all__ = [
    "QdrantHit",
    "base_code",
    "country_filter_for",
    "country_to_collection",
    "cross_lang_lookup",
    "cross_language_search",
    "lookup_full_rows",
    "search",
    "search_with_fallback",
    "substitute_abstract_parents",
]

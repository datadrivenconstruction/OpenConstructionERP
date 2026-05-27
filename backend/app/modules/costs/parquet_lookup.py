# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Polars-based lookup for CWICR's full 84-column rate data.

The Qdrant store (:mod:`app.modules.costs.qdrant_adapter`) carries a
deliberately narrow payload — only the keys and the columns the Query
API filters on. Heavy fields (prices, labor lines, full resource list,
budget sums, regional adjustments) live in per-region parquet:

    <CWICR_PARQUET_ROOT>/<XX>___DDC_CWICR/
        <region>_workitems_costs_resources_DDC_CWICR.parquet

This module memoises a :func:`polars.scan_parquet` lazy frame per
country and returns rows by ``rate_code`` in O(50ms) on warm cache.

Why polars (not pandas)
-----------------------

* ``scan_parquet`` is mmap-backed and lazy — we never materialise the
  full 50-100K-row DataFrame for an N-row lookup.
* Predicate pushdown means the parquet engine only reads the row groups
  that contain the wanted ``rate_code`` values.
* Already in the dependency budget for the new pipeline; no need to
  share pandas' GIL contention with the rest of the request lifecycle.

Resolution order
----------------

1. Explicit ``cwicr_parquet_root`` setting in :class:`AppSettings`.
2. ``CWICR_PARQUET_ROOT`` environment variable.
3. ``~/.openestimator/cwicr/`` (consistent with the embedded Qdrant
   default).

The module is import-safe even when ``polars`` is missing — heavy
imports happen on first call so a fresh install without the
``[semantic]`` extra still boots.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)


# Per-region parquet filename pattern. The DDC pipeline ships these as
# ``<XX>___DDC_CWICR/<REGION>_workitems_costs_resources_DDC_CWICR.parquet``;
# we discover them dynamically per country code so a tenant can add a
# new region by dropping the directory in without code changes.
_PARQUET_GLOB = "*_workitems_costs_resources_DDC_CWICR.parquet"


def _resolve_root() -> Path:
    """‌⁠‍Return the configured CWICR parquet root.

    Created on first call if it doesn't exist (the empty case is
    handled by the per-country resolver — a missing parquet for a given
    country surfaces as an empty result, not an exception).
    """

    s = get_settings()
    raw = (
        getattr(s, "cwicr_parquet_root", "")
        or os.environ.get("CWICR_PARQUET_ROOT", "")
        or os.path.expanduser("~/.openestimator/cwicr")
    )
    return Path(raw)


@lru_cache(maxsize=64)
def _parquet_for_country(country: str) -> Path | None:
    """‌⁠‍Resolve the parquet file for a given country code, or ``None``.

    Memoised so repeated lookups skip the directory scan. The cache key
    is the upper-cased country head so ``DE_BERLIN`` and ``DE`` resolve
    to the same parquet.
    """

    root = _resolve_root()
    if not root.exists():
        logger.debug("CWICR parquet root missing: %s", root)
        return None

    head = (country or "").strip().upper().split("_", 1)[0]
    if not head:
        return None

    # Try a few directory shapes the DDC pipeline emits:
    #   <ROOT>/<XX>___DDC_CWICR/<region>.parquet
    #   <ROOT>/<region>.parquet
    candidates: list[Path] = []
    for sub in root.iterdir():
        if sub.is_dir() and head in sub.name.upper():
            candidates.extend(sub.glob(_PARQUET_GLOB))
    candidates.extend(root.glob(_PARQUET_GLOB))

    for path in candidates:
        if head in path.name.upper():
            return path

    logger.debug("CWICR parquet not found for country=%s under %s", head, root)
    return None


@lru_cache(maxsize=32)
def _scan(parquet_path: str) -> Any:
    """Memoised lazy frame for a single parquet file.

    The ``lru_cache`` keeps one ``LazyFrame`` per file so repeated
    lookups share the parquet metadata read. The frame itself is
    cheap (no materialisation) but the file-open + schema-read cost
    is non-trivial across many small lookups.
    """

    try:
        import polars as pl
    except ImportError as exc:  # pragma: no cover — optional [semantic] extra
        raise RuntimeError(
            "polars is not installed; install the [semantic] extra: pip install openconstructionerp[semantic]"
        ) from exc

    return pl.scan_parquet(parquet_path)


async def lookup_rows(
    *,
    country: str,
    rate_codes: list[str],
) -> list[dict[str, Any]]:
    """Return full parquet rows for the given rate codes, in input order.

    Codes that don't match in the parquet are dropped silently — the
    caller can re-correlate by the ``rate_code`` field on each returned
    row when input-order alignment matters. Empty input or missing
    parquet returns ``[]``.
    """

    if not rate_codes:
        return []

    parquet_path = _parquet_for_country(country)
    if parquet_path is None:
        logger.warning("CWICR parquet lookup skipped: no parquet for country=%s", country)
        return []

    try:
        import polars as pl
    except ImportError:  # pragma: no cover
        return []

    lf = _scan(str(parquet_path))
    # Predicate pushdown: polars only reads the row groups containing
    # any of these codes. ``collect()`` materialises only the matching
    # rows, not the whole 50K-row frame.
    df = lf.filter(pl.col("rate_code").is_in(rate_codes)).collect()

    rows = df.to_dicts()
    # Preserve input order so the caller can zip(rate_codes, rows).
    by_code = {str(r.get("rate_code")): r for r in rows}
    return [by_code[code] for code in rate_codes if code in by_code]


def parquet_root() -> Path:
    """Public accessor for the resolved parquet root.

    Used by smoke-test endpoints to surface the configured path in
    diagnostics ("/api/v1/costs/qdrant-search/?diag=1").
    """

    return _resolve_root()


def parquet_path_for_country(country: str) -> Path | None:
    """Public accessor for per-country parquet resolution.

    Mirrors the internal :func:`_parquet_for_country` so smoke probes
    can confirm a file is reachable without the full lookup roundtrip.
    """

    return _parquet_for_country(country)


def clear_parquet_caches() -> None:
    """Invalidate all memoised parquet state.

    Call this after dropping a new CWICR parquet file into the data
    directory so the next :func:`lookup_rows` call rescans the directory
    and opens the new file instead of using a stale ``lru_cache`` entry.

    Two caches are cleared:

    * :func:`_parquet_for_country` — directory scan results keyed on the
      upper-cased country head (``DE``, ``US``, etc.). Must be cleared
      whenever the set of parquet files changes so the path resolver
      discovers newly-added files.
    * :func:`_scan` — Polars ``LazyFrame`` handles keyed on the absolute
      parquet path string. A ``LazyFrame`` holds an mmap/file descriptor
      open on all platforms. Clearing this cache closes those handles,
      which is important on Windows where an open mmap blocks file
      replacement (the ``os error 5`` / Access Denied symptom). Without
      this clear, replacing a parquet file while the backend is running
      leaves the old frame in the cache and all subsequent lookups read
      stale data silently.
    """

    _parquet_for_country.cache_clear()
    _scan.cache_clear()
    logger.info("parquet_lookup: caches cleared (directory + LazyFrame handles)")


__all__ = [
    "clear_parquet_caches",
    "lookup_rows",
    "parquet_path_for_country",
    "parquet_root",
]

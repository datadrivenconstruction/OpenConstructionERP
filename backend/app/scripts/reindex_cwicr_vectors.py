# DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP
"""Runnable ingest that (re)indexes a CWICR national or regional base into
its per-language vector collection.

Purpose
=======

The national and regional cost bases under ``WORLD_COST_BASES/`` ship as
work-item parquets, not as pre-built vector snapshots. This script is the
runnable entry point that turns one such parquet into vector points so
semantic cost search has something to retrieve. It reads the parquet with
pandas, collapses the resource lines down to one point per work item
(distinct ``rate_code``), embeds the work-item description, and upserts
through the shared multi-collection layer
(:func:`app.core.vector_index.reindex_collection`).

The target collection name is resolved from the region exactly the way the
match path resolves it, via
:func:`app.modules.costs.qdrant_adapter.country_to_collection`, so a base
always lands in its own language collection:

    BR_NATIONAL   -> cwicr_pt_v3    (SINAPI, shares the Portuguese collection)
    ES_ANDALUCIA  -> cwicr_es_v3    (BCCA Andalucia)
    IT_TOSCANA    -> cwicr_it_v3    (Prezzario Regione Toscana)
    VN_NATIONAL   -> cwicr_vi_v3    (Dinh Muc national norms)
    ID_NATIONAL   -> cwicr_id_v3    (AHSP national analyses)
    GR_NATIONAL   -> cwicr_el_v3    (GGDE analytical tariffs, brand-new Greek collection)

Which vector store this writes to
=================================

Important operational note. This script writes through the generic
multi-collection layer in :mod:`app.core.vector`, which is the
sentence-transformers embedder (multilingual e5-small, 384 dimensions) on
top of the embedded LanceDB store by default, or the same shape on a Qdrant
server when ``VECTOR_BACKEND=qdrant`` is set. That store is what the
cross-module semantic search (unified search, Cost Explorer) reads through
:func:`app.core.vector_index.search_collection`.

It is NOT the same store the match-elements path reads. That path
(:func:`app.modules.costs.qdrant_adapter.search`) expects the DDC bge-m3
snapshots: named ``dense`` plus ``sparse`` vectors at 1024 dimensions,
recovered from ``*_EMBEDDINGS_BGEM3_V3_DDC_CWICR.snapshot`` files onto a real
Qdrant server. Those snapshots cannot be produced from a parquet with the
imports available here, so this script does not feed the match path. See the
handover note returned to the lead for the recommended follow-up (either ship
bge-m3 snapshots for the six bases, or point the generic search at these
collections). If ``VECTOR_BACKEND=qdrant`` is set AND the generic store shares
the Qdrant instance that holds the bge-m3 ``cwicr_*_v3`` collections, using the
same collection name would collide; prefer LanceDB for the generic store, or
override the name with ``--collection``.

Operator commands (run from the ``backend`` directory)
======================================================

Dry-run first to see the point count, target collection and a sample payload
without embedding or connecting to any store::

    python -m app.scripts.reindex_cwicr_vectors \
        --parquet ../WORLD_COST_BASES/ES_ANDALUCIA_workitems_costs_resources_DDC_CWICR.parquet \
        --region ES_ANDALUCIA --dry-run

Real ingest for each of the six bases (drop ``--dry-run``)::

    python -m app.scripts.reindex_cwicr_vectors --parquet ../WORLD_COST_BASES/BR_workitems_costs_resources_DDC_CWICR.parquet --region BR_NATIONAL
    python -m app.scripts.reindex_cwicr_vectors --parquet ../WORLD_COST_BASES/ES_ANDALUCIA_workitems_costs_resources_DDC_CWICR.parquet --region ES_ANDALUCIA
    python -m app.scripts.reindex_cwicr_vectors --parquet ../WORLD_COST_BASES/IT_TOSCANA_workitems_costs_resources_DDC_CWICR.parquet --region IT_TOSCANA
    python -m app.scripts.reindex_cwicr_vectors --parquet ../WORLD_COST_BASES/GR_workitems_costs_resources_DDC_CWICR.parquet --region GR_NATIONAL
    python -m app.scripts.reindex_cwicr_vectors --parquet ../WORLD_COST_BASES/VN_workitems_costs_resources_DDC_CWICR.parquet --region VN_NATIONAL
    python -m app.scripts.reindex_cwicr_vectors --parquet ../WORLD_COST_BASES/ID_workitems_costs_resources_DDC_CWICR.parquet --region ID_NATIONAL

GR_NATIONAL is the one that materialises a brand-new collection
(``cwicr_el_v3``); the other five upsert into a language collection that other
catalogues already share, so per-region filtering relies on the ``region`` and
``country`` payload fields this script writes.

Idempotency
===========

Point ids are a deterministic UUID5 of ``region`` plus ``rate_code``, so
re-running the ingest upserts the same points instead of duplicating them.
Note that it does not delete rate codes that were removed from a base between
runs; the generic layer only deletes by id, not by a region payload filter, so
a full per-region wipe is out of scope here.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import logging
import math
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger("reindex_cwicr_vectors")

# Deterministic namespace for work-item point ids. Fixed once so the UUID5 of
# a given region plus rate_code is stable across runs and hosts, which is what
# makes the upsert idempotent.
_ID_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "openconstructionerp/cwicr/work-item")

# Short module tag stamped on every point by the generic layer.
_MODULE_NAME = "costs"

# Column-name candidates, most preferred first. The national bases share the
# 95-column DDC schema, but resolving by candidate list keeps the script
# working if a base uses a slightly different header.
_CODE_COLUMNS: tuple[str, ...] = ("rate_code", "code", "work_item_code", "item_code")
_FINAL_NAME_COLUMNS: tuple[str, ...] = (
    "rate_final_name",
    "rate_name",
    "description",
    "rate_original_name",
)
_ORIGINAL_NAME_COLUMNS: tuple[str, ...] = ("rate_original_name",)
_UNIT_COLUMNS: tuple[str, ...] = ("rate_unit", "unit", "rate_unit_copy")
_ABSTRACT_COLUMNS: tuple[str, ...] = ("is_abstract",)
_SCOPE_COLUMNS: tuple[str, ...] = ("is_scope",)
_TOTAL_COST_COLUMNS: tuple[str, ...] = ("total_cost_per_position", "total_cost", "rate")
_DEPARTMENT_COLUMNS: tuple[str, ...] = ("department_name", "department_code")
_SUBSECTION_COLUMNS: tuple[str, ...] = ("subsection_name", "subsection_code")
_CATEGORY_COLUMNS: tuple[str, ...] = ("category_type",)
_CATALOGUE_COLUMNS: tuple[str, ...] = ("collection_name", "collection_code")
_INSTITUTION_COLUMNS: tuple[str, ...] = ("source_institution",)
_YEAR_COLUMNS: tuple[str, ...] = ("source_year",)


# ── Value cleaning ───────────────────────────────────────────────────────


def _clean_str(value: Any) -> str:
    """Return a trimmed string, mapping null or NaN to an empty string."""
    if value is None:
        return ""
    try:
        if isinstance(value, float) and math.isnan(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if text.lower() in ("nan", "none", "<na>"):
        return ""
    return text


def _clean_bool(value: Any) -> bool:
    """Coerce a parquet cell to a plain bool, tolerant of strings and NaN."""
    if isinstance(value, bool):
        return value
    text = _clean_str(value).lower()
    return text in ("true", "1", "yes", "y")


def _clean_float(value: Any) -> float | None:
    """Return a finite float or ``None`` for empty, NaN or unparseable input."""
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


# ── Work-item row ────────────────────────────────────────────────────────


@dataclass(slots=True)
class _WorkItem:
    """One CWICR work item, collapsed from its resource lines.

    Attributes:
        id: Deterministic UUID5 string used as the vector point id.
        region: The full region id passed on the command line (e.g. ES_ANDALUCIA).
        country: The ISO-3166 head resolved for the region (e.g. ES), for
            per-country filtering inside a shared language collection.
        code: The work-item rate code (distinct per point).
        unit: The rate unit of measure.
        description: The canonical work-item name that gets embedded.
        description_original: The native-language name, when it differs.
        is_abstract: True for section headers that carry no unit price.
        total_cost: Total unit cost of the work item, or None when absent.
        department: Department name or code, for payload context.
        subsection: Subsection name or code, for payload context.
        category: Category type, for payload context.
        catalogue: Source catalogue display name.
        source_institution: Publishing institution.
        source_year: Publication year as a string.
    """

    id: str
    region: str
    country: str
    code: str
    unit: str
    description: str
    description_original: str
    is_abstract: bool
    total_cost: float | None
    department: str
    subsection: str
    category: str
    catalogue: str
    source_institution: str
    source_year: str


# ── Embedding adapter over the parquet rows ──────────────────────────────


class _CwicrCatalogueAdapter:
    """Adapter satisfying :class:`app.core.vector_index.EmbeddingAdapter`.

    Maps a :class:`_WorkItem` to the text that gets embedded and to the light
    payload stored alongside the vector for hit rendering and region
    filtering.
    """

    module_name: str = _MODULE_NAME

    def __init__(self, collection_name: str) -> None:
        """Bind the adapter to a resolved target collection.

        Args:
            collection_name: The per-language collection the points go into.
        """
        self.collection_name = collection_name

    def to_text(self, row: _WorkItem) -> str:
        """Return the text to embed for a work item.

        The canonical description anchors the vector. The native-language name
        is appended when it differs so the multilingual encoder keeps recall in
        both the source language and the normalized one, and the unit adds a
        light lexical anchor, mirroring the BOQ adapter.
        """
        parts: list[str] = []
        if row.description:
            parts.append(row.description)
        if row.description_original and row.description_original != row.description:
            parts.append(row.description_original)
        if row.unit:
            parts.append(row.unit)
        return " | ".join(parts)

    def to_payload(self, row: _WorkItem) -> dict[str, Any]:
        """Return the JSON-serialisable payload stored with the vector.

        Carries at least region, code, unit and description so hits render
        without a database round-trip and so a caller can narrow a shared
        language collection to this base by region or country.
        """
        title = (row.description or row.description_original or row.code)[:120]
        payload: dict[str, Any] = {
            "title": title,
            "region": row.region,
            "country": row.country,
            "code": row.code,
            "unit": row.unit,
            "description": row.description or row.description_original,
            "is_abstract": row.is_abstract,
            "source": "cwicr",
        }
        if row.description_original and row.description_original != row.description:
            payload["description_original"] = row.description_original
        if row.total_cost is not None:
            payload["total_cost"] = row.total_cost
        if row.department:
            payload["department"] = row.department
        if row.subsection:
            payload["subsection"] = row.subsection
        if row.category:
            payload["category"] = row.category
        if row.catalogue:
            payload["catalogue"] = row.catalogue
        if row.source_institution:
            payload["source_institution"] = row.source_institution
        if row.source_year:
            payload["source_year"] = row.source_year
        return payload

    def project_id_of(self, row: _WorkItem) -> str | None:  # noqa: ARG002 - protocol shape
        """Cost catalogue rates are cross-project, so there is no owning project."""
        return None


# ── Region and column resolution ─────────────────────────────────────────


def _force_pure_collection_routing() -> None:
    """Pin the collection probe off so ingest targets the base's own collection.

    :func:`country_to_collection` normally substitutes an available collection
    when the native one is absent from a live Qdrant. For ingest that would be
    wrong: a brand-new base such as GR_NATIONAL must resolve to cwicr_el_v3 so
    the collection gets created, not silently redirected to whatever already
    exists. Setting the probe off keeps the resolution pure and offline. This
    runs before the first settings read in this short-lived process, so the
    cached settings pick it up.
    """
    os.environ["CWICR_COLLECTION_PROBE"] = "0"


def _resolve_collection(region: str, override: str | None) -> str:
    """Resolve the target collection for a region, honouring an override.

    Args:
        region: Region id such as ES_ANDALUCIA or GR_NATIONAL.
        override: Explicit collection name, or None to resolve from the region.

    Returns:
        The collection name the points will be written into.
    """
    if override:
        return override
    from app.modules.costs.qdrant_adapter import country_to_collection

    return country_to_collection(region)


def _resolve_country(region: str) -> str:
    """Return the ISO-3166 head for a region, or an empty string when none.

    Uses the same pin the search path uses so the ``country`` payload matches
    what a region-narrowed query would filter on.
    """
    from app.modules.costs.qdrant_adapter import country_filter_for

    return country_filter_for(region) or ""


def _resolve_language(region: str) -> str:
    """Return the ISO-639-1 language tag for a region, for operator output."""
    from app.core.match_service.region_language import language_for

    return language_for(region)


def _resolve_column(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    """Return the first candidate present in ``columns``, or None."""
    present = set(columns)
    for candidate in candidates:
        if candidate in present:
            return candidate
    return None


# ── Parquet loading ──────────────────────────────────────────────────────


def _load_work_items(
    parquet_path: Path,
    region: str,
    country: str,
    limit: int | None,
) -> list[_WorkItem]:
    """Load one work item per distinct rate code from a base parquet.

    The parquet holds one row per resource line, so several rows share a rate
    code. Rows flagged as the scope of work are preferred as the representative
    row when the flag is present; otherwise the first row per code is kept. The
    work-item-level fields (name, unit, total cost) are identical across a
    code's lines, so the choice only affects tie-breaking.

    Args:
        parquet_path: Path to a ``*_workitems_costs_resources_DDC_CWICR.parquet``.
        region: Region id to stamp into each point's payload.
        country: ISO-3166 head to stamp into each point's payload.
        limit: Optional cap on the number of work items, for testing.

    Returns:
        A list of :class:`_WorkItem`, one per distinct rate code with a
        non-empty description.

    Raises:
        ValueError: When no rate-code or description column can be resolved.
    """
    frame = pd.read_parquet(parquet_path)
    columns = list(frame.columns)

    code_col = _resolve_column(columns, _CODE_COLUMNS)
    final_col = _resolve_column(columns, _FINAL_NAME_COLUMNS)
    if not code_col:
        raise ValueError(f"no rate-code column found in {parquet_path.name}; looked for {_CODE_COLUMNS}")
    if not final_col:
        raise ValueError(f"no description column found in {parquet_path.name}; looked for {_FINAL_NAME_COLUMNS}")

    original_col = _resolve_column(columns, _ORIGINAL_NAME_COLUMNS)
    unit_col = _resolve_column(columns, _UNIT_COLUMNS)
    abstract_col = _resolve_column(columns, _ABSTRACT_COLUMNS)
    scope_col = _resolve_column(columns, _SCOPE_COLUMNS)
    total_col = _resolve_column(columns, _TOTAL_COST_COLUMNS)
    department_col = _resolve_column(columns, _DEPARTMENT_COLUMNS)
    subsection_col = _resolve_column(columns, _SUBSECTION_COLUMNS)
    category_col = _resolve_column(columns, _CATEGORY_COLUMNS)
    catalogue_col = _resolve_column(columns, _CATALOGUE_COLUMNS)
    institution_col = _resolve_column(columns, _INSTITUTION_COLUMNS)
    year_col = _resolve_column(columns, _YEAR_COLUMNS)

    # Prefer the scope-of-work row as the representative for each code.
    if scope_col:
        frame = frame.sort_values(by=scope_col, ascending=False, kind="stable")
    frame = frame.drop_duplicates(subset=[code_col], keep="first")

    needed = [
        c
        for c in (
            code_col,
            final_col,
            original_col,
            unit_col,
            abstract_col,
            total_col,
            department_col,
            subsection_col,
            category_col,
            catalogue_col,
            institution_col,
            year_col,
        )
        if c
    ]
    records = frame[needed].to_dict("records")

    items: list[_WorkItem] = []
    for rec in records:
        code = _clean_str(rec.get(code_col))
        if not code:
            continue
        description = _clean_str(rec.get(final_col)) if final_col else ""
        description_original = _clean_str(rec.get(original_col)) if original_col else ""
        if not description:
            description = description_original
        if not description:
            # Nothing to embed for this code, skip it.
            continue
        point_id = str(uuid.uuid5(_ID_NAMESPACE, f"{region}:{code}"))
        items.append(
            _WorkItem(
                id=point_id,
                region=region,
                country=country,
                code=code,
                unit=_clean_str(rec.get(unit_col)) if unit_col else "",
                description=description,
                description_original=description_original,
                is_abstract=_clean_bool(rec.get(abstract_col)) if abstract_col else False,
                total_cost=_clean_float(rec.get(total_col)) if total_col else None,
                department=_clean_str(rec.get(department_col)) if department_col else "",
                subsection=_clean_str(rec.get(subsection_col)) if subsection_col else "",
                category=_clean_str(rec.get(category_col)) if category_col else "",
                catalogue=_clean_str(rec.get(catalogue_col)) if catalogue_col else "",
                source_institution=_clean_str(rec.get(institution_col)) if institution_col else "",
                source_year=_clean_str(rec.get(year_col)) if year_col else "",
            )
        )
        if limit is not None and len(items) >= limit:
            break
    return items


# ── Infrastructure checks ────────────────────────────────────────────────


def _installed(module_name: str) -> bool:
    """Return True when ``module_name`` is importable, without importing it."""
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:  # noqa: BLE001 - a broken meta-path finder must not crash the check
        return False


def _check_infrastructure() -> str | None:
    """Return an operator hint when required infrastructure is missing.

    Best-effort and import-only: it checks that an embedder and the active
    vector store library are installed. It does not test Qdrant reachability;
    an unreachable server is caught after the fact when the indexed count comes
    back zero. Returns None when everything needed looks present.
    """
    if not (_installed("sentence_transformers") or _installed("fastembed")):
        return (
            "no embedding model is installed. Install the semantic extra and rerun: "
            "pip install openconstructionerp[semantic]"
        )
    backend = os.environ.get("VECTOR_BACKEND", "lancedb").strip().lower()
    if backend == "qdrant":
        if not _installed("qdrant_client"):
            return (
                "VECTOR_BACKEND=qdrant but qdrant-client is not installed. Install the semantic "
                "extra and start Qdrant, then rerun: pip install openconstructionerp[semantic]"
            )
    elif not _installed("lancedb"):
        return (
            "the LanceDB vector store is not installed. Install the semantic extra and rerun: "
            "pip install openconstructionerp[semantic]"
        )
    return None


# ── Dry-run and real ingest ──────────────────────────────────────────────


def _print_dry_run(
    *,
    region: str,
    language: str,
    country: str,
    collection: str,
    items: list[_WorkItem],
    adapter: _CwicrCatalogueAdapter,
    parquet_path: Path,
) -> None:
    """Print what a real run would index, without embedding or connecting."""
    abstract = sum(1 for it in items if it.is_abstract)
    print(f"source parquet : {parquet_path}")
    print(f"region         : {region}")
    print(f"language        : {language}")
    print(f"country pin    : {country or '(none, whole language collection)'}")
    print(f"collection     : {collection}")
    print(f"work items     : {len(items)} points would be indexed")
    print(f"  of which abstract section headers: {abstract}")
    print("dry-run: nothing was embedded and no store was contacted.")
    sample = items[:2]
    for i, row in enumerate(sample, start=1):
        print(f"\n--- sample point {i} of {len(sample)} ---")
        print(f"id        : {row.id}")
        print(f"embed text: {adapter.to_text(row)}")
        print("payload   :")
        print(json.dumps(adapter.to_payload(row), ensure_ascii=False, indent=2, default=str))


async def _run_real(adapter: _CwicrCatalogueAdapter, items: list[_WorkItem]) -> dict[str, Any]:
    """Embed and upsert the work items through the shared reindex helper.

    The reindex helper is non-fatal: on a missing embedder or an unreachable
    store it logs and returns a zero count rather than raising, so the caller
    inspects the returned count to decide the exit status.
    """
    from app.core.vector_index import reindex_collection

    return await reindex_collection(adapter, items)


# ── CLI ──────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="reindex_cwicr_vectors",
        description=(
            "Reindex a CWICR national or regional base parquet into its per-language "
            "vector collection so semantic cost search has vectors for it."
        ),
    )
    parser.add_argument(
        "--parquet",
        required=True,
        help="Path to a *_workitems_costs_resources_DDC_CWICR.parquet base file.",
    )
    parser.add_argument(
        "--region",
        required=True,
        help="Region id, e.g. ES_ANDALUCIA or GR_NATIONAL. Resolves the collection and region pin.",
    )
    parser.add_argument(
        "--collection",
        default=None,
        help="Optional collection-name override. Defaults to the region's language collection.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read and build points, print the plan and a sample, but do not embed or connect.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on the number of work items, for testing.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the reindex CLI.

    Args:
        argv: Optional argument vector, defaulting to ``sys.argv[1:]``.

    Returns:
        Process exit code: 0 on success, non-zero on a bad path, empty base,
        or missing or unreachable infrastructure.
    """
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Pin pure routing before the first settings read so the base lands in its
    # own language collection instead of an availability-probe fallback.
    _force_pure_collection_routing()

    parquet_path = Path(args.parquet).expanduser()
    if not parquet_path.is_file():
        print(f"error: parquet not found: {parquet_path}", file=sys.stderr)
        return 1

    if args.limit is not None and args.limit <= 0:
        print("error: --limit must be a positive integer", file=sys.stderr)
        return 1

    region = args.region.strip().upper()
    collection = _resolve_collection(region, args.collection)
    country = _resolve_country(region)
    language = _resolve_language(region)
    adapter = _CwicrCatalogueAdapter(collection)

    try:
        items = _load_work_items(parquet_path, region, country, args.limit)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - surface a clean message, never a raw trace
        print(f"error: failed to read {parquet_path.name}: {exc}", file=sys.stderr)
        return 1

    if not items:
        print(f"error: no work items with a description found in {parquet_path.name}", file=sys.stderr)
        return 1

    if args.dry_run:
        _print_dry_run(
            region=region,
            language=language,
            country=country,
            collection=collection,
            items=items,
            adapter=adapter,
            parquet_path=parquet_path,
        )
        return 0

    infra_hint = _check_infrastructure()
    if infra_hint is not None:
        print(f"error: {infra_hint}", file=sys.stderr)
        return 1

    print(f"indexing {len(items)} work items from {parquet_path.name} into {collection} ...")
    try:
        result = asyncio.run(_run_real(adapter, items))
    except Exception as exc:  # noqa: BLE001 - never surface a raw trace on infra failure
        print(
            "error: indexing failed. Ensure the embedding model is installed and the vector "
            f"store is reachable, then rerun. Detail: {exc}",
            file=sys.stderr,
        )
        return 1

    indexed = int(result.get("indexed", 0))
    if indexed == 0:
        print(
            "error: nothing was indexed. The embedding model may be missing or the vector store "
            "may be unreachable. Install openconstructionerp[semantic], start the store, then rerun.",
            file=sys.stderr,
        )
        return 1

    print(f"done: indexed {indexed} points into {collection} (skipped {int(result.get('skipped', 0))}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

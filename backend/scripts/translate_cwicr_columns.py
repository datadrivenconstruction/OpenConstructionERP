"""Backfill CWICR cost-database localized columns.

The CWICR import pipeline (``router.py::_load_cwicr_data``) writes the raw
German vocabulary tokens into ``classification.category``,
``metadata.variant_stats.unit / .group`` and per-component ``unit``.
At read time, ``app.modules.costs.translations.localize_cost_row`` mirrors
those into ``*_localized`` keys based on the request locale — but new
clients may want the localized values to land *in the database itself*
so they don't have to pass a locale on every request.

This script walks the active cost database, applies
``localize_cost_row`` once per supported locale (or just one specific
locale via ``--locale``), and persists the augmented JSON columns back
to the SQLite ``oe_costs_item`` table.

Idempotent — running it twice produces the same row content.  Source
fields (``category``, ``unit``, ``group``) are NEVER overwritten;  only
the ``*_localized`` mirror keys are added or refreshed.

Usage:
    # Dry run — print what would change for a single locale.
    python -m backend.scripts.translate_cwicr_columns --locale ro --dry-run

    # Persist Bulgarian translations for every loaded region.
    python -m backend.scripts.translate_cwicr_columns --locale bg

    # Persist all supported locales (slow on large DBs — 16 passes).
    python -m backend.scripts.translate_cwicr_columns --all-locales

    # Limit to one region.
    python -m backend.scripts.translate_cwicr_columns --locale ro --region RO_BUCHAREST

The script does NOT touch parquet source files — those remain the
canonical CWICR upstream.  Only the SQLite cache is updated.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path

# Allow running as a plain script from anywhere — add backend/ to sys.path
# so ``app.modules.costs.translations`` is importable.  The ``-m`` form
# also works without this when run from the repo root.
_THIS = Path(__file__).resolve()
_BACKEND_ROOT = _THIS.parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.modules.costs.translations import (  # noqa: E402
    SUPPORTED_LOCALES,
    localize_cost_row,
)

logger = logging.getLogger("translate_cwicr_columns")

DEFAULT_DB_CANDIDATES = (
    "backend/openestimate.db",
    "backend/data/openestimate.db",
    "openestimate.db",
)


def _find_default_db() -> Path | None:
    """Walk a few well-known relative paths to locate the active SQLite DB."""
    for candidate in DEFAULT_DB_CANDIDATES:
        p = Path.cwd() / candidate
        if p.is_file():
            return p
    # Try one level up — common when the script is invoked from `backend/`.
    for candidate in DEFAULT_DB_CANDIDATES:
        p = Path.cwd().parent / candidate
        if p.is_file():
            return p
    return None


def _process_row(
    row_id: str,
    classification_raw: str | None,
    components_raw: str | None,
    metadata_raw: str | None,
    locale: str,
) -> tuple[str, str, str] | None:
    """Compute the new ``(classification, components, metadata)`` JSON tuple.

    Returns ``None`` when no field would change (skip write).
    """
    try:
        cls = json.loads(classification_raw) if classification_raw else {}
    except json.JSONDecodeError:
        cls = {}
    try:
        comps = json.loads(components_raw) if components_raw else []
    except json.JSONDecodeError:
        comps = []
    try:
        meta = json.loads(metadata_raw) if metadata_raw else {}
    except json.JSONDecodeError:
        meta = {}

    if not isinstance(cls, dict):
        cls = {}
    if not isinstance(comps, list):
        comps = []
    if not isinstance(meta, dict):
        meta = {}

    before = (json.dumps(cls, sort_keys=True), json.dumps(comps, sort_keys=True), json.dumps(meta, sort_keys=True))
    localize_cost_row(
        classification=cls,
        metadata=meta,
        components=comps,
        locale=locale,
    )
    after = (json.dumps(cls, sort_keys=True), json.dumps(comps, sort_keys=True), json.dumps(meta, sort_keys=True))

    if before == after:
        return None

    return (json.dumps(cls), json.dumps(comps), json.dumps(meta))


def backfill(
    db_path: Path,
    locale: str,
    region: str | None = None,
    dry_run: bool = False,
    chunk: int = 1000,
) -> tuple[int, int]:
    """Run the backfill against a single locale.

    Returns ``(scanned, updated)`` counts.  When ``dry_run`` is true,
    ``updated`` reflects how many rows *would* change.
    """
    if locale not in SUPPORTED_LOCALES:
        logger.warning(
            "Locale %r has no translation file — skipping (supported: %s)",
            locale,
            ", ".join(SUPPORTED_LOCALES),
        )
        return 0, 0

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    where = "1=1"
    params: list[str] = []
    if region:
        where = "region = ?"
        params.append(region)

    cur.execute(f"SELECT COUNT(*) FROM oe_costs_item WHERE {where}", params)
    total = cur.fetchone()[0]
    logger.info(
        "Scanning %d rows in %s (locale=%s, region=%s, dry_run=%s)",
        total,
        db_path,
        locale,
        region or "*",
        dry_run,
    )

    scanned = 0
    updated = 0
    last_id: str | None = None

    while True:
        if last_id is None:
            cur.execute(
                f"SELECT id, classification, components, metadata FROM oe_costs_item "
                f"WHERE {where} ORDER BY id LIMIT ?",
                [*params, chunk],
            )
        else:
            cur.execute(
                f"SELECT id, classification, components, metadata FROM oe_costs_item "
                f"WHERE {where} AND id > ? ORDER BY id LIMIT ?",
                [*params, last_id, chunk],
            )
        rows = cur.fetchall()
        if not rows:
            break

        write_batch: list[tuple[str, str, str, str]] = []
        for r in rows:
            scanned += 1
            new = _process_row(
                row_id=r["id"],
                classification_raw=r["classification"],
                components_raw=r["components"],
                metadata_raw=r["metadata"],
                locale=locale,
            )
            if new is None:
                continue
            cls_json, comp_json, meta_json = new
            write_batch.append((cls_json, comp_json, meta_json, r["id"]))
            updated += 1
            last_id = r["id"]

        # Always advance last_id to the last scanned row, not just last
        # written one — otherwise an all-no-op chunk loops forever.
        last_id = rows[-1]["id"]

        if write_batch and not dry_run:
            cur.executemany(
                "UPDATE oe_costs_item "
                "SET classification = ?, components = ?, metadata = ? "
                "WHERE id = ?",
                write_batch,
            )
            conn.commit()

        logger.info("  ... progress: scanned=%d updated=%d", scanned, updated)

    conn.close()
    logger.info(
        "Done. locale=%s region=%s scanned=%d updated=%d (dry_run=%s)",
        locale,
        region or "*",
        scanned,
        updated,
        dry_run,
    )
    return scanned, updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Path to openestimate.db (auto-detected if omitted).",
    )
    parser.add_argument(
        "--locale",
        type=str,
        default=None,
        help="Single locale to backfill (e.g. ro, bg, sv).",
    )
    parser.add_argument(
        "--all-locales",
        action="store_true",
        help="Backfill every locale that has a translation file.",
    )
    parser.add_argument(
        "--region",
        type=str,
        default=None,
        help="Limit to a single region (e.g. RO_BUCHAREST).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't write to the DB — just count rows that would change.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose progress logging.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)-7s %(message)s",
    )

    db_path = args.db or _find_default_db()
    if db_path is None or not db_path.is_file():
        sys.stderr.write(
            "Could not find openestimate.db. Pass --db /path/to/openestimate.db\n"
        )
        return 2

    if not args.locale and not args.all_locales:
        sys.stderr.write("Specify --locale <code> or --all-locales\n")
        return 2

    locales = list(SUPPORTED_LOCALES) if args.all_locales else [args.locale]
    grand_scanned = 0
    grand_updated = 0
    for loc in locales:
        scanned, updated = backfill(
            db_path=db_path,
            locale=loc,
            region=args.region,
            dry_run=args.dry_run,
        )
        grand_scanned += scanned
        grand_updated += updated

    print(
        f"Total: scanned={grand_scanned} updated={grand_updated} "
        f"(dry_run={args.dry_run}) db={db_path} locales={len(locales)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

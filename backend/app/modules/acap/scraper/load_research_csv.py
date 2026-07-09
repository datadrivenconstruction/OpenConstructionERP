# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Load the NotebookLM-researched Batam price CSV into oe_acap_material_price.

The CSV (``data/prices/batam_notebooklm_2026.csv``) is a curated, already-clipped
snapshot of Batam 2026 market prices researched via NotebookLM deep-research over
Batam toko/marketplace/arsiteqi/sobatbangun sources (see
docs/research/batam-prices-notebooklm-2026.md for provenance + the clip rationale).

It upserts through the same idempotent :func:`persist_prices` path the live
scraper uses (natural key region+source+item_type+item_name), under
``source="notebooklm-research"`` so these rows COEXIST with the live-scraped rows;
the RAB picks the latest by ``scraped_at``. Prices are validated against sane
per-type bounds — a malformed/out-of-range row is SKIPPED and reported, never
loaded as a guess.

Run:  python -m app.modules.acap.scraper.load_research_csv [--commit]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
from datetime import datetime, timezone
from pathlib import Path

from app.database import async_session_factory
from app.modules.acap.scraper.base import PriceRecord
from app.modules.acap.scraper.persist import persist_prices

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "prices" / "batam_notebooklm_2026.csv"
SOURCE = "notebooklm-research"
VALID_TYPES = {"material", "upah_harian", "upah_borongan"}
BOUNDS = {
    "material": (100, 5_000_000),
    "upah_harian": (50_000, 500_000),
    "upah_borongan": (1_000, 5_000_000),
}


def _int(s: str) -> int | None:
    digits = "".join(ch for ch in str(s) if ch.isdigit())
    return int(digits) if digits else None


def read_records(path: Path) -> tuple[list[PriceRecord], list[tuple[dict, str]]]:
    records: list[PriceRecord] = []
    skipped: list[tuple[dict, str]] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            it = (row.get("item_type") or "").strip().lower()
            name = (row.get("item_name") or "").strip()
            pmin, pmax = _int(row.get("price_min")), _int(row.get("price_max"))
            if it not in VALID_TYPES or not name or pmin is None or pmax is None:
                skipped.append((row, "bad type/name/price"))
                continue
            if pmax < pmin:
                pmin, pmax = pmax, pmin
            lo, hi = BOUNDS[it]
            if pmin < lo or pmax > hi:
                skipped.append((row, f"out of bounds [{lo},{hi}]"))
                continue
            records.append(
                PriceRecord(
                    source=SOURCE,
                    source_url=(row.get("source_url") or "").strip() or "notebooklm",
                    item_type=it,
                    item_name=name,
                    satuan=(row.get("satuan") or "").strip() or None,
                    price_min=pmin,
                    price_max=pmax,
                    extraction_method="notebooklm-research",
                )
            )
    return records, skipped


async def _main(path: Path, commit: bool) -> None:
    records, skipped = read_records(path)
    print(f"valid={len(records)} skipped={len(skipped)} source={path.name}")
    for row, why in skipped:
        print(f"  SKIP ({why}): {row.get('item_type')}|{row.get('item_name')}")
    if not commit:
        print("DRY RUN — pass --commit to persist.")
        return
    async with async_session_factory() as session:
        n = await persist_prices(session, "BATAM", records, scraped_at=datetime.now(timezone.utc))
        await session.commit()
    print(f"PERSISTED rows touched={n}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=CSV_PATH)
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    asyncio.run(_main(args.csv, args.commit))

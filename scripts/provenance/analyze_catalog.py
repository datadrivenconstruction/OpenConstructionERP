# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Read-only analysis of a CWICR resource catalog to inform canary design.

Prints the column layout, the resource_code token alphabet, the distribution of
type/category/unit/currency, and price-field ranges - everything the canary
seeder needs to emit entries that look native to each base.
"""

from __future__ import annotations

import csv
import re
import sys
from collections import Counter
from pathlib import Path

CATALOG_DIR = Path("data/catalog/regions")


def analyze(path: Path) -> None:
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    if not rows:
        print(f"{path.name}: EMPTY")
        return
    cols = list(rows[0].keys())
    print(f"\n=== {path.name} ===")
    print("rows:", len(rows))
    print("cols:", cols)

    # resource_code token alphabet (split on _ and -)
    syl = Counter()
    tok = Counter()
    for r in rows:
        code = r["resource_code"]
        for t in re.split(r"[_-]", code):
            if t:
                tok[t] += 1
                for s in re.findall(r"[A-Z][a-z]*|[A-Z]{2}", t):
                    syl[s] += 1
    print("distinct code tokens:", len(tok), "| top:", [t for t, _ in tok.most_common(20)])

    for col in ("type", "category", "unit", "currency"):
        vals = Counter(r[col] for r in rows)
        top = vals.most_common(8)
        print(f"{col}: {len(vals)} distinct | top:", top)

    # price ranges
    for col in ("price_avg", "price_min", "price_max"):
        nums = []
        for r in rows:
            try:
                nums.append(float(r[col]))
            except (ValueError, KeyError):
                pass
        if nums:
            nums.sort()
            print(f"{col}: min={nums[0]:.2f} p50={nums[len(nums)//2]:.2f} max={nums[-1]:.2f}")

    # a couple real rows for reference
    print("sample codes:", [r["resource_code"] for r in rows[:6]])


if __name__ == "__main__":
    targets = sys.argv[1:] or ["DDC_CWICR_DE_BERLIN_Catalog.csv", "DDC_CWICR_ZH_SHANGHAI_Catalog.csv", "DDC_CWICR_RU_STPETERSBURG_Catalog.csv"]
    for name in targets:
        analyze(CATALOG_DIR / name)

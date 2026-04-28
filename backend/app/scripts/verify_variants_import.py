"""Scratch verification for CWICR abstract-resource variant parsing.

Exercises the new `_split_bul` + variant-build logic from
`backend/app/modules/costs/router.py::_process_and_insert_cwicr` in isolation
on a small sample of rows. Does NOT run the full importer.

Usage:
    python -m app.scripts.verify_variants_import

Two sections:
  (A) Synthetic sample using the column names from the implementation plan
      (these may not exist in any current parquet — see report).
  (B) Real-parquet check: load ENG_TORONTO and report which abstract columns
      are actually present, plus run a parallel parse using the parquet's
      real column names mapped onto the same logic.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


# --- Helpers (verbatim from router.py change) ---
def _safe_float(v: object) -> float:
    if v is None:
        return 0.0
    try:
        f = float(v)  # type: ignore[arg-type]
        return 0.0 if math.isnan(f) else f
    except (ValueError, TypeError):
        return 0.0


def _safe_str(v: object) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def _split_bul(value: object) -> list[str]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    return [p.strip() for p in str(value).split("\u2022") if p.strip()]


def parse_variants(row: dict[str, Any], cols: dict[str, str]) -> dict[str, Any]:
    """Run the variant-build logic on a single row dict using a column-name map.

    `cols` maps logical names to actual column names in the row. This allows
    running the same logic against either the plan's names or the real
    parquet's names (which differ).
    """
    metadata: dict[str, Any] = {}
    labels = _split_bul(row.get(cols["variants"]))
    values = _split_bul(row.get(cols["all_values"]))
    counts = _split_bul(row.get(cols["position_count"]))
    pu_vals = _split_bul(row.get(cols["all_values_per_unit"]))
    if labels and len(labels) > 1 and len(values) == len(labels):
        variants = []
        for i, (lbl, val) in enumerate(zip(labels, values, strict=False)):
            v = _safe_float(val)
            if v <= 0:
                continue
            variants.append(
                {
                    "index": i,
                    "label": lbl[:200],
                    "price": round(v, 2),
                    "position_count": int(_safe_float(counts[i])) if i < len(counts) else 0,
                    "price_per_unit": round(_safe_float(pu_vals[i]), 4) if i < len(pu_vals) else None,
                }
            )
        if variants:
            metadata["variants"] = variants
            metadata["variant_stats"] = {
                "min": round(_safe_float(row.get(cols["est_min"])), 2),
                "max": round(_safe_float(row.get(cols["est_max"])), 2),
                "mean": round(_safe_float(row.get(cols["est_mean"])), 2),
                "median": round(_safe_float(row.get(cols["est_median"])), 2),
                "unit": _safe_str(row.get(cols["unit"]))[:20],
                "group": _safe_str(row.get(cols["group"]))[:120],
                "count": len(variants),
            }
    return metadata


# Plan-spec column names (used by router.py)
PLAN_COLS = {
    "variants": "price_abstract_resource_variants",
    "all_values": "price_abstract_resource_all_values",
    "position_count": "price_abstract_resource_position_count",
    "all_values_per_unit": "price_abstract_resource_all_values_per_unit",
    "est_min": "price_abstract_resource_est_price_min",
    "est_max": "price_abstract_resource_est_price_max",
    "est_mean": "price_abstract_resource_est_price_mean",
    "est_median": "price_abstract_resource_est_price_median",
    "unit": "price_abstract_resource_unit",
    "group": "price_abstract_resource_group_per_unit",
}

# Actual column names observed in real CWICR parquet (ENG_TORONTO, MX_MEXICOCITY, etc.)
REAL_COLS = {
    "variants": "price_abstract_resource_variable_parts",
    "all_values": "price_abstract_resource_est_price_all_values",
    "position_count": "price_abstract_resource_position_count",  # single float, not bullet list
    "all_values_per_unit": "price_abstract_resource_est_price_all_values_per_unit",
    "est_min": "price_abstract_resource_est_price_min",
    "est_max": "price_abstract_resource_est_price_max",
    "est_mean": "price_abstract_resource_est_price_mean",
    "est_median": "price_abstract_resource_est_price_median",
    "unit": "price_abstract_resource_unit",
    "group": "price_abstract_resource_group_per_unit",
}


def section_a_synthetic() -> None:
    print("=" * 70)
    print("(A) SYNTHETIC ROWS — using plan's column names")
    print("=" * 70)
    bul = "\u2022"
    sample = {
        "rate_code": "TEST_001",
        "price_abstract_resource_variants": (
            f"Concrete C30/37 ready-mix delivered {bul} "
            f"Concrete C30/37 site-mixed {bul} "
            f"Concrete C30/37 pumped"
        ),
        "price_abstract_resource_all_values": f"125.50 {bul} 98.75 {bul} 142.00",
        "price_abstract_resource_position_count": f"42 {bul} 18 {bul} 7",
        "price_abstract_resource_all_values_per_unit": f"125.5000 {bul} 98.7500 {bul} 142.0000",
        "price_abstract_resource_est_price_min": "98.75",
        "price_abstract_resource_est_price_max": "142.00",
        "price_abstract_resource_est_price_mean": 122.08,
        "price_abstract_resource_est_price_median": 125.5,
        "price_abstract_resource_unit": "m3",
        "price_abstract_resource_group_per_unit": "Concrete works",
    }
    md = parse_variants(sample, PLAN_COLS)
    print("rate_code:", sample["rate_code"])
    print("metadata:", json.dumps(md, indent=2, ensure_ascii=False))
    print()

    # Edge cases for _split_bul
    print("--- _split_bul edge cases ---")
    cases = [None, float("nan"), "", "  ", "single", f"a {bul} b {bul}  {bul} c", 42, "12.50"]
    for c in cases:
        print(f"  _split_bul({c!r}) = {_split_bul(c)!r}")
    print()

    # Single-variant case (should NOT produce variants metadata)
    print("--- single-label row (should produce empty metadata) ---")
    single = {**sample}
    single["price_abstract_resource_variants"] = "Only one option"
    single["price_abstract_resource_all_values"] = "100.00"
    md_single = parse_variants(single, PLAN_COLS)
    print("metadata:", json.dumps(md_single, ensure_ascii=False))
    print()


def section_b_real_parquet(parquet_path: Path) -> None:
    print("=" * 70)
    print(f"(B) REAL PARQUET — {parquet_path.name}")
    print("=" * 70)
    if not parquet_path.exists():
        print(f"  parquet not found at {parquet_path}; skipping")
        return

    df = pd.read_parquet(parquet_path)
    print(f"total rows: {len(df)}")
    abstract_cols = sorted(c for c in df.columns if "price_abstract" in c.lower())
    print(f"abstract-related columns ({len(abstract_cols)}):")
    for c in abstract_cols:
        print(f"  {c}")
    print()

    plan_present = [c for c in PLAN_COLS.values() if c in df.columns]
    real_present = [c for c in REAL_COLS.values() if c in df.columns]
    print(f"plan-named cols present in this parquet: {len(plan_present)}/{len(PLAN_COLS)}")
    print(f"real-name cols present in this parquet: {len(real_present)}/{len(REAL_COLS)}")
    print()

    # Run plan-name parse on first 5 abstract rows — expect empty results
    # because the plan's column names don't match.
    if "row_type" in df.columns:
        ab = df[df["row_type"] == "Abstract resource"].head(5)
    else:
        ab = df.head(5)
    print("--- parsing 5 abstract rows using PLAN names (expected: empty, columns missing) ---")
    for i, (idx, row) in enumerate(ab.iterrows()):
        md = parse_variants(row.to_dict(), PLAN_COLS)
        rate = row.get("rate_code", "?")
        print(f"  [{i}] rate_code={rate!r}  variants_count={len(md.get('variants', []))}")
    print()

    # Run real-name parse on the same rows — expect non-empty results.
    print("--- parsing 5 abstract rows using REAL parquet column names ---")
    for i, (idx, row) in enumerate(ab.iterrows()):
        md = parse_variants(row.to_dict(), REAL_COLS)
        rate = row.get("rate_code", "?")
        n = len(md.get("variants", []))
        print(f"  [{i}] rate_code={rate!r}  variants_count={n}")
        if i == 0 and n > 0:
            print("       sample full metadata for first row:")
            print(json.dumps(md, indent=8, ensure_ascii=False)[:2500])
    print()


if __name__ == "__main__":
    section_a_synthetic()

    parquet = Path(
        r"C:\Users\Artem Boiko\Desktop\CodeProjects\legal-restructure-2026-04"
        r"\OpenConstructionEstimate-DDC-CWICR\EN___DDC_CWICR"
        r"\ENG_TORONTO_workitems_costs_resources_DDC_CWICR.parquet"
    )
    section_b_real_parquet(parquet)

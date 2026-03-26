"""Build resource catalogs for ALL 11 CWICR regions."""
import glob
import math
import os
import pandas as pd

GITHUB_DIR = os.path.expanduser("~/Documents/GitHub/OpenConstructionEstimate-DDC-CWICR")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "catalog", "regions")
os.makedirs(OUT_DIR, exist_ok=True)

REGIONS = {
    "AR": {"name": "Arabic (Dubai)", "currency": "AED", "lang": "ar"},
    "DE": {"name": "German (Berlin)", "currency": "EUR", "lang": "de"},
    "EN": {"name": "English (Toronto)", "currency": "CAD", "lang": "en"},
    "ES": {"name": "Spanish (Barcelona)", "currency": "EUR", "lang": "es"},
    "FR": {"name": "French (Paris)", "currency": "EUR", "lang": "fr"},
    "HI": {"name": "Hindi (Mumbai)", "currency": "INR", "lang": "hi"},
    "PT": {"name": "Portuguese (Sao Paulo)", "currency": "BRL", "lang": "pt"},
    "RU": {"name": "Russian (St.Petersburg)", "currency": "RUB", "lang": "ru"},
    "UK": {"name": "English UK (London)", "currency": "GBP", "lang": "en"},
    "US": {"name": "English US (New York)", "currency": "USD", "lang": "en"},
    "ZH": {"name": "Chinese (Shanghai)", "currency": "CNY", "lang": "zh"},
}

MAT = {
    "Concrete & Cement": ["concrete", "cement", "mortar"],
    "Steel & Metal": ["steel", "metal", "iron", "forging", "structure"],
    "Welding Consumables": ["weld", "electrode"],
    "Wood & Timber": ["wood", "timber", "plywood", "board", "sleeper"],
    "Pipes & Fittings": ["pipe", "tube", "valve", "fitting"],
    "Paint & Coatings": ["paint", "primer", "varnish", "enamel"],
    "Insulation": ["insulation", "thermal", "mineral wool"],
    "Aggregates": ["sand", "gravel", "crushed", "rock", "soil"],
    "Fasteners": ["bolt", "nut", "screw", "nail", "anchor"],
    "Waterproofing": ["waterproof", "bitumen", "membrane"],
    "Electrical": ["cable", "wire", "insulating tape"],
    "Glass": ["glass", "window"],
    "Chemicals": ["oxygen", "acetylene", "propane", "acid", "alcohol"],
    "Water": ["water", "tap water"],
    "Rubber": ["rubber", "gasket", "seal"],
}
EQU = {
    "Cranes": ["crane", "lifting"],
    "Trucks": ["truck", "flatbed", "tractor"],
    "Welding Equip.": ["weld", "inverter"],
    "Excavators": ["excavator"],
    "Bulldozers": ["bulldozer"],
    "Hoists": ["winch", "hoist"],
    "Compressors": ["compressor"],
    "Pumps": ["pump"],
}


def sf(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    try:
        return round(float(v), 4)
    except (ValueError, TypeError):
        return None


def ss(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    return str(v).strip()


def real_type(row):
    rt = ss(row.get("row_type", "")).lower()

    # Machinist / Operator detection (all languages)
    MACHINIST_WORDS = ["machinist", "maschinist", "machiniste", "المشغل", "操作员", "maquinista", "operador", "मशीनिस्ट"]
    if any(w in rt for w in MACHINIST_WORDS):
        return "Operator"

    # Electricity detection (all languages)
    ELECTRICITY_WORDS = ["electric", "elektriz", "électric", "الكهرباء", "电力", "eletric", "बिजली"]
    if any(w in rt for w in ELECTRICITY_WORDS):
        return "Electricity"

    # Abstract resource detection (all languages) — check both flag and row_type
    ABSTRACT_WORDS = ["abstract", "abstrakt", "abstraite", "مجرد", "抽象", "abstrato", "abstracto", "अमूर्त"]
    if bool(row.get("is_abstract", False)) or any(w in rt for w in ABSTRACT_WORDS):
        return "Abstract Material"

    if bool(row.get("is_machine", False)):
        return "Equipment"

    if bool(row.get("is_material", False)):
        u = ss(row.get("resource_unit", "")).lower()
        # Labor unit detection (all languages)
        LABOR_UNITS = [
            "hrs", "h", "person-hour", "person-hours",
            "std.", "stunden",  # German
            "heures", "heure",  # French
            "ساعات",  # Arabic
            "手表", "小时",  # Chinese
            "horas", "hora",  # Spanish/Portuguese
            "часы", "ч", "чел.-ч",  # Russian
            "घंटे", "च",  # Hindi
        ]
        if any(u == lu or u.startswith(lu) for lu in LABOR_UNITS):
            return "Labor"
        return "Material"
    return "Other"


def categorize(name, typ):
    nl = name.lower()
    cs = MAT if typ in ("Material", "Abstract Material") else EQU if typ == "Equipment" else {}
    for c, ks in cs.items():
        if any(k in nl for k in ks):
            return c
    return {"Labor": "Labor", "Operator": "Operators", "Electricity": "Electricity"}.get(typ, "General")


def process_region(region_code, parquet_path, region_info):
    """Process one region and return summary."""
    df = pd.read_parquet(parquet_path)
    df.columns = [str(c).strip().lower() for c in df.columns]

    res = df[
        (df["row_type"] != "Scope of work")
        & (df["resource_name"].notna())
        & (df["resource_name"].str.strip() != "")
    ].copy()
    res["_t"] = res.apply(real_type, axis=1)

    grouped = res.groupby(["resource_code", "_t"], sort=False)

    rows = []
    for (code, tp), gr in grouped:
        f = gr.iloc[0]
        # Column names differ: EN has _eur suffix, others don't
        price_col = "resource_price_per_unit_eur_current" if "resource_price_per_unit_eur_current" in gr.columns else "resource_price_per_unit_current"
        cost_col = "resource_cost_eur" if "resource_cost_eur" in gr.columns else "resource_cost"
        ra = gr[price_col].dropna()
        ra = ra[ra > 0]
        co = gr[cost_col].dropna()
        co = co[co > 0]
        qt = gr["resource_quantity"].dropna()
        qt = qt[qt > 0]

        nm = ss(f.get("resource_name", ""))
        un = ss(f.get("resource_unit", ""))

        r = {
            "resource_code": code,
            "name": nm,
            "type": tp,
            "category": categorize(nm, tp),
            "unit": un,
            "price_avg": round(float(ra.mean()), 2) if len(ra) else 0,
            "price_min": round(float(ra.min()), 2) if len(ra) else 0,
            "price_max": round(float(ra.max()), 2) if len(ra) else 0,
            "price_median": round(float(ra.median()), 2) if len(ra) else 0,
            "price_variants": int(ra.nunique()) if len(ra) else 0,
            "currency": region_info["currency"],
            "avg_cost_per_use": round(float(co.mean()), 2) if len(co) else 0,
            "avg_qty_per_use": round(float(qt.mean()), 4) if len(qt) else 0,
            "usage_count": len(gr),
            "used_in_work_items": int(gr["rate_code"].nunique()),
            "parent_category": ss(f.get("category_type", "")),
            "parent_collection": ss(f.get("collection_name", ""))[:80],
            "parent_department": ss(f.get("department_name", ""))[:80],
            "parent_section": ss(f.get("section_name", ""))[:80],
        }
        rows.append(r)

    out = pd.DataFrame(rows).sort_values("usage_count", ascending=False)

    # Get parquet filename prefix for naming
    pq_name = os.path.basename(parquet_path).replace("_workitems_costs_resources_DDC_CWICR.parquet", "")
    fname = f"DDC_CWICR_{pq_name}_Catalog"

    # CSV
    csv_path = os.path.join(OUT_DIR, f"{fname}.csv")
    out.to_csv(csv_path, index=False, encoding="utf-8")

    # Excel
    xlsx_path = os.path.join(OUT_DIR, f"{fname}.xlsx")
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as w:
        out.to_excel(w, sheet_name="All Resources", index=False)
        for t in ["Material", "Equipment", "Abstract Material", "Labor", "Operator", "Electricity"]:
            s = out[out["type"] == t]
            if len(s):
                s.to_excel(w, sheet_name=t, index=False)

    csv_kb = os.path.getsize(csv_path) // 1024
    xlsx_kb = os.path.getsize(xlsx_path) // 1024

    return {
        "region": region_code,
        "name": region_info["name"],
        "currency": region_info["currency"],
        "total": len(out),
        "materials": len(out[out["type"] == "Material"]),
        "equipment": len(out[out["type"] == "Equipment"]),
        "abstract": len(out[out["type"] == "Abstract Material"]),
        "labor": len(out[out["type"] == "Labor"]),
        "csv_kb": csv_kb,
        "xlsx_kb": xlsx_kb,
        "fname": fname,
    }


def main():
    print("=" * 70)
    print("  DDC CWICR — Building Resource Catalogs for ALL 11 Regions")
    print("=" * 70)

    results = []

    for region_code, info in sorted(REGIONS.items()):
        region_dir = os.path.join(GITHUB_DIR, f"{region_code}___DDC_CWICR")
        parquets = glob.glob(os.path.join(region_dir, "*.parquet"))
        if not parquets:
            print(f"\n  {region_code}: NO PARQUET FILE — skipping")
            continue

        parquet_path = parquets[0]
        print(f"\n  {region_code} — {info['name']} ({info['currency']})...")

        try:
            result = process_region(region_code, parquet_path, info)
            results.append(result)
            print(f"    {result['total']:,} resources | Mat:{result['materials']} Equ:{result['equipment']} Abs:{result['abstract']} Lab:{result['labor']}")
            print(f"    CSV: {result['csv_kb']} KB | Excel: {result['xlsx_kb']} KB")
        except Exception as e:
            print(f"    ERROR: {e}")

    print(f"\n{'=' * 70}")
    print(f"  COMPLETE — {len(results)} regions processed")
    print(f"{'=' * 70}")
    print(f"\n  {'Region':<6s} {'Name':<30s} {'Curr':<5s} {'Total':>6s} {'Mat':>5s} {'Equ':>5s} {'Abs':>5s} {'Lab':>4s}")
    print(f"  {'-'*6} {'-'*30} {'-'*5} {'-'*6} {'-'*5} {'-'*5} {'-'*5} {'-'*4}")
    for r in results:
        print(f"  {r['region']:<6s} {r['name']:<30s} {r['currency']:<5s} {r['total']:>6,} {r['materials']:>5,} {r['equipment']:>5,} {r['abstract']:>5,} {r['labor']:>4}")

    total_all = sum(r["total"] for r in results)
    print(f"\n  Total across all regions: {total_all:,} resources")
    print(f"  Output: {OUT_DIR}")


if __name__ == "__main__":
    main()

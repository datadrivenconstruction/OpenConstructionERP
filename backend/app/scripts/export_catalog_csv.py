"""Export all CWICR resources into a single unified CSV for GitHub.

Extracts every unique resource (material, equipment, labor, operator, electricity)
from cost item components and writes a single flat CSV with unified columns.

Usage:
    cd backend
    python -m app.scripts.export_catalog_csv
"""

import csv
import json
import os
import sqlite3

# ── Category rules ──────────────────────────────────────────────────────────

MATERIAL_CATS = {
    "Concrete & Cement": ["concrete", "cement", "mortar"],
    "Steel & Metal": ["steel", "metal", "iron", "forging", "structure", "channel", "angle", "beam"],
    "Welding Consumables": ["weld", "electrode", "wire sv-"],
    "Wood & Timber": ["wood", "timber", "lumber", "plywood", "board", "sleeper", "prop"],
    "Pipes & Fittings": ["pipe", "tube", "valve", "fitting", "flange"],
    "Paint & Coatings": ["paint", "primer", "varnish", "putty", "enamel", "lacquer", "coating"],
    "Insulation": ["insulation", "thermal", "mineral wool"],
    "Aggregates & Earth": ["sand", "gravel", "crushed", "rock", "soil", "clay"],
    "Fasteners": ["bolt", "nut", "screw", "washer", "nail", "anchor", "rivet"],
    "Waterproofing": ["waterproof", "bitumen", "membrane", "mastic", "roofing"],
    "Electrical": ["cable", "wire pn", "wire ap", "electric", "insulating tape"],
    "Glass & Glazing": ["glass", "window", "glazing"],
    "Chemicals & Gases": ["oxygen", "acetylene", "propane", "acid", "alcohol", "solvent", "kerosene"],
    "Water & Utilities": ["water", "tap water"],
    "Rubber & Gaskets": ["rubber", "gasket", "seal", "paronite"],
}
EQUIP_CATS = {
    "Cranes": ["crane", "lifting"],
    "Trucks & Vehicles": ["truck", "flatbed", "semi-trailer", "tractor", "platform"],
    "Welding Equipment": ["weld", "arc weld", "inverter"],
    "Excavators": ["excavator", "bucket"],
    "Bulldozers": ["bulldozer"],
    "Hoists & Winches": ["winch", "hoist", "pulling force"],
    "Compressors": ["compressor"],
    "Pumps": ["pump"],
    "Pipe Equipment": ["pipe cut", "pipe bend"],
    "Testing Equipment": ["flaw detect", "radiograph"],
}


def categorize(name: str, typ: str) -> str:
    nl = name.lower()
    cats = MATERIAL_CATS if typ == "material" else EQUIP_CATS if typ == "equipment" else {}
    for cat, kws in cats.items():
        if any(kw in nl for kw in kws):
            return cat
    return {
        "labor": "Labor Grades",
        "operator": "Machine Operators",
        "electricity": "Electricity",
    }.get(typ, "Other")


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    db_path = os.path.join(os.path.dirname(__file__), "..", "..", "openestimate.db")
    conn = sqlite3.connect(db_path)

    print("Reading cost items with components...")
    rows = conn.execute(
        "SELECT code, description, unit, rate, region, classification, components, metadata "
        "FROM oe_costs_item WHERE components != '[]' AND components IS NOT NULL"
    ).fetchall()
    print(f"  {len(rows)} cost items found")

    # Aggregate by resource code + type
    resources: dict[str, dict] = {}

    for item_code, item_desc, item_unit, item_rate, region, cls_raw, comps_raw, meta_raw in rows:
        try:
            comps = json.loads(comps_raw) if isinstance(comps_raw, str) else comps_raw
            cls = json.loads(cls_raw) if isinstance(cls_raw, str) else (cls_raw or {})
        except Exception:
            continue

        for c in comps:
            code = c.get("code", "")
            if not code:
                continue

            key = f"{code}|{c.get('type', '')}"
            rate = c.get("unit_rate", 0) or 0
            cost = c.get("cost", 0) or 0
            qty = c.get("quantity", 0) or 0

            if key not in resources:
                resources[key] = {
                    "resource_code": code,
                    "resource_name": c.get("name", ""),
                    "resource_type": c.get("type", ""),
                    "unit": c.get("unit", ""),
                    "rates": [],
                    "costs": [],
                    "quantities": [],
                    "usage_count": 0,
                    "parent_collections": set(),
                    "parent_departments": set(),
                    "parent_categories": set(),
                    "regions": set(),
                    "parent_codes": set(),
                }

            r = resources[key]
            if rate > 0:
                r["rates"].append(rate)
            if cost > 0:
                r["costs"].append(cost)
            if qty > 0:
                r["quantities"].append(qty)
            r["usage_count"] += 1
            r["regions"].add(region or "")
            r["parent_codes"].add(item_code)
            if isinstance(cls, dict):
                col = cls.get("collection", "")
                dep = cls.get("department", "")
                cat = cls.get("category", "")
                if col:
                    r["parent_collections"].add(col)
                if dep:
                    r["parent_departments"].add(dep)
                if cat:
                    r["parent_categories"].add(cat)

    print(f"  {len(resources)} unique resource entries")

    # Build output rows
    output = []
    for key, r in resources.items():
        rates = [x for x in r["rates"] if x > 0]
        if not rates:
            continue

        avg_rate = round(sum(rates) / len(rates), 2)
        min_rate = round(min(rates), 2)
        max_rate = round(max(rates), 2)

        costs = [x for x in r["costs"] if x > 0]
        avg_cost = round(sum(costs) / len(costs), 2) if costs else 0

        qtys = [x for x in r["quantities"] if x > 0]
        avg_qty = round(sum(qtys) / len(qtys), 4) if qtys else 0

        category = categorize(r["resource_name"], r["resource_type"])

        output.append({
            "resource_code": r["resource_code"],
            "resource_name": r["resource_name"],
            "resource_type": r["resource_type"],
            "category": category,
            "unit": r["unit"],
            "unit_rate_avg": avg_rate,
            "unit_rate_min": min_rate,
            "unit_rate_max": max_rate,
            "avg_cost_per_use": avg_cost,
            "avg_quantity_per_use": avg_qty,
            "currency": "EUR",
            "usage_count": r["usage_count"],
            "price_variants": len(set(round(x, 2) for x in rates)),
            "regions": ";".join(sorted(r["regions"])),
            "parent_work_category": ";".join(sorted(list(r["parent_categories"])[:3])),
            "parent_collection": ";".join(sorted(list(r["parent_collections"])[:3])),
            "parent_department": ";".join(sorted(list(r["parent_departments"])[:2])),
            "used_in_items_count": len(r["parent_codes"]),
        })

    output.sort(key=lambda x: -x["usage_count"])

    # Write CSV
    out_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "catalog")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "cwicr_all_resources.csv")

    fields = [
        "resource_code",
        "resource_name",
        "resource_type",
        "category",
        "unit",
        "unit_rate_avg",
        "unit_rate_min",
        "unit_rate_max",
        "avg_cost_per_use",
        "avg_quantity_per_use",
        "currency",
        "usage_count",
        "price_variants",
        "used_in_items_count",
        "regions",
        "parent_work_category",
        "parent_collection",
        "parent_department",
    ]

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(output)

    size_kb = os.path.getsize(out_path) // 1024
    print(f"\nExported: {out_path}")
    print(f"Total: {len(output)} resources | {size_kb} KB")
    print(f"\nColumns ({len(fields)}):")
    for col in fields:
        print(f"  {col}")

    print(f"\nBy type:")
    by_type: dict[str, int] = {}
    for r in output:
        t = r["resource_type"]
        by_type[t] = by_type.get(t, 0) + 1
    for t, cnt in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {t}: {cnt}")

    print(f"\nBy category (top 20):")
    by_cat: dict[str, int] = {}
    for r in output:
        c = r["category"]
        by_cat[c] = by_cat.get(c, 0) + 1
    for c, cnt in sorted(by_cat.items(), key=lambda x: -x[1])[:20]:
        print(f"  {c}: {cnt}")

    print(f"\nTop 10 most-used resources:")
    for r in output[:10]:
        print(
            f"  {r['resource_type']:<12s} "
            f"{r['resource_name'][:45]:<45s} "
            f"{r['unit']:<15s} "
            f"avg={r['unit_rate_avg']:>10.2f} "
            f"used={r['usage_count']}"
        )

    conn.close()


if __name__ == "__main__":
    main()

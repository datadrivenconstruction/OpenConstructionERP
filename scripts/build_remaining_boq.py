#!/usr/bin/env python3
"""Construct remaining BOQ positions for TCG Brentwood Concrete Curb, Trenching,
Excavation, and Additional Work — using USA_TENNESSEE cost database items."""
import json, os, sys, urllib.error, urllib.parse, urllib.request

BASE = "http://localhost:8082/api/v1"
BOQ_ID = "914edded-ddc5-446a-ac30-a4dd34b020f9"
COST_IDS = {
    "ASP-PAV-01": "3050bf15-df87-434f-bf23-4f91c0f249f0",
    "CON-CUR-01": "1faed9f9-69df-4ea8-84b4-7eb75db0dd34",
    "CON-RCB-01": "59aa46a5-6761-4aa1-90d7-08c9209eaea5",
    "DRN-PRM-01": "9ae460a6-f0b5-49ba-b784-c1821496818c",
    "EQP-RNT-HMR": "c58d8bf8-0587-42d3-9743-178c21b80708",
    "EXC-BLK-01": "26650cb3-7160-4918-a8de-3e6b910ffb08",
    "EXC-CRW-01": "a8e34f24-3c5e-4d4c-b8fe-e279e64622ec",
    "FILL-CMP-01": "31a41024-5707-49db-8f50-d22919956739",
    "GRD-CRW-01": "03caf0c9-1891-4536-aaa5-97f2f9660a94",
    "GRD-SIT-01": "c306dd7c-cf17-435b-82ce-5e360d89f293",
    "STN-BSE-01": "f43fa511-2e24-4727-b87d-f8a62bc1ac9e",
    "STR-HDW-01": "0226654c-3921-46e8-af3d-d52a21949195",
    "STR-RCP-18": "a554af08-725c-45ed-b3b2-097678de08e9",
    "UT-COM-01": "fe010fc3-be36-4216-8533-4ee29c97daa3",
    "UT-ELC-01": "a174da8d-490c-48f5-8d38-edfa1cfa19d8",
    "UT-GAS-01": "42302363-5cee-41b8-8484-b1c5749e3cae",
    "UT-SWR-01": "1d5ee85c-7399-4cf3-9ca4-a27281657365",
    "UT-WTR-01": "eaa3f048-2587-4326-a356-2d2a608cbdb7",
}

TOKEN = None

def api(method, path, data=None):
    url = f"{BASE}{path}"
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = json.loads(e.read().decode())
        print(f"  ERROR {method} {path}: {detail.get('detail', detail)}", file=sys.stderr)
        return None

def login():
    global TOKEN
    r = api("POST", "/users/auth/demo-login/", {"email": "estimator@openestimator.io"})
    if r and "access_token" in r:
        TOKEN = r["access_token"]
        print("✓ Logged in")
    else:
        print("✗ Login failed"); sys.exit(1)

def load_cost_rates():
    r = api("GET", "/costs/?region=USA_TENNESSEE&limit=30")
    rates = {}
    for item in r.get("items", []):
        rates[item["code"]] = item["rate"]
    return rates

def main():
    login()
    cost_rates = load_cost_rates()
    print(f"✓ Loaded rates for {len(cost_rates)} cost items\n")

    POSITIONS = [
        # ── Job 4: Concrete Curb (38447) ──
        ["04.10.0010", "Concrete curb and gutter — 75 LF street frontage, 3500 PSI", "LF", 75, "CON-CUR-01"],
        ["04.10.0020", "Concrete ribbon curb — 844 LF driveway/parking perimeter, 3500 PSI", "LF", 844, "CON-RCB-01"],
        ["04.20.0010", "Subgrade preparation — curb and walkway areas", "SF", 1500, "GRD-SIT-01"],
        ["04.20.0020", "Stone base — 8\" #2A crushed aggregate under asphalt", "SF", 500, "STN-BSE-01"],
        ["04.20.0030", "Asphalt pavement — 3.5\" hot mix, road widening area", "SF", 500, "ASP-PAV-01"],
        ["04.20.0040", "Subgrade preparation — walkway areas", "SF", 2000, "GRD-SIT-01"],

        # ── Job 5: Trenching (38522) ──
        ["05.10.0010", "Sanitary sewer — 4\" PVC SDR-35 service line, 3' deep", "LF", 200, "UT-SWR-01"],
        ["05.10.0020", "Water service — 4\" PVC C900 service line, 3' deep", "LF", 200, "UT-WTR-01"],
        ["05.20.0010", "Electrical conduit — 3\" PVC schedule 40, stone dust bed, red tracer tape", "LF", 900, "UT-ELC-01"],
        ["05.20.0020", "Communications conduit — 1.5\" PVC, shares trench with electrical", "LF", 900, "UT-COM-01"],
        ["05.30.0010", "Gas line trench — 3' wide × 3' deep, stone dust backfill, yellow tape (pipe by others)", "LF", 400, "UT-GAS-01"],
        ["05.40.0010", "18\" RCP storm pipe — Class III, installed in trench", "LF", 125, "STR-RCP-18"],
        ["05.40.0020", "Precast concrete headwall — 18\" with outlet protection rip rap", "EA", 2, "STR-HDW-01"],

        # ── Job 6: Excavation (38577) ──
        ["06.10.0010", "Crawlspace and footer excavation — 5 foundations, precision grade, stockpile on site", "CY", 720, "EXC-CRW-01"],
        ["06.20.0010", "Foundation perimeter drain — 4\" corrugated perforated, geotextile wrap, #57 stone", "LF", 1000, "DRN-PRM-01"],
        ["06.30.0010", "Fine grade crawlspace — vapor barrier + 4\" #57 stone, 5 foundations", "SF", 5000, "GRD-CRW-01"],
        ["06.40.0010", "Fine grade garage areas — 5 garages, grade and compact", "SF", 2400, "GRD-SIT-01"],
        ["06.40.0020", "Fine grade porch areas — 5 porches, grade and compact", "SF", 1000, "GRD-SIT-01"],

        # ── Job 7: Additional Work (38578) ──
        ["07.10.0010", "Site layout and staking — establish corners, foundation elevation, utility locate", "LS", 1, None],
        ["07.20.0010", "Topsoil strip and stockpile — 6\" cut, stockpile on site", "CY", 200, "EXC-BLK-01"],
        ["07.20.0020", "Bulk excavation — cut to design subgrade, stockpile on site", "CY", 200, "EXC-BLK-01"],
        ["07.20.0030", "Structural fill import — placement, moisture condition, compaction to 95%", "CY", 200, "FILL-CMP-01"],
        ["07.20.0040", "Site grading and fine grade — entire disturbed area", "SF", 8400, "GRD-SIT-01"],
        ["07.30.0010", "Excavator 30T with hydraulic hammer — monthly rental", "MO", 1, "EQP-RNT-HMR"],
    ]

    items = []
    grand_total = 0.0

    for ordinal, desc, unit, qty, code in POSITIONS:
        if code and code in cost_rates:
            rate = cost_rates[code]
        elif code == "SIT-LAY-01" or code is None:
            rate = 1200.00  # manual lump sum for site layout
        else:
            rate = cost_rates.get(code, 0.0)
        total = round(qty * rate, 2)
        grand_total += total
        item = {
            "ordinal": ordinal,
            "description": desc,
            "unit": unit,
            "quantity": qty,
            "unit_rate": rate,
            "source": "manual" if code is None else "cost_database",
            "classification": {},
            "metadata": {"tcg_job_code": ordinal[:2]},
        }
        if code and code in COST_IDS:
            item["cost_item_id"] = COST_IDS[code]
        items.append(item)
        print(f"  {ordinal}  {desc[:55]:55s}  {qty:>6} {unit:>3} × ${rate:>8.2f} = ${total:>10.2f}")

    print(f"\n  {'─'*50}")
    print(f"  POSITIONS: {len(items)}    DIRECT COST: ${grand_total:,.2f}")
    print(f"  {'─'*50}\n")

    payload = {"items": items}
    print(f"Importing {len(items)} positions to BOQ {BOQ_ID}...")
    result = api("POST", f"/boq/boqs/{BOQ_ID}/positions/bulk/", payload)

    if result is None:
        print("✗ Import failed")
        sys.exit(1)

    print(f"✓ Imported {len(result)} positions")
    print(f"\nBOQ URL: /boq/boqs/{BOQ_ID}")

if __name__ == "__main__":
    main()
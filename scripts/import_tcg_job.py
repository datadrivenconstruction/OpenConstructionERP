#!/usr/bin/env python3
"""
TCG Brentwood Sitework → OCERP Import Script
Maps BedRock estimate data to OCERP BOQ positions using US cost database.
"""

import json
import sys
import urllib.request
import urllib.error
import urllib.parse

BASE_URL = "http://localhost:8082/api/v1"
TOKEN = None
PROJECT_ID = "7aa0a1a5-f20e-4653-b77b-b67883c47f2e"
BOQ_ID = "19369993-8fbc-416e-ab87-d844bd683986"


def api_call(method, path, data=None):
    url = f"{BASE_URL}{path}"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
    }
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err = json.loads(e.read().decode())
        print(f"ERROR {method} {path}: {err}", file=sys.stderr)
        raise


def login():
    global TOKEN
    resp = api_call("POST", "/users/auth/demo-login/", {"email": "estimator@openestimator.io"})
    TOKEN = resp["access_token"]
    print(f"Logged in. Token: {TOKEN[:30]}...")


def search_costs(query, limit=5):
    """Search the US cost database for relevant items."""
    resp = api_call("GET", f"/costs/?search={urllib.parse.quote(query)}&limit={limit}")
    return resp.get("items", [])


def add_position(ordinal, description, unit, quantity, unit_rate, cost_item_id=None, notes=None):
    """Add a position to the BOQ."""
    payload = {
        "boq_id": BOQ_ID,
        "ordinal": ordinal,
        "description": description,
        "unit": unit,
        "quantity": str(quantity),
        "unit_rate": str(unit_rate),
        "total": str(round(float(quantity) * float(unit_rate), 2)),
    }
    if cost_item_id:
        payload["cost_item_id"] = cost_item_id
    if notes:
        payload["notes"] = notes
    return api_call("POST", f"/boq/boqs/{BOQ_ID}/positions/", payload)


def add_markup(name, markup_type, percentage, category, apply_to):
    """Add a markup to the BOQ."""
    payload = {
        "name": name,
        "markup_type": markup_type,
        "percentage": percentage,
        "category": category,
        "apply_to": apply_to,
    }
    return api_call("POST", f"/boq/boqs/{BOQ_ID}/markups/", payload)


def main():
    login()

    # ── JOB 38254: Economy Level Site ──────────────────────────────────────
    print("\n=== Adding Job 38254: Economy Level Site ===")
    
    # Search for relevant cost items
    items = search_costs("site preparation grading", limit=10)
    print(f"Found {len(items)} site prep items")
    for i in items[:3]:
        print(f"  - {i['code']}: {i['description']} [{i['unit']}] ${i['rate']}")

    # Add positions (using catalog rates where available)
    positions = [
        ("01.01.0010", "Site preparation - cut and stockpile topsoil", "SF", 45225, 0.15),
        ("01.01.0020", "Excavate and level site for building pads", "SF", 45225, 0.50),
        ("01.01.0030", "Import and compact fill material", "CY", 1955, 8.00),
        ("01.01.0040", "Compact to 95% - subgrade preparation", "SF", 45225, 0.25),
        ("01.01.0050", "Berm construction and grading", "LF", 500, 15.00),
        ("01.01.0060", "Straw mulch stabilization", "SF", 45225, 0.08),
        ("01.01.0070", "Soil compaction testing (5 sites)", "EA", 5, 900.00),
        ("01.01.0080", "Equipment rental", "LS", 1, 3000.00),
        ("01.01.0090", "Straw stabilization", "LS", 1, 3200.00),
    ]
    for p in positions:
        add_position(*p)
        print(f"  Added {p[0]}: {p[1]}")

    # ── JOB 38304: Demolition & Disposal ───────────────────────────────────
    print("\n=== Adding Job 38304: Demolition & Disposal ===")
    
    demo_items = search_costs("demolition", limit=10)
    print(f"Found {len(demo_items)} demolition items")
    for i in demo_items[:3]:
        print(f"  - {i['code']}: {i['description']} [{i['unit']}] ${i['rate']}")

    positions = [
        ("01.02.0010", "Erosion controls - silt fence, matting", "LF", 325, 12.00),
        ("01.02.0020", "Construction entrance 20'x100'", "LS", 1, 2600.00),
        ("01.02.0030", "Orange construction fence", "LF", 325, 6.00),
        ("01.02.0040", "Demolish existing residence", "SF", 1500, 8.00),
        ("01.02.0050", "Demolish existing garage", "SF", 400, 7.00),
        ("01.02.0060", "Shed and treehouse removal", "EA", 2, 1500.00),
        ("01.02.0070", "Concrete removal (walkway, driveway, patio)", "SF", 1500, 6.00),
        ("01.02.0080", "Asphalt driveway removal", "SF", 8400, 4.00),
        ("01.02.0090", "Tree removal (12 trees)", "EA", 12, 750.00),
        ("01.02.0100", "Dumpster disposal (11 loads)", "EA", 11, 800.00),
        ("01.02.0110", "Haul concrete debris (6 loads)", "EA", 6, 450.00),
        ("01.02.0120", "Haul asphalt debris (7 loads)", "EA", 7, 450.00),
        ("01.02.0130", "Equipment rental", "LS", 1, 2800.00),
        ("01.02.0140", "Demo labor and supervision", "HR", 779, 24.00),
    ]
    for p in positions:
        add_position(*p)
        print(f"  Added {p[0]}: {p[1]}")

    # ── JOB 38396: French Drain / Stormwater ───────────────────────────────
    print("\n=== Adding Job 38396: French Drain / Stormwater ===")
    
    positions = [
        ("02.01.0010", "Stormwater excavation", "CY", 860, 12.00),
        ("02.01.0020", "Geotextile fabric", "SF", 8326, 0.50),
        ("02.01.0030", "Coarse sand bedding (3\")", "CY", 130, 35.00),
        ("02.01.0040", "#57 stone (24\")", "CY", 620, 45.00),
        ("02.01.0050", "#8 stone top course (2\")", "CY", 50, 55.00),
        ("02.01.0060", "Observation wells", "EA", 4, 275.00),
        ("02.01.0070", "Fabric (12 rolls)", "EA", 12, 200.00),
        ("02.01.0080", "Pipe for observation wells", "LS", 1, 1100.00),
        ("02.01.0090", "Equipment rental", "LS", 1, 2000.00),
        ("02.01.0100", "Rock excavation allowance", "HR", 50, 450.00),
    ]
    for p in positions:
        add_position(*p)
        print(f"  Added {p[0]}: {p[1]}")

    # ── Markups ────────────────────────────────────────────────────────────
    print("\n=== Adding Markups ===")
    markups = [
        ("Material Markup", "percentage", 20.0, "overhead", "direct_cost"),
        ("Labor Markup", "percentage", 20.0, "overhead", "direct_cost"),
        ("Overhead & Indirect", "percentage", 10.0, "overhead", "direct_cost"),
        ("Profit", "percentage", 8.0, "profit", "direct_cost"),
    ]
    for m in markups:
        add_markup(*m)
        print(f"  Added markup: {m[0]} {m[2]}%")

    print("\n=== Import Complete ===")
    print(f"Project: {PROJECT_ID}")
    print(f"BOQ: {BOQ_ID}")
    
    # Get BOQ summary
    boq = api_call("GET", f"/boq/boqs/{BOQ_ID}")
    print(f"\nBOQ Summary:")
    print(f"  Positions: {len(boq.get('positions', []))}")
    print(f"  Markups: {len(boq.get('markups', []))}")


if __name__ == "__main__":
    main()

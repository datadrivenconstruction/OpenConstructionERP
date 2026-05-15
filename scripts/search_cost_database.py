#!/usr/bin/env python3
"""
Map BedRock estimate to OCERP cost database items.
Uses cost database rates, not original estimate rates.
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


def search_costs(query, limit=50):
    """Search the US cost database."""
    resp = api_call("GET", f"/costs/?search={urllib.parse.quote(query)}&limit={limit}")
    return resp.get("items", [])


def add_position(ordinal, description, unit, quantity, unit_rate, cost_item_id=None, notes=None):
    """Add a position linked to a cost database item."""
    payload = {
        "boq_id": BOQ_ID,
        "ordinal": ordinal,
        "description": description,
        "unit": unit,
        "quantity": str(quantity),
        "unit_rate": str(unit_rate),
        "total": str(round(float(quantity) * float(unit_rate), 2)),
        "cost_item_id": cost_item_id,
    }
    if notes:
        payload["notes"] = notes
    return api_call("POST", f"/boq/boqs/{BOQ_ID}/positions/", payload)


def print_items(items, label, max_items=10):
    """Print cost items for review."""
    print(f"\n=== {label} ({len(items)} found) ===")
    for i, item in enumerate(items[:max_items]):
        print(f"  [{i+1}] {item['code']}: {item['description']} [{item['unit']}] ${item['rate']}")
        if item.get('classification'):
            cls = item['classification']
            cat = cls.get('category', '')
            dept = cls.get('department', '')
            if cat or dept:
                print(f"       Class: {cat} / {dept}")
        if item.get('components'):
            for comp in item['components'][:2]:
                print(f"       {comp['type']}: {comp['name']} {comp['quantity']} {comp['unit']} @ ${comp['unit_rate']} = ${comp['cost']}")
    if len(items) > max_items:
        print(f"  ... and {len(items) - max_items} more")


def main():
    login()

    print("=" * 60)
    print("COST DATABASE MAPPING SEARCH")
    print("=" * 60)

    # ── Search all relevant categories ──────────────────────────────────────
    searches = {
        "site_prep": search_costs("site preparation", 20),
        "topsoil": search_costs("topsoil removal", 20),
        "excavation_bulk": search_costs("bulk excavation", 20),
        "excavation_trench": search_costs("trench excavation", 20),
        "grading": search_costs("grading slope", 20),
        "fill_compaction": search_costs("fill compaction", 20),
        "erosion_control": search_costs("erosion control", 20),
        "silt_fence": search_costs("silt fence", 20),
        "construction_entrance": search_costs("construction entrance", 20),
        "demolition_masonry": search_costs("demolition masonry wall", 20),
        "demolition_concrete": search_costs("demolition concrete", 20),
        "demolition_structure": search_costs("demolition structure", 20),
        "concrete_removal": search_costs("concrete removal", 20),
        "asphalt_removal": search_costs("asphalt removal", 20),
        "tree_removal": search_costs("tree removal", 20),
        "haul_debris": search_costs("haul debris", 20),
        "dumpster": search_costs("dumpster", 20),
        "curb_concrete": search_costs("concrete curb", 20),
        "trench_utility": search_costs("utility trench", 20),
        "pipe_water": search_costs("water pipe", 20),
        "pipe_sewer": search_costs("sewer pipe", 20),
        "pipe_conduit": search_costs("electrical conduit", 20),
        "french_drain": search_costs("french drain", 20),
        "stormwater": search_costs("stormwater", 20),
        "geotextile": search_costs("geotextile", 20),
        "stone_base": search_costs("stone base", 20),
        "sand_bedding": search_costs("sand bedding", 20),
        "observation_well": search_costs("observation well", 20),
        "concrete_pipe": search_costs("concrete pipe", 20),
        "headwall": search_costs("headwall", 20),
        "compaction_test": search_costs("compaction test", 20),
        "equipment_rental": search_costs("equipment rental excavator", 20),
        "straw_mulch": search_costs("straw mulch", 20),
        "berm": search_costs("berm construction", 20),
    }

    for label, items in searches.items():
        print_items(items, label.replace("_", " ").title())

    # ── List items with NO matches ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print("ITEMS WITH ZERO DATABASE MATCHES")
    print("=" * 60)
    unmatched = [label.replace("_", " ").title() for label, items in searches.items() if len(items) == 0]
    for item in unmatched:
        print(f"  ⚠️  {item}: NO MATCHES")

    print("\n" + "=" * 60)
    print("MAPPING COMPLETE - Review items above")
    print("=" * 60)
    print(f"\nProject: {PROJECT_ID}")
    print(f"BOQ: {BOQ_ID}")
    print("\nNext: Select specific cost items and map to BOQ positions.")


if __name__ == "__main__":
    main()

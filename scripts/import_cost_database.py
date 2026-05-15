#!/usr/bin/env python3
"""
Import US Tennessee Sitework Cost Items into OCERP.
Run from project root:
  python scripts/import_cost_database.py                          # Batch 1 (default)
  python scripts/import_cost_database.py --file data/us_tn_concrete_utilities_costs.json  # Batch 2

Requires OCERP backend running at http://localhost:8082
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
import urllib.parse

BASE_URL = "http://localhost:8082/api/v1"
TOKEN = None

parser = argparse.ArgumentParser(description="Import cost items JSON into OCERP")
parser.add_argument(
    "--file", default="data/us_tn_sitework_costs.json",
    help="Path to cost items JSON file (default: data/us_tn_sitework_costs.json)"
)


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
        print(f"  ERROR {method} {path}: {err.get('detail', err)}", file=sys.stderr)
        return None


def login():
    global TOKEN
    resp = api_call("POST", "/users/auth/demo-login/", {"email": "estimator@openestimator.io"})
    if resp and "access_token" in resp:
        TOKEN = resp["access_token"]
        print("✓ Logged in as estimator@openestimator.io")
    else:
        print("✗ Login failed")
        sys.exit(1)


def validate_item(item):
    """Validate that rate == sum(components.cost)"""
    total = item.get("rate", 0)
    components = item.get("components", [])
    calculated = sum(c.get("cost", 0) for c in components)
    if abs(total - calculated) > 0.01:
        print(f"  ⚠️  {item['code']}: rate={total}, calculated={calculated:.2f} (diff={total-calculated:.2f})")
        return False
    return True


def main():
    args = parser.parse_args()
    data_file = args.file

    print("=" * 60)
    print("US Tennessee Sitework Cost Database — Import Script")
    print("=" * 60)

    # Login
    login()

    # Load data
    print(f"\nLoading {data_file}...")
    with open(data_file, "r") as f:
        items = json.load(f)
    print(f"  Found {len(items)} cost items")

    # Validate all items
    print("\nValidating component math...")
    valid = True
    for item in items:
        if not validate_item(item):
            valid = False
    if not valid:
        print("\n✗ Validation failed. Fix errors before importing.")
        sys.exit(1)
    print("  ✓ All items pass validation")

    # Import via bulk API
    print("\nImporting to OCERP...")
    result = api_call("POST", "/costs/bulk/", items)

    if result is None:
        print("✗ Bulk import failed")
        sys.exit(1)

    imported = len(result)
    print(f"  ✓ Imported {imported} cost items")

    # Verify
    print("\nVerifying import...")
    for item in items[:3]:
        search = urllib.parse.quote(item["code"])
        resp = api_call("GET", f"/costs/?search={search}&region=USA_TENNESSEE")
        if resp and resp.get("total", 0) > 0:
            print(f"  ✓ {item['code']} found in database")
        else:
            print(f"  ⚠️  {item['code']} not found (may have been skipped)")

    print("\n" + "=" * 60)
    print("Import complete!")
    print("=" * 60)
    print(f"\nView in OCERP: /costs?region=USA_TENNESSEE")
    print(f"Or search individual items:")
    for item in items:
        print(f"  /costs?search={urllib.parse.quote(item['code'])}")


if __name__ == "__main__":
    main()
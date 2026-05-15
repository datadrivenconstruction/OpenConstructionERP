#!/usr/bin/env python3
"""
Import US Tennessee Cost Items into OCERP + Extract to Catalog.

This script:
1. Logs in with regular user credentials
2. Imports both Tennessee data files (sitework + concrete/utilities)
3. Triggers catalog extraction for USA_TENNESSEE region
4. Verifies results

Usage:
    python scripts/import_tennessee_costs.py

Requires OCERP backend running at http://localhost:8000
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
import urllib.parse

BASE_URL = "http://localhost:8000/api/v1"
TOKEN = None

parser = argparse.ArgumentParser(description="Import Tennessee cost items into OCERP")
parser.add_argument(
    "--email", default="sergeilapp@gmail.com",
    help="Login email (default: sergeilapp@gmail.com)"
)
parser.add_argument(
    "--password", default="GWzGrjN.3txM332",
    help="Login password"
)
parser.add_argument(
    "--port", default="8000",
    help="Backend port (default: 8000)"
)
parser.add_argument(
    "--data-dir", default="/tmp/tn_import/tn_import_package/data",
    help="Directory containing the JSON data files"
)


def api_call(method, path, data=None, token=None):
    """Make an API call and return JSON response."""
    url = f"{BASE_URL}{path}"
    headers = {
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_body = resp.read().decode()
            return json.loads(resp_body) if resp_body else {}
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()
        try:
            err = json.loads(err_body)
        except json.JSONDecodeError:
            err = err_body
        print(f"  ERROR {method} {path}: {err.get('detail', err) if isinstance(err, dict) else err}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  ERROR {method} {path}: {e}", file=sys.stderr)
        return None


def login(email, password):
    """Authenticate and store access token."""
    global TOKEN
    resp = api_call("POST", "/users/auth/login/", {"email": email, "password": password})
    if resp and "access_token" in resp:
        TOKEN = resp["access_token"]
        print(f"  Logged in as {email}")
        return True
    else:
        print(f"  Login failed for {email}")
        return False


def slugify(text: str) -> str:
    """Create a short code-friendly slug from text."""
    import re
    text = re.sub(r'[^\w\s]', '', text.lower())
    words = text.split()
    # Take first 3 significant words, max 6 chars each
    significant = [w[:6] for w in words if len(w) > 2][:3]
    return '-'.join(significant) if significant else 'item'


def generate_component_codes(items):
    """Add unique codes to components that don't have them."""
    code_counter = {}
    for item in items:
        for comp in item.get("components", []):
            if not comp.get("code"):
                base = f"TN-{comp['type'][:3].upper()}-{slugify(comp['name'])}"
                if base in code_counter:
                    code_counter[base] += 1
                    comp["code"] = f"{base}-{code_counter[base]:02d}"
                else:
                    code_counter[base] = 1
                    comp["code"] = base
    return items


def validate_item(item):
    """Validate that rate == sum(components.cost)"""
    total = item.get("rate", 0)
    components = item.get("components", [])
    calculated = sum(c.get("cost", 0) for c in components)
    if abs(total - calculated) > 0.01:
        print(f"  {item['code']}: rate={total}, calculated={calculated:.2f} (diff={total-calculated:.2f})")
        return False
    return True


def import_file(filepath):
    """Import a single JSON file of cost items."""
    print(f"\nLoading {filepath}...")
    with open(filepath, "r") as f:
        items = json.load(f)
    print(f"  Found {len(items)} cost items")

    # Generate component codes for catalog extraction
    print("  Generating component codes...")
    items = generate_component_codes(items)
    codes_added = sum(
        1 for item in items for comp in item.get("components", []) if comp.get("code", "").startswith("TN-")
    )
    print(f"  Added {codes_added} component codes")

    # Validate all items
    print("  Validating component math...")
    invalid = []
    for item in items:
        if not validate_item(item):
            invalid.append(item['code'])
    if invalid:
        print(f"  Validation failed for {len(invalid)} items: {', '.join(invalid)}")
        return None, 0
    print("  All items pass validation")

    # Import via bulk API
    print("  Importing to OCERP...")
    result = api_call("POST", "/costs/bulk/", items, token=TOKEN)

    if result is None:
        print("  Bulk import failed")
        return None, 0

    imported = len(result)
    print(f"  Imported {imported} cost items")
    return items, imported


def verify_items(items, sample_size=3):
    """Verify a sample of imported items exist in the database."""
    print("\nVerifying import...")
    for item in items[:sample_size]:
        search = urllib.parse.quote(item["code"])
        resp = api_call("GET", f"/costs/?search={search}&region=USA_TENNESSEE", token=TOKEN)
        if resp and resp.get("total", 0) > 0:
            print(f"  {item['code']} found in database")
        else:
            print(f"  {item['code']} not found (may have been skipped)")


def extract_catalog():
    """Trigger catalog extraction from cost items."""
    print("\nTriggering catalog extraction...")
    result = api_call("POST", "/catalog/extract/", {}, token=TOKEN)
    if result:
        total = result.get("total_extracted", 0)
        by_type = result.get("by_type", {})
        print(f"  Extracted {total} resources: {by_type}")
        return True
    else:
        print("  Catalog extraction failed (admin permission may be required)")
        return False


def check_catalog_stats():
    """Check catalog stats to see if Tennessee resources appeared."""
    print("\nChecking catalog stats...")
    resp = api_call("GET", "/catalog/stats/", token=TOKEN)
    if resp:
        total = resp.get("total", 0)
        by_type = resp.get("by_type", [])
        by_category = resp.get("by_category", [])
        print(f"  Total catalog resources: {total}")
        if by_type:
            print(f"  By type:")
            for t in by_type:
                print(f"    {t['resource_type']}: {t['count']}")
    else:
        print("  Could not fetch catalog stats")


def main():
    args = parser.parse_args()
    global BASE_URL
    BASE_URL = f"http://localhost:{args.port}/api/v1"

    print("=" * 60)
    print("US Tennessee Cost Database Import + Catalog Extraction")
    print("=" * 60)

    # Login
    print("\nAuthenticating...")
    if not login(args.email, args.password):
        sys.exit(1)

    # Import both files
    files = [
        f"{args.data_dir}/us_tn_sitework_costs.json",
        f"{args.data_dir}/us_tn_concrete_utilities_costs.json",
    ]

    total_imported = 0
    all_items = []

    for filepath in files:
        items, count = import_file(filepath)
        if items is not None:
            total_imported += count
            all_items.extend(items)

    # Verify a sample
    if all_items:
        verify_items(all_items)

    # Extract catalog
    extract_catalog()

    # Check stats
    check_catalog_stats()

    # Summary
    print("\n" + "=" * 60)
    print("Import complete!")
    print("=" * 60)
    print(f"\nTotal cost items imported: {total_imported}")
    print(f"\nView in OCERP:")
    print(f"  Costs: http://localhost:{args.port}/costs?region=USA_TENNESSEE")
    print(f"  Catalog: http://localhost:{args.port}/catalog")
    print(f"\nSearch individual items:")
    for item in all_items[:5]:
        print(f"  /costs?search={urllib.parse.quote(item['code'])}")
    if len(all_items) > 5:
        print(f"  ... and {len(all_items) - 5} more")


if __name__ == "__main__":
    main()

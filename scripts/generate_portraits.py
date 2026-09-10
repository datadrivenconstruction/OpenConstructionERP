#!/usr/bin/env python3
"""Generate missing country portraits using OpenAI gpt-image-1 (DALL-E 3).

Reads the briefs from list_missing_country_portraits.py infrastructure,
generates each portrait via the OpenAI Images API, resizes to 340x480 WebP,
and saves to frontend/public/assets/people/.

Usage::

    python scripts/generate_portraits.py                    # all missing
    python scripts/generate_portraits.py --country AU       # one country
    python scripts/generate_portraits.py --country AU --limit 5  # first N
    python scripts/generate_portraits.py --dry-run          # show what would be generated

Requires: OPENAI_API_KEY in .env or environment, openai>=1.0, Pillow.
"""

from __future__ import annotations

import argparse
import base64
import io
import os
import sys
import time
from pathlib import Path

# Load .env if python-dotenv is available
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

from openai import OpenAI
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
PEOPLE_DIR = ROOT / "frontend" / "public" / "assets" / "people"

# Re-use the data from list_missing_country_portraits
sys.path.insert(0, str(ROOT / "scripts"))
from list_missing_country_portraits import (
    MARKET_NAMES,
    brief_for,
    wanted_by_country,
)

TARGET_W, TARGET_H = 340, 480


def generate_one(client: OpenAI, filename: str, prompt: str) -> bytes:
    """Generate a single portrait and return WebP bytes at 340x480."""
    # gpt-image-1 supports 1024x1792 for portrait orientation
    response = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        n=1,
        size="1024x1536",
        quality="low",
    )

    # The response may contain b64_json or a URL depending on API version
    item = response.data[0]
    if hasattr(item, "b64_json") and item.b64_json:
        img_data = base64.b64decode(item.b64_json)
    elif hasattr(item, "url") and item.url:
        import urllib.request

        with urllib.request.urlopen(item.url) as resp:
            img_data = resp.read()
    else:
        raise RuntimeError("No image data in response")

    img = Image.open(io.BytesIO(img_data))
    img = img.resize((TARGET_W, TARGET_H), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=82)
    return buf.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--country", help="restrict to one region code, e.g. AU")
    parser.add_argument("--limit", type=int, help="max portraits to generate per country")
    parser.add_argument("--dry-run", action="store_true", help="show prompts, do not generate")
    parser.add_argument(
        "--priority-roles",
        nargs="*",
        default=[
            "general-contractor",
            "site-supervisor",
            "estimator",
            "owner-client",
            "construction-manager",
        ],
        help="roles to generate first within each country",
    )
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY", "").strip().strip("'\"")
    if not api_key and not args.dry_run:
        print("OPENAI_API_KEY not set", file=sys.stderr)
        return 1

    client = OpenAI(api_key=api_key) if not args.dry_run else None

    on_disk = {p.name for p in PEOPLE_DIR.glob("prf-*.webp")}
    wanted, cases = wanted_by_country()

    if args.country:
        code = args.country.strip().upper()
        if code not in wanted:
            print(f"no playbooks carry region {code}")
            return 1
        wanted = {code: wanted[code]}

    # Zero-coverage countries first, then by case count
    zero_countries = sorted(
        [r for r in wanted if len(wanted[r] - on_disk) == len(wanted[r])],
        key=lambda r: (-cases.get(r, 0), r),
    )
    partial_countries = sorted(
        [r for r in wanted if r not in zero_countries and (wanted[r] - on_disk)],
        key=lambda r: (-cases.get(r, 0), r),
    )
    order = zero_countries + partial_countries

    total_generated = 0
    total_failed = 0

    for region in order:
        missing = sorted(wanted[region] - on_disk)
        if not missing:
            continue

        # Sort: priority roles first, then alphabetically
        priority = args.priority_roles or []

        def sort_key(name: str) -> tuple[int, str]:
            stem = name.split("-", 2)[-1].removesuffix(".webp")
            try:
                idx = priority.index(stem)
            except ValueError:
                idx = len(priority)
            return (idx, name)

        missing.sort(key=sort_key)

        if args.limit:
            missing = missing[: args.limit]

        print(f"\n=== {MARKET_NAMES.get(region, region)} ({region}), {len(missing)} portraits ===")

        for name in missing:
            prompt = brief_for(name)
            if not prompt:
                print(f"  SKIP {name} (no brief)")
                continue

            if args.dry_run:
                print(f"  {name}")
                print(f"    {prompt[:120]}...")
                continue

            dest = PEOPLE_DIR / name
            print(f"  generating {name} ...", end=" ", flush=True)
            try:
                webp_bytes = generate_one(client, name, prompt)
                dest.write_bytes(webp_bytes)
                total_generated += 1
                size_kb = len(webp_bytes) / 1024
                print(f"OK ({size_kb:.1f} KB)")
            except Exception as e:
                total_failed += 1
                print(f"FAILED: {e}")

            # Rate limiting: be gentle with the API
            time.sleep(1)

    if not args.dry_run:
        print(f"\nDone: {total_generated} generated, {total_failed} failed")
        if total_generated > 0:
            print("Run: python scripts/gen_case_country_portraits.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())

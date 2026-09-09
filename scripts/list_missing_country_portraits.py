# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Name every country portrait the cases area can ask for but does not have.

The case honeycomb shows a specialist for each case. It asks for
``prf-<country>-<stem>.webp`` and falls back, one file at a time, to the
country-blind ``prf-<stem>.webp`` when the country one is missing. That
fallback is deliberate and it is also why the gap is invisible: a market with
half its art looks exactly like a market with all of it, and nothing fails.

So the question "which countries have their own faces" has a misleading
answer. Six countries have *some*, and every one of them still falls back for
roughly half the roles its own cases reach. This script answers the question
that can be acted on instead: for each market, exactly which files are
missing.

The list is not a matter of taste. For a region it is the union of the role
casts of the company types that region's playbooks declare, so it grows when
a playbook is added and it is empty for a role no case in that market plays.
Art outside the list is never requested; art inside it that is absent is a
tile showing the wrong country.

Everything is read from the tree rather than restated here, because both
halves move: the casts live in ``caseFaces.ts`` and the company types live in
the playbooks. Restating either would drift silently, which is the failure
this whole file exists to expose.

Usage::

    python scripts/list_missing_country_portraits.py            # summary and list
    python scripts/list_missing_country_portraits.py --summary  # counts only
    python scripts/list_missing_country_portraits.py --country ZA

This reports; it never fails a build. Missing art is a backlog, not a defect,
and a gate that reddened on it would be red for as long as the backlog exists
and would teach everyone to ignore it. The gate that must stay green is
``caseFaces.test.ts``, which checks the folder and the generated manifest
agree. After adding files, run ``scripts/gen_case_country_portraits.py``.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "frontend" / "src" / "features" / "cases" / "data"
FACES_FILE = ROOT / "frontend" / "src" / "features" / "cases" / "caseFaces.ts"
PEOPLE_DIR = ROOT / "frontend" / "public" / "assets" / "people"

#: What the generator and the runtime both expect of a portrait file.
PORTRAIT_SIZE = "340x480"


def read_role_cast() -> dict[str, list[str]]:
    """Parse ``ROLE_CAST`` out of caseFaces.ts.

    Parsed rather than duplicated: a copy here would be a second source of
    truth for who holds a role, and the two would part company the first time
    somebody added a stem.
    """
    text = FACES_FILE.read_text(encoding="utf-8")
    start = text.find("export const ROLE_CAST")
    if start < 0:
        raise SystemExit(f"ROLE_CAST not found in {FACES_FILE}, the casting table has moved or been renamed")
    body = text[start : text.index("\n};", start)]
    cast: dict[str, list[str]] = {}
    for match in re.finditer(r"'([a-z-]+)':\s*\[(.*?)]", body, re.DOTALL):
        cast[match.group(1)] = re.findall(r"'(prf-[a-z0-9-]+)'", match.group(2))
    if not cast:
        raise SystemExit("ROLE_CAST parsed to nothing, the shape of the table has changed")
    return cast


def read_playbooks() -> list[tuple[str, list[str]]]:
    """Return ``(region, company_types)`` for every playbook that names a region.

    A playbook without a region is a universal case and reaches no country
    art, so it is not skipped by accident, it is skipped because it asks for
    nothing.
    """
    found: list[tuple[str, list[str]]] = []
    for path in sorted(DATA_DIR.glob("*.playbook.ts")):
        text = path.read_text(encoding="utf-8")
        region = re.search(r'region:\s*"([A-Z]{2})"', text)
        if not region:
            continue
        block = re.search(r"companyTypes:\s*\[(.*?)]", text, re.DOTALL)
        pairs = re.findall(r"'([a-z-]+)'|\"([a-z-]+)\"", block.group(1)) if block else []
        found.append((region.group(1), [single or double for single, double in pairs]))
    return found


def wanted_by_country() -> tuple[dict[str, set[str]], dict[str, int]]:
    cast = read_role_cast()
    wanted: dict[str, set[str]] = {}
    cases: dict[str, int] = {}
    for region, company_types in read_playbooks():
        code = region.lower()
        cases[region] = cases.get(region, 0) + 1
        bucket = wanted.setdefault(region, set())
        for company_type in company_types:
            for stem in cast.get(company_type, []):
                bucket.add(f"prf-{code}-{stem[len('prf-') :]}.webp")
    return wanted, cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--summary", action="store_true", help="counts only, no filenames")
    parser.add_argument("--country", help="restrict to one region code, for example ZA")
    args = parser.parse_args()

    if not PEOPLE_DIR.is_dir():
        raise SystemExit(f"{PEOPLE_DIR} does not exist")
    on_disk = {path.name for path in PEOPLE_DIR.glob("prf-*.webp")}
    wanted, cases = wanted_by_country()
    if args.country:
        code = args.country.strip().upper()
        if code not in wanted:
            print(f"no playbooks carry region {code}; regions present: {', '.join(sorted(wanted))}")
            return 0
        wanted = {code: wanted[code]}

    order = sorted(wanted, key=lambda region: (-cases[region], region))
    total = 0
    print(f"{'country':>8}  {'cases':>5}  {'asked':>5}  {'have':>4}  {'missing':>7}")
    for region in order:
        want = wanted[region]
        missing = len(want - on_disk)
        total += missing
        print(f"{region:>8}  {cases[region]:>5}  {len(want):>5}  {len(want) - missing:>4}  {missing:>7}")

    print(f"\n{total} portraits missing, all {PORTRAIT_SIZE} webp, into {PEOPLE_DIR.relative_to(ROOT).as_posix()}/")
    if total:
        print("after adding them, run: python scripts/gen_case_country_portraits.py")
    if args.summary:
        return 0

    for region in order:
        missing = sorted(wanted[region] - on_disk)
        if not missing:
            print(f"\n{region}: every portrait its cases reach is on disk")
            continue
        print(f"\n{region} ({len(missing)}):")
        for name in missing:
            print(f"  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

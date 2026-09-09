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
    python scripts/list_missing_country_portraits.py --briefs    # one brief per file

``--briefs`` exists because a list of two hundred filenames is not yet a piece
of work anybody can pick up. Whoever produces the art needs to know, for each
file, which market it is for and which trade the person in it does, and those
two facts are already in the filename and nowhere in a form a photographer or
an art tool can read. So the brief is derived from the same two halves the
count is: the country code, and the role stem.

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

#: The house style, read off the fifty portraits already shipped rather than
#: invented: a waist-up portrait, the subject facing the camera on a real
#: working site, flat overcast daylight, working clothes and the one tool or
#: document their trade actually carries. It is stated here because it is
#: stated nowhere else, and a brief that omits it produces art that does not sit
#: beside what is already on the page.
HOUSE_STYLE = (
    "Waist-up portrait, subject facing camera, photographed on a real working "
    "construction site with the site legible but out of focus behind them. "
    "Flat overcast daylight, no studio lighting, no retouching. Working clothes "
    "and safety equipment as that trade in that country actually wears them. "
    "Vertical, 340x480."
)

#: The markets the cases are written for. Names only, so a brief can say
#: "Brazil" rather than "BR"; nothing the product renders reads this. Country
#: names in the UI come from ``Intl.DisplayNames`` in
#: ``frontend/src/features/cases/regions.ts`` and must keep coming from there,
#: because those are translated and these are not.
MARKET_NAMES = {
    "AU": "Australia",
    "BR": "Brazil",
    "CA": "Canada",
    "CN": "China",
    "DE": "Germany",
    "ES": "Spain",
    "GB": "the United Kingdom",
    "HU": "Hungary",
    "IN": "India",
    "MX": "Mexico",
    "NZ": "New Zealand",
    "RU": "Russia",
    "SA": "Saudi Arabia",
    "US": "the United States",
    "ZA": "South Africa",
}

#: What the person in each portrait does, keyed by the stem the filename
#: carries. The stems are the ones ``ROLE_CAST`` deals from; a stem added there
#: without an entry here is reported rather than guessed at, because a brief
#: that invents a trade is worse than one that says it does not know.
ROLE_BRIEFS = {
    "architecture-engineering": "an architect or design engineer, holding rolled drawings or a tablet showing a plan",
    "bim-vdc": "a BIM or VDC coordinator, at a laptop showing a coordinated model, on site rather than in an office",
    "commercial-manager": "a commercial manager, with a measured bill or a contract folder",
    "construction-manager": "a construction manager, with a marked-up programme or a radio",
    "design-build": "a design and build project lead, with drawings in one hand on a site under construction",
    "estimator": "a cost estimator or quantity surveyor, with a measured bill and a scale rule",
    "facility-manager": "a facility manager, in a plant room or a finished building being handed over",
    "fitout-interiors": "a fit-out and interiors contractor, in a partly finished interior with materials samples",
    "general-contractor": "a main contractor, with rolled drawings, on a structure under construction",
    "government-agency": "a public authority officer inspecting works, with a clipboard or an inspection tablet",
    "homebuilder": "a residential homebuilder, on a house under construction typical of that country",
    "hse-manager": "a health and safety manager, with a permit board or an inspection tablet",
    "mep-contractor": "a mechanical or electrical contractor, with services being installed behind them",
    "owner-client": "an owner or client representative visiting the works, dressed for an office but wearing site PPE",
    "procurement-manager": "a procurement manager, at a materials laydown area or a delivery being checked in",
    "quality-manager": "a quality manager, taking a measurement or reviewing an inspection record",
    "real-estate-developer": "a property developer, on a development site with the scheme going up behind them",
    "scheduler-planner": "a planner or scheduler, with a printed programme on a site table",
    "site-supervisor": "a site supervisor or foreman, mid-shift, with the crew's work behind them",
    "subcontractor": "a trade subcontractor at their own trade's work, tools in hand",
    "sustainability-esg": "a sustainability or ESG lead, with insulation, recycled material or a metering point behind them",
}


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


def brief_for(name: str) -> str | None:
    """The one-line commission for a portrait filename, or None if it cannot be written.

    Returns None rather than a plausible sentence when the stem is not one this
    file knows. A brief for an invented trade would be produced, paid for and
    only then found to be the wrong picture.
    """
    stem = name[len("prf-") :].removesuffix(".webp")
    code, _, role = stem.partition("-")
    market = MARKET_NAMES.get(code.upper())
    described = ROLE_BRIEFS.get(role)
    if market is None or described is None:
        return None
    return f"A construction professional in {market}: {described}. {HOUSE_STYLE}"


def print_briefs(order: list[str], wanted: dict[str, set[str]], on_disk: set[str]) -> None:
    """One commission per missing file, grouped by market."""
    unknown: list[str] = []
    for region in order:
        missing = sorted(wanted[region] - on_disk)
        if not missing:
            continue
        print(f"\n=== {MARKET_NAMES.get(region, region)} ({region}), {len(missing)} ===")
        for name in missing:
            brief = brief_for(name)
            if brief is None:
                unknown.append(name)
                continue
            print(f"\n{name}\n  {brief}")
    if unknown:
        print(f"\n{len(unknown)} file(s) have no brief because their role stem is not described in this script:")
        for name in unknown:
            print(f"  {name}")
        print("Add the stem to ROLE_BRIEFS rather than letting the brief be guessed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--summary", action="store_true", help="counts only, no filenames")
    parser.add_argument("--country", help="restrict to one region code, for example ZA")
    parser.add_argument("--briefs", action="store_true", help="one commission per missing file, ready to hand over")
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

    if args.briefs:
        print_briefs(order, wanted, on_disk)
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

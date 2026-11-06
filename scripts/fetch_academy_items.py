"""Snapshot the public Academy site (courses, process guides, checklists, videos).

``scripts/build_video_catalog.py --courses`` turns one committed file,
``scripts/video_catalog/academy_items.json``, into the typed modules the app
links from. This script writes that file from the public site, so a new course
reaches the platform in two steps: re-run this script, give each unmapped item
its ``app_routes`` in the snapshot, then re-run ``build_video_catalog.py
--courses``.

Only public data is read: the sitemaps, then each English (unprefixed) page of
the four kinds. No account, no key. Prices are never stored: the site shows
none, and only the free/paid flag is kept (a course page that says "All N tasks
free" is free, "Pro . first K of N tasks free" is paid). An item that left the
sitemap is dropped; a changed title, URL, language list or flag is updated.

``app_routes`` is editorial. An item already in the snapshot keeps its routes;
a new course takes them from its task-module tags, a new process guide from its
subject, and anything else stays empty and is reported as unmapped.

Usage:
    py -3.14 scripts/fetch_academy_items.py [--out FILE] [--check]

With ``--check`` nothing is written; the run prints the added, removed, changed
and unmapped items and exits 1 if there is any.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "scripts" / "video_catalog" / "academy_items.json"
SITE = "https://openconstructionacademy.com"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en"}
PAGE_KIND = re.compile(r"^/(courses|processes|videos)/[^/]+/$|^/checklists/[a-z]{2}/[^/]+/$")

# Course task-module tags to app routes (first-time mapping of a new course only).
COURSE_TAG_ROUTES = {
    "BOQ": ["/boq"],
    "Contracts": ["/contracts"],
    "Variations": ["/variations", "/changeorders"],
    "Bid management": ["/tendering", "/bid-management"],
    "PDF takeoff": ["/takeoff"],
    "Schedule": ["/schedule"],
    "Site diary": ["/daily-diary"],
    "CVR": ["/cvr"],
    "Risk register": ["/risks"],
    "Inspections": ["/inspections"],
    "Carbon": ["/carbon"],
    "Safety": ["/safety"],
    "BIM hub": ["/bim"],
    "Defects": ["/defects-liability"],
    "Documents": ["/documents"],
    "Clash detection": ["/clash"],
    "Earned value": ["/full-evm", "/cost-control"],
    "Closeout": ["/closeout"],
    "Punch list": ["/punchlist"],
    "RFI": ["/rfi"],
    "NCR": ["/ncr"],
    "DWG takeoff": ["/dwg-takeoff"],
    "BIM requirements (IDS)": ["/requirements"],
    "BCF issues": ["/bcf"],
    "BIM": ["/bim"],
    "Cost database": ["/costs"],
}
# Process guide subject to app routes.
PROCESS_ROUTES = {
    "project-setup": ["/projects/new", "/projects"],
    "bim-coordination": ["/bim", "/clash", "/bcf"],
    "carbon": ["/carbon"],
    "takeoff": ["/takeoff", "/dwg-takeoff", "/quantities"],
    "estimating": ["/boq", "/estimate-basis"],
    "cost-data": ["/costs", "/cost-explorer", "/catalog"],
    "tendering": ["/tendering", "/bid-management", "/rfq-bidding"],
    "procurement": ["/procurement", "/supplier-catalogs"],
    "contracts": ["/contracts"],
    "scheduling": ["/schedule"],
    "risk": ["/risks", "/risk-analysis"],
    "cost-control": ["/cost-control", "/full-evm", "/cvr", "/5d"],
    "change-orders": ["/changeorders", "/variations"],
    "progress-billing": ["/finance"],
    "cash-flow": ["/finance", "/5d"],
    "claims": ["/claims-evidence", "/contracts"],
    "site-diary": ["/daily-diary"],
    "quality": ["/inspections", "/ncr", "/qms"],
    "safety": ["/safety"],
    "documents": ["/documents", "/files", "/cde"],
    "handover": ["/closeout", "/defects-liability"],
}
VIDEO_ID = re.compile(r"embed/([\w-]{11})")


def get(url: str) -> str:
    """Fetch a public page as text."""
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=40) as response:
        return response.read().decode("utf-8")


def text_of(fragment: str) -> str:
    """Visible text of an HTML fragment on one line."""
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))).strip()


def sitemap_paths() -> list[str]:
    """Every English page path of the four kinds named in the sitemaps, sorted."""
    paths: set[str] = set()
    for sub in re.findall(r"<loc>([^<]+)</loc>", get(f"{SITE}/sitemap.xml")):
        for loc in re.findall(r"<loc>([^<]+)</loc>", get(sub)):
            path = loc.removeprefix(SITE)
            if PAGE_KIND.match(path):
                paths.add(path)
    return sorted(paths)


def page_facts(path: str) -> tuple[str, str, str, list[str]]:
    """Page html, title, kind and the languages it lists."""
    page = get(SITE + path)
    heading = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    title = text_of(heading.group(1)) if heading else ""
    languages = [x for x in re.findall(r'<link rel="alternate" hreflang="([^"]*)"', page) if x != "x-default"]
    return page, title, path.split("/")[1], languages


def course_list_facts() -> dict[str, dict]:
    """The course index's JSON-LD items by URL: free flag and study time."""
    found: dict[str, dict] = {}
    for block in re.findall(
        r'<script type="application/ld\+json">(.*?)</script>',
        get(f"{SITE}/courses/"),
        re.S,
    ):
        data = json.loads(block)
        if data.get("@type") == "ItemList":
            for entry in data["itemListElement"]:
                found[entry["item"]["url"]] = entry["item"]
    return found


def scrape_course(path: str, page: str, title: str, languages: list[str], listing: dict[str, dict]) -> dict:
    """A course as a snapshot item; the price is not read."""
    plain = text_of(page)
    entry = listing.get(f"{SITE}{path}", {})
    badge = re.search(r"(All \d+ tasks free|Pro · first \d+ of \d+ tasks free)", plain)
    badge_text = badge.group(1) if badge else ""
    if entry.get("isAccessibleForFree") is True and badge_text.startswith("All"):
        access = "free"
    elif entry.get("isAccessibleForFree") is False and badge_text.startswith("Pro"):
        access = "paid"
    else:
        access = "unknown"
    hours = re.search(r"([\d.]+) h of study", plain)
    language = re.search(r"Language (.*?) Country and rules", plain)
    track = re.search(r"Part of track (.*?) Who this course", plain)
    tags = sorted({html.unescape(x) for x in re.findall(r'class="co-tmod"[^>]*>([^<]*)<', page)})
    item = {
        "id": "course:" + path.split("/")[2],
        "kind": "course",
        "title": title,
        "url": SITE + path,
        "languages": languages,
        "content_language": language.group(1) if language else None,
        "access": access,
        "duration": entry.get("timeRequired"),
        "study_hours": float(hours.group(1)) if hours else None,
        "topics": tags,
    }
    routes: list[str] = []
    for tag in tags:
        routes += [r for r in COURSE_TAG_ROUTES.get(tag, []) if r not in routes]
    item["app_routes"] = routes
    if track:
        item["track"] = track.group(1)
    return item


def scrape(path: str, listing: dict[str, dict]) -> dict:
    """One page as a snapshot item."""
    page, title, kind, languages = page_facts(path)
    if kind == "courses":
        return scrape_course(path, page, title, languages, listing)
    if kind == "videos":
        embed = VIDEO_ID.search(page)
        return {
            "id": "video:" + path.split("/")[2],
            "kind": "video",
            "title": title,
            "url": SITE + path,
            "access": "free",
            "youtube_id": embed.group(1) if embed else None,
        }
    if kind == "processes":
        subject = path.split("/")[2]
        return {
            "id": "article:process-" + subject,
            "kind": "article",
            "title": title,
            "url": SITE + path,
            "languages": languages,
            "access": "free",
            "topics": [subject],
            "app_routes": PROCESS_ROUTES.get(subject, []),
        }
    country = path.split("/")[2]
    return {
        "id": "checklist:" + path.split("/")[3],
        "kind": "checklist",
        "title": title,
        "url": SITE + path,
        "languages": languages,
        "content_language": "hr" if country == "hr" else "en",
        "access": "free",
        "topics": [],
        "app_routes": [],
        "market": country.upper(),
    }


def merge(old: dict[str, dict], fresh: dict[str, dict]) -> list[dict]:
    """Fresh facts over the old item; editorial fields of the old item are kept."""
    merged: list[dict] = []
    for item_id, new in fresh.items():
        was = old.get(item_id)
        if was:
            for field in (
                "app_routes",
                "topics",
                "market",
                "content_language",
                "parent_course",
            ):
                if was.get(field) and field in new and (not new[field] or new["kind"] != "course" or field != "topics"):
                    new[field] = was[field]
            if new["kind"] == "course" and not new.get("content_language"):
                new["content_language"] = was.get("content_language")
            if new.get("youtube_id") is None and was.get("youtube_id"):
                new["youtube_id"] = was["youtube_id"]
        merged.append(new)
    return merged


def report(old: dict[str, dict], merged: list[dict]) -> int:
    """Print what differs from the committed snapshot; the number of problems."""
    new_ids = {i["id"] for i in merged}
    added = [i for i in merged if i["id"] not in old]
    removed = [old[k] for k in old if k not in new_ids]
    changed = [i for i in merged if i["id"] in old and old[i["id"]] != i]
    unmapped = [i for i in merged if i["kind"] != "video" and not i.get("app_routes")]
    unknown = [i for i in merged if i["access"] not in ("free", "paid")]
    counts = {k: sum(1 for i in merged if i["kind"] == k) for k in ("course", "article", "checklist", "video")}
    paid = sum(1 for i in merged if i["kind"] == "course" and i["access"] == "paid")
    courses = counts["course"]
    print(f"{len(merged)} academy items {counts}; courses {courses - paid} free, {paid} paid")
    for label, rows in (
        ("added", added),
        ("removed", removed),
        ("changed", changed),
        ("unmapped", unmapped),
        ("access unknown", unknown),
    ):
        print(
            f"{label}: "
            + ("none" if not rows else f"{len(rows)}\n  " + "\n  ".join(f"{r['id']} {r['title']}" for r in rows))
        )
    return len(added) + len(removed) + len(changed) + len(unmapped) + len(unknown)


def main() -> None:
    """Read the site and write, or check, the snapshot."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Snapshot file to write.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Write nothing; fail if the snapshot is behind the site.",
    )
    args = parser.parse_args()
    out = Path(args.out)
    old = {i["id"]: i for i in json.loads(out.read_text(encoding="utf-8"))} if out.is_file() else {}
    paths = sitemap_paths()
    if not paths:
        raise SystemExit("ERROR: the sitemaps listed no academy pages")
    listing = course_list_facts()
    with ThreadPoolExecutor(max_workers=6) as pool:
        scraped = list(pool.map(lambda p: scrape(p, listing), paths))
    fresh = {i["id"]: i for i in scraped}
    # Same order as the committed file: courses, videos, checklists, articles by kind, then id.
    order = {"video": 0, "course": 1, "checklist": 2, "article": 3}
    merged = merge(old, dict(sorted(fresh.items(), key=lambda kv: (order[kv[1]["kind"]], kv[0]))))
    sys.stdout.reconfigure(encoding="utf-8")
    problems = report(old, merged)
    if args.check:
        raise SystemExit(1 if problems else 0)
    out.write_text(
        json.dumps(merged, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"-> {out}")


if __name__ == "__main__":
    main()

"""Rebuild the Videos catalogue from the video production registries.

The Videos page reads one generated, typed module
(``frontend/src/features/videos/academyCatalog.generated.ts``) and one folder of
compressed covers (``frontend/public/assets/videos/academy/``). Both come from
this script, never from hand edits, so adding a YouTube id after an upload is a
re-run and nothing else.

Sources, in the order they are trusted:

1. The published-links document (``ВСЕ_ВИДЕО_СО_ССЫЛКАМИ.html``), the
   authority for which videos have a YouTube id. Only the card id and the link
   are read from it; its prose is not. ``youtube_ids`` in the editorial file
   adds an id the document does not carry yet (a video uploaded before the
   document was updated). An id that contradicts another source stops the run.
2. ``gallery.json`` and ``setup_supplement.json`` from the YouTube publishing
   package: titles, short descriptions, language, series, chapters, duration
   and covers of the Builder's Playbook videos and the setup lesson.
3. The academy draft ``lessons.json`` and the Landshut ``FILMS_REGISTRY.json``:
   the German series, with its stage, roles, market, cases and chapters.
4. ``scripts/video_catalog/editorial.json``: stage, roles, market, cases and
   result for the videos the registries do not classify, plus overrides. These
   links are editorial proposals.

Case ids are checked against ``frontend/src/features/cases/data``. A case that
does not exist is dropped from the output and reported; it stays in the source.

No video file, subtitle file or local path reaches the output. MP4 files are
never shipped: every video plays from the channel.

A published video's cover is the channel's own thumbnail, loaded by the page
from the YouTube image host (``maxresdefault``; the page falls back to
``hqdefault``). Only a video that is not out yet ships a local WebP cover, and
that file is deleted by the next run once the video has an id. Unless
``--offline`` is given, the run checks that each ``maxresdefault`` exists and
lists the ones that will fall back.

Usage:
    py -3.14 scripts/build_video_catalog.py [--out-root DIR] [--publish-dir DIR]
        [--links-doc FILE] [--lessons FILE] [--films FILE] [--landshut-covers DIR]
        [--offline] [--check]
"""

from __future__ import annotations

import argparse
import html
import io
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
EDITORIAL = ROOT / "scripts" / "video_catalog" / "editorial.json"
CASES_DIR = ROOT / "frontend" / "src" / "features" / "cases" / "data"
DESKTOP = Path.home() / "Desktop"

DEFAULTS = {
    "publish_dir": DESKTOP / "BuildersPlaybook" / "YOUTUBE_PUBLISH_2026-09-25",
    "links_doc": DESKTOP / "BuildersPlaybook" / "ВСЕ_ВИДЕО_СО_ССЫЛКАМИ.html",
    "lessons": DESKTOP
    / "CodeProjects"
    / "use_cases_ocerp"
    / "academy-2030"
    / "web"
    / "lessons.json",
    "films": DESKTOP
    / "CodeProjects"
    / "use_cases_ocerp"
    / "codex_video"
    / "landshut-videothek-de"
    / "FILMS_REGISTRY.json",
    "landshut_covers": DESKTOP
    / "CodeProjects"
    / "use_cases_ocerp"
    / "codex_video"
    / "youtube-landshut-de-20260914"
    / "THUMBNAILS_UPLOAD_READY_CLEAN",
}

GENERATED_TS = Path("frontend/src/features/videos/academyCatalog.generated.ts")
GENERATED_INDEX = Path("frontend/src/features/videos/academyIndex.generated.ts")
COVERS_DIR = Path("frontend/public/assets/videos/academy")
COVER_URL = "/assets/videos/academy"
COVER_SIZE = (512, 288)
COVER_MAX_BYTES = 28 * 1024

STAGES = (
    "define",
    "design",
    "estimate",
    "procure",
    "plan",
    "build",
    "handover",
    "operate",
)
ROLES = (
    "estimator",
    "quantity-surveyor",
    "site-manager",
    "project-manager",
    "bim-coordinator",
    "procurement-buyer",
    "planner",
    "hse-officer",
    "design-lead",
    "document-controller",
    "commercial-manager",
    "accountant",
    "contract-administrator",
    "finance-manager",
    "foreman",
)
RESULTS = (
    "gaeb",
    "bill",
    "rate",
    "cost",
    "qty",
    "award",
    "invoice",
    "programme",
    "change",
    "site",
    "handover",
    "order",
)
YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")

# Mirrors DEFAULT_STAGE_BY_CATEGORY and STAGE_OVERRIDES in features/cases/stages.ts.
# academyCatalog.test.ts compares the output against the runtime function.
STAGE_BY_CATEGORY = {
    "estimating": "estimate",
    "tendering": "procure",
    "bim": "design",
    "planning": "plan",
    "site": "build",
    "quality": "build",
    "commercial": "build",
    "handover": "handover",
}
STAGE_OVERRIDES = {
    "set-up-a-new-project": "define",
    "feasibility-budget-before-design": "define",
    "set-up-the-asset-register-for-fm": "operate",
    "defects-liability-period-tracking": "operate",
}


def fail(message: str) -> None:
    """Stop the run with a message on stderr."""
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_json(path: Path) -> dict:
    """Read a UTF-8 JSON file, failing with the path when it is missing."""
    if not path.is_file():
        fail(f"source not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# ── Cases ────────────────────────────────────────────────────────────────────


def normalize_route(to: str) -> str:
    """Unscoped, query-less route base, as ``normalizeCaseRoute`` computes it."""
    if ":projectId" in to:
        to = re.sub(r"^/projects/:projectId", "", to) or "/"
        if not to.startswith("/"):
            to = "/" + to
    return to.split("?")[0]


def load_cases() -> dict[str, dict]:
    """Every shipped playbook: title pair, market, stage and module routes."""
    cases: dict[str, dict] = {}
    for path in sorted(CASES_DIR.glob("*.playbook.ts")):
        src = path.read_text(encoding="utf-8")

        def top(field: str, text: str = src) -> str | None:
            m = re.search(rf'\n  {field}:\s*"([^"]*)"', text)
            return m.group(1) if m else None

        case_id = top("id")
        if not case_id:
            continue
        title_default = re.search(r'titleDefault:\s*\n?\s*"((?:[^"\\]|\\.)*)"', src)
        routes: list[str] = []
        for to in re.findall(r'\n\s+to:\s*"([^"]+)"', src):
            route = normalize_route(to)
            if route not in routes:
                routes.append(route)
        category = top("category") or ""
        cases[case_id] = {
            "titleKey": top("titleKey") or "",
            "titleDefault": json.loads(f'"{title_default.group(1)}"')
            if title_default
            else case_id,
            "region": top("region"),
            "stage": top("stage")
            or STAGE_OVERRIDES.get(case_id)
            or STAGE_BY_CATEGORY.get(category, "build"),
            "routes": routes,
        }
    if not cases:
        fail(f"no playbooks found under {CASES_DIR}")
    return cases


# ── Sources ──────────────────────────────────────────────────────────────────


def parse_links_doc(path: Path) -> dict[str, str | None]:
    """Card id -> YouTube id (or None) from the published-links document."""
    if not path.is_file():
        fail(f"source not found: {path}")
    text = path.read_text(encoding="utf-8")
    out: dict[str, str | None] = {}
    for card in text.split("<section>")[1:]:
        meta = re.search(r'<div class="meta">([^<·]+)·', card)
        if not meta:
            continue
        card_id = html.unescape(meta.group(1)).strip()
        link = re.search(
            r'class="youtube" href="https://(?:youtu\.be/|www\.youtube\.com/watch\?v=)([A-Za-z0-9_-]{11})',
            card,
        )
        out[card_id] = link.group(1) if link else None
    if not out:
        fail(f"no video cards found in {path}")
    return out


def clock_to_seconds(clock: str) -> int:
    """``mm:ss`` or ``h:mm:ss`` to whole seconds."""
    total = 0
    for part in clock.split(":"):
        total = total * 60 + int(part)
    return total


def chapters_from_description(description: str) -> list[dict]:
    """Chapter lines (``00:24 Title``) written into a YouTube description."""
    return [
        {"t": clock_to_seconds(m.group(1)), "title": m.group(2).strip()}
        for m in re.finditer(
            r"^((?:\d+:)?\d{1,2}:\d{2})\s+(.+)$", description, re.MULTILINE
        )
    ]


def first_paragraph(text: str) -> str:
    """The first paragraph of a description, joined onto one line."""
    return " ".join(text.strip().split("\n\n")[0].split())


# ── Covers ───────────────────────────────────────────────────────────────────


def write_cover(src: Path, dest: Path) -> int:
    """Re-encode ``src`` as a 512x288 WebP no larger than COVER_MAX_BYTES."""
    if not src.is_file():
        fail(f"cover not found: {src}")
    image = Image.open(src).convert("RGB")
    target_ratio = COVER_SIZE[0] / COVER_SIZE[1]
    ratio = image.width / image.height
    if abs(ratio - target_ratio) > 0.01:
        # Centre-crop to 16:9 rather than stretch.
        if ratio > target_ratio:
            w = round(image.height * target_ratio)
            left = (image.width - w) // 2
            image = image.crop((left, 0, left + w, image.height))
        else:
            h = round(image.width / target_ratio)
            top = (image.height - h) // 2
            image = image.crop((0, top, image.width, top + h))
    image = image.resize(COVER_SIZE, Image.LANCZOS)
    for quality in range(78, 30, -4):
        buf = io.BytesIO()
        image.save(buf, "WEBP", quality=quality, method=6)
        if buf.tell() <= COVER_MAX_BYTES:
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = buf.getvalue()
            if not dest.is_file() or dest.read_bytes() != data:
                dest.write_bytes(data)
            return len(data)
    fail(f"cover {src} does not fit in {COVER_MAX_BYTES} bytes")
    return 0


def thumbnail_url(youtube_id: str, size: str = "maxresdefault") -> str:
    """The channel thumbnail the page shows for a published video."""
    return f"https://i.ytimg.com/vi/{youtube_id}/{size}.jpg"


def has_maxres_thumbnail(youtube_id: str) -> bool | None:
    """Whether ``maxresdefault`` exists; None when the host cannot be reached.

    It exists only for uploads of at least 720p. A missing one comes back as a
    404, or as a 120x90 placeholder, and the page then shows ``hqdefault``.
    """
    try:
        with urllib.request.urlopen(thumbnail_url(youtube_id), timeout=20) as response:
            data = response.read()
    except urllib.error.HTTPError:
        return False
    except (urllib.error.URLError, TimeoutError):
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            return image.width > 120
    except OSError:
        return False


def cover_slug(video_id: str) -> str:
    """File name for a video's cover."""
    return re.sub(r"[^a-z0-9]+", "-", video_id.lower()).strip("-")


# ── Build ────────────────────────────────────────────────────────────────────


def build(args: argparse.Namespace) -> None:
    """Read every source, validate, write the covers and the typed module."""
    out_root = Path(args.out_root)
    editorial = read_json(EDITORIAL)
    cases = load_cases()
    links = parse_links_doc(Path(args.links_doc))
    gallery = read_json(Path(args.publish_dir) / "gallery.json")
    setup = read_json(Path(args.publish_dir) / "setup_supplement.json")
    lessons = read_json(Path(args.lessons))
    films = read_json(Path(args.films))
    overlay: dict = editorial["videos"]
    series_meta: dict = editorial["series"]

    gallery_ids = {v["id"] for v in gallery["videos"]}
    expected = gallery_ids | {"Setup_EN"}
    if set(links) != expected:
        fail(
            "the links document and gallery.json list different videos: "
            f"only in document {sorted(set(links) - expected)}, only in gallery {sorted(expected - set(links))}"
        )

    videos: list[dict] = []
    covers: dict[str, Path] = {}

    # Setup lesson (published, outside gallery.json).
    setup_overlay = overlay["Setup_EN"]
    setup_yt = links["Setup_EN"]
    supplement_yt = re.search(r"([A-Za-z0-9_-]{11})$", setup.get("youtubeUrl") or "")
    if supplement_yt and setup_yt and supplement_yt.group(1) != setup_yt:
        fail(
            f"Setup_EN: document says {setup_yt}, setup_supplement.json says {supplement_yt.group(1)}"
        )
    setup_chapters = chapters_from_description(setup["description"])
    duration_card = re.search(
        r"Setup_EN · [^·]+· (\d+:\d{2})",
        Path(args.links_doc).read_text(encoding="utf-8"),
    )
    videos.append(
        {
            "id": "Setup_EN",
            "youtubeId": setup_yt,
            "language": "en",
            "title": setup["title"],
            "description": first_paragraph(setup["description"]),
            "chapters": setup_chapters,
            "duration": clock_to_seconds(duration_card.group(1))
            if duration_card
            else None,
            "recordedOn": "17.7",
            **{k: setup_overlay[k] for k in ("series", "seriesOrder", "startHere")},
        }
    )
    covers["Setup_EN"] = Path(args.publish_dir) / setup["thumbnail"]

    # Builder's Playbook videos from gallery.json.
    for v in gallery["videos"]:
        doc_yt = links[v["id"]]
        if v.get("youtube_id") and doc_yt and v["youtube_id"] != doc_yt:
            fail(
                f"{v['id']}: document says {doc_yt}, gallery.json says {v['youtube_id']}"
            )
        series_id = editorial["gallery_series"].get(v["series"])
        if not series_id:
            fail(
                f"{v['id']}: series {v['series']!r} has no entry in editorial gallery_series"
            )
        videos.append(
            {
                "id": v["id"],
                "youtubeId": doc_yt,
                "language": v["language"],
                "title": v["title"],
                "description": v["short_description"],
                "chapters": [
                    {"t": int(c["seconds"]), "title": c["title"]} for c in v["chapters"]
                ],
                "duration": round(v["duration_seconds"]),
                "series": series_id,
                "seriesOrder": v["series_order"],
            }
        )
        covers[v["id"]] = Path(args.publish_dir) / v["thumbnail"]

    # The German Landshut series.
    registry = {e["id"]: e for e in films["episodes"]}
    landshut = next(s for s in lessons["series"] if s["id"] == "landshut-de")
    for f in lessons["films"]:
        if f["series"] != "landshut-de":
            continue
        e = registry.get(f["id"])
        if not e:
            fail(f"{f['id']}: in lessons.json but not in FILMS_REGISTRY.json")
        videos.append(
            {
                "id": f["id"],
                "youtubeId": f.get("youtube"),
                "language": landshut["language"],
                "title": e["title"],
                "titleEn": f["title"],
                "description": e["description"],
                "produces": f.get("produces"),
                "chapters": [
                    {"t": int(c["time"]), "title": c["title"]} for c in e["chapters"]
                ],
                "duration": round(e["duration"]),
                "series": "landshut-de",
                "seriesOrder": f["no"],
                "stage": f["stage"],
                "roles": f["roles"],
                "market": f["region"],
                "cases": f["cases"],
            }
        )
        covers[f["id"]] = (
            Path(args.landshut_covers) / f"landshut-{f['no']:02d}-cover.jpg"
        )

    # Earlier walkthroughs and talks, kept in the editorial file.
    for x in editorial.get("extras", []):
        videos.append(
            {
                k: x[k]
                for k in (
                    "id",
                    "youtubeId",
                    "language",
                    "title",
                    "description",
                    "series",
                    "seriesOrder",
                    "recordedOn",
                    "duration",
                )
                if k in x
            }
            | {"chapters": []}
        )
        covers[x["id"]] = EDITORIAL.parent / x["cover"]

    # Ids added in the editorial file ahead of the links document.
    by_id = {v["id"]: v for v in videos}
    for vid, yt in editorial.get("youtube_ids", {}).items():
        if vid.startswith("_"):
            continue
        if vid not in by_id:
            fail(f"youtube_ids: {vid!r} is not a video in the catalogue")
        known = by_id[vid]["youtubeId"]
        if known and known != yt:
            fail(f"{vid}: youtube_ids says {yt}, the sources say {known}")
        by_id[vid]["youtubeId"] = yt

    # Overlay, classification and validation.
    orphans: dict[str, list[str]] = {}
    extras_by_id = {x["id"]: x for x in editorial.get("extras", [])}
    for v in videos:
        o = {**overlay.get(v["id"], {}), **extras_by_id.get(v["id"], {})}
        for field in ("stage", "roles", "market", "cases", "result", "startHere"):
            if field in o:
                v[field] = o[field]
        v.setdefault("roles", [])
        v.setdefault("market", None)
        v.setdefault("cases", [])
        v.setdefault("result", None)
        series = series_meta.get(v["series"])
        if not series:
            fail(f"{v['id']}: unknown series {v['series']!r}")
        v["channel"] = series["channel"]
        if v.get("stage") not in STAGES:
            fail(f"{v['id']}: stage {v.get('stage')!r} is not a lifecycle stage")
        bad_roles = [r for r in v["roles"] if r not in ROLES]
        if bad_roles:
            fail(f"{v['id']}: unknown roles {bad_roles}")
        if v["result"] is not None and v["result"] not in RESULTS:
            fail(f"{v['id']}: unknown result {v['result']!r}")
        if v["youtubeId"] is not None and not YOUTUBE_ID.match(v["youtubeId"]):
            fail(f"{v['id']}: malformed YouTube id {v['youtubeId']!r}")
        v["status"] = "published" if v["youtubeId"] else "coming_soon"
        missing = [c for c in v["cases"] if c not in cases]
        if missing:
            orphans[v["id"]] = missing
        v["cases"] = [c for c in v["cases"] if c in cases]
        routes: list[str] = []
        for c in v["cases"]:
            for r in cases[c]["routes"]:
                if r not in routes:
                    routes.append(r)
        v["routes"] = routes
        v["cover"] = (
            thumbnail_url(v["youtubeId"])
            if v["youtubeId"]
            else f"{COVER_URL}/{cover_slug(v['id'])}.webp"
        )

    ids = [v["id"] for v in videos]
    if len(set(ids)) != len(ids):
        fail(f"duplicate video ids: {sorted({i for i in ids if ids.count(i) > 1})}")
    yts = [v["youtubeId"] for v in videos if v["youtubeId"]]
    if len(set(yts)) != len(yts):
        fail("a YouTube id is used by two videos")

    series_order = {sid: s["order"] for sid, s in series_meta.items()}
    videos.sort(key=lambda v: (series_order[v["series"]], v["seriesOrder"], v["id"]))

    # Local covers, for the videos that are not out yet only.
    cover_bytes = 0
    local = [v for v in videos if not v["youtubeId"]]
    if not args.check:
        for v in local:
            cover_bytes += write_cover(
                covers[v["id"]], out_root / COVERS_DIR / f"{cover_slug(v['id'])}.webp"
            )
        # A published video's cover now comes from the channel, and a removed
        # video's is dead weight in the wheel: both go.
        wanted = {f"{cover_slug(v['id'])}.webp" for v in local}
        for stale in (out_root / COVERS_DIR).glob("*.webp"):
            if stale.name not in wanted:
                stale.unlink()
    fallback: list[str] = []
    if not args.offline:
        for v in videos:
            if v["youtubeId"] and has_maxres_thumbnail(v["youtubeId"]) is False:
                fallback.append(v["id"])

    used_cases = sorted({c for v in videos for c in v["cases"]})
    field_order = (
        "id",
        "youtubeId",
        "status",
        "channel",
        "language",
        "market",
        "series",
        "seriesOrder",
        "startHere",
        "stage",
        "roles",
        "cases",
        "routes",
        "result",
        "title",
        "titleEn",
        "description",
        "produces",
        "recordedOn",
        "duration",
        "cover",
        "chapters",
    )
    catalog = {
        "channelId": gallery["channel_id"],
        "channelName": gallery["channel"],
        "series": [
            {
                "id": sid,
                **{
                    k: s[k]
                    for k in ("title", "titleKey", "language", "market", "channel")
                    if k in s
                },
            }
            for sid, s in sorted(series_meta.items(), key=lambda kv: kv[1]["order"])
        ],
        "videos": [
            {k: v[k] for k in field_order if k in v and v[k] is not None}
            for v in videos
        ],
        "cases": {c: cases[c] for c in used_cases},
    }
    body = json.dumps(catalog, ensure_ascii=False, indent=2)
    ts = (
        "// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP\n"
        "// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction\n"
        "//\n"
        "// GENERATED by scripts/build_video_catalog.py from the video production\n"
        "// registries and scripts/video_catalog/editorial.json. Do not edit by hand:\n"
        "// change a source and re-run the script.\n\n"
        "import type { AcademyCatalog } from './academyTypes';\n\n"
        f"export const ACADEMY_CATALOG: AcademyCatalog = {body};\n"
    )
    # A few hundred bytes the app shell and the case runner can import eagerly
    # to decide whether to load the catalogue at all.
    route_counts: dict[str, int] = {}
    case_counts: dict[str, int] = {}
    for v in videos:
        for r in v["routes"]:
            route_counts[r] = route_counts.get(r, 0) + 1
        for c in v["cases"]:
            case_counts[c] = case_counts.get(c, 0) + 1
    routes_json = json.dumps(dict(sorted(route_counts.items())), indent=2)
    cases_json = json.dumps(dict(sorted(case_counts.items())), indent=2)
    index_ts = (
        "// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP\n"
        "// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction\n"
        "//\n"
        "// GENERATED by scripts/build_video_catalog.py. How many videos link to each\n"
        "// module route and each case, so a screen can tell whether it has videos\n"
        "// without loading the catalogue. Two exports, so the app shell pulls in\n"
        "// the route counts only. Do not edit by hand.\n\n"
        f"export const VIDEO_COUNT_BY_ROUTE: Record<string, number> = {routes_json};\n\n"
        f"export const VIDEO_COUNT_BY_CASE: Record<string, number> = {cases_json};\n"
    )
    for rel, text in ((GENERATED_TS, ts), (GENERATED_INDEX, index_ts)):
        target = out_root / rel
        if args.check:
            current = target.read_text(encoding="utf-8") if target.is_file() else ""
            if current != text:
                fail(f"{rel} is out of date; re-run scripts/build_video_catalog.py")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")

    published = sum(1 for v in videos if v["status"] == "published")
    chapters = sum(len(v["chapters"]) for v in videos)
    print(
        f"videos: {len(videos)} ({published} published, {len(videos) - published} coming soon)"
    )
    print(f"chapters: {chapters}")
    print(f"cases linked: {len(used_cases)} distinct")
    if not args.check:
        print(
            f"local covers (coming soon only): {len(local)} files, {cover_bytes} bytes"
            f" ({cover_bytes / 1024:.1f} KiB)"
        )
    if not args.offline:
        print(
            "channel covers without maxresdefault (page shows hqdefault): "
            + (", ".join(fallback) if fallback else "none")
        )
    if orphans:
        print("orphan case ids (kept in the source, left out of the catalogue):")
        for vid, missing in orphans.items():
            print(f"  {vid}: {', '.join(missing)}")
    else:
        print("orphan case ids: none")


def main() -> None:
    """Parse arguments and run the build."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--out-root", default=str(ROOT), help="Tree to write into (default: the repo)."
    )
    parser.add_argument("--publish-dir", default=str(DEFAULTS["publish_dir"]))
    parser.add_argument("--links-doc", default=str(DEFAULTS["links_doc"]))
    parser.add_argument("--lessons", default=str(DEFAULTS["lessons"]))
    parser.add_argument("--films", default=str(DEFAULTS["films"]))
    parser.add_argument("--landshut-covers", default=str(DEFAULTS["landshut_covers"]))
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Do not check the channel thumbnails.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the generated module is out of date.",
    )
    build(parser.parse_args())


if __name__ == "__main__":
    main()

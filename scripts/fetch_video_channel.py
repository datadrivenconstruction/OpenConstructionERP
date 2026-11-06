"""Snapshot the public OpenConstruction Academy channel for the Videos catalogue.

``scripts/build_video_catalog.py`` takes the series that were published straight
to the channel (with no production registry behind them) from one committed
file, ``scripts/video_catalog/channel_snapshot.json``. This script writes that
file from the public channel pages, so a new upload reaches the platform in two
steps: re-run this script, then give the video a line in ``channel_videos`` of
``scripts/video_catalog/editorial.json`` and re-run the catalogue build.

Only public data is read (the uploads playlist, the playlists tab and each
watch page), with no API key and no account. Per video the snapshot keeps the
channel title, the first paragraph of the description, the chapter lines of the
description, the running time and the publication date. Per playlist it keeps
the title and the video ids in playlist order.

With ``--check`` nothing is written: the run lists the public uploads that the
generated catalogue does not carry, and the carried ids that are no longer
public, and exits 1 if there is any. It reads only the uploads list, so the
weekly workflow can run it without the video production files.

Usage:
    py -3.14 scripts/fetch_video_channel.py [--out FILE] [--check]
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "scripts" / "video_catalog" / "channel_snapshot.json"
CHANNEL_ID = "UCQ3IWLMLnBFwNeG5VBxXQ5Q"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en",
    "Cookie": "CONSENT=YES+1",
}
VIDEO_ID = re.compile(r'"videoId":"([\w-]{11})"')
PLAYLIST_ID = re.compile(r'"playlistId":"(PL[\w-]+)"')
CATALOGUE = ROOT / "frontend" / "src" / "features" / "videos" / "academyCatalog.generated.ts"
MAX_UPLOADS = 2000
CHAPTER_LINE = re.compile(r"^((?:\d+:)?\d{1,2}:\d{2})\s+(.+)$", re.MULTILINE)


def get(url: str) -> str:
    """Fetch a public YouTube page as text."""
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=40) as response:
        return response.read().decode("utf-8")


def unique(pattern: re.Pattern[str], text: str) -> list[str]:
    """Every match of ``pattern``'s first group, first occurrence order."""
    return list(dict.fromkeys(pattern.findall(text)))


def clock_to_seconds(clock: str) -> int:
    """``mm:ss`` or ``h:mm:ss`` to whole seconds."""
    total = 0
    for part in clock.split(":"):
        total = total * 60 + int(part)
    return total


def first_paragraph(text: str) -> str:
    """The first paragraph of a description, joined onto one line."""
    return " ".join(text.strip().split("\n\n")[0].split())


def walk_video_ids(node: object, found: list[str]) -> None:
    """Collect every ``videoId`` of a decoded YouTube response, in order."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "videoId" and isinstance(value, str):
                found.append(value)
            else:
                walk_video_ids(value, found)
    elif isinstance(node, list):
        for value in node:
            walk_video_ids(value, found)


def walk_tokens(node: object, found: list[str]) -> None:
    """Collect every continuation token of a decoded YouTube response."""
    if isinstance(node, dict):
        command = node.get("continuationCommand")
        if isinstance(command, dict) and isinstance(command.get("token"), str):
            found.append(command["token"])
        for value in node.values():
            walk_tokens(value, found)
    elif isinstance(node, list):
        for value in node:
            walk_tokens(value, found)


def all_uploads() -> list[str]:
    """Every public upload id, newest first, following the playlist's continuations."""
    page = get(f"https://www.youtube.com/playlist?list=UU{CHANNEL_ID[2:]}&hl=en")
    uploads = unique(VIDEO_ID, page)
    # The page carries the public web-client key and version of the site itself.
    key = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', page)
    version = re.search(r'"clientVersion":"([^"]+)"', page)
    tokens = re.findall(r'"continuationCommand":\{"token":"([^"]+)"', page)[-1:]
    while tokens and key and version and len(uploads) < MAX_UPLOADS:
        body = json.dumps(
            {
                "context": {
                    "client": {
                        "clientName": "WEB",
                        "clientVersion": version.group(1),
                        "hl": "en",
                    }
                },
                "continuation": tokens[0],
            }
        ).encode()
        request = urllib.request.Request(
            f"https://www.youtube.com/youtubei/v1/browse?key={key.group(1)}",
            data=body,
            headers={**HEADERS, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=40) as response:
            data = json.loads(response.read().decode("utf-8"))
        ids: list[str] = []
        walk_video_ids(data, ids)
        uploads = list(dict.fromkeys(uploads + ids))
        tokens = []
        walk_tokens(data, tokens)
        tokens = tokens[-1:]
    return uploads


def check_against_catalogue(uploads: list[str]) -> int:
    """Print the uploads the catalogue lacks and the ids it carries that are gone; exit code."""
    source = CATALOGUE.read_text(encoding="utf-8")
    catalogue = json.loads(source[source.index("= {") + 2 : source.rindex(";")])
    # Talks and walkthroughs of the other channel are in the catalogue but not in this uploads list.
    carried = {v["youtubeId"] for v in catalogue["videos"] if v.get("youtubeId") and v.get("channel") == "academy"}
    new = [v for v in uploads if v not in carried]
    gone = sorted(carried - set(uploads))
    print(f"{len(uploads)} public uploads, {len(carried)} in the catalogue")
    print("uploads not in the catalogue: " + ("none" if not new else ", ".join(new)))
    print("catalogue ids no longer public: " + ("none" if not gone else ", ".join(gone)))
    return 1 if new or gone else 0


def video_details(youtube_id: str) -> dict:
    """Title, summary, chapters, running time and date of one public video."""
    page = get(f"https://www.youtube.com/watch?v={youtube_id}&hl=en")
    match = re.search(r"ytInitialPlayerResponse\s*=\s*(\{.+?\});(?:var|</script>)", page)
    if not match:
        raise SystemExit(f"ERROR: no player data on the watch page of {youtube_id}")
    player = json.loads(match.group(1))
    details = player.get("videoDetails", {})
    micro = player.get("microformat", {}).get("playerMicroformatRenderer", {})
    description = details.get("shortDescription", "")
    return {
        "youtubeId": youtube_id,
        "title": details.get("title", ""),
        "summary": first_paragraph(description),
        "chapters": [
            {"t": clock_to_seconds(m.group(1)), "title": m.group(2).strip()} for m in CHAPTER_LINE.finditer(description)
        ],
        "duration": int(details.get("lengthSeconds") or 0),
        "published": (micro.get("publishDate") or "")[:10],
    }


def main() -> None:
    """Read the channel and write the snapshot."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Snapshot file to write.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Write nothing; fail if the catalogue is behind the channel.",
    )
    args = parser.parse_args()

    # The uploads playlist (UU + the channel id without its UC) lists every
    # public upload, newest first, a hundred per page.
    uploads = all_uploads()
    if not uploads:
        raise SystemExit("ERROR: the uploads playlist came back empty")
    if args.check:
        raise SystemExit(check_against_catalogue(uploads))

    playlists = []
    for playlist_id in unique(
        PLAYLIST_ID,
        get(f"https://www.youtube.com/channel/{CHANNEL_ID}/playlists?hl=en"),
    ):
        page = get(f"https://www.youtube.com/playlist?list={playlist_id}&hl=en")
        title = re.search(r'<meta property="og:title" content="([^"]*)"', page)
        playlists.append(
            {
                "id": playlist_id,
                "title": html.unescape(title.group(1)) if title else "",
                "videos": [v for v in unique(VIDEO_ID, page) if v in uploads],
            }
        )

    videos = sorted((video_details(v) for v in uploads), key=lambda v: (v["published"], v["title"]))
    snapshot = {
        "_note": "Written by scripts/fetch_video_channel.py from the public channel pages. Do not edit by hand.",
        "channelId": CHANNEL_ID,
        "videos": videos,
        "playlists": sorted(playlists, key=lambda p: p["id"]),
    }
    out = Path(args.out)
    out.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"{len(videos)} public videos, {len(playlists)} playlists -> {out}")


if __name__ == "__main__":
    main()

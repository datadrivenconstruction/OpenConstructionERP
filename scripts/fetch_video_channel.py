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

Usage:
    py -3.14 scripts/fetch_video_channel.py [--out FILE]
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
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en", "Cookie": "CONSENT=YES+1"}
VIDEO_ID = re.compile(r'"videoId":"([\w-]{11})"')
PLAYLIST_ID = re.compile(r'"playlistId":"(PL[\w-]+)"')
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
    args = parser.parse_args()

    # The uploads playlist (UU + the channel id without its UC) lists every
    # public upload in one page of up to a hundred, newest first.
    uploads = unique(VIDEO_ID, get(f"https://www.youtube.com/playlist?list=UU{CHANNEL_ID[2:]}&hl=en"))
    if not uploads:
        raise SystemExit("ERROR: the uploads playlist came back empty")
    if len(uploads) >= 100:
        raise SystemExit("ERROR: 100 uploads or more; the first page no longer holds them all")

    playlists = []
    for playlist_id in unique(PLAYLIST_ID, get(f"https://www.youtube.com/channel/{CHANNEL_ID}/playlists?hl=en")):
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
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"{len(videos)} public videos, {len(playlists)} playlists -> {out}")


if __name__ == "__main__":
    main()

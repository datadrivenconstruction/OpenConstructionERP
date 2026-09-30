"""Render the two README "Project growth" charts from the GitHub API.

    docs/readme-charts/star-history-{light,dark}.svg
    docs/readme-charts/download-history-{light,dark}.svg

Both charts put real calendar time on the x axis. An earlier version spaced the
points by index, one step per star or per release, which stretched quiet weeks
and squeezed busy ones and gave every curve the same smooth shape whatever the
repository actually did. It also printed month-day labels without a year and
lived on the marketing site, where nothing regenerated it.

Star history is the cumulative count of the current stargazers by the day each
of them starred, from `GET /repos/{repo}/stargazers` with the
`application/vnd.github.star+json` media type, which carries `starred_at`.
Someone who starred and later unstarred is not in that list, so the line never
shows a star that is gone. The line is drawn as steps, one per day with stars,
and nothing is interpolated between them.

Release downloads are the GitHub release asset download counts as the API
reports them today, summed per release and accumulated in the order the releases
were published. A point therefore reads "downloads so far of every release
published up to this date", not "downloads that happened by this date": GitHub
keeps no per-day history of asset downloads.

Usage:
    python scripts/render_readme_growth_charts.py
    GH_TOKEN=$(gh auth token) python scripts/render_readme_growth_charts.py

The token is optional. Without it the unauthenticated rate limit of 60 requests
an hour still covers a repository with a few thousand stars.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path

REPO = "datadrivenconstruction/OpenConstructionERP"
API = f"https://api.github.com/repos/{REPO}"
OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "readme-charts"

THEMES = {
    "light": {"bg": "#ffffff", "text": "#1f2328", "sub": "#59636e", "grid": "#d1d9e0"},
    "dark": {"bg": "#0d1117", "text": "#f0f6fc", "sub": "#9198a1", "grid": "#3d444d"},
}
ACCENTS = {
    "stars": {"light": "#bf8700", "dark": "#e3b341"},
    "downloads": {"light": "#0969da", "dark": "#4493f8"},
}

W, H = 720, 320
PAD_L, PAD_R, PAD_T, PAD_B = 64, 28, 52, 40
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"


def _get(url: str, accept: str = "application/vnd.github+json") -> tuple[list | dict, str]:
    req = urllib.request.Request(url, headers={"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"})
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read()), resp.headers.get("Link", "")


def _paginate(url: str, accept: str = "application/vnd.github+json") -> list[dict]:
    items: list[dict] = []
    next_url: str | None = url
    while next_url:
        page, link = _get(next_url, accept)
        items.extend(page)
        next_url = None
        for part in link.split(","):
            if 'rel="next"' in part:
                next_url = part[part.index("<") + 1 : part.index(">")]
    return items


def _day(ts: str) -> date:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).date()


def star_series() -> list[tuple[date, int]]:
    """Cumulative stars at the end of each day that had at least one."""
    stars = _paginate(f"{API}/stargazers?per_page=100", "application/vnd.github.star+json")
    per_day: dict[date, int] = {}
    for s in stars:
        d = _day(s["starred_at"])
        per_day[d] = per_day.get(d, 0) + 1
    total, series = 0, []
    for d in sorted(per_day):
        total += per_day[d]
        series.append((d, total))
    return series


def download_series() -> list[tuple[date, int]]:
    """Cumulative asset downloads of the releases published up to each release date."""
    releases = [r for r in _paginate(f"{API}/releases?per_page=100") if not r["draft"] and r["published_at"]]
    per_day: dict[date, int] = {}
    for r in releases:
        d = _day(r["published_at"])
        per_day[d] = per_day.get(d, 0) + sum(a["download_count"] for a in r["assets"])
    total, series = 0, []
    for d in sorted(per_day):
        total += per_day[d]
        series.append((d, total))
    return series


def _nice_step(max_val: int) -> int:
    raw = max(max_val, 1) / 4
    mag = 10 ** (len(str(int(raw))) - 1)
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return int(m * mag)
    return int(10 * mag)


def _month_ticks(start: date, end: date) -> list[date]:
    ticks, y, m = [], start.year, start.month + 1
    while True:
        if m > 12:
            y, m = y + 1, 1
        t = date(y, m, 1)
        if t > end:
            return ticks
        ticks.append(t)
        m += 1


def render(series: list[tuple[date, int]], start: date, end: date, theme: str, kind: str) -> str:
    c, accent = THEMES[theme], ACCENTS[kind][theme]
    title, unit = ("Star history", "stars") if kind == "stars" else ("Release downloads", "downloads")
    note = (
        "Current stargazers by the day they starred"
        if kind == "stars"
        else "GitHub release assets, accumulated by release date"
    )
    total = series[-1][1]
    step = _nice_step(total)
    y_max = step * -(-total // step)
    span = max((end - start).days, 1)
    cw, ch = W - PAD_L - PAD_R, H - PAD_T - PAD_B

    def x(d: date) -> float:
        return PAD_L + (d - start).days / span * cw

    def y(v: int) -> float:
        return PAD_T + ch - v / y_max * ch

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'font-family="{FONT}" role="img" aria-label="{title}: {total:,} {unit} as of {end.isoformat()}">',
        f'<rect width="{W}" height="{H}" rx="8" fill="{c["bg"]}"/>',
        f'<text x="{PAD_L}" y="22" fill="{c["text"]}" font-size="14" font-weight="600">{title}</text>',
        f'<text x="{PAD_L}" y="39" fill="{c["sub"]}" font-size="11">{note}</text>',
        f'<text x="{W - PAD_R}" y="22" fill="{c["text"]}" font-size="14" font-weight="600" '
        f'text-anchor="end">{total:,} {unit}</text>',
        f'<text x="{W - PAD_R}" y="39" fill="{c["sub"]}" font-size="11" text-anchor="end">'
        f"as of {end.day} {MONTHS[end.month - 1]} {end.year}</text>",
    ]
    for v in range(0, y_max + 1, step):
        gy = y(v)
        parts.append(
            f'<line x1="{PAD_L}" y1="{gy:.1f}" x2="{W - PAD_R}" y2="{gy:.1f}" stroke="{c["grid"]}" stroke-width="0.6"/>'
        )
        parts.append(
            f'<text x="{PAD_L - 8}" y="{gy + 4:.1f}" fill="{c["sub"]}" font-size="11" text-anchor="end">{v:,}</text>'
        )
    ticks = _month_ticks(start, end)
    for t in ticks:
        tx = x(t)
        label = MONTHS[t.month - 1] + (f" {t.year}" if t.month == 1 or t == ticks[0] else "")
        parts.append(
            f'<line x1="{tx:.1f}" y1="{PAD_T + ch:.1f}" x2="{tx:.1f}" y2="{PAD_T + ch + 4:.1f}" stroke="{c["sub"]}"/>'
        )
        parts.append(
            f'<text x="{tx:.1f}" y="{H - 14}" fill="{c["sub"]}" font-size="11" text-anchor="middle">{label}</text>'
        )
    parts.append(
        f'<line x1="{PAD_L}" y1="{PAD_T + ch:.1f}" x2="{W - PAD_R}" y2="{PAD_T + ch:.1f}" stroke="{c["sub"]}"/>'
    )

    # Step line: the value holds until the next day that changed it, and runs flat to today.
    pts = [(x(start), y(0))]
    prev = 0
    for d, v in series:
        pts += [(x(d), y(prev)), (x(d), y(v))]
        prev = v
    pts.append((x(end), y(prev)))
    line = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
    base = PAD_T + ch
    parts.append(
        f'<polygon points="{x(start):.1f},{base:.1f} {line} {x(end):.1f},{base:.1f}" fill="{accent}" fill-opacity="0.12"/>'
    )
    parts.append(f'<polyline points="{line}" fill="none" stroke="{accent}" stroke-width="2" stroke-linejoin="round"/>')
    parts.append(f'<circle cx="{x(end):.1f}" cy="{y(total):.1f}" r="3.5" fill="{accent}"/>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="output directory")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    repo, _ = _get(API)
    start = _day(repo["created_at"])
    end = datetime.now(UTC).date()
    for kind, series in (("stars", star_series()), ("downloads", download_series())):
        if not series:
            raise SystemExit(f"no {kind} data returned by the API")
        name = "star-history" if kind == "stars" else "download-history"
        for theme in THEMES:
            path = args.out / f"{name}-{theme}.svg"
            path.write_text(render(series, start, end, theme, kind), encoding="utf-8")
        print(f"{name}: {series[-1][1]:,} {kind} over {len(series)} days with changes, as of {end}")


if __name__ == "__main__":
    main()

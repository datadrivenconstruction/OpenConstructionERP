"""Crawl each brand homepage and extract a likely logo asset URL.

For a small set of construction/engineering firms whose Google faviconV2
returns a generic globe, this script visits the live homepage and pulls
the first <img> in <header> (or with 'logo' in class/src/alt) so we get
the actual brand mark instead of a placeholder.

Output: prints a Python dict literal that can be pasted into a follow-up
script to update the marquee chips.
"""
import re
import urllib.request
import urllib.parse
import ssl
from html.parser import HTMLParser

DOMAINS = [
    # Try a wide net of plausible domain variants for the still-missing brands.
    ("tmmgroup.com", "TMM Group"),
    ("tmm-group.com", "TMM Group v2"),
    ("www.tmm-group.com", "TMM Group v3"),
    ("tmm.com.tr", "TMM Group v4"),
    ("pbs-ingenieure.de", "pbs Ingenieure v2"),
    ("www.pbs-ingenieure.de", "pbs Ingenieure v3"),
    ("axia-energy.com", "AXIA Energia v2"),
    ("axiaenergia.com", "AXIA Energia v3"),
    ("axiaenergia.it", "AXIA Energia v4"),
    ("www.axia-energia.it", "AXIA Energia v5"),
    ("scon-renewables.de", "scon v2"),
    ("www.scon-renewables.de", "scon v3"),
    ("scon.de", "scon v4"),
    ("shapemaker.io", "Shapemaker"),
    ("www.shapemaker.io", "Shapemaker v2"),
    ("hofschroeer.com", "Hofschroeer"),
    ("www.hofschroeer.com", "Hofschroeer v2"),
]


class FindLogo(HTMLParser):
    """Walk the DOM, score each <img>, and keep the highest-scoring one."""

    def __init__(self, base: str):
        super().__init__()
        self.base = base
        self.in_header = 0
        self.candidates: list[tuple[int, str, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag == "header":
            self.in_header += 1
        if tag == "img":
            d = dict(attrs)
            src = d.get("src") or d.get("data-src") or ""
            if not src or src.startswith("data:"):
                return
            alt = (d.get("alt") or "").lower()
            cls = (d.get("class") or "").lower()
            score = 0
            blob = (src + " " + alt + " " + cls).lower()
            if "logo" in blob:
                score += 6
            if "brand" in blob:
                score += 3
            if self.in_header:
                score += 4
            if any(b in src.lower() for b in ("favicon", "icon-", "/icons/", "social", "twitter", "facebook", "linkedin", "youtube", "instagram", "wechat")):
                score -= 8
            # Prefer SVG / PNG over WebP/JPG (better compositing, smaller).
            if src.lower().endswith(".svg"):
                score += 3
            elif src.lower().endswith(".png"):
                score += 2
            self.candidates.append((score, src, alt))

    def handle_endtag(self, tag):
        if tag == "header" and self.in_header:
            self.in_header -= 1


def absolute(base: str, src: str) -> str:
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("http"):
        return src
    return urllib.parse.urljoin(base, src)


def find_logo(domain: str) -> str | None:
    base = f"https://{domain}/"
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # allow self-signed/expired
        req = urllib.request.Request(
            base,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; LogoFinder/1.0)",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
            raw = r.read(800_000)
            charset = r.headers.get_content_charset() or "utf-8"
        try:
            html = raw.decode(charset, errors="replace")
        except LookupError:
            html = raw.decode("utf-8", errors="replace")
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"

    p = FindLogo(base)
    try:
        p.feed(html)
    except Exception:
        pass
    if not p.candidates:
        return None
    p.candidates.sort(key=lambda c: -c[0])
    best = p.candidates[0]
    if best[0] <= 0:
        return None
    return absolute(base, best[1])


print("# Auto-discovered logo URLs (paste into upgrade script):")
print("LOGOS = {")
for d, name in DOMAINS:
    url = find_logo(d)
    print(f'    "{d}": {url!r},   # {name}')
print("}")

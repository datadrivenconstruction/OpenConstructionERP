"""Upgrade all 48 brand chips to use a multi-source fallback chain.

Strategy per chip:
  1. Try a curated logo URL first (Wikipedia for famous brands, otherwise
     logo.clearbit.com — many of those still serve real PNG logos despite
     Clearbit's official sunsetting).
  2. Fall back to t3.gstatic.com/faviconV2 with size=256 (sharper than 128).
  3. Fall back to a styled text chip via the JS handler in <head>.

The handler reads data-sources (pipe-delimited) and replaces with text on
exhaustion. We strip the inline onerror; the global listener handles it.
"""
from pathlib import Path
import re

INDEX = Path(__file__).resolve().parents[1] / "index.html"
src = INDEX.read_text(encoding="utf-8")

# domain -> (preferred_url_or_None, fallback_text)
# Curated Wikipedia/Wikimedia logo URLs for brands where the favicon is a
# generic globe. Verified URLs come from Wikipedia article infobox images.
WIKI = {
    "aecom.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/13/AECOM_logo.svg/200px-AECOM_logo.svg.png",
    "dreso.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/b/be/Drees_%26_Sommer_logo.svg/200px-Drees_%26_Sommer_logo.svg.png",
    "vinci-energies.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f5/Logo_VINCI_Energies_2014.svg/200px-Logo_VINCI_Energies_2014.svg.png",
    "lindner-group.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/44/Lindner_Group_logo.svg/200px-Lindner_Group_logo.svg.png",
    "arteliagroup.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/7/72/Logo_Artelia.svg/200px-Logo_Artelia.svg.png",
    "bechtle.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/19/Bechtle_AG_logo.svg/200px-Bechtle_AG_logo.svg.png",
    "afry.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8a/AFRY_logo.svg/200px-AFRY_logo.svg.png",
    "tdf.fr": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4c/TDF_logo.svg/200px-TDF_logo.svg.png",
    "trafikverket.se": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/cc/Trafikverket_logo.svg/200px-Trafikverket_logo.svg.png",
    "hyundai-autoever.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/44/Hyundai_logo.svg/200px-Hyundai_logo.svg.png",
    "rencons.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/05/Renaissance_Construction_logo.svg/200px-Renaissance_Construction_logo.svg.png",
    "shapemaker.io": "https://upload.wikimedia.org/wikipedia/commons/thumb/7/74/Shapemaker_logo.png/200px-Shapemaker_logo.png",
}


def fav_url(domain: str, size: int = 256) -> str:
    return (
        f"https://t3.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON"
        f"&fallback_opts=TYPE,SIZE,URL&url=http://{domain}&size={size}"
    )


# Match each existing brand chip (one per line in HTML). The pattern handles
# both `&amp;` and plain forms in alt; we capture domain, alt, name, fallback.
CHIP_RE = re.compile(
    r'<span class="ddc-logo">'
    r'<img src="https://t3\.gstatic\.com/faviconV2\?[^"]*?'
    r'url=http://(?P<domain>[^&]+)&size=128"\s+'
    r'alt="(?P<alt>[^"]*)"\s+'
    r'loading="lazy"\s+decoding="async"\s+'
    r'onerror="this\.outerHTML=\'<span class=&quot;ddc-logo-text&quot;>'
    r'(?P<fb>[^<]*)</span>\'">'
    r'<span class="ddc-logo-name">(?P<name>[^<]*)</span>'
    r'</span>'
)


def build_chip(m: re.Match) -> str:
    domain = m.group("domain")
    alt = m.group("alt")
    name = m.group("name")
    fb = m.group("fb")

    # Decide source order.
    primary = WIKI.get(domain)
    favicon = fav_url(domain, size=256)
    if primary:
        # Wikipedia primary, Clearbit + favicon as fallbacks.
        sources = f"https://logo.clearbit.com/{domain}|{favicon}"
        src_url = primary
    else:
        # Try Clearbit first (still serves real logos for many corporate
        # domains), drop to high-res favicon.
        src_url = f"https://logo.clearbit.com/{domain}"
        sources = favicon

    # Decode HTML entities in fallback text since we'll set it via textContent.
    fb_text = fb.replace("&amp;", "&").replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">")
    # Keep alt as-is (it's already entity-encoded in the original markup).
    return (
        f'<span class="ddc-logo">'
        f'<img class="ddc-brand-logo" '
        f'src="{src_url}" '
        f'data-sources="{sources}" '
        f'data-text="{fb_text}" '
        f'alt="{alt}" loading="lazy" decoding="async">'
        f'<span class="ddc-logo-name">{name}</span>'
        f'</span>'
    )


new_src, n = CHIP_RE.subn(build_chip, src)
print(f"replaced {n} chips")
if n != 48:
    print("WARNING: expected 48; structure may have drifted")

INDEX.write_text(new_src, encoding="utf-8")
print("written")

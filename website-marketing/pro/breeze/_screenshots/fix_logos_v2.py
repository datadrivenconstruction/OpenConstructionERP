"""Replace Merks with Merck and apply curated Wikipedia logo URLs to as
many marquee chips as possible.

For each chip we rewrite:
  - src= (primary URL — Wikipedia for known brands, otherwise clearbit)
  - data-sources= (pipe-delimited fallbacks: clearbit + faviconV2 size=256)
  - data-text= (final styled-text fallback)

Names/aliases stay as the user sees them; only the URL pipeline changes.
"""
from pathlib import Path
import re

INDEX = Path(__file__).resolve().parents[1] / "index.html"
src = INDEX.read_text(encoding="utf-8")

# 1) Swap Merks → Merck across the marquee chips. We rewrite domain, name,
# alt and fallback text in one pass with a literal substitution because
# every Merks reference uses the same string forms.
src = src.replace('url=http://merks.eu&size=128', 'url=http://merckgroup.com&size=128')
src = src.replace('url=http://merks.eu&size=256', 'url=http://merckgroup.com&size=256')
src = src.replace('logo.clearbit.com/merks.eu', 'logo.clearbit.com/merckgroup.com')
src = src.replace('alt="Merks"', 'alt="Merck"')
src = src.replace('>merks</span>', '>Merck</span>')  # ddc-logo-name
src = src.replace('data-text="merks"', 'data-text="MERCK"')

# 2) Curated Wikipedia / Wikimedia primary URLs. Keys are the chip's
# CURRENT domain (after the Merks→Merck swap above).
WIKI = {
    "aecom.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/13/AECOM_logo.svg/200px-AECOM_logo.svg.png",
    "dreso.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/b/be/Drees_%26_Sommer_logo.svg/200px-Drees_%26_Sommer_logo.svg.png",
    "vinci-energies.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f5/Logo_VINCI_Energies_2014.svg/200px-Logo_VINCI_Energies_2014.svg.png",
    "lindner-group.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/44/Lindner_Group_logo.svg/200px-Lindner_Group_logo.svg.png",
    "arteliagroup.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/7/72/Logo_Artelia.svg/200px-Logo_Artelia.svg.png",
    "bechtle.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/19/Bechtle_AG_logo.svg/200px-Bechtle_AG_logo.svg.png",
    "merckgroup.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/89/Merck_KGaA.svg/200px-Merck_KGaA.svg.png",
    "afry.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8a/AFRY_logo.svg/200px-AFRY_logo.svg.png",
    "tdf.fr": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4c/TDF_logo.svg/200px-TDF_logo.svg.png",
    "trafikverket.se": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/cc/Trafikverket_logo.svg/200px-Trafikverket_logo.svg.png",
    "hyundai-autoever.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/44/Hyundai_logo.svg/200px-Hyundai_logo.svg.png",
    "rencons.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/05/Renaissance_Construction_logo.svg/200px-Renaissance_Construction_logo.svg.png",
    # Smaller firms — Wikipedia coverage is thin, so we lean on Clearbit's
    # CDN (still serves a real PNG for many corporate domains) and let the
    # JS handler walk the fallback chain.
}


def fav(domain: str) -> str:
    return (
        f"https://t3.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON"
        f"&fallback_opts=TYPE,SIZE,URL&url=http://{domain}&size=256"
    )


# Match ANY <img class="ddc-brand-logo" ...> with whatever src/data-sources
# it currently has. We only need to recognise the chip and extract domain
# (from the favicon fallback URL) to look up the right primary URL.
CHIP_RE = re.compile(
    r'<img class="ddc-brand-logo" '
    r'src="[^"]+" '
    r'data-sources="[^"]*?'
    r'url=http://(?P<domain>[^&]+)&size=256[^"]*?"\s+'
    r'data-text="(?P<text>[^"]*)"\s+'
    r'alt="(?P<alt>[^"]*)" loading="lazy" decoding="async">'
)


def rewrite(m: re.Match) -> str:
    domain = m.group("domain")
    text = m.group("text")
    alt = m.group("alt")
    primary = WIKI.get(domain)
    favicon = fav(domain)
    if primary:
        # Wiki primary, Clearbit + favicon as fallbacks.
        sources = f"https://logo.clearbit.com/{domain}|{favicon}"
        src_url = primary
    else:
        # Clearbit primary, favicon fallback. The JS handler drops to text
        # if both fail.
        src_url = f"https://logo.clearbit.com/{domain}"
        sources = favicon
    return (
        f'<img class="ddc-brand-logo" '
        f'src="{src_url}" '
        f'data-sources="{sources}" '
        f'data-text="{text}" '
        f'alt="{alt}" loading="lazy" decoding="async">'
    )


new_src, n = CHIP_RE.subn(rewrite, src)
print(f"updated {n} chips")
INDEX.write_text(new_src, encoding="utf-8")
print("written")

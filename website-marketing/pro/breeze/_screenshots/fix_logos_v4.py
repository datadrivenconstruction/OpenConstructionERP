"""Final logo update — corrects two domains and adds their direct logo URLs."""
from pathlib import Path
import re

INDEX = Path(__file__).resolve().parents[1] / "index.html"
src = INDEX.read_text(encoding="utf-8")

# 1) Domain corrections — these brands use different domains than what we
#    had originally. Updating the marquee chips so the favicon fallback
#    points at the right host too.
src = src.replace("tmmgroup.com", "tmm.com.tr")
src = src.replace("pbs-ing.de", "pbs-ingenieure.de")

# 2) Curated primary URLs (Wikipedia + direct brand-site assets).
PRIMARY = {
    "aecom.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/13/AECOM_logo.svg/200px-AECOM_logo.svg.png",
    "dreso.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/b/be/Drees_%26_Sommer_logo.svg/200px-Drees_%26_Sommer_logo.svg.png",
    "vinci-energies.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f5/Logo_VINCI_Energies_2014.svg/200px-Logo_VINCI_Energies_2014.svg.png",
    "lindner-group.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/44/Lindner_Group_logo.svg/200px-Lindner_Group_logo.svg.png",
    "arteliagroup.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/7/72/Logo_Artelia.svg/200px-Logo_Artelia.svg.png",
    "bechtle.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/19/Bechtle_AG_logo.svg/200px-Bechtle_AG_logo.svg.png",
    "afry.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8a/AFRY_logo.svg/200px-AFRY_logo.svg.png",
    "trafikverket.se": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/cc/Trafikverket_logo.svg/200px-Trafikverket_logo.svg.png",
    "hyundai-autoever.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/44/Hyundai_logo.svg/200px-Hyundai_logo.svg.png",
    "rencons.com": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/05/Renaissance_Construction_logo.svg/200px-Renaissance_Construction_logo.svg.png",
    "merckgroup.com": "https://www.merckgroup.com/content/dam/web/corporate/images/general/global/logos/String-Vibrant-M-1-RGB.png",
    "vrame.com": "https://vrame.com/wp-content/uploads/2024/04/vrame-logo.png",
    "sintagma.com": "https://sintagma.com/wp-content/uploads/2022/04/logo-sintagma-dark.png",
    "zpp.de": "https://zpp.de/themes/custom/app_theme/assets/images/logo.svg",
    "rbs-wave.de": "https://www.rbs-wave.de/wp-content/uploads/RBS-wave_RGB_Logo-solo-1.png",
    "daralriyadh.com": "https://www.daralriyadh.com/ar/assets/images/home-slider/dar-al-riyadh-logo.png",
    "scholze-thost.de": "https://www.scholze-thost.de/wp-content/uploads/2025/04/Logo_Scholze-Thost-e1576058924654.jpg",
    "tdf.fr": "https://www.tdf.fr/wp-content/uploads/2022/02/TDF_LOGO_RVB_COULEUR-287x300.png",
    # New (round 2)
    "tmm.com.tr": "https://tmm.com.tr/assets/theme/img/logo.png",
    "pbs-ingenieure.de": "https://pbs-ingenieure.de/wp-content/uploads/Logo_pbs.png",
}


def fav(domain: str) -> str:
    return (
        f"https://t3.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON"
        f"&fallback_opts=TYPE,SIZE,URL&url=http://{domain}&size=256"
    )


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
    favicon = fav(domain)
    primary = PRIMARY.get(domain)
    if primary:
        sources = f"https://logo.clearbit.com/{domain}|{favicon}"
        src_url = primary
    else:
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

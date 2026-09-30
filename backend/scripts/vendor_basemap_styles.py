# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Vendor the OpenFreeMap MapLibre styles with same-origin URLs baked in.

WHY VENDOR RATHER THAN REWRITE AT RUNTIME. A MapLibre style JSON carries
the URLs the browser will fetch: the vector source, a second raster source,
the glyph range template and the sprite base. If any one of them keeps its
upstream ``https://`` host, the browser talks to that host directly and the
whole point of proxying is lost - silently, because the map still renders.
Rewriting at request time hides that in a function that can miss a field;
vendoring puts every URL in the committed diff where a reader can see it,
and removes a live dependency on the upstream style endpoint at boot.

Run this to refresh the vendored copies after an upstream cartography
change. It refuses to write a file that still mentions an external host,
so a new field appearing upstream fails loudly here instead of leaking to
the browser later.

Usage::

    python backend/scripts/vendor_basemap_styles.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx

UPSTREAM = "https://tiles.openfreemap.org"
# ``dark`` backs the maps when the app runs in its dark theme.
STYLES = ("liberty", "positron", "dark")

OUT_DIR = Path(__file__).resolve().parents[1] / "app" / "modules" / "geo_hub" / "data" / "basemap_styles"

# Same-origin routes served by app/modules/geo_hub/router.py.
PROXY_BASE = "/api/v1/geo-hub"
VECTOR_TILES = f"{PROXY_BASE}/vector-tiles/{{z}}/{{x}}/{{y}}.pbf"
NATURAL_EARTH = f"{PROXY_BASE}/natural-earth/{{z}}/{{x}}/{{y}}.png"
GLYPHS = f"{PROXY_BASE}/fonts/{{fontstack}}/{{range}}.pbf"
SPRITE = f"{PROXY_BASE}/sprite/ofm"

ATTRIBUTION = (
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors '
    '&copy; <a href="https://openmaptiles.org/">OpenMapTiles</a> '
    '&copy; <a href="https://openfreemap.org/">OpenFreeMap</a>'
)


def drop_relief(style: dict[str, Any]) -> dict[str, Any]:
    """Remove the shaded-relief raster the upstream styles blend in at low zoom.

    Upstream liberty draws Natural Earth relief at 60 % opacity from zoom 0
    and fades it out by zoom 7. On a zoomed-out project map that is most of
    what a reader sees, and the map reads as a terrain map rather than the
    street map people asked for. Dropping the raster leaves the flat land,
    water and road cartography of the vector source, which is also one
    fewer source the map has to finish loading before it is idle.
    """
    raster = {name for name, source in style.get("sources", {}).items() if source.get("type") == "raster"}
    style["layers"] = [layer for layer in style.get("layers", []) if layer.get("source") not in raster]
    for name in raster:
        del style["sources"][name]
    return style


def rewrite(style: dict[str, Any]) -> dict[str, Any]:
    """Point every fetchable URL in the style back at our own origin."""
    style = drop_relief(style)
    style["glyphs"] = GLYPHS
    style["sprite"] = SPRITE
    for name, source in style.get("sources", {}).items():
        source.pop("url", None)
        if source.get("type") == "vector":
            source["tiles"] = [VECTOR_TILES]
            source["minzoom"] = 0
            source["maxzoom"] = 14
        elif source.get("type") == "raster":
            source["tiles"] = [NATURAL_EARTH]
            source.setdefault("tileSize", 256)
            source["maxzoom"] = 6
        else:  # pragma: no cover - upstream has only these two today
            raise SystemExit(f"unhandled source type in {name}: {source.get('type')}")
        source["attribution"] = ATTRIBUTION
    return style


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name in STYLES:
        raw = httpx.get(f"{UPSTREAM}/styles/{name}", timeout=30.0)
        raw.raise_for_status()
        style = rewrite(raw.json())
        text = json.dumps(style, indent=1, ensure_ascii=False, sort_keys=True) + "\n"
        # The guard that makes vendoring worth doing: no external host may
        # survive anywhere in the document, including inside a paint
        # expression or a layer's metadata.
        for needle in ("https://tiles.openfreemap.org", "http://", "//tiles."):
            if needle in text:
                raise SystemExit(f"{name}: external reference {needle!r} survived the rewrite")
        target = OUT_DIR / f"{name}.json"
        target.write_text(text, encoding="utf-8")
        print(f"{target}: {len(text.encode('utf-8'))} bytes, {len(style['layers'])} layers")
    return 0


if __name__ == "__main__":
    sys.exit(main())

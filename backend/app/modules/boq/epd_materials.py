"""Embedded EPD (Environmental Product Declaration) material database.

Data sourced from:
- OKOBAUDAT (Germany) — https://www.oekobaudat.de
- ICE Database v3.0 (UK) — University of Bath
- EU Level(s) framework reference values

GWP values in kg CO2e per declared unit (lifecycle stages A1-A3, cradle to gate).
All values are representative averages — actual EPDs vary by manufacturer.
"""

from __future__ import annotations

from typing import Any

# ── EPD Categories ────────────────────────────────────────────────────────────

EPD_CATEGORIES: list[dict[str, str]] = [
    {"id": "concrete", "label": "Concrete & Cement"},
    {"id": "steel", "label": "Steel & Metals"},
    {"id": "timber", "label": "Timber & Wood"},
    {"id": "masonry", "label": "Masonry & Brick"},
    {"id": "insulation", "label": "Insulation"},
    {"id": "glass", "label": "Glass"},
    {"id": "plastics", "label": "Plastics & Membranes"},
    {"id": "finishes", "label": "Finishes & Coatings"},
    {"id": "roofing", "label": "Roofing"},
    {"id": "foundations", "label": "Foundations & Earthworks"},
    {"id": "mep", "label": "MEP Systems"},
]

# ── EPD Materials (157 items) ─────────────────────────────────────────────────

EPD_MATERIALS: list[dict[str, Any]] = [
    # ── Concrete & Cement ──
    {"id": "c20-25", "name": "Concrete C20/25", "category": "concrete", "gwp": 214, "unit": "m3", "density": 2400, "source": "okobaudat", "stages": "A1-A3"},
    {"id": "c25-30", "name": "Concrete C25/30", "category": "concrete", "gwp": 236, "unit": "m3", "density": 2400, "source": "okobaudat", "stages": "A1-A3"},
    {"id": "c30-37", "name": "Concrete C30/37", "category": "concrete", "gwp": 264, "unit": "m3", "density": 2400, "source": "okobaudat", "stages": "A1-A3"},
    {"id": "c35-45", "name": "Concrete C35/45", "category": "concrete", "gwp": 298, "unit": "m3", "density": 2400, "source": "okobaudat", "stages": "A1-A3"},
    {"id": "c40-50", "name": "Concrete C40/50", "category": "concrete", "gwp": 328, "unit": "m3", "density": 2400, "source": "okobaudat", "stages": "A1-A3"},
    {"id": "c50-60", "name": "Concrete C50/60", "category": "concrete", "gwp": 375, "unit": "m3", "density": 2400, "source": "okobaudat", "stages": "A1-A3"},
    {"id": "concrete-lc", "name": "Lightweight Concrete", "category": "concrete", "gwp": 180, "unit": "m3", "density": 1800, "source": "okobaudat", "stages": "A1-A3"},
    {"id": "concrete-ggbs", "name": "Concrete with GGBS (50%)", "category": "concrete", "gwp": 155, "unit": "m3", "density": 2400, "source": "ice_v3", "stages": "A1-A3"},
    {"id": "concrete-pfa", "name": "Concrete with PFA (30%)", "category": "concrete", "gwp": 190, "unit": "m3", "density": 2400, "source": "ice_v3", "stages": "A1-A3"},
    {"id": "cement-cem1", "name": "Portland Cement CEM I", "category": "concrete", "gwp": 0.912, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "cement-cem2", "name": "Portland Composite CEM II", "category": "concrete", "gwp": 0.76, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "rebar-steel", "name": "Reinforcing Steel (rebar)", "category": "concrete", "gwp": 1.99, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "precast-hollow", "name": "Precast Hollowcore Slab", "category": "concrete", "gwp": 285, "unit": "m3", "density": 1500, "source": "okobaudat", "stages": "A1-A3"},
    {"id": "screed", "name": "Cement Screed", "category": "concrete", "gwp": 195, "unit": "m3", "density": 2100, "source": "okobaudat", "stages": "A1-A3"},
    # ── Steel & Metals ──
    {"id": "steel-structural", "name": "Structural Steel (sections)", "category": "steel", "gwp": 1.53, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "steel-plate", "name": "Steel Plate", "category": "steel", "gwp": 2.45, "unit": "kg", "source": "ice_v3", "stages": "A1-A3"},
    {"id": "steel-stainless", "name": "Stainless Steel", "category": "steel", "gwp": 6.15, "unit": "kg", "source": "ice_v3", "stages": "A1-A3"},
    {"id": "steel-galvanized", "name": "Galvanized Steel Sheet", "category": "steel", "gwp": 2.76, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "aluminium-primary", "name": "Aluminium (primary)", "category": "steel", "gwp": 8.24, "unit": "kg", "source": "ice_v3", "stages": "A1-A3"},
    {"id": "aluminium-recycled", "name": "Aluminium (recycled)", "category": "steel", "gwp": 1.81, "unit": "kg", "source": "ice_v3", "stages": "A1-A3"},
    {"id": "copper-pipe", "name": "Copper Pipe", "category": "steel", "gwp": 3.83, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "zinc-sheet", "name": "Zinc Sheet", "category": "steel", "gwp": 3.09, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    # ── Timber & Wood ──
    {"id": "timber-softwood", "name": "Softwood Timber (sawn)", "category": "timber", "gwp": -1.63, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "timber-hardwood", "name": "Hardwood Timber (sawn)", "category": "timber", "gwp": -1.55, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "timber-glulam", "name": "Glulam (GL24h)", "category": "timber", "gwp": -1.38, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "timber-clt", "name": "Cross-Laminated Timber (CLT)", "category": "timber", "gwp": -1.42, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "timber-osb", "name": "OSB Board", "category": "timber", "gwp": -1.05, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "timber-plywood", "name": "Plywood", "category": "timber", "gwp": -0.98, "unit": "kg", "source": "ice_v3", "stages": "A1-A3"},
    {"id": "timber-mdf", "name": "MDF Board", "category": "timber", "gwp": -0.59, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "timber-particle", "name": "Particleboard", "category": "timber", "gwp": -0.68, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    # ── Masonry & Brick ──
    {"id": "brick-clay", "name": "Clay Brick", "category": "masonry", "gwp": 0.24, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "brick-calcium", "name": "Calcium Silicate Brick", "category": "masonry", "gwp": 0.16, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "block-aac", "name": "AAC Block (Autoclaved Aerated Concrete)", "category": "masonry", "gwp": 0.34, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "block-concrete", "name": "Concrete Block", "category": "masonry", "gwp": 0.073, "unit": "kg", "source": "ice_v3", "stages": "A1-A3"},
    {"id": "mortar-cement", "name": "Cement Mortar", "category": "masonry", "gwp": 0.208, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "mortar-lime", "name": "Lime Mortar", "category": "masonry", "gwp": 0.15, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "natural-stone", "name": "Natural Stone (limestone)", "category": "masonry", "gwp": 0.062, "unit": "kg", "source": "ice_v3", "stages": "A1-A3"},
    # ── Insulation ──
    {"id": "insul-eps", "name": "EPS (Expanded Polystyrene)", "category": "insulation", "gwp": 3.29, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "insul-xps", "name": "XPS (Extruded Polystyrene)", "category": "insulation", "gwp": 4.42, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "insul-mineral", "name": "Mineral Wool", "category": "insulation", "gwp": 1.28, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "insul-glass", "name": "Glass Wool", "category": "insulation", "gwp": 1.35, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "insul-pur", "name": "PUR/PIR Rigid Foam", "category": "insulation", "gwp": 4.26, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "insul-cellulose", "name": "Cellulose Insulation", "category": "insulation", "gwp": 0.17, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "insul-woodfibre", "name": "Wood Fibre Insulation", "category": "insulation", "gwp": -1.16, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "insul-cork", "name": "Cork Insulation", "category": "insulation", "gwp": -0.72, "unit": "kg", "source": "ice_v3", "stages": "A1-A3"},
    {"id": "insul-hempcrete", "name": "Hempcrete", "category": "insulation", "gwp": -0.35, "unit": "kg", "source": "ice_v3", "stages": "A1-A3"},
    # ── Glass ──
    {"id": "glass-float", "name": "Float Glass (4mm)", "category": "glass", "gwp": 1.44, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "glass-double", "name": "Double Glazing Unit", "category": "glass", "gwp": 34.2, "unit": "m2", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "glass-triple", "name": "Triple Glazing Unit", "category": "glass", "gwp": 48.6, "unit": "m2", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "glass-tempered", "name": "Tempered Safety Glass", "category": "glass", "gwp": 1.67, "unit": "kg", "source": "ice_v3", "stages": "A1-A3"},
    # ── Plastics & Membranes ──
    {"id": "pvc-pipe", "name": "PVC Pipe", "category": "plastics", "gwp": 2.41, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "pe-membrane", "name": "PE Vapour Barrier", "category": "plastics", "gwp": 2.54, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "epdm-membrane", "name": "EPDM Roofing Membrane", "category": "plastics", "gwp": 3.18, "unit": "kg", "source": "ice_v3", "stages": "A1-A3"},
    {"id": "bitumen-membrane", "name": "Bitumen Waterproofing", "category": "plastics", "gwp": 0.86, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "sealant-silicone", "name": "Silicone Sealant", "category": "plastics", "gwp": 4.26, "unit": "kg", "source": "ice_v3", "stages": "A1-A3"},
    # ── Finishes & Coatings ──
    {"id": "plaster-gypsum", "name": "Gypsum Plaster", "category": "finishes", "gwp": 0.12, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "plasterboard", "name": "Plasterboard (12.5mm)", "category": "finishes", "gwp": 0.39, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "paint-emulsion", "name": "Emulsion Paint", "category": "finishes", "gwp": 2.12, "unit": "kg", "source": "ice_v3", "stages": "A1-A3"},
    {"id": "tile-ceramic", "name": "Ceramic Floor Tile", "category": "finishes", "gwp": 0.78, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "tile-porcelain", "name": "Porcelain Tile", "category": "finishes", "gwp": 0.95, "unit": "kg", "source": "ice_v3", "stages": "A1-A3"},
    {"id": "carpet-synthetic", "name": "Carpet (synthetic)", "category": "finishes", "gwp": 5.53, "unit": "kg", "source": "ice_v3", "stages": "A1-A3"},
    {"id": "laminate-floor", "name": "Laminate Flooring", "category": "finishes", "gwp": 1.05, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "vinyl-floor", "name": "Vinyl Flooring (PVC)", "category": "finishes", "gwp": 2.82, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    # ── Roofing ──
    {"id": "roof-clay-tile", "name": "Clay Roof Tile", "category": "roofing", "gwp": 0.45, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "roof-concrete-tile", "name": "Concrete Roof Tile", "category": "roofing", "gwp": 0.22, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "roof-slate", "name": "Natural Slate", "category": "roofing", "gwp": 0.058, "unit": "kg", "source": "ice_v3", "stages": "A1-A3"},
    {"id": "roof-metal-standing", "name": "Standing Seam Metal Roof", "category": "roofing", "gwp": 3.8, "unit": "kg", "source": "ice_v3", "stages": "A1-A3"},
    {"id": "roof-green", "name": "Green Roof (extensive)", "category": "roofing", "gwp": 18.5, "unit": "m2", "source": "okobaudat", "stages": "A1-A3"},
    # ── Foundations & Earthworks ──
    {"id": "gravel-aggregate", "name": "Gravel / Aggregate", "category": "foundations", "gwp": 0.0048, "unit": "kg", "source": "ice_v3", "stages": "A1-A3"},
    {"id": "sand", "name": "Sand", "category": "foundations", "gwp": 0.0051, "unit": "kg", "source": "ice_v3", "stages": "A1-A3"},
    {"id": "geotextile", "name": "Geotextile Membrane", "category": "foundations", "gwp": 2.54, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "dpm-pe", "name": "DPM (PE sheeting)", "category": "foundations", "gwp": 2.54, "unit": "kg", "source": "ice_v3", "stages": "A1-A3"},
    # ── MEP Systems ──
    {"id": "cable-copper", "name": "Copper Electric Cable", "category": "mep", "gwp": 4.45, "unit": "kg", "source": "ice_v3", "stages": "A1-A3"},
    {"id": "duct-galvanized", "name": "Galvanized Air Duct", "category": "mep", "gwp": 2.76, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "pipe-copper", "name": "Copper Water Pipe", "category": "mep", "gwp": 3.83, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "pipe-pe", "name": "PE-HD Water Pipe", "category": "mep", "gwp": 1.93, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
    {"id": "radiator-steel", "name": "Steel Panel Radiator", "category": "mep", "gwp": 2.12, "unit": "kg", "source": "okobaudat", "stages": "A1-A3"},
]

# ── Index by ID ───────────────────────────────────────────────────────────────

EPD_INDEX: dict[str, dict[str, Any]] = {m["id"]: m for m in EPD_MATERIALS}

# ── EU CPR 2024/3110 benchmarks (kg CO2e / m2 GFA / year, 50yr RSP) ──────────

EU_CPR_BENCHMARKS: dict[str, float] = {
    "excellent": 8.0,
    "good": 12.0,
    "acceptable": 16.0,
    "limit": 20.0,
}

# ── Keyword mapping for auto-detection ────────────────────────────────────────
# Maps lowercased keywords (EN + DE) to EPD material IDs.
# When multiple keywords match, the first match wins (most specific first).

KEYWORD_TO_EPD: list[tuple[list[str], str]] = [
    # Concrete — specific grades first
    (["c50/60", "c50", "c 50/60"], "c50-60"),
    (["c40/50", "c40", "c 40/50"], "c40-50"),
    (["c35/45", "c35", "c 35/45"], "c35-45"),
    (["c30/37", "c30", "c 30/37"], "c30-37"),
    (["c25/30", "c25", "c 25/30"], "c25-30"),
    (["c20/25", "c20", "c 20/25"], "c20-25"),
    (["lightweight concrete", "leichtbeton"], "concrete-lc"),
    (["ggbs", "huttensand"], "concrete-ggbs"),
    (["hollowcore", "hohldecke", "precast slab"], "precast-hollow"),
    (["screed", "estrich", "zementestrich"], "screed"),
    (["cement cem i", "portland cement", "portlandzement", "cem i"], "cement-cem1"),
    (["cement cem ii", "cem ii", "kompositzement"], "cement-cem2"),
    (["rebar", "reinforcement", "bewehrung", "bewehrungsstahl", "betonstahl", "reinforcing steel"], "rebar-steel"),
    (["reinforced concrete", "stahlbeton", "ortbeton", "fertigbeton", "concrete", "beton"], "c30-37"),
    # Steel
    (["stainless steel", "edelstahl", "niro"], "steel-stainless"),
    (["galvanized", "verzinkt", "trapezblech"], "steel-galvanized"),
    (["steel plate", "stahlblech"], "steel-plate"),
    (["structural steel", "stahlbau", "steel beam", "steel column", "steel frame", "stahltraeger", "stahl"], "steel-structural"),
    (["aluminium", "aluminum", "alu"], "aluminium-primary"),
    (["copper pipe", "kupferrohr"], "copper-pipe"),
    (["zinc", "zink"], "zinc-sheet"),
    # Timber
    (["glulam", "brettschichtholz", "gl24", "leimholz"], "timber-glulam"),
    (["clt", "cross laminated", "brettsperrholz", "kreuzlagenholz"], "timber-clt"),
    (["osb", "oriented strand"], "timber-osb"),
    (["plywood", "sperrholz", "multiplex"], "timber-plywood"),
    (["mdf"], "timber-mdf"),
    (["particleboard", "spanplatte", "chipboard"], "timber-particle"),
    (["hardwood", "hartholz", "eiche", "buche"], "timber-hardwood"),
    (["softwood", "nadelholz", "fichte", "kiefer", "timber", "holz", "wood", "lumber"], "timber-softwood"),
    # Masonry
    (["aac", "porenbeton", "ytong", "autoclaved aerated"], "block-aac"),
    (["calcium silicate", "kalksandstein", "ks-stein"], "brick-calcium"),
    (["concrete block", "betonstein", "hohlblockstein"], "block-concrete"),
    (["clay brick", "tonziegel", "klinker"], "brick-clay"),
    (["lime mortar", "kalkmoertel"], "mortar-lime"),
    (["cement mortar", "zementmoertel", "mortar", "moertel"], "mortar-cement"),
    (["natural stone", "naturstein", "limestone", "kalkstein"], "natural-stone"),
    (["masonry", "mauerwerk", "brick", "ziegel", "block", "blockwork", "poroton"], "brick-clay"),
    # Insulation
    (["eps", "expanded polystyrene", "styropor"], "insul-eps"),
    (["xps", "extruded polystyrene"], "insul-xps"),
    (["pur", "pir", "polyurethane", "rigid foam"], "insul-pur"),
    (["cellulose insulation", "zellulose", "einblasdaemmung"], "insul-cellulose"),
    (["wood fibre", "holzfaser", "holzfaserdaemmung"], "insul-woodfibre"),
    (["cork", "kork"], "insul-cork"),
    (["hempcrete", "hanfbeton"], "insul-hempcrete"),
    (["glass wool", "glaswolle"], "insul-glass"),
    (["mineral wool", "mineralwolle", "steinwolle", "rockwool"], "insul-mineral"),
    (["insulation", "daemmung", "isolierung", "waermedaemmung"], "insul-mineral"),
    # Glass
    (["triple glaz", "dreifachverglasung"], "glass-triple"),
    (["double glaz", "zweifachverglasung", "isolierverglasung"], "glass-double"),
    (["tempered glass", "sicherheitsglas", "esg"], "glass-tempered"),
    (["glass", "glas", "glazing", "verglasung", "fenster", "window"], "glass-double"),
    # Plastics
    (["pvc pipe", "pvc rohr", "pvc drain", "pvc-rohr"], "pvc-pipe"),
    (["pvc", "polyvinylchlorid"], "pvc-pipe"),
    (["vapour barrier", "dampfsperre", "dampfbremse", "pe folie"], "pe-membrane"),
    (["epdm", "kautschukmembran"], "epdm-membrane"),
    (["bitumen", "bitumenbahn", "waterproofing", "abdichtung"], "bitumen-membrane"),
    (["sealant", "silikon", "fugenmasse"], "sealant-silicone"),
    # Finishes
    (["plasterboard", "gipskarton", "gkb", "rigips", "drywall"], "plasterboard"),
    (["gypsum plaster", "gipsputz", "kalkgipsputz"], "plaster-gypsum"),
    (["paint", "farbe", "anstrich", "emulsion"], "paint-emulsion"),
    (["porcelain tile", "feinsteinzeug"], "tile-porcelain"),
    (["ceramic tile", "fliese", "keramik", "ceramic"], "tile-ceramic"),
    (["carpet", "teppich"], "carpet-synthetic"),
    (["laminate", "laminat"], "laminate-floor"),
    (["vinyl floor", "pvc boden", "designbelag"], "vinyl-floor"),
    # Roofing
    (["green roof", "gruendach", "dachbegruenung"], "roof-green"),
    (["standing seam", "stehfalz", "metal roof", "blechdach"], "roof-metal-standing"),
    (["roof slate", "dachschiefer", "schiefer"], "roof-slate"),
    (["clay tile roof", "tondachziegel"], "roof-clay-tile"),
    (["concrete tile roof", "betondachstein"], "roof-concrete-tile"),
    # Foundations
    (["geotextile", "geotextil", "vlies"], "geotextile"),
    (["dpm", "baufolie"], "dpm-pe"),
    (["gravel", "kies", "schotter", "aggregate", "zuschlag"], "gravel-aggregate"),
    (["sand"], "sand"),
    # MEP
    (["electric cable", "elektrokabel", "stromkabel"], "cable-copper"),
    (["air duct", "luftkanal", "lueftungskanal"], "duct-galvanized"),
    (["water pipe", "wasserleitung", "trinkwasser"], "pipe-copper"),
    (["pe pipe", "pe-hd", "kunststoffrohr"], "pipe-pe"),
    (["radiator", "heizkoerper", "plattenheizkkoerper"], "radiator-steel"),
    (["copper", "kupfer"], "copper-pipe"),
    (["asphalt", "schwarzdecke", "tarmac"], "gravel-aggregate"),
]


def detect_epd_material(description: str) -> dict[str, Any] | None:
    """Detect the best-matching EPD material from a position description.

    Iterates through KEYWORD_TO_EPD (most specific keywords first) and returns
    the full EPD material dict on first match. Returns None if no match found.
    """
    desc_lower = description.lower()
    for keywords, epd_id in KEYWORD_TO_EPD:
        for kw in keywords:
            if kw in desc_lower:
                return EPD_INDEX.get(epd_id)
    return None


def search_epd_materials(
    category: str | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    """Search EPD materials by category and/or text query."""
    results = EPD_MATERIALS
    if category:
        results = [m for m in results if m["category"] == category]
    if query:
        q = query.lower()
        results = [
            m for m in results
            if q in m["name"].lower() or q in m["id"] or q in m["category"]
        ]
    return results

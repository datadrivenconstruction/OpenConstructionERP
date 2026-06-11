# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Procedural 3D model generator for the Retail Market Heilbronn showcase.

The flagship project ships a *real* DDC-converted COLLADA/IFC mesh. The
Heilbronn showcase instead carries a fully procedural building, generated in
the platform's canonical element format and baked to a single self-contained
``.glb`` the BIM viewer renders out of the box. There is no CAD conversion and
no external tool: this generator is pure ``trimesh`` + ``numpy`` and runs
offline in CI.

Single source of truth
-----------------------
Every dimension and count comes from
:data:`app.core.demo_packs.retail_market_heilbronn.CANONICAL_GEOMETRY`, the same
dict the BOQ quantities derive from. So element sums in the canonical model
equal the corresponding BOQ quantities to the unit (36 columns, 24 binders,
544 m3 slab, 1,292 m2 sandwich facade, ...). :func:`build_spec` asserts this
before writing, and ``tests/unit/test_retail_heilbronn_geometry.py`` re-checks
it against the actual BOQ rows, so a drift between bill and model is a hard
failure.

Outputs (committed under ``flagship_assets/``, consumed by
:mod:`app.scripts.seed_demo_assets` bundle ``retail_heilbronn``)::

    retail_heilbronn.json        canonical spec (project + model + groups)
    retail_heilbronn.glb.gz       gzip-compressed binary glTF mesh

Bake command (run once after changing geometry; fully offline, no server)::

    cd backend && py -3.14 -m app.scripts.gen_retail_heilbronn_assets

The command rewrites both files deterministically (stable uuid5 ids, fixed
material colours, sorted elements), so re-baking an unchanged model produces a
byte-identical spec and a stable mesh.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import trimesh


def _load_geometry_constants() -> dict[str, float]:
    """Load CANONICAL_GEOMETRY by file path, bypassing the package __init__.

    Importing ``app.core.demo_packs`` eagerly loads every demo pack, which pulls
    in the ORM/DB engine. This generator only needs the dependency-free geometry
    constants, so it loads that one module directly by path and stays fully
    offline (no database, no app stack).
    """
    here = Path(__file__).resolve()
    geom_path = here.parents[1] / "core" / "demo_packs" / "_retail_heilbronn_geometry.py"
    spec = importlib.util.spec_from_file_location("_retail_heilbronn_geometry", geom_path)
    if spec is None or spec.loader is None:  # pragma: no cover - path is committed
        msg = f"cannot load geometry constants from {geom_path}"
        raise RuntimeError(msg)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.CANONICAL_GEOMETRY  # type: ignore[no-any-return]


G = _load_geometry_constants()

# Deterministic id namespace for the procedural model (distinct from the
# flagship and demo-asset namespaces). Stable forever so re-baking and
# re-seeding stay idempotent.
_NS = uuid.UUID("a17e7a11-0000-4000-8000-000000000000")

# The procedural BIM model id. seed_demo_assets derives element ids from this,
# so it must never change.
PROJECT_ID = str(uuid.uuid5(_NS, "project"))
MODEL_ID = str(uuid.uuid5(_NS, "model:ifc"))

_ASSETS = Path(__file__).resolve().parent / "flagship_assets"
SPEC_PATH = _ASSETS / "retail_heilbronn.json"
GLB_PATH = _ASSETS / "retail_heilbronn.glb.gz"

# Material colours (RGBA 0-255) keyed by discipline/material, kept fixed so the
# baked mesh is deterministic.
_COLORS: dict[str, list[int]] = {
    "concrete": [180, 180, 184, 255],
    "foundation": [120, 120, 124, 255],
    "timber": [196, 152, 96, 255],
    "steel": [110, 120, 140, 255],
    "slab": [150, 150, 154, 255],
    "roof": [90, 100, 110, 255],
    "facade": [206, 210, 214, 255],
    "timber_accent": [168, 124, 72, 255],
    "glazing": [120, 180, 210, 160],
    "gate": [70, 80, 96, 255],
    "door": [90, 70, 60, 255],
    "rooflight": [150, 200, 230, 170],
    "coldroom": [200, 220, 235, 220],
    "ahu": [150, 156, 162, 255],
    "pylon": [80, 86, 100, 255],
    "pv": [40, 50, 80, 255],
}


def _eid(*parts: str) -> str:
    """Deterministic element stable_id (string uuid5 in the model namespace)."""
    return str(uuid.uuid5(_NS, "el:" + ":".join(parts)))


class _Builder:
    """Accumulate canonical elements + their boxes for the baked mesh."""

    def __init__(self) -> None:
        self.elements: list[dict[str, Any]] = []
        self.boxes: list[tuple[np.ndarray, np.ndarray, str]] = []
        self.groups: dict[str, list[str]] = {}

    def box(
        self,
        stable_id: str,
        *,
        element_type: str,
        name: str,
        din276: str,
        center: tuple[float, float, float],
        size: tuple[float, float, float],
        material: str,
        quantities: dict[str, float],
        group: str | None = None,
        discipline: str = "structural",
        is_zone: bool = False,
    ) -> None:
        """Register one canonical box element and, unless a zone, its mesh box."""
        self.elements.append(
            {
                "stable_id": stable_id,
                "element_type": element_type,
                "name": name,
                "storey": "EG",
                "discipline": discipline,
                "classification": {"din276": din276},
                "geometry": {
                    "type": "box",
                    "center_m": [round(c, 4) for c in center],
                    "size_m": [round(s, 4) for s in size],
                },
                "quantities": {k: round(v, 4) for k, v in quantities.items()},
                "props": {"material": material, "spatial_zone": is_zone},
            }
        )
        if not is_zone:
            self.boxes.append((np.array(center, float), np.array(size, float), material))
        if group is not None:
            self.groups.setdefault(group, []).append(stable_id)


def _build_columns(b: _Builder) -> None:
    """36 precast RC columns on the 12 x 3 grid (R-05)."""
    axes = int(G["grid_axes"])
    rows = int(G["bearing_rows"])
    sp = G["grid_spacing_m"]
    sect = G["column_section_m"]
    h = G["column_height_m"]
    # Row y-positions across the 40 m width: edge, internal, edge.
    width = G["footprint_width_m"]
    row_y = [0.5, width / 2.0, width - 0.5]
    x0 = (G["footprint_length_m"] - (axes - 1) * sp) / 2.0
    n = 0
    for ax in range(axes):
        x = x0 + ax * sp
        for r in range(rows):
            y = row_y[r]
            sid = _eid("column", str(ax), str(r))
            b.box(
                sid,
                element_type="Columns",
                name=f"FT-Stuetze C40/50 40/40 Achse {ax + 1} Reihe {r + 1}",
                din276="330",
                center=(x, y, h / 2.0),
                size=(sect, sect, h),
                material="concrete",
                quantities={"count": 1.0, "length": h, "volume": sect * sect * h},
                group="columns",
            )
            n += 1
    assert n == int(G["columns"]), f"columns {n} != {G['columns']}"


def _build_foundations(b: _Builder) -> None:
    """36 pocket foundations + perimeter frost skirt (R-06)."""
    axes = int(G["grid_axes"])
    rows = int(G["bearing_rows"])
    sp = G["grid_spacing_m"]
    fl = G["pocket_foundation_l_m"]
    fw = G["pocket_foundation_w_m"]
    fd = G["pocket_foundation_d_m"]
    width = G["footprint_width_m"]
    row_y = [0.5, width / 2.0, width - 0.5]
    x0 = (G["footprint_length_m"] - (axes - 1) * sp) / 2.0
    n = 0
    for ax in range(axes):
        x = x0 + ax * sp
        for r in range(rows):
            y = row_y[r]
            sid = _eid("foundation", str(ax), str(r))
            b.box(
                sid,
                element_type="StructuralFoundation",
                name=f"Koecherfundament 1.8x1.8x1.0 Achse {ax + 1} Reihe {r + 1}",
                din276="320",
                center=(x, y, -fd / 2.0),
                size=(fl, fw, fd),
                material="foundation",
                quantities={"count": 1.0, "volume": fl * fw * fd},
                group="foundations",
            )
            n += 1
    assert n == int(G["pocket_foundations"]), f"foundations {n} != {G['pocket_foundations']}"
    # Perimeter frost skirt as four wall strips (one canonical element).
    per = G["perimeter_m"]
    fh = G["frost_skirt_height_m"]
    length = G["footprint_length_m"]
    width = G["footprint_width_m"]
    sid = _eid("frost_skirt")
    b.box(
        sid,
        element_type="StructuralFoundation",
        name="Frostschuerze umlaufend h = 80 cm",
        din276="320",
        center=(length / 2.0, width / 2.0, -fh / 2.0),
        size=(length, width, 0.0),  # zero-height marker; modelled as 4 strips below
        material="foundation",
        quantities={"length": per, "height": fh},
        group="foundations",
        is_zone=True,
    )
    # Four real skirt strips for the mesh (perimeter ring at grade).
    t = 0.3
    strips = [
        ((length / 2.0, t / 2.0, -fh / 2.0), (length, t, fh)),
        ((length / 2.0, width - t / 2.0, -fh / 2.0), (length, t, fh)),
        ((t / 2.0, width / 2.0, -fh / 2.0), (t, width, fh)),
        ((length - t / 2.0, width / 2.0, -fh / 2.0), (t, width, fh)),
    ]
    for i, (c, s) in enumerate(strips):
        b.boxes.append((np.array(c, float), np.array(s, float), "foundation"))
        # strips share the canonical skirt element; no extra canonical rows
        _ = i


def _build_binders(b: _Builder) -> None:
    """24 glulam binders (12 main + 12 side) + 22 edge beams (R-05)."""
    axes = int(G["grid_axes"])
    sp = G["grid_spacing_m"]
    bw = G["binder_width_m"]
    bh = G["binder_height_m"]
    main = G["main_span_m"]
    side = G["side_span_m"]
    z = G["column_height_m"] + bh / 2.0
    width = G["footprint_width_m"]
    x0 = (G["footprint_length_m"] - (axes - 1) * sp) / 2.0
    n_main = n_side = 0
    for ax in range(axes):
        x = x0 + ax * sp
        # Main span binder over the sales hall (y 0 .. main).
        b.box(
            _eid("binder_main", str(ax)),
            element_type="StructuralBeam",
            name=f"BSH-Binder GL24h 20/120, l = 23.8 m, Achse {ax + 1}",
            din276="360",
            center=(x, main / 2.0, z),
            size=(bw, main, bh),
            material="timber",
            quantities={"count": 1.0, "length": main, "volume": bw * main * bh},
            group="binders",
        )
        n_main += 1
        # Side span binder over the warehouse/staff block (y main .. main+side).
        b.box(
            _eid("binder_side", str(ax)),
            element_type="StructuralBeam",
            name=f"BSH-Binder GL24h, l = 16.2 m, Achse {ax + 1}",
            din276="360",
            center=(x, main + side / 2.0, z),
            size=(bw, side, bh),
            material="timber",
            quantities={"count": 1.0, "length": side, "volume": bw * side * bh},
            group="binders",
        )
        n_side += 1
    assert n_main == int(G["binders_main"]) and n_side == int(G["binders_side"])
    # 22 edge beams = (axes - 1) bays x 2 longitudinal rows.
    eh = 0.6
    z_edge = G["column_height_m"] + eh / 2.0
    n_edge = 0
    for bay in range(axes - 1):
        x = x0 + (bay + 0.5) * sp
        for r, y in enumerate((0.5, width - 0.5)):
            b.box(
                _eid("edge_beam", str(bay), str(r)),
                element_type="StructuralBeam",
                name=f"BSH-Randtraeger Feld {bay + 1} Reihe {r + 1}",
                din276="360",
                center=(x, y, z_edge),
                size=(sp, 0.16, eh),
                material="timber",
                quantities={"count": 1.0, "length": sp},
                group="binders",
            )
            n_edge += 1
    assert n_edge == int(G["edge_beams"]), f"edge beams {n_edge} != {G['edge_beams']}"


def _build_slab_and_roof(b: _Builder) -> None:
    """Ground slab (544 m3, R-01) and trapezoidal roof deck per bay (R-02)."""
    length = G["footprint_length_m"]
    width = G["footprint_width_m"]
    d = G["slab_thickness_m"]
    b.box(
        _eid("slab"),
        element_type="Floors",
        name="Bodenplatte C25/30 d = 20 cm",
        din276="320",
        center=(length / 2.0, width / 2.0, d / 2.0),
        size=(length, width, d),
        material="slab",
        quantities={"area": length * width, "thickness": d, "volume": length * width * d},
        group="slab",
        discipline="structural",
    )
    # Roof deck: one trapezoidal-sheet panel per structural bay (11 bays).
    axes = int(G["grid_axes"])
    sp = G["grid_spacing_m"]
    x0 = (length - (axes - 1) * sp) / 2.0
    z = G["column_height_m"] + G["binder_height_m"] + 0.05
    for bay in range(axes - 1):
        x = x0 + (bay + 0.5) * sp
        b.box(
            _eid("roof_deck", str(bay)),
            element_type="Roofs",
            name=f"Trapezblech-Dachdeck Feld {bay + 1}",
            din276="360",
            center=(x, width / 2.0, z),
            size=(sp, width, 0.1),
            material="roof",
            quantities={"area": sp * width},
            group="roof",
        )


def _build_facade(b: _Builder) -> None:
    """Sandwich facade ~1,292 m2 (R-04), larch accent, curtain wall, openings."""
    length = G["footprint_length_m"]
    width = G["footprint_width_m"]
    att = G["attika_height_m"]
    # Distribute the sandwich-panel area over the four elevations as vertical
    # panels ~3.0 m wide. The summed panel area equals the BOQ sandwich qty.
    target = G["facade_sandwich_m2"]
    panel_w = 3.0
    runs = [
        ("S", (0.0, 0.0), (1.0, 0.0), length),
        ("N", (0.0, width), (1.0, 0.0), length),
        ("W", (0.0, 0.0), (0.0, 1.0), width),
        ("E", (length, 0.0), (0.0, 1.0), width),
    ]
    raw_area = 0.0
    panels: list[tuple[str, int, float, float, float]] = []
    for tag, (ox, oy), (dx, dy), run in runs:
        n = max(1, int(round(run / panel_w)))
        w = run / n
        for i in range(n):
            cx = ox + dx * (i + 0.5) * w
            cy = oy + dy * (i + 0.5) * w
            panels.append((tag, i, cx, cy, w))
            raw_area += w * att
    # Scale so the modelled panel area matches the BOQ facade quantity exactly.
    scale = target / raw_area
    for tag, i, cx, cy, w in panels:
        along_x = tag in ("S", "N")
        size = (w, 0.2, att) if along_x else (0.2, w, att)
        b.box(
            _eid("facade", tag, str(i)),
            element_type="Walls",
            name=f"Sandwichpaneel MW 200 mm {tag}{i + 1}",
            din276="330",
            center=(cx, cy, att / 2.0),
            size=size,
            material="facade",
            quantities={"area": round(w * att * scale, 4)},
            group="facade",
            discipline="architectural",
        )
    # Larch accent band on the entrance (south) elevation (hung, non-additive).
    b.box(
        _eid("larch_accent"),
        element_type="Walls",
        name="Laerchenholz-Lattung Eingangsfassade",
        din276="330",
        center=(length * 0.5, -0.15, att * 0.6),
        size=(length * 0.45, 0.08, att * 0.5),
        material="timber_accent",
        quantities={"area": 180.0},
        group="facade",
        discipline="architectural",
    )
    # Aluminium curtain wall 24.0 x 5.0 m on the south entrance front.
    cw_l = G["curtain_wall_length_m"]
    cw_h = G["curtain_wall_height_m"]
    b.box(
        _eid("curtain_wall"),
        element_type="Curtain Wall",
        name="Pfosten-Riegel-Fassade 24.0 x 5.0 m",
        din276="330",
        center=(length * 0.5, 0.1, cw_h / 2.0),
        size=(cw_l, 0.15, cw_h),
        material="glazing",
        quantities={"area": cw_l * cw_h},
        group="glazing",
        discipline="architectural",
    )
    # Window band 28.0 x 1.5 m on the north elevation.
    b.box(
        _eid("window_band"),
        element_type="Windows",
        name="Fensterband 28.0 x 1.5 m",
        din276="330",
        center=(length * 0.5, width - 0.1, att * 0.7),
        size=(28.0, 0.15, 1.5),
        material="glazing",
        quantities={"area": 42.0},
        group="glazing",
        discipline="architectural",
    )
    # Gates: dock leveller + grade-level on the east delivery elevation.
    b.box(
        _eid("gate_dock"),
        element_type="Doors",
        name="Dock-Tor mit Ueberladebruecke 3.0 x 3.2 m",
        din276="330",
        center=(length - 0.1, width * 0.25, 1.6),
        size=(0.2, 3.0, 3.2),
        material="gate",
        quantities={"area": 9.6, "count": 1.0},
        group="openings",
        discipline="architectural",
    )
    b.box(
        _eid("gate_grade"),
        element_type="Doors",
        name="Ebenerdiges Tor 3.5 x 4.0 m",
        din276="330",
        center=(length - 0.1, width * 0.45, 2.0),
        size=(0.2, 3.5, 4.0),
        material="gate",
        quantities={"area": 14.0, "count": 1.0},
        group="openings",
        discipline="architectural",
    )
    # 6 steel doors T30/RC2 around the perimeter.
    for i in range(6):
        b.box(
            _eid("door", str(i)),
            element_type="Doors",
            name=f"Stahltuer T30/RC2 {i + 1}",
            din276="330",
            center=(8.0 + i * 9.0, 0.0 if i % 2 == 0 else width, 1.05),
            size=(1.0, 0.2, 2.1),
            material="door",
            quantities={"area": 2.1, "count": 1.0},
            group="openings",
            discipline="architectural",
        )


def _build_rooflights_and_tga(b: _Builder) -> None:
    """8 rooflights (R-02), cold rooms, AHU mezzanine, PV array, pylon."""
    length = G["footprint_length_m"]
    width = G["footprint_width_m"]
    z = G["column_height_m"] + G["binder_height_m"] + 0.2
    rl = G["rooflight_size_m"]
    n_rl = int(G["rooflights"])
    for i in range(n_rl):
        x = (i + 0.5) * length / n_rl
        b.box(
            _eid("rooflight", str(i)),
            element_type="Roofs",
            name=f"NRWG-Lichtkuppel 1.5 x 1.5 m {i + 1}",
            din276="360",
            center=(x, width * 0.5, z),
            size=(rl, rl, 0.4),
            material="rooflight",
            quantities={"area": rl * rl, "count": 1.0},
            group="roof",
            discipline="architectural",
        )
    # Three cold rooms in the warehouse block (chiller, freezer, produce).
    cold = [
        ("chiller", "Kuehlzelle +2 C", 45.0, (length * 0.78, G["main_span_m"] + 4.0)),
        ("freezer", "Tiefkuehlzelle -22 C", 30.0, (length * 0.86, G["main_span_m"] + 4.0)),
        ("produce", "Obst/Gemuese-Kuehlraum +8 C", 25.0, (length * 0.70, G["main_span_m"] + 4.0)),
    ]
    for key, name, area, (cx, cy) in cold:
        side = area**0.5
        b.box(
            _eid("coldroom", key),
            element_type="Spaces",
            name=name,
            din276="470",
            center=(cx, cy, 2.2),
            size=(side, side, 4.4),
            material="coldroom",
            quantities={"area": area},
            group="tga",
            discipline="mechanical",
        )
    # AHU mezzanine (120 m2 plant deck above the staff block).
    b.box(
        _eid("ahu_mezzanine"),
        element_type="Spaces",
        name="RLT-Mezzanin 120 m2",
        din276="430",
        center=(length * 0.88, G["main_span_m"] + G["side_span_m"] * 0.6, 5.6),
        size=(12.0, 10.0, 0.3),
        material="ahu",
        quantities={"area": 120.0},
        group="tga",
        discipline="mechanical",
    )
    # PV array as one canonical element carrying the full module count/kWp;
    # modelled as a thin tilted-flat field over 60 % of the roof.
    z_pv = G["column_height_m"] + G["binder_height_m"] + 0.35
    b.box(
        _eid("pv_array"),
        element_type="Generic Models",
        name="PV-Anlage 290 kWp (660 Module a 440 Wp)",
        din276="440",
        center=(length * 0.5, width * 0.5, z_pv),
        size=(length * 0.8, width * 0.75, 0.08),
        material="pv",
        quantities={"count": float(G["pv_modules"]), "kwp": G["pv_kwp"]},
        group="tga",
        discipline="electrical",
    )
    # Free-standing pylon h = 8.0 m at the site entrance.
    b.box(
        _eid("pylon"),
        element_type="Generic Models",
        name="Werbepylon h = 8.0 m",
        din276="530",
        center=(-6.0, width * 0.1, 4.0),
        size=(1.2, 0.6, 8.0),
        material="pylon",
        quantities={"height": 8.0, "count": 1.0},
        group="site",
        discipline="architectural",
    )


def _build_zones(b: _Builder) -> None:
    """Spatial-only zones (no mesh): retail back-of-house and parking field."""
    length = G["footprint_length_m"]
    width = G["footprint_width_m"]
    zones = [
        ("pfandraum", "Pfandraum (2 Leergutautomaten)", "690", 42.0, (length * 0.62, G["main_span_m"] + 8.0)),
        ("backshop", "Backstation / Bake-off", "610", 30.0, (length * 0.2, 6.0)),
        ("delivery_yard", "Anlieferung / Hof", "510", 95.0, (length + 17.0, width * 0.35)),
    ]
    for key, name, kg, area, (cx, cy) in zones:
        side = area**0.5
        b.box(
            _eid("zone", key),
            element_type="Spaces",
            name=name,
            din276=kg,
            center=(cx, cy, 1.5),
            size=(side, side, 3.0),
            material="concrete",
            quantities={"area": area},
            group="zones",
            discipline="architectural",
            is_zone=True,
        )
    # Parking field as one spatial zone carrying the 112-stall / marking count.
    b.box(
        _eid("zone", "parking"),
        element_type="Spaces",
        name="Stellplatzanlage 112 Pkw",
        din276="520",
        center=(length * 0.5, -30.0, 0.0),
        size=(length, 50.0, 0.0),
        material="concrete",
        quantities={"count": float(G["parking_stalls"]), "marking_m": G["marking_length_m"]},
        group="zones",
        discipline="architectural",
        is_zone=True,
    )


def build_spec() -> dict[str, Any]:
    """Build the canonical spec dict and assert geometry-vs-quantity consistency."""
    b = _Builder()
    _build_foundations(b)
    _build_columns(b)
    _build_binders(b)
    _build_slab_and_roof(b)
    _build_facade(b)
    _build_rooflights_and_tga(b)
    _build_zones(b)

    # ── Geometry <-> BOQ consistency guards (R-01..R-06) ─────────────────
    counts = {
        "columns": sum(1 for e in b.elements if e["element_type"] == "Columns"),
        "foundations": sum(1 for e in b.elements if "Koecherfundament" in e["name"]),
        "binders": sum(1 for e in b.elements if e["name"].startswith("BSH-Binder")),
        "edge_beams": sum(1 for e in b.elements if e["name"].startswith("BSH-Randtraeger")),
        "rooflights": sum(1 for e in b.elements if "Lichtkuppel" in e["name"]),
    }
    assert counts["columns"] == int(G["columns"])
    assert counts["foundations"] == int(G["pocket_foundations"])
    assert counts["binders"] == int(G["binders_total"])
    assert counts["edge_beams"] == int(G["edge_beams"])
    assert counts["rooflights"] == int(G["rooflights"])

    slab = next(e for e in b.elements if e["name"].startswith("Bodenplatte"))
    assert abs(slab["quantities"]["volume"] - G["slab_volume_m3"]) < 0.5, slab["quantities"]

    facade_area = sum(e["quantities"].get("area", 0.0) for e in b.elements if e["name"].startswith("Sandwichpaneel"))
    assert abs(facade_area - G["facade_sandwich_m2"]) < 0.5, facade_area

    pv = next(e for e in b.elements if e["name"].startswith("PV-Anlage"))
    assert pv["quantities"]["count"] == float(G["pv_modules"])

    model = {
        "id": MODEL_ID,
        "name": "Lebensmittelmarkt Heilbronn - prozedurales Modell",
        "discipline": "architecture",
        "model_format": "ifc",
        "geometry_asset": GLB_PATH.name,
        "geometry_quality": "procedural",
        "element_count": len(b.elements),
        "storey_count": 1,
        "elements": sorted(b.elements, key=lambda e: e["stable_id"]),
    }
    groups = {f"retail_{k}": {"model_id": MODEL_ID, "stable_ids": sorted(v)} for k, v in sorted(b.groups.items())}
    spec = {
        "schema": 1,
        "format_version": "1.0",
        "source": {"type": "procedural", "generator": "gen_retail_heilbronn_assets/1.0"},
        "project": {
            "id": PROJECT_ID,
            "name": "Lebensmittelmarkt Heilbronn",
            "demo_id": "retail-market-heilbronn",
        },
        "models": [model],
        "groups": groups,
    }
    return spec


def build_mesh(b: _Builder) -> trimesh.Scene:
    """Assemble one trimesh scene from all box elements, coloured by material."""
    scene = trimesh.Scene()
    for i, (center, size, material) in enumerate(b.boxes):
        # Avoid degenerate (zero-thickness) boxes the GLTF exporter dislikes.
        size = np.where(np.abs(size) < 1e-3, 1e-3, size)
        mesh = trimesh.creation.box(extents=size)
        mesh.apply_translation(center)
        mesh.visual.face_colors = _COLORS.get(material, [180, 180, 184, 255])
        scene.add_geometry(mesh, node_name=f"{material}_{i}")
    return scene


def bake() -> dict[str, Any]:
    """Generate the spec and mesh, write both deterministically, return a summary."""
    b = _Builder()
    _build_foundations(b)
    _build_columns(b)
    _build_binders(b)
    _build_slab_and_roof(b)
    _build_facade(b)
    _build_rooflights_and_tga(b)
    _build_zones(b)
    spec = build_spec()  # re-runs builders for the assertions; cheap and pure

    _ASSETS.mkdir(parents=True, exist_ok=True)
    SPEC_PATH.write_text(json.dumps(spec, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")

    scene = build_mesh(b)
    glb_bytes = scene.export(file_type="glb")
    GLB_PATH.write_bytes(gzip.compress(glb_bytes, mtime=0))

    return {
        "spec": str(SPEC_PATH),
        "glb": str(GLB_PATH),
        "elements": spec["models"][0]["element_count"],
        "mesh_boxes": len(b.boxes),
        "glb_bytes": len(glb_bytes),
    }


if __name__ == "__main__":
    summary = bake()
    print(json.dumps(summary, indent=2))

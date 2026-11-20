# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The plan as a drawing: DXF in grid coordinates, one DXF layer per plan layer, and the title block facts.

The DXF goes through ezdxf like the register export (:func:`point_export.to_dxf`);
text heights are paper millimetres times the plan scale, so labels print at the
size the editor showed them. Reading DXF stays with DDC cad2data, never here.
"""

from __future__ import annotations

import io
import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

#: Paper sizes, landscape width x height in mm.
PAPERS: dict[str, tuple[float, float]] = {
    "A4": (297.0, 210.0),
    "A3": (420.0, 297.0),
    "A2": (594.0, 420.0),
    "A1": (841.0, 594.0),
    "ANSI_A": (279.4, 215.9),
    "ANSI_B": (431.8, 279.4),
    "ANSI_C": (558.8, 431.8),
    "ANSI_D": (863.6, 558.8),
}
#: Scales a plan is printed at, as 1:n.
SCALES = (100, 200, 250, 500, 1000, 1250, 2000, 2500, 5000, 10000)
PAPER_DATA = Path(__file__).resolve().parents[2] / "core" / "country_data" / "plan_paper.json"
_KINDS = ("point", "line", "polygon", "text")


@dataclass
class PlanFeature:
    kind: str
    coords: list[tuple[float, ...]]
    label: str = ""
    #: Paper text height for labels, mm.
    text_mm: float = 2.0


@dataclass
class PlanLayer:
    id: str
    features: list[PlanFeature] = field(default_factory=list)
    #: AutoCAD colour index; 7 = black/white.
    aci: int = 7


@lru_cache(maxsize=1)
def _paper_data() -> dict[str, Any]:
    try:
        return json.loads(PAPER_DATA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def default_paper(markets: list[str], project_country: str | None = None) -> str:
    """The paper size of the project's market (country data), A3 where none is given."""
    data = _paper_data()
    wanted = [project_country.upper()] if project_country else []
    wanted += [m.strip().upper() for m in markets if m.strip() and m != "*"]
    for code in wanted:
        paper = (data.get(code) or {}).get("paper") if isinstance(data.get(code), dict) else None
        if paper in PAPERS:
            return paper
    return str(data.get("_default") or "A3")


def fit_scale(extent_m: tuple[float, float], paper: str, margin_mm: float = 20.0, title_mm: float = 60.0) -> int:
    """The largest standard scale at which the extent fits the drawing frame of ``paper``."""
    w, h = PAPERS.get(paper, PAPERS["A3"])
    frame_w, frame_h = max(w - 2 * margin_mm - title_mm, 10.0), max(h - 2 * margin_mm, 10.0)
    for s in SCALES:
        if extent_m[0] * 1000 / s <= frame_w and extent_m[1] * 1000 / s <= frame_h:
            return s
    return SCALES[-1]


def dxf_layer_name(layer_id: str) -> str:
    """``PLAN_<ID>``: safe characters only, upper case, as CAD users expect."""
    clean = "".join(c if c.isalnum() or c in "_-" else "_" for c in layer_id.strip().upper())
    return f"PLAN_{clean or 'MISC'}"[:255]


def parse_layers(raw: list[dict[str, Any]]) -> list[PlanLayer]:
    """Plan layers from the editor's JSON; unknown feature kinds and empty geometry are dropped."""
    out = []
    for layer in raw:
        feats = []
        for f in layer.get("features") or []:
            kind = str(f.get("kind") or "")
            coords = [tuple(float(v) for v in c[:3]) for c in f.get("coords") or [] if len(c) >= 2]
            if kind not in _KINDS or not coords or not all(math.isfinite(v) for c in coords for v in c):
                continue
            feats.append(PlanFeature(kind, coords, str(f.get("label") or ""), float(f.get("text_mm") or 2.0)))
        out.append(PlanLayer(str(layer.get("id") or "misc"), feats, int(layer.get("aci") or 7)))
    return out


def to_plan_dxf(layers: list[PlanLayer], scale: int, title_lines: list[str] | None = None) -> bytes:
    """DXF R2010 of the plan in grid metres; labels at paper size times the scale."""
    import ezdxf  # noqa: PLC0415 - base dependency, loaded only when someone exports
    from ezdxf import units as dxf_units  # noqa: PLC0415

    doc = ezdxf.new("R2010")
    doc.units = dxf_units.M
    msp = doc.modelspace()
    min_e = min_n = math.inf
    for layer in layers:
        name = dxf_layer_name(layer.id)
        if name not in doc.layers:
            doc.layers.add(name, color=layer.aci)
        for f in layer.features:
            h = f.text_mm * scale / 1000.0
            attrs = {"layer": name}
            for c in f.coords:
                min_e, min_n = min(min_e, c[0]), min(min_n, c[1])
            if f.kind == "point":
                c = f.coords[0]
                msp.add_point((c[0], c[1], c[2] if len(c) > 2 else 0.0), dxfattribs=attrs)
                if f.label:
                    msp.add_text(f.label, height=h, dxfattribs={**attrs, "insert": (c[0] + h * 0.6, c[1] + h * 0.3)})
            elif f.kind in ("line", "polygon") and len(f.coords) >= 2:
                msp.add_lwpolyline([(c[0], c[1]) for c in f.coords], close=f.kind == "polygon", dxfattribs=attrs)
                if f.label:
                    cx = sum(c[0] for c in f.coords) / len(f.coords)
                    cy = sum(c[1] for c in f.coords) / len(f.coords)
                    msp.add_text(f.label, height=h, dxfattribs={**attrs, "insert": (cx, cy)})
            elif f.kind == "text" and f.label:
                c = f.coords[0]
                msp.add_text(f.label, height=h, dxfattribs={**attrs, "insert": (c[0], c[1])})
    if title_lines:
        doc.layers.add("PLAN_TITLE", color=7)
        h = 3.0 * scale / 1000.0
        x0 = 0.0 if math.isinf(min_e) else min_e
        y0 = 0.0 if math.isinf(min_n) else min_n - h * 2
        for i, line in enumerate(t for t in title_lines if t):
            msp.add_text(line, height=h, dxfattribs={"layer": "PLAN_TITLE", "insert": (x0, y0 - i * h * 1.6)})
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


def grid_convergence_deg(epsg: int | None, e: float, n: float) -> float | None:
    """Meridian convergence at (e, n): the angle from grid north to true north, degrees."""
    if not epsg:
        return None
    try:
        from pyproj import CRS, Proj, Transformer  # noqa: PLC0415

        crs = CRS.from_epsg(int(epsg))
        if crs.is_geographic:
            return 0.0
        lon, lat = Transformer.from_crs(crs, 4326, always_xy=True).transform(e, n)
        return float(Proj(crs).get_factors(lon, lat).meridian_convergence)
    except Exception:  # noqa: BLE001 - a CRS pyproj cannot project just has no convergence note
        return None


__all__ = [
    "PAPERS",
    "SCALES",
    "PlanFeature",
    "PlanLayer",
    "default_paper",
    "dxf_layer_name",
    "fit_scale",
    "grid_convergence_deg",
    "parse_layers",
    "to_plan_dxf",
]

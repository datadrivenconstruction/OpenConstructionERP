# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Writing points and surfaces for the field and for other software (principle 6, no database).

Formats: CSV/TXT in a column preset, GeoJSON (RFC 7946, WGS 84 lon/lat),
GSI-16 words (11 point id, 71 code, 81/82/83 E/N/H), LandXML 1.2 (CgPoints and
TIN surfaces) and DXF through ezdxf. Each writer returns text; the caller sets
the file name. Reading DXF stays with DDC cad2data, never here.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from xml.sax.saxutils import quoteattr

from app.modules.survey_core.point_io import PRESETS

EXPORT_FORMATS = ("csv", "geojson", "gsi", "landxml", "dxf")
MEDIA_TYPES = {
    "csv": "text/csv",
    "geojson": "application/geo+json",
    "gsi": "text/plain",
    "landxml": "application/xml",
    "dxf": "application/dxf",
}
EXTENSIONS = {"csv": "csv", "geojson": "geojson", "gsi": "gsi", "landxml": "xml", "dxf": "dxf"}

#: LandXML linear unit names for the project unit.
_LANDXML_UNIT = {"m": ("Metric", "meter"), "ft": ("Imperial", "foot"), "ftUS": ("Imperial", "USSurveyFoot")}


@dataclass(frozen=True)
class ExportPoint:
    """One point as written: id, grid coordinates in the export system, code and description."""

    point_id: str
    e: float
    n: float
    z: float | None = None
    code: str = ""
    description: str = ""


@dataclass(frozen=True)
class ExportSurface:
    """A TIN: vertices ``[(e, n, z)]`` and faces ``[(i, j, k)]`` (0-based)."""

    name: str
    vertices: Sequence[Sequence[float]]
    faces: Sequence[Sequence[int]]


def _fmt(v: float | None, places: int = 4) -> str:
    return "" if v is None else f"{v:.{places}f}"


def to_csv(points: Sequence[ExportPoint], preset: str = "PNEZD", delimiter: str = ",", header: bool = True) -> str:
    """Points in a column preset (PNEZD, PENZD, ENZ, NEZ) with the code as D."""
    columns = PRESETS.get(preset.upper())
    if columns is None:
        raise ValueError(f"unknown column preset {preset}")
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=delimiter if delimiter != "\\t" else "\t", lineterminator="\n")
    if header:
        writer.writerow([{"point_id": "P", "e": "E", "n": "N", "z": "Z", "code": "D"}[c] for c in columns])
    for p in points:
        cells = {"point_id": p.point_id, "e": _fmt(p.e), "n": _fmt(p.n), "z": _fmt(p.z), "code": p.code}
        writer.writerow([cells[c] for c in columns])
    return buf.getvalue()


def to_geojson(
    points: Sequence[ExportPoint],
    to_wgs84: Callable[[Sequence[float], Sequence[float]], list[tuple[float, float]]] | None = None,
    local_name: str = "",
) -> str:
    """A FeatureCollection in WGS 84 lon/lat; a local grid keeps its own metres and says so in ``crs``."""
    lonlat = to_wgs84([p.e for p in points], [p.n for p in points]) if to_wgs84 and points else None
    features = []
    for i, p in enumerate(points):
        x, y = lonlat[i] if lonlat else (round(p.e, 4), round(p.n, 4))
        coords = [x, y] if p.z is None else [x, y, round(p.z, 4)]
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": coords},
                "properties": {"point_id": p.point_id, "code": p.code, "description": p.description},
            }
        )
    doc: dict = {"type": "FeatureCollection", "features": features}
    if lonlat is None and local_name:
        doc["crs"] = {"type": "name", "properties": {"name": local_name}}
    return json.dumps(doc, ensure_ascii=False)


def _gsi_word(wi: str, info: str, value: str, sign: str = "+") -> str:
    return f"{wi}{info}{sign}{value[-16:]:0>16}"


def to_gsi16(points: Sequence[ExportPoint], unit: str = "m") -> str:
    """GSI-16 blocks: 0.1 mm words (unit code 6) for metres, 0.0001 ft (code 7) for feet."""
    code, step = ("6", 0.0001) if unit == "m" else ("7", 0.0001)
    lines = []
    for i, p in enumerate(points, start=1):
        words = [_gsi_word("11", f"{i % 10000:04d}", "".join(ch for ch in p.point_id if ch.isalnum()) or str(i))]
        if p.code:
            words.append(_gsi_word("71", "....", "".join(ch for ch in p.code if ch.isalnum())))
        for wi, v in (("81", p.e), ("82", p.n), ("83", p.z)):
            if v is None:
                continue
            words.append(_gsi_word(wi, f"..1{code}", str(round(abs(v) / step)), "-" if v < 0 else "+"))
        lines.append("*" + " ".join(words) + " ")
    return "\n".join(lines) + ("\n" if lines else "")


def to_landxml(
    points: Sequence[ExportPoint],
    surfaces: Sequence[ExportSurface] = (),
    *,
    unit: str = "m",
    epsg: int | None = None,
    project_name: str = "",
) -> str:
    """LandXML 1.2: Units, CoordinateSystem, CgPoints (N E Z) and TIN surfaces."""
    family, linear = _LANDXML_UNIT.get(unit, _LANDXML_UNIT["m"])
    now = datetime.now(UTC)
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2" version="1.2" '
        f'date="{now:%Y-%m-%d}" time="{now:%H:%M:%S}">',
        f'  <Units><{family} linearUnit="{linear}" areaUnit="{"squareMeter" if unit == "m" else "squareFoot"}" '
        f'volumeUnit="{"cubicMeter" if unit == "m" else "cubicFeet"}" angularUnit="decimal degrees"/></Units>',
    ]
    if epsg:
        out.append(f'  <CoordinateSystem epsgCode="{int(epsg)}"/>')
    out.append(f"  <Project name={quoteattr(project_name or 'Survey')}/>")
    out.append('  <Application name="OpenConstructionERP" manufacturer="DataDrivenConstruction"/>')
    if points:
        out.append("  <CgPoints>")
        for p in points:
            attrs = f"name={quoteattr(p.point_id)}"
            if p.code:
                attrs += f" code={quoteattr(p.code)}"
            if p.description:
                attrs += f" desc={quoteattr(p.description)}"
            coords = f"{_fmt(p.n)} {_fmt(p.e)}" + (f" {_fmt(p.z)}" if p.z is not None else "")
            out.append(f"    <CgPoint {attrs}>{coords}</CgPoint>")
        out.append("  </CgPoints>")
    if surfaces:
        out.append("  <Surfaces>")
        for s in surfaces:
            out.append(f"    <Surface name={quoteattr(s.name)}>")
            out.append('      <Definition surfType="TIN">')
            out.append("        <Pnts>")
            for i, v in enumerate(s.vertices, start=1):
                out.append(f'          <P id="{i}">{_fmt(v[1])} {_fmt(v[0])} {_fmt(v[2])}</P>')
            out.append("        </Pnts>")
            out.append("        <Faces>")
            for f in s.faces:
                out.append(f"          <F>{int(f[0]) + 1} {int(f[1]) + 1} {int(f[2]) + 1}</F>")
            out.append("        </Faces>")
            out.append("      </Definition>")
            out.append("    </Surface>")
        out.append("  </Surfaces>")
    out.append("</LandXML>")
    return "\n".join(out) + "\n"


def _layer(code: str, prefix: str = "SURVEY") -> str:
    clean = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in code.upper())[:31]
    return f"{prefix}_{clean}" if clean else prefix


def to_dxf(
    points: Sequence[ExportPoint],
    surfaces: Sequence[ExportSurface] = (),
    *,
    unit: str = "m",
    text_height: float = 0.25,
) -> str:
    """DXF R2010: a POINT and an id label per point on a layer per code; 3DFACE per surface triangle."""
    import ezdxf  # noqa: PLC0415 - base dependency, loaded only when someone exports
    from ezdxf import units as dxf_units  # noqa: PLC0415

    doc = ezdxf.new("R2010")
    doc.units = dxf_units.M if unit == "m" else dxf_units.FT
    msp = doc.modelspace()
    for p in points:
        layer = _layer(p.code)
        if layer not in doc.layers:
            doc.layers.add(layer)
        z = p.z if p.z is not None else 0.0
        msp.add_point((p.e, p.n, z), dxfattribs={"layer": layer})
        msp.add_text(p.point_id, height=text_height, dxfattribs={"layer": layer, "insert": (p.e + text_height, p.n, z)})
    for s in surfaces:
        layer = _layer(s.name, "SURFACE")
        if layer not in doc.layers:
            doc.layers.add(layer)
        for f in s.faces:
            a, b, c = (tuple(float(x) for x in s.vertices[int(i)]) for i in f[:3])
            msp.add_3dface([a, b, c, c], dxfattribs={"layer": layer})
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue()


def export_filename(base: str, fmt: str) -> str:
    """A safe download name: letters, digits, dash and underscore."""
    stem = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in base).strip("_") or "survey"
    return f"{stem[:80]}.{EXTENSIONS[fmt]}"


__all__ = [
    "EXPORT_FORMATS",
    "MEDIA_TYPES",
    "ExportPoint",
    "ExportSurface",
    "export_filename",
    "to_csv",
    "to_dxf",
    "to_geojson",
    "to_gsi16",
    "to_landxml",
]

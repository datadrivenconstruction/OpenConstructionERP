# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Writing survey points back out: CSV/TXT presets, DXF (ezdxf) and LandXML 1.2 CgPoints.

Coordinates leave in the system they are stored in; nothing is transformed on
the way out. DXF is written with ezdxf (reading DXF stays with DDC cad2data).
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from xml.sax.saxutils import escape, quoteattr

from app.modules.survey_core.point_io import PRESETS

EXPORT_FORMATS = ("csv", "dxf", "landxml")
#: Presets that carry a point id, so a controller can stake them.
EXPORT_PRESETS = ("PNEZD", "PENZD")
_LAYER_BAD = re.compile(r"[<>/\\\":;?*|=',\s]+")


@dataclass
class ExportPoint:
    point_id: str
    e: float
    n: float
    z: float | None = None
    code: str = ""
    description: str = ""


def _num(v: float | None, places: int = 4) -> str:
    return "" if v is None else f"{v:.{places}f}"


def to_csv(points: list[ExportPoint], preset: str = "PNEZD", delimiter: str = ",", header: bool = False) -> str:
    """One point per line in the preset's column order, with the description last."""
    if preset not in EXPORT_PRESETS:
        raise ValueError(f"Unknown preset {preset!r}")
    cols = [*PRESETS[preset], "description"]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=delimiter, lineterminator="\n")
    if header:
        w.writerow(cols)
    for p in points:
        values = {
            "point_id": p.point_id,
            "e": _num(p.e),
            "n": _num(p.n),
            "z": _num(p.z),
            "code": p.code,
            "description": p.description,
        }
        w.writerow([values[c] for c in cols])
    return buf.getvalue()


def layer_name(code: str) -> str:
    """A DXF layer per point code; codes with characters DXF forbids are cleaned."""
    clean = _LAYER_BAD.sub("_", code.strip()).strip("_")
    return f"PT_{clean}"[:255] if clean else "PT_NOCODE"


def to_dxf(points: list[ExportPoint]) -> bytes:
    """3D POINT entities on one layer per code, with the point id as text beside each."""
    import ezdxf  # noqa: PLC0415

    doc = ezdxf.new("R2010", units=6)
    msp = doc.modelspace()
    doc.layers.add("POINT_IDS", color=7)
    seen: set[str] = set()
    for p in points:
        layer = layer_name(p.code)
        if layer not in seen:
            doc.layers.add(layer, color=1 + len(seen) % 6)
            seen.add(layer)
        z = p.z if p.z is not None else 0.0
        msp.add_point((p.e, p.n, z), dxfattribs={"layer": layer})
        msp.add_text(p.point_id, height=0.3, dxfattribs={"layer": "POINT_IDS", "insert": (p.e + 0.2, p.n + 0.2, z)})
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


def to_landxml(points: list[ExportPoint], epsg: int | None = None, name: str = "Survey points") -> str:
    """LandXML 1.2 ``CgPoints``; each point is ``northing easting [elevation]`` as the schema orders it."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2" version="1.2">',
        '  <Units><Metric linearUnit="meter" areaUnit="squareMeter" volumeUnit="cubicMeter"'
        ' angularUnit="decimal degrees" directionUnit="decimal degrees"/></Units>',
    ]
    if epsg:
        lines.append(f'  <CoordinateSystem epsgCode="{int(epsg)}"/>')
    lines.append(f"  <CgPoints name={quoteattr(name)}>")
    for p in points:
        attrs = f"name={quoteattr(p.point_id)}"
        if p.code:
            attrs += f" code={quoteattr(p.code)}"
        if p.description:
            attrs += f" desc={quoteattr(p.description)}"
        coords = f"{_num(p.n)} {_num(p.e)}" + (f" {_num(p.z)}" if p.z is not None else "")
        lines.append(f"    <CgPoint {attrs}>{escape(coords)}</CgPoint>")
    lines += ["  </CgPoints>", "</LandXML>", ""]
    return "\n".join(lines)


__all__ = ["EXPORT_FORMATS", "EXPORT_PRESETS", "ExportPoint", "layer_name", "to_csv", "to_dxf", "to_landxml"]

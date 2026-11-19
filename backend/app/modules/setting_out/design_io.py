# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Read design stakes and alignments from CSV and LandXML 1.2, and measured stakes from CSV.

CSV: a header row names the columns (``point``/``id``, ``e``/``easting``,
``n``/``northing``, ``z``/``height``, ``chainage``/``station``, ``offset``,
``code``/``description``, and for measured files ``instrument``, ``control``,
``measured_by``). Without a header the order is P,E,N,Z,code. A row with a
chainage and no E/N is placed on the request's alignment.

LandXML: ``CgPoints/CgPoint`` become design points and ``Alignments/Alignment``
(``CoordGeom`` with ``Line``, ``Curve`` and clothoid ``Spiral``) becomes the
alignment, and its ``Profile/ProfAlign`` (``PVI`` and ``ParaCurve``) the vertical
profile. LandXML writes northing before easting. A spiral without its length,
radii or tangent direction is reported (SRV-071) and skipped. Parsing goes
through defusedxml, so entity expansion and external entities are refused.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field

from defusedxml import ElementTree as SafeET

from app.modules.setting_out.road_geometry import ProfileError, Pvi, VerticalProfile
from app.modules.setting_out.stakeout_math import Alignment, AlignmentError, ArcElement, LineElement, SpiralElement

MAX_ROWS = 5000

_ALIASES: dict[str, str] = {
    "point": "point_id",
    "point_id": "point_id",
    "pointid": "point_id",
    "id": "point_id",
    "name": "point_id",
    "p": "point_id",
    "e": "e",
    "east": "e",
    "easting": "e",
    "x": "e",
    "n": "n",
    "north": "n",
    "northing": "n",
    "y": "n",
    "z": "z",
    "h": "z",
    "height": "z",
    "elevation": "z",
    "chainage": "chainage",
    "station": "chainage",
    "ch": "chainage",
    "offset": "offset",
    "off": "offset",
    "code": "code",
    "description": "code",
    "desc": "code",
    "instrument": "instrument",
    "control": "control_ref",
    "control_ref": "control_ref",
    "measured_by": "measured_by",
    "by": "measured_by",
    "note": "note",
}
_DEFAULT_ORDER = ("point_id", "e", "n", "z", "code")


@dataclass
class Problem:
    """One thing a file got wrong, with its 1-based line (0 = whole file)."""

    line: int
    message: str
    point_id: str = ""


@dataclass
class DesignPoint:
    point_id: str
    e: float | None
    n: float | None
    z: float | None = None
    chainage: float | None = None
    offset: float | None = None
    code: str = ""
    line: int = 0


@dataclass
class MeasuredRow:
    point_id: str
    e: float
    n: float
    z: float | None = None
    instrument: str = ""
    control_ref: str = ""
    measured_by: str = ""
    note: str = ""
    line: int = 0


@dataclass
class DesignFile:
    points: list[DesignPoint] = field(default_factory=list)
    alignment: Alignment | None = None
    profile: VerticalProfile | None = None
    problems: list[Problem] = field(default_factory=list)
    rows_read: int = 0
    #: Spiral elements skipped for a missing parameter (SRV-071), by element number.
    spirals_skipped: list[int] = field(default_factory=list)


def _num(cell: str) -> float | None:
    cell = (cell or "").strip().replace(" ", "")
    if not cell:
        return None
    try:
        return float(cell)
    except ValueError:
        # Decimal comma, as many instruments write in European locales.
        try:
            return float(cell.replace(",", "."))
        except ValueError:
            return None


def _rows(text: str) -> list[list[str]]:
    sample = text[:2000]
    delim = ";" if sample.count(";") > sample.count(",") else ("\t" if "\t" in sample else ",")
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    return list(reader)


def _columns(first: list[str]) -> tuple[dict[str, int], bool]:
    """Column index by field; ``True`` when ``first`` was a header row."""
    mapped = {}
    for i, cell in enumerate(first):
        key = _ALIASES.get(cell.strip().lower().replace(" ", "_"))
        if key and key not in mapped:
            mapped[key] = i
    if "point_id" in mapped and ({"e", "n"} <= mapped.keys() or "chainage" in mapped):
        return mapped, True
    return {k: i for i, k in enumerate(_DEFAULT_ORDER)}, False


def _cell(row: list[str], cols: dict[str, int], key: str) -> str:
    i = cols.get(key)
    return row[i].strip() if i is not None and i < len(row) else ""


def parse_design_csv(text: str) -> DesignFile:
    """Design stakes from a CSV/TXT file."""
    out = DesignFile()
    rows = _rows(text)
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        out.problems.append(Problem(0, "empty file"))
        return out
    cols, has_header = _columns(rows[0])
    body = rows[1:] if has_header else rows
    seen: set[str] = set()
    for idx, row in enumerate(body[:MAX_ROWS], start=2 if has_header else 1):
        out.rows_read += 1
        pid = _cell(row, cols, "point_id")
        e, n = _num(_cell(row, cols, "e")), _num(_cell(row, cols, "n"))
        ch, off = _num(_cell(row, cols, "chainage")), _num(_cell(row, cols, "offset"))
        if not pid:
            out.problems.append(Problem(idx, "no point id"))
            continue
        if (e is None or n is None) and ch is None:
            out.problems.append(Problem(idx, "no coordinates and no chainage", pid))
            continue
        if pid in seen:
            out.problems.append(Problem(idx, "point id used twice; first kept", pid))
            continue
        seen.add(pid)
        out.points.append(
            DesignPoint(
                point_id=pid,
                e=e,
                n=n,
                z=_num(_cell(row, cols, "z")),
                chainage=ch,
                offset=off,
                code=_cell(row, cols, "code")[:64],
                line=idx,
            )
        )
    if len(body) > MAX_ROWS:
        out.problems.append(Problem(0, f"only the first {MAX_ROWS} rows were read"))
    return out


def parse_measured_csv(text: str) -> tuple[list[MeasuredRow], list[Problem]]:
    """Measured stakes (point id, E, N, optional Z and who/what measured them)."""
    rows = _rows(text)
    rows = [r for r in rows if any(c.strip() for c in r)]
    out: list[MeasuredRow] = []
    problems: list[Problem] = []
    if not rows:
        return out, [Problem(0, "empty file")]
    cols, has_header = _columns(rows[0])
    for idx, row in enumerate((rows[1:] if has_header else rows)[:MAX_ROWS], start=2 if has_header else 1):
        pid = _cell(row, cols, "point_id")
        e, n = _num(_cell(row, cols, "e")), _num(_cell(row, cols, "n"))
        if not pid or e is None or n is None:
            problems.append(Problem(idx, "needs point id, E and N", pid))
            continue
        out.append(
            MeasuredRow(
                point_id=pid,
                e=e,
                n=n,
                z=_num(_cell(row, cols, "z")),
                instrument=_cell(row, cols, "instrument")[:255],
                control_ref=_cell(row, cols, "control_ref")[:255],
                measured_by=_cell(row, cols, "measured_by")[:255],
                note=_cell(row, cols, "note")[:1000],
                line=idx,
            )
        )
    return out, problems


# ── LandXML ───────────────────────────────────────────────────────────────


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(node, name: str) -> list:
    return [c for c in list(node) if _local(c.tag) == name]


def _ne(text: str | None) -> tuple[float, float, float | None] | None:
    """LandXML ``"N E [Z]"`` as (E, N, Z)."""
    parts = (text or "").split()
    try:
        vals = [float(p) for p in parts[:3]]
    except ValueError:
        return None
    if len(vals) < 2:
        return None
    return vals[1], vals[0], (vals[2] if len(vals) > 2 else None)


def _pt(node, name: str) -> tuple[float, float] | None:
    found = _children(node, name)
    hit = _ne(found[0].text) if found else None
    return (hit[0], hit[1]) if hit else None


def parse_landxml(text: str | bytes, alignment_name: str = "") -> DesignFile:
    """Design points (``CgPoint``) and the first, or the named, alignment of a LandXML file."""
    out = DesignFile()
    try:
        root = SafeET.fromstring(text)
    except Exception as exc:  # noqa: BLE001 - defusedxml raises several types for refused or broken XML
        out.problems.append(Problem(0, f"not a readable LandXML file: {type(exc).__name__}"))
        return out
    if _local(root.tag) != "LandXML":
        out.problems.append(Problem(0, "root element is not LandXML"))
        return out
    seen: set[str] = set()
    for group in _children(root, "CgPoints"):
        for node in _children(group, "CgPoint"):
            out.rows_read += 1
            pid = (node.get("name") or node.get("oID") or "").strip()
            ne = _ne(node.text)
            if not pid or ne is None:
                out.problems.append(Problem(0, "CgPoint without a name or coordinates", pid))
                continue
            if pid in seen:
                out.problems.append(Problem(0, "point id used twice; first kept", pid))
                continue
            seen.add(pid)
            out.points.append(DesignPoint(pid, ne[0], ne[1], ne[2], code=(node.get("code") or "")[:64]))
    for group in _children(root, "Alignments"):
        for al in _children(group, "Alignment"):
            name = al.get("name") or ""
            if alignment_name and name != alignment_name:
                continue
            if out.alignment is None:
                out.alignment = _alignment(al, name, out.problems, out.spirals_skipped)
                out.profile = _profile(al, out.problems)
    return out


def _float_attr(el, name: str) -> float | None:
    raw = (el.get(name) or "").strip()
    if not raw:
        return None
    if raw.upper() in ("INF", "INFINITY"):
        return math.inf
    try:
        return float(raw)
    except ValueError:
        return None


def _tangent_out(el: LineElement | ArcElement | SpiralElement) -> float:
    """Azimuth in degrees of the tangent at the end of ``el``."""
    if isinstance(el, LineElement):
        return math.degrees(math.atan2(el.end[0] - el.start[0], el.end[1] - el.start[1]))
    if isinstance(el, SpiralElement):
        return math.degrees(el.azimuth_at(el.length))
    radial = math.atan2(el.end[0] - el.center[0], el.end[1] - el.center[1])
    return math.degrees(radial + (-math.pi / 2 if el.ccw else math.pi / 2))


def _spiral(el, start: tuple[float, float] | None, previous: float | None) -> SpiralElement | None:
    length = _float_attr(el, "length")
    r0, r1 = _float_attr(el, "radiusStart"), _float_attr(el, "radiusEnd")
    if start is None or not length or length <= 0 or r0 is None or r1 is None:
        return None
    if (el.get("spiType") or "clothoid").lower() != "clothoid":
        return None
    pi = _pt(el, "PI")
    if pi is not None and pi != start:
        azimuth = math.degrees(math.atan2(pi[0] - start[0], pi[1] - start[1]))
    elif previous is not None:
        azimuth = previous
    else:
        return None
    ccw = (el.get("rot") or "ccw").lower() != "cw"
    return SpiralElement(start, azimuth, length, None if math.isinf(r0) else r0, None if math.isinf(r1) else r1, ccw)


def _alignment(node, name: str, problems: list[Problem], skipped: list[int] | None = None) -> Alignment | None:
    elements: list[LineElement | ArcElement | SpiralElement] = []
    number = 0
    for geom in _children(node, "CoordGeom"):
        for el in list(geom):
            kind = _local(el.tag)
            number += 1
            start, end = _pt(el, "Start"), _pt(el, "End")
            if kind == "Line" and start and end:
                elements.append(LineElement(start, end))
            elif kind == "Curve" and start and end and _pt(el, "Center"):
                ccw = (el.get("rot") or "ccw").lower() != "cw"
                elements.append(ArcElement(start, _pt(el, "Center"), end, ccw))  # type: ignore[arg-type]
            elif kind == "Spiral":
                spiral = _spiral(el, start, _tangent_out(elements[-1]) if elements else None)
                if spiral is None:
                    problems.append(
                        Problem(0, f"SRV-071: {name} element {number}: Spiral parameter missing; element skipped")
                    )
                    if skipped is not None:
                        skipped.append(number)
                else:
                    elements.append(spiral)
            else:
                problems.append(Problem(0, f"alignment {name}: {kind} element skipped (lines, arcs and spirals only)"))
    if not elements:
        problems.append(Problem(0, f"alignment {name} has no line or arc"))
        return None
    try:
        start_ch = float(node.get("staStart") or 0.0)
    except ValueError:
        start_ch = 0.0
    return Alignment(tuple(elements), start_ch, name)


def _profile(node, problems: list[Problem]) -> VerticalProfile | None:
    """The first ``ProfAlign`` under the alignment's ``Profile``: PVIs and parabolic curves."""
    for prof in _children(node, "Profile"):
        for pa in _children(prof, "ProfAlign"):
            pvis: list[Pvi] = []
            label = pa.get("name") or ""
            for el in list(pa):
                kind = _local(el.tag)
                parts = (el.text or "").split()
                try:
                    ch, level = float(parts[0]), float(parts[1])
                except (IndexError, ValueError):
                    problems.append(Problem(0, f"profile {label}: {kind} without station and level"))
                    continue
                if kind == "ParaCurve":
                    pvis.append(Pvi(ch, level, _float_attr(el, "length") or 0.0))
                else:
                    if kind != "PVI":
                        problems.append(Problem(0, f"profile {label}: {kind} read as a PVI without a curve"))
                    pvis.append(Pvi(ch, level))
            try:
                return VerticalProfile(tuple(pvis), label)
            except ProfileError as exc:
                problems.append(Problem(0, str(exc)))
                return None
    return None


def place_on_alignment(points: list[DesignPoint], alignment: Alignment | None, problems: list[Problem]) -> None:
    """Fill E/N of chainage-only points and the chainage/offset of E/N points, in place."""
    for p in points:
        try:
            if p.e is None or p.n is None:
                if alignment is None:
                    problems.append(Problem(p.line, "chainage given but the request has no alignment", p.point_id))
                    continue
                p.e, p.n = alignment.point_at(p.chainage or 0.0, p.offset or 0.0)
            elif alignment is not None and p.chainage is None:
                p.chainage, p.offset = alignment.station_offset(p.e, p.n)
        except AlignmentError as exc:
            problems.append(Problem(p.line, str(exc), p.point_id))
    points[:] = [p for p in points if p.e is not None and p.n is not None]


# ── Alignment JSON (stored on the request) ────────────────────────────────


def alignment_to_json(al: Alignment) -> dict:
    els = []
    for el in al.elements:
        if isinstance(el, LineElement):
            els.append({"type": "line", "start": list(el.start), "end": list(el.end)})
        elif isinstance(el, SpiralElement):
            els.append(
                {
                    "type": "spiral",
                    "start": list(el.start),
                    "azimuth_deg": el.azimuth_deg,
                    "length": el.length,
                    "radius_start": el.radius_start,
                    "radius_end": el.radius_end,
                    "ccw": el.ccw,
                }
            )
        else:
            els.append(
                {"type": "arc", "start": list(el.start), "center": list(el.center), "end": list(el.end), "ccw": el.ccw}
            )
    return {"name": al.name, "start_chainage": al.start_chainage, "length": round(al.length, 4), "elements": els}


def alignment_from_json(data: dict | None) -> Alignment | None:
    if not data or not data.get("elements"):
        return None
    els: list[LineElement | ArcElement | SpiralElement] = []
    for el in data["elements"]:
        if el.get("type") == "line":
            els.append(LineElement(tuple(el["start"]), tuple(el["end"])))  # type: ignore[arg-type]
        elif el.get("type") == "arc":
            els.append(ArcElement(tuple(el["start"]), tuple(el["center"]), tuple(el["end"]), bool(el["ccw"])))  # type: ignore[arg-type]
        elif el.get("type") == "spiral":
            els.append(
                SpiralElement(
                    tuple(el["start"]),  # type: ignore[arg-type]
                    float(el["azimuth_deg"]),
                    float(el["length"]),
                    el.get("radius_start"),
                    el.get("radius_end"),
                    bool(el["ccw"]),
                )
            )
    return Alignment(tuple(els), float(data.get("start_chainage") or 0.0), str(data.get("name") or ""))


__all__ = [
    "DesignFile",
    "DesignPoint",
    "MeasuredRow",
    "Problem",
    "alignment_from_json",
    "alignment_to_json",
    "parse_design_csv",
    "parse_landxml",
    "parse_measured_csv",
    "place_on_alignment",
]

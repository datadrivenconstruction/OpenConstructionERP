# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Read design stakes and alignments from CSV and LandXML 1.2, and measured stakes from CSV.

CSV: a header row names the columns (``point``/``id``, ``e``/``easting``,
``n``/``northing``, ``z``/``height``, ``chainage``/``station``, ``offset``,
``code``/``description``, and for measured files ``instrument``, ``control``,
``measured_by``). Without a header the order is P,E,N,Z,code. A row with a
chainage and no E/N is placed on the request's alignment.

LandXML: ``CgPoints/CgPoint`` become design points and ``Alignments/Alignment``
(``CoordGeom`` with ``Line`` and ``Curve``) becomes the alignment. LandXML writes
northing before easting. Spirals are reported and skipped. Parsing goes through
defusedxml, so entity expansion and external entities are refused.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from defusedxml import ElementTree as SafeET

from app.modules.setting_out.stakeout_math import Alignment, AlignmentError, ArcElement, LineElement

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
    problems: list[Problem] = field(default_factory=list)
    rows_read: int = 0


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
                out.alignment = _alignment(al, name, out.problems)
    return out


def _alignment(node, name: str, problems: list[Problem]) -> Alignment | None:
    elements: list[LineElement | ArcElement] = []
    for geom in _children(node, "CoordGeom"):
        for el in list(geom):
            kind = _local(el.tag)
            start, end = _pt(el, "Start"), _pt(el, "End")
            if kind == "Line" and start and end:
                elements.append(LineElement(start, end))
            elif kind == "Curve" and start and end and _pt(el, "Center"):
                ccw = (el.get("rot") or "ccw").lower() != "cw"
                elements.append(ArcElement(start, _pt(el, "Center"), end, ccw))  # type: ignore[arg-type]
            else:
                problems.append(Problem(0, f"alignment {name}: {kind} element skipped (lines and arcs only)"))
    if not elements:
        problems.append(Problem(0, f"alignment {name} has no line or arc"))
        return None
    try:
        start_ch = float(node.get("staStart") or 0.0)
    except ValueError:
        start_ch = 0.0
    return Alignment(tuple(elements), start_ch, name)


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
        else:
            els.append(
                {"type": "arc", "start": list(el.start), "center": list(el.center), "end": list(el.end), "ccw": el.ccw}
            )
    return {"name": al.name, "start_chainage": al.start_chainage, "length": round(al.length, 4), "elements": els}


def alignment_from_json(data: dict | None) -> Alignment | None:
    if not data or not data.get("elements"):
        return None
    els: list[LineElement | ArcElement] = []
    for el in data["elements"]:
        if el.get("type") == "line":
            els.append(LineElement(tuple(el["start"]), tuple(el["end"])))  # type: ignore[arg-type]
        elif el.get("type") == "arc":
            els.append(ArcElement(tuple(el["start"]), tuple(el["center"]), tuple(el["end"]), bool(el["ccw"])))  # type: ignore[arg-type]
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

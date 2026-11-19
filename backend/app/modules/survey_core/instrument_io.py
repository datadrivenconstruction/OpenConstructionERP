# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Instrument and exchange files read by format, never by vendor: GSI-8/16, JobXML, LandXML 1.2 points.

Units are explicit. Metres, the international foot (0.3048 m exact) and the
US survey foot (1200/3937 m; deprecated from 1 Jan 2023 by the NIST/NOAA
Federal Register notice of 5 Oct 2020) are told apart only when the file or
the person says which: a file in feet for a metre project needs a choice
(SRV-031), nothing is guessed.

GSI words (word index, WI): 11 point id, 71 code, 81/82/83 E/N/H. The sixth
character of a word is the unit code: 0 = mm, 1 = 0.001 ft, 6 = 0.1 mm,
7 = 0.0001 ft, 8 = 0.01 mm (the format's published word-index reference).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET

from app.modules.survey_core.point_io import MAX_TEXT_BYTES, ParsedPoint, ParseResult, Problem, _fits, _kind_for

FT = 0.3048
FT_US = 1200.0 / 3937.0
#: Metres per unit.
UNIT_M = {"m": 1.0, "ft": FT, "ftUS": FT_US}
LINEAR_UNITS = tuple(UNIT_M)

#: GSI unit code -> (unit, value of one in the last digit).
GSI_UNITS: dict[str, tuple[str, float]] = {
    "0": ("m", 0.001),
    "6": ("m", 0.0001),
    "8": ("m", 0.00001),
    "1": ("feet", 0.001),
    "7": ("feet", 0.0001),
}
_GSI_RAW = {"21", "22", "31", "32", "33"}


@dataclass
class InstrumentParse:
    """Points in the file's own unit, the unit it declares (``m`` / ``feet`` / ``ft`` / ``ftUS``) and problems."""

    result: ParseResult
    unit: str = "m"
    raw_skipped: int = 0


def _check_size(text: str) -> str:
    if len(text.encode("utf-8", errors="ignore")) > MAX_TEXT_BYTES:
        raise ValueError("file larger than 5 MB")
    return text.lstrip("﻿")


def detect_format(text: str, filename: str = "") -> str | None:
    """``gsi`` / ``jobxml`` / ``landxml`` from the content, else ``None``."""
    head = text.lstrip("﻿")[:4000]
    if "<LandXML" in head:
        return "landxml"
    if "<JOBFile" in head:
        return "jobxml"
    first = next((ln.strip() for ln in head.splitlines() if ln.strip()), "")
    if re.match(r"^\*?11[0-9.]{4}[+-]", first) or filename.lower().endswith(".gsi"):
        return "gsi"
    return None


# ── GSI ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def _gsi_id(data: str) -> str:
    v = data.lstrip("0")
    return v or "0"


def parse_gsi(text: str, default_kind: str = "topo") -> InstrumentParse:
    """Read GSI-8 (16-character words) or GSI-16 (24-character, line starts with ``*``) blocks."""
    lines = _check_size(text).splitlines()
    result = ParseResult()
    out = InstrumentParse(result=result)
    units: set[str] = set()
    for line_no, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        result.rows_read += 1
        words = line.lstrip("*").split()
        pid, code = "", ""
        coords: dict[str, float] = {}
        has_raw = False
        bad = False
        for w in words:
            if len(w) < 8:
                continue
            wi, info, sign, data = w[:2], w[2:6], w[6], w[7:]
            if wi == "11":
                pid = _gsi_id(data)
            elif wi == "71":
                code = data.lstrip("0")
            elif wi in ("81", "82", "83"):
                unit_code = info[3]
                if unit_code not in GSI_UNITS:
                    result.problems.append(Problem("SRV-030", line_no, pid, f"{wi}:{unit_code}"))
                    bad = True
                    continue
                unit, step = GSI_UNITS[unit_code]
                units.add(unit)
                try:
                    value = int(data) * step
                except ValueError:
                    bad = True
                    continue
                value = round(value, 6)
                coords[wi] = -value if sign == "-" else value
            elif wi in _GSI_RAW:
                has_raw = True
        if bad:
            if not any(p.line == line_no and p.rule_id == "SRV-030" for p in result.problems):
                result.problems.append(Problem("IMP-001", line_no, pid))
            continue
        if "81" not in coords or "82" not in coords:
            if has_raw:
                out.raw_skipped += 1
            continue
        e, n, z = coords["81"], coords["82"], coords.get("83")
        if not _fits(e, n, z):
            result.problems.append(Problem("IMP-001", line_no, pid))
            continue
        result.points.append(
            ParsedPoint(
                line=line_no,
                point_id=(pid or str(len(result.points) + 1))[:64],
                e=e,
                n=n,
                z=z,
                code=code[:64],
                kind=_kind_for(code, "", default_kind),
            )
        )
    if len(units) > 1:
        # Metre and foot words in one file cannot be scaled to one unit; nothing is read.
        result.problems.append(Problem("SRV-030", 0, "", "mixed"))
        result.points.clear()
    out.unit = "feet" if units == {"feet"} else "m"
    if out.raw_skipped:
        result.problems.append(Problem("SRV-032", 0, "", str(out.raw_skipped)))
    return out


# ── XML helpers ───────────────────────────────────────────────────────────────────────────────────────────────────


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el: Element, name: str) -> Element | None:
    return next((c for c in el if _local(c.tag) == name), None)


def _text(el: Element | None, name: str) -> str:
    c = _child(el, name) if el is not None else None
    return (c.text or "").strip() if c is not None else ""


def _float(raw: str) -> float | None:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def _xml(text: str) -> Element:
    try:
        return SafeET.fromstring(_check_size(text).encode("utf-8"))
    except SafeET.ParseError as exc:
        raise ValueError("not a well-formed XML file") from exc


# ── JobXML ────────────────────────────────────────────────────────────────────────────────────────────────────────


def parse_jobxml(text: str, default_kind: str = "topo") -> InstrumentParse:
    """Reduced grid coordinates of a JobXML file (metres, as JobXML stores them).

    ``Reductions/Point`` is read first; without it, ``FieldBook/PointRecord``
    entries with a ``Grid`` or ``ComputedGrid`` block. Records with only raw
    observations are counted and skipped (SRV-032). Deleted records are ignored.
    """
    root = _xml(text)
    if _local(root.tag) != "JOBFile":
        raise ValueError("not a JobXML file")
    result = ParseResult()
    out = InstrumentParse(result=result, unit="m")
    reductions = [el for el in root.iter() if _local(el.tag) == "Reductions"]
    records: list[tuple[str, str, Element | None]] = []
    if reductions:
        for el in reductions[0]:
            if _local(el.tag) == "Point":
                records.append((_text(el, "Name"), _text(el, "Code"), _child(el, "Grid")))
    else:
        for el in root.iter():
            if _local(el.tag) != "PointRecord" or (el.get("Deleted") or "").lower() == "true":
                continue
            grid = _child(el, "Grid")
            if grid is None:
                grid = _child(el, "ComputedGrid")
            records.append((_text(el, "Name"), _text(el, "Code"), grid))
    seen: set[str] = set()
    for seq, (name, code, grid) in enumerate(records, start=1):
        result.rows_read += 1
        e = _float(_text(grid, "East")) if grid is not None else None
        n = _float(_text(grid, "North")) if grid is not None else None
        if e is None or n is None:
            out.raw_skipped += 1
            continue
        z = _float(_text(grid, "Elevation"))
        pid = (name or str(seq))[:64]
        if pid in seen:
            continue
        seen.add(pid)
        if not _fits(e, n, z):
            result.problems.append(Problem("IMP-001", seq, pid))
            continue
        result.points.append(
            ParsedPoint(line=seq, point_id=pid, e=e, n=n, z=z, code=code[:64], kind=_kind_for(code, "", default_kind))
        )
    if out.raw_skipped:
        result.problems.append(Problem("SRV-032", 0, "", str(out.raw_skipped)))
    return out


# ── LandXML ───────────────────────────────────────────────────────────────────────────────────────────────────────

_LANDXML_UNITS = {
    "meter": "m",
    "metre": "m",
    "millimeter": "mm",
    "foot": "feet",
    "internationalfoot": "ft",
    "ussurveyfoot": "ftUS",
}


def landxml_unit(root: Element) -> str:
    """``m`` / ``ft`` / ``ftUS`` / ``feet`` (foot, definition not stated) from ``Units``; metres when absent."""
    units = next((el for el in root.iter() if _local(el.tag) == "Units"), None)
    if units is None:
        return "m"
    for el in units:
        lin = (el.get("linearUnit") or "").replace(" ", "").lower()
        if lin:
            return _LANDXML_UNITS.get(lin, lin)
    return "m"


def parse_landxml_points(text: str, default_kind: str = "topo") -> InstrumentParse:
    """``CgPoints/CgPoint`` of a LandXML 1.2 file into register points (text order is N E Z)."""
    root = _xml(text)
    if _local(root.tag) != "LandXML":
        raise ValueError("not a LandXML file")
    unit = landxml_unit(root)
    result = ParseResult()
    out = InstrumentParse(result=result, unit=unit)
    if unit not in ("m", "ft", "ftUS", "feet"):
        result.problems.append(Problem("SRV-030", 0, "", unit))
        return out
    by_name: dict[str, tuple[float, float, float | None]] = {}
    seq = 0
    for el in root.iter():
        if _local(el.tag) != "CgPoint":
            continue
        seq += 1
        result.rows_read += 1
        name = (el.get("name") or el.get("oID") or "").strip() or str(seq)
        ref = (el.get("pntRef") or "").strip()
        values = [_float(v) for v in (el.text or "").split()]
        if not values and ref in by_name:
            n, e, z = by_name[ref]
        elif len(values) >= 2 and None not in values:
            n, e = values[0], values[1]
            z = values[2] if len(values) > 2 else None
        else:
            result.problems.append(Problem("IMP-001", seq, name))
            continue
        by_name[name] = (n, e, z)  # type: ignore[assignment]
        if not _fits(e, n, z):  # type: ignore[arg-type]
            result.problems.append(Problem("IMP-001", seq, name))
            continue
        code = (el.get("code") or "").strip()
        result.points.append(
            ParsedPoint(
                line=seq,
                point_id=name[:64],
                e=e,  # type: ignore[arg-type]
                n=n,  # type: ignore[arg-type]
                z=z,
                code=code[:64],
                description=(el.get("desc") or "")[:255],
                kind=_kind_for(code, "", default_kind),
            )
        )
    return out


# ── Units ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def resolve_unit(file_unit: str, project_unit: str, foot_definition: str = "") -> str | None:
    """The definite unit the file's numbers are in, or ``None`` when a foot choice is needed (SRV-031).

    A file that says only "feet" takes the project's own foot when the project
    works in feet; a metre project must say which foot.
    """
    if file_unit in ("m", "ft", "ftUS"):
        return file_unit
    if file_unit == "feet":
        if foot_definition in ("ft", "ftUS"):
            return foot_definition
        if project_unit in ("ft", "ftUS"):
            return project_unit
        return None
    return None


def convert_points(points: list[ParsedPoint], from_unit: str, to_unit: str) -> None:
    """Scale E/N/Z in place from one linear unit to another."""
    if from_unit == to_unit:
        return
    f = UNIT_M[from_unit] / UNIT_M[to_unit]
    for p in points:
        p.e, p.n = round(p.e * f, 4), round(p.n * f, 4)
        if p.z is not None:
            p.z = round(p.z * f, 4)


def unit_of_crs_axis(axis_unit: str) -> str:
    """Project linear unit from the CRS axis unit name pyproj reports."""
    u = (axis_unit or "").lower()
    if "us survey foot" in u:
        return "ftUS"
    if "foot" in u:
        return "ft"
    return "m"


__all__ = [
    "FT",
    "FT_US",
    "GSI_UNITS",
    "LINEAR_UNITS",
    "UNIT_M",
    "InstrumentParse",
    "convert_points",
    "detect_format",
    "landxml_unit",
    "parse_gsi",
    "parse_jobxml",
    "parse_landxml_points",
    "resolve_unit",
    "unit_of_crs_axis",
]

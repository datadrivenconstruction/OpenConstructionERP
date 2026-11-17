# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Reading survey point files (no database).

CSV/TXT point files come in a handful of column orders (PNEZD, PENZD, ENZ,
NEZ); the person confirms the order in a column mapper, so this module guesses
but never decides. GeoJSON points follow RFC 7946 (WGS 84 lon/lat) unless the
legacy ``crs`` member names another EPSG code.

Problems are returned, not raised: a bad row is reported with its line number
and the rest of the file still reads.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field

from app.modules.survey_core.survey_math import same_position

FIELDS = ("point_id", "e", "n", "z", "code", "description", "kind", "sigma")
KINDS = ("control", "benchmark", "topo", "stake", "asbuilt")
PRESETS: dict[str, list[str]] = {
    "PNEZD": ["point_id", "n", "e", "z", "code"],
    "PENZD": ["point_id", "e", "n", "z", "code"],
    "ENZ": ["e", "n", "z"],
    "NEZ": ["n", "e", "z"],
}
DUPLICATE_POLICIES = ("keep_first", "keep_last", "skip")

#: Point codes that name a kind on their own; anything else imports as the chosen default kind.
CODE_KINDS = {"CP": "control", "CTRL": "control", "BM": "benchmark", "STK": "stake", "AB": "asbuilt"}

MAX_TEXT_BYTES = 5 * 1024 * 1024
_DELIMS = (",", ";", "\t", "|", " ")
_HEADER_WORDS = {
    "point_id": ("point", "pt", "id", "name", "pnt", "number", "no", "p"),
    "e": ("e", "east", "easting", "x", "y_east"),
    "n": ("n", "north", "northing", "y", "x_north"),
    "z": ("z", "h", "elev", "elevation", "height", "rl", "level"),
    "code": ("code", "d", "desc", "description", "feature"),
}


@dataclass
class ParsedPoint:
    """One point read from a file."""

    line: int
    point_id: str
    e: float
    n: float
    z: float | None = None
    code: str = ""
    description: str = ""
    kind: str = "topo"
    sigma: float | None = None


@dataclass
class Problem:
    """Something wrong with a row. ``rule_id`` is a SRV rule or an import check (IMP-*)."""

    rule_id: str
    line: int
    point_id: str = ""
    detail: str = ""


@dataclass
class ParseResult:
    """All points read, every problem found, and how many data rows the file had."""

    rows_read: int = 0
    points: list[ParsedPoint] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)


def _clean(text: str) -> str:
    if len(text.encode("utf-8", errors="ignore")) > MAX_TEXT_BYTES:
        raise ValueError("file larger than 5 MB")
    return text.lstrip("﻿")


def _lines(text: str) -> list[tuple[int, str]]:
    return [(i + 1, ln) for i, ln in enumerate(text.splitlines()) if ln.strip() and not ln.lstrip().startswith("#")]


def split_line(line: str, delimiter: str) -> list[str]:
    """One line split on the delimiter; runs of blanks count as one when the delimiter is a space."""
    if delimiter == " ":
        return line.split()
    return [c.strip() for c in next(csv.reader([line], delimiter=delimiter))]


def detect_delimiter(text: str) -> tuple[str, float]:
    """The delimiter that splits the first rows into the same number of columns, with a confidence."""
    sample = [ln for _, ln in _lines(_clean(text))[:20]]
    if not sample:
        return ",", 0.0
    best, best_score = ",", 0.0
    for delim in _DELIMS:
        counts = [len(split_line(ln, delim)) for ln in sample]
        if min(counts) < 2:
            continue
        modal = max(set(counts), key=counts.count)
        score = counts.count(modal) / len(counts)
        # A space only wins when nothing else splits; coordinates never contain commas or tabs.
        if delim == " ":
            score *= 0.9
        if score > best_score:
            best, best_score = delim, score
    return best, round(best_score, 2)


def _num(raw: str) -> float | None:
    s = raw.strip().replace(" ", "")
    if not s:
        return None
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        value = float(s)
    except ValueError:
        return None
    return value if value == value and abs(value) != float("inf") else None


def _header_field(cell: str) -> str | None:
    word = re.sub(r"[^a-z_]", "", cell.strip().casefold())
    for fld, words in _HEADER_WORDS.items():
        if word in words:
            return fld
    return None


def guess_preset(rows: list[list[str]]) -> tuple[str, float]:
    """The likely column preset and a confidence. A header row decides; otherwise magnitudes do.

    A projected northing is usually far larger than the easting (UTM: 7 digits
    against 6), so the bigger column is read as N. On a local grid the two are
    alike and the confidence says so.
    """
    if not rows:
        return "PENZD", 0.0
    head = [_header_field(c) for c in rows[0]]
    if "e" in head and "n" in head:
        first_e = head.index("e") < head.index("n")
        has_id = head[0] == "point_id"
        name = ("PENZD" if first_e else "PNEZD") if has_id else ("ENZ" if first_e else "NEZ")
        return name, 0.95
    data = [r for r in rows if len(r) >= 3]
    if not data:
        return "PENZD", 0.0
    first_numeric = all(_num(r[0]) is not None for r in data[:20])
    with_id = not first_numeric or len(data[0]) >= 4
    a, b = (1, 2) if with_id else (0, 1)
    votes = [(_num(r[a]), _num(r[b])) for r in data[:50] if len(r) > b]
    votes = [(x, y) for x, y in votes if x is not None and y is not None]
    if not votes:
        return ("PENZD" if with_id else "ENZ"), 0.3
    bigger_first = sum(1 for x, y in votes if abs(x) > abs(y) * 2) / len(votes)
    bigger_second = sum(1 for x, y in votes if abs(y) > abs(x) * 2) / len(votes)
    if bigger_first >= 0.8:
        return ("PNEZD" if with_id else "NEZ"), round(0.6 + 0.3 * bigger_first, 2)
    if bigger_second >= 0.8:
        return ("PENZD" if with_id else "ENZ"), round(0.6 + 0.3 * bigger_second, 2)
    return ("PENZD" if with_id else "ENZ"), 0.4


def _kind_for(code: str, raw_kind: str, default_kind: str) -> str:
    k = raw_kind.strip().casefold()
    if k in KINDS:
        return k
    return CODE_KINDS.get(code.strip().upper(), default_kind)


def _flag_duplicates(result: ParseResult) -> None:
    seen: dict[str, ParsedPoint] = {}
    flagged: set[str] = set()
    for p in result.points:
        first = seen.get(p.point_id)
        if first is None:
            seen[p.point_id] = p
            continue
        if not same_position((first.e, first.n, first.z), (p.e, p.n, p.z)) and p.point_id not in flagged:
            flagged.add(p.point_id)
            result.problems.append(Problem("SRV-003", p.line, p.point_id))


def parse_points(
    text: str,
    *,
    columns: list[str],
    delimiter: str = ",",
    has_header: bool = False,
    default_kind: str = "topo",
) -> ParseResult:
    """Read a delimited point file with an explicit column mapping.

    Args:
        text: File content.
        columns: Field per column (``FIELDS`` or ``""`` to skip the column).
        delimiter: One of ``, ; \\t | `` or a space (any run of blanks).
        has_header: Skip the first non-empty line.
        default_kind: Kind for points whose code names none.

    Raises:
        ValueError: when the mapping lacks E or N, or the file is too large.
    """
    if "e" not in columns or "n" not in columns:
        raise ValueError("the mapping needs an E and an N column")
    if default_kind not in KINDS:
        default_kind = "topo"
    lines = _lines(_clean(text))
    if has_header and lines:
        lines = lines[1:]
    result = ParseResult(rows_read=len(lines))
    idx = {f: columns.index(f) for f in FIELDS if f in columns}
    for seq, (line_no, raw) in enumerate(lines, start=1):
        cells = split_line(raw, delimiter)

        def cell(name: str, cells: list[str] = cells) -> str:
            i = idx.get(name)
            return cells[i] if i is not None and i < len(cells) else ""

        e, n = _num(cell("e")), _num(cell("n"))
        z_raw = cell("z")
        z = _num(z_raw) if z_raw else None
        pid = cell("point_id").strip() or str(seq)
        if e is None or n is None or (z_raw and z is None):
            result.problems.append(Problem("IMP-001", line_no, pid))
            continue
        code = cell("code")
        sigma_raw = cell("sigma")
        result.points.append(
            ParsedPoint(
                line=line_no,
                point_id=pid[:64],
                e=e,
                n=n,
                z=z,
                code=code[:64],
                description=cell("description")[:255],
                kind=_kind_for(code, cell("kind"), default_kind),
                sigma=_num(sigma_raw) if sigma_raw else None,
            )
        )
    _flag_duplicates(result)
    return result


def _epsg_of(crs_member: object) -> int | None:
    if not isinstance(crs_member, dict):
        return None
    name = str((crs_member.get("properties") or {}).get("name") or "")
    m = re.search(r"EPSG:{1,2}(\d+)$", name.replace("urn:ogc:def:crs:", ""))
    return int(m.group(1)) if m else None


def parse_geojson(text: str, default_kind: str = "topo") -> tuple[ParseResult, int]:
    """Points of a GeoJSON FeatureCollection and the EPSG code their coordinates are in.

    Raises:
        ValueError: when the text is not a GeoJSON object.
    """
    try:
        doc = json.loads(_clean(text))
    except json.JSONDecodeError as exc:
        raise ValueError("not a GeoJSON file") from exc
    if not isinstance(doc, dict):
        raise ValueError("not a GeoJSON file")
    if doc.get("type") == "FeatureCollection":
        features = doc.get("features") or []
    elif doc.get("type") == "Feature":
        features = [doc]
    else:
        raise ValueError("not a GeoJSON FeatureCollection")
    epsg = _epsg_of(doc.get("crs")) or 4326
    result = ParseResult(rows_read=len(features))
    seq = 0
    for line_no, feat in enumerate(features, start=1):
        geom = (feat or {}).get("geometry") or {}
        props = (feat or {}).get("properties") or {}
        coords = geom.get("coordinates")
        pts = [coords] if geom.get("type") == "Point" else coords if geom.get("type") == "MultiPoint" else None
        if not pts:
            result.problems.append(Problem("IMP-002", line_no, detail=str(geom.get("type") or "")))
            continue
        base_id = str(props.get("point_id") or props.get("id") or props.get("name") or feat.get("id") or "").strip()
        for k, c in enumerate(pts):
            seq += 1
            pid = base_id if base_id and len(pts) == 1 else (f"{base_id}-{k + 1}" if base_id else str(seq))
            try:
                e, n = float(c[0]), float(c[1])
                z = float(c[2]) if len(c) > 2 and c[2] is not None else None
            except (TypeError, ValueError, IndexError):
                result.problems.append(Problem("IMP-001", line_no, pid))
                continue
            code = str(props.get("code") or "")
            result.points.append(
                ParsedPoint(
                    line=line_no,
                    point_id=pid[:64],
                    e=e,
                    n=n,
                    z=z,
                    code=code[:64],
                    description=str(props.get("description") or "")[:255],
                    kind=_kind_for(code, str(props.get("kind") or ""), default_kind),
                )
            )
    _flag_duplicates(result)
    return result, epsg


def resolve_duplicates(points: list[ParsedPoint], policy: str) -> list[ParsedPoint]:
    """One point per id: the first reading, the last, or none of a conflicting id (``skip``)."""
    by_id: dict[str, list[ParsedPoint]] = {}
    for p in points:
        by_id.setdefault(p.point_id, []).append(p)
    out: list[ParsedPoint] = []
    for p in points:
        group = by_id[p.point_id]
        conflicting = any(not same_position((group[0].e, group[0].n, group[0].z), (q.e, q.n, q.z)) for q in group)
        if policy == "skip" and conflicting:
            continue
        chosen = group[-1] if policy == "keep_last" else group[0]
        if p is chosen:
            out.append(p)
    return out

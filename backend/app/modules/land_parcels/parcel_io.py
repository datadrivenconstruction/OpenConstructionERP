# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Parcel files in and out: GeoJSON, zipped Shapefile (pyshp) and DXF (ezdxf).

Reading returns rings and problems, never raises on one bad feature: a feature
without a polygon is reported with its number and the rest is still read. The
file's CRS is reported (GeoJSON ``crs`` member, Shapefile ``.prj``) so the
caller can show both systems before anything is transformed.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from app.modules.land_parcels.geometry import open_ring, ring_closed

Ring = list[tuple[float, float]]

ID_FIELDS = ("parcel_id", "parcel_ref", "parcel", "ref", "id", "name")
LEGAL_AREA_FIELDS = ("legal_area", "area_legal", "registered_area", "legal_a", "area")
STATUSES = ("needed", "negotiating", "acquired", "expropriation")
MAX_FEATURES = 5000


@dataclass
class ParsedFeature:
    """One polygon read from a file."""

    index: int
    ref: str
    name: str
    legal_area: Decimal | None
    status: str
    ring: Ring
    closed: bool
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedFile:
    """Everything one file yielded."""

    features: list[ParsedFeature] = field(default_factory=list)
    problems: list[dict[str, Any]] = field(default_factory=list)
    epsg: int | None = None
    fields: list[str] = field(default_factory=list)


def _pick(props: dict[str, Any], wanted: str, candidates: tuple[str, ...]) -> Any:
    lower = {str(k).lower(): v for k, v in props.items()}
    if wanted:
        return lower.get(wanted.lower())
    for c in candidates:
        if lower.get(c) not in (None, ""):
            return lower[c]
    return None


def _dec(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        out = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() and out >= 0 else None


def _status(value: Any) -> str:
    s = str(value or "").strip().lower()
    return s if s in STATUSES else "needed"


def _feature(
    result: ParsedFile, index: int, props: dict[str, Any], rings: list[Ring], id_field: str, area_field: str
) -> None:
    if not rings or len(open_ring(rings[0])) < 3:
        result.problems.append({"index": index, "code": "no_polygon", "detail": "Feature has no polygon ring"})
        return
    if len(rings) > 1:
        result.problems.append(
            {"index": index, "code": "holes_ignored", "detail": f"{len(rings) - 1} inner ring(s) ignored"}
        )
    ref = str(_pick(props, id_field, ID_FIELDS) or "").strip() or f"#{index + 1}"
    name = str(props.get("name") or props.get("NAME") or "").strip()
    result.features.append(
        ParsedFeature(
            index=index,
            ref=ref[:100],
            name=name[:255] if name != ref else "",
            legal_area=_dec(_pick(props, area_field, LEGAL_AREA_FIELDS)),
            status=_status(props.get("status") or props.get("STATUS")),
            ring=[(float(x), float(y)) for x, y, *_ in rings[0]],
            closed=ring_closed(rings[0]),
            properties={str(k): v for k, v in props.items()},
        )
    )


def _epsg_of(crs_member: object) -> int | None:
    import re  # noqa: PLC0415

    if not isinstance(crs_member, dict):
        return None
    name = str((crs_member.get("properties") or {}).get("name") or "")
    m = re.search(r"EPSG:{1,2}(\d+)$", name.replace("urn:ogc:def:crs:", ""))
    return int(m.group(1)) if m else None


def parse_geojson(text: str, id_field: str = "", area_field: str = "") -> ParsedFile:
    """Polygons of a GeoJSON FeatureCollection (or one Feature / geometry)."""
    try:
        doc = json.loads(text.lstrip("﻿"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Not a JSON file: {exc.msg} at line {exc.lineno}") from exc
    if not isinstance(doc, dict):
        raise ValueError("Not a GeoJSON object")
    result = ParsedFile(epsg=_epsg_of(doc.get("crs")))
    if doc.get("type") == "FeatureCollection":
        features = doc.get("features") or []
    elif doc.get("type") == "Feature":
        features = [doc]
    else:
        features = [{"type": "Feature", "properties": {}, "geometry": doc}]
    if len(features) > MAX_FEATURES:
        raise ValueError(f"More than {MAX_FEATURES} features")
    keys: set[str] = set()
    for i, feat in enumerate(features):
        if not isinstance(feat, dict):
            result.problems.append({"index": i, "code": "no_polygon", "detail": "Not a feature"})
            continue
        props = feat.get("properties") or {}
        keys.update(str(k) for k in props)
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if geom.get("type") == "MultiPolygon":
            if len(coords) != 1:
                result.problems.append(
                    {"index": i, "code": "multipolygon", "detail": "A parcel must be one polygon; split it first"}
                )
                continue
            coords = coords[0]
        elif geom.get("type") != "Polygon":
            coords = []
        try:
            rings = [[(float(c[0]), float(c[1])) for c in ring] for ring in coords]
        except (TypeError, ValueError, IndexError):
            rings = []
        _feature(result, i, props, rings, id_field, area_field)
    result.fields = sorted(keys)
    return result


def _zip_members(data: bytes) -> dict[str, bytes]:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("Not a zip file: a Shapefile comes as .zip with .shp, .shx and .dbf") from exc
    out: dict[str, bytes] = {}
    total = 0
    for info in zf.infolist():
        ext = info.filename.rsplit(".", 1)[-1].lower()
        if ext in ("shp", "shx", "dbf", "prj", "cpg") and ext not in out:
            total += info.file_size
            if total > 50 * 1024 * 1024:
                raise ValueError("Shapefile is larger than 50 MB")
            out[ext] = zf.read(info)
    for ext in ("shp", "dbf"):
        if ext not in out:
            raise ValueError(f"The zip has no .{ext} file")
    return out


def _epsg_from_prj(wkt: str) -> int | None:
    try:
        from pyproj import CRS  # noqa: PLC0415

        return CRS.from_wkt(wkt).to_epsg(min_confidence=70)
    except Exception:  # noqa: BLE001 - an unreadable .prj means "unknown", the user declares it
        return None


def _shp_rings(shape: Any) -> list[Ring]:
    parts = list(shape.parts) + [len(shape.points)]
    return [[(float(x), float(y)) for x, y, *_ in shape.points[a:b]] for a, b in zip(parts, parts[1:], strict=False)]


def parse_shapefile_zip(data: bytes, id_field: str = "", area_field: str = "") -> ParsedFile:
    """Polygons of a zipped Shapefile; the CRS comes from its ``.prj`` when present."""
    import shapefile  # noqa: PLC0415 - pyshp

    members = _zip_members(data)
    encoding = (members.get("cpg") or b"utf-8").decode("ascii", "ignore").strip() or "utf-8"
    reader = shapefile.Reader(
        shp=io.BytesIO(members["shp"]),
        shx=io.BytesIO(members["shx"]) if "shx" in members else None,
        dbf=io.BytesIO(members["dbf"]),
        encoding=encoding,
        encodingErrors="replace",
    )
    result = ParsedFile(epsg=_epsg_from_prj(members["prj"].decode("utf-8", "ignore")) if "prj" in members else None)
    result.fields = [f[0] for f in reader.fields[1:]]
    if len(reader) > MAX_FEATURES:
        raise ValueError(f"More than {MAX_FEATURES} features")
    for i, sr in enumerate(reader.iterShapeRecords()):
        if sr.shape.shapeType not in (shapefile.POLYGON, shapefile.POLYGONZ, shapefile.POLYGONM):
            result.problems.append({"index": i, "code": "no_polygon", "detail": "Not a polygon shape"})
            continue
        rings = _shp_rings(sr.shape)
        outer = [r for r in rings if _signed_area(r) < 0] or rings[:1]
        if len(outer) > 1:
            result.problems.append(
                {"index": i, "code": "multipolygon", "detail": "A parcel must be one polygon; split it first"}
            )
            continue
        rest = [r for r in rings if r is not outer[0]]
        _feature(result, i, sr.record.as_dict(), [outer[0], *rest], id_field, area_field)
    return result


def _signed_area(ring: Ring) -> float:
    pts = open_ring(ring)
    return (
        sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1] for i in range(len(pts)))
        / 2
    )


def _closed(ring: Ring, clockwise: bool) -> Ring:
    pts = open_ring(ring)
    if (_signed_area(pts) < 0) != clockwise:
        pts = list(reversed(pts))
    return [*pts, pts[0]]


# ── Export ──────────────────────────────────────────────────────────────────
# Each parcel is a plain dict: ref, name, status, legal_area, computed_area, ring [(e, n)], points [...].


def to_geojson(parcels: list[dict[str, Any]], epsg: int | None) -> bytes:
    """A FeatureCollection in the project CRS, named by the legacy ``crs`` member."""
    doc: dict[str, Any] = {"type": "FeatureCollection", "features": []}
    if epsg:
        doc["crs"] = {"type": "name", "properties": {"name": f"urn:ogc:def:crs:EPSG::{epsg}"}}
    for p in parcels:
        ring = _closed(p["ring"], clockwise=False)
        doc["features"].append(
            {
                "type": "Feature",
                "properties": {
                    "parcel_id": p["ref"],
                    "name": p.get("name") or "",
                    "status": p.get("status") or "needed",
                    "legal_area": _num(p.get("legal_area")),
                    "computed_area": _num(p.get("computed_area")),
                },
                "geometry": {"type": "Polygon", "coordinates": [[[round(x, 4), round(y, 4)] for x, y in ring]]},
            }
        )
    return json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8")


def _num(value: Any) -> float | None:
    return None if value is None else float(value)


def to_shapefile_zip(parcels: list[dict[str, Any]], epsg: int | None, stem: str = "parcels") -> bytes:
    """A zip with .shp/.shx/.dbf/.cpg (+ .prj when the CRS is known)."""
    import shapefile  # noqa: PLC0415 - pyshp

    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    w = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYGON, encoding="utf-8")
    w.field("PARCEL_ID", "C", size=100)
    w.field("NAME", "C", size=100)
    w.field("STATUS", "C", size=20)
    w.field("LEGAL_A", "N", size=16, decimal=2)
    w.field("COMP_A", "N", size=16, decimal=2)
    for p in parcels:
        w.poly([[list(pt) for pt in _closed(p["ring"], clockwise=True)]])
        w.record(
            p["ref"],
            (p.get("name") or "")[:100],
            p.get("status") or "needed",
            _num(p.get("legal_area")),
            _num(p.get("computed_area")),
        )
    w.close()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{stem}.shp", shp.getvalue())
        zf.writestr(f"{stem}.shx", shx.getvalue())
        zf.writestr(f"{stem}.dbf", dbf.getvalue())
        zf.writestr(f"{stem}.cpg", "UTF-8")
        if epsg:
            try:
                from pyproj import CRS  # noqa: PLC0415
                from pyproj.enums import WktVersion  # noqa: PLC0415

                zf.writestr(f"{stem}.prj", CRS.from_epsg(epsg).to_wkt(WktVersion.WKT1_ESRI))
            except Exception:  # noqa: BLE001 - a missing .prj is better than no export
                pass
    return out.getvalue()


def to_dxf(parcels: list[dict[str, Any]]) -> bytes:
    """Boundaries as closed polylines, ids as text, boundary points with labels; units metres."""
    import ezdxf  # noqa: PLC0415

    doc = ezdxf.new("R2010", units=6)
    msp = doc.modelspace()
    for name, colour in (("PARCELS", 3), ("PARCEL_IDS", 7), ("BOUNDARY_POINTS", 1)):
        doc.layers.add(name, color=colour)
    for p in parcels:
        ring = open_ring(p["ring"])
        msp.add_lwpolyline(ring, close=True, dxfattribs={"layer": "PARCELS"})
        cx = sum(x for x, _ in ring) / len(ring)
        cy = sum(y for _, y in ring) / len(ring)
        msp.add_text(p["ref"], height=1.5, dxfattribs={"layer": "PARCEL_IDS", "insert": (cx, cy)})
        for pt in p.get("points") or []:
            msp.add_point((pt["e"], pt["n"]), dxfattribs={"layer": "BOUNDARY_POINTS"})
            if pt.get("label"):
                msp.add_text(
                    pt["label"],
                    height=0.6,
                    dxfattribs={"layer": "BOUNDARY_POINTS", "insert": (pt["e"] + 0.3, pt["n"] + 0.3)},
                )
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


__all__ = [
    "STATUSES",
    "ParsedFeature",
    "ParsedFile",
    "parse_geojson",
    "parse_shapefile_zip",
    "to_dxf",
    "to_geojson",
    "to_shapefile_zip",
]

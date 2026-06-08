# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""GeoJSON & KML import / export.

GeoJSON is trivial (it is just JSON). The interesting work is a small,
``defusedxml``-based KML parser that turns the most common KML shapes
into GeoJSON FeatureCollections so the rest of the pipeline only needs
to think about one format.

Security hardening (Round 7):

* :func:`kml_looks_like_kml` checks the leading bytes of a KML upload -
  ``<?xml`` or ``<kml`` (whitespace / UTF-8 BOM tolerant). Used by the
  import endpoint to short-circuit obviously-non-KML payloads with a
  precise 415 rather than letting them fall into the XML parser and
  surface as a generic ValueError.
* :func:`validate_geojson` caps the inbound FeatureCollection at
  ``MAX_GEOJSON_FEATURES`` so a multi-MB payload cannot DoS the JSON
  column. Anything over the cap raises ``ValueError`` and the router
  translates that to 422.

We deliberately do NOT pull ``fastkml`` or ``pykml`` as a dependency -
both are LGPL/MIT but neither is needed for the small subset we
support:

* ``<Placemark>`` -> ``Feature``
* ``<Point>`` -> ``Point`` (lon, lat[, alt])
* ``<LineString>`` -> ``LineString``
* ``<Polygon>`` with ``<outerBoundaryIs>`` -> ``Polygon`` (single ring)
* ``<MultiGeometry>`` -> ``GeometryCollection`` (best-effort)
* ``<ExtendedData>`` / ``<Data>`` -> ``properties``

That covers boundary / easement / drone scan exports from common GIS
and survey tools. Anything more exotic falls back to a coordinate-less
``Feature`` with the unparsed text in ``properties._unparsed``.
"""

from __future__ import annotations

import logging
from typing import Any
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as DET

logger = logging.getLogger(__name__)

_KML_NS = "{http://www.opengis.net/kml/2.2}"


def _strip_ns(tag: str) -> str:
    """``{http://...}Placemark`` -> ``Placemark``. Robust to no-namespace KML."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _parse_coords(text: str) -> list[list[float]]:
    """Parse a KML coordinates blob into a list of ``[lon, lat, alt]``.

    KML's ``<coordinates>`` is whitespace-separated ``lon,lat[,alt]``
    triplets. The KML 2.2 spec allows tabs, newlines or spaces between
    triplets; tolerate all three.
    """
    out: list[list[float]] = []
    for token in text.replace("\n", " ").replace("\t", " ").split():
        token = token.strip()
        if not token:
            continue
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            lon = float(parts[0])
            lat = float(parts[1])
            alt = float(parts[2]) if len(parts) >= 3 else 0.0
        except ValueError:
            continue
        out.append([lon, lat, alt])
    return out


def _find(elem: Element, tag: str) -> Element | None:
    """``elem.find(tag)`` that ignores the KML namespace."""
    for child in elem.iter():
        if _strip_ns(child.tag) == tag:
            return child
    return None


def _find_direct(elem: Element, tag: str) -> Element | None:
    """Like :func:`_find`, but only at depth 1 (not descendants)."""
    for child in elem:
        if _strip_ns(child.tag) == tag:
            return child
    return None


def _parse_geometry(geom: Element) -> dict[str, Any] | None:
    name = _strip_ns(geom.tag)
    if name == "Point":
        coords_el = _find(geom, "coordinates")
        if coords_el is None or coords_el.text is None:
            return None
        pts = _parse_coords(coords_el.text)
        if not pts:
            return None
        return {"type": "Point", "coordinates": pts[0]}
    if name == "LineString":
        coords_el = _find(geom, "coordinates")
        if coords_el is None or coords_el.text is None:
            return None
        pts = _parse_coords(coords_el.text)
        if len(pts) < 2:
            return None
        return {"type": "LineString", "coordinates": pts}
    if name == "Polygon":
        outer = _find(geom, "outerBoundaryIs")
        if outer is None:
            return None
        coords_el = _find(outer, "coordinates")
        if coords_el is None or coords_el.text is None:
            return None
        ring = _parse_coords(coords_el.text)
        if len(ring) < 3:
            return None
        # GeoJSON Polygon: outer ring first, holes after. Close the
        # ring if KML left it open.
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        rings: list[list[list[float]]] = [ring]
        for inner_el in geom.iter():
            if _strip_ns(inner_el.tag) != "innerBoundaryIs":
                continue
            hole_coords_el = _find(inner_el, "coordinates")
            if hole_coords_el is None or hole_coords_el.text is None:
                continue
            hole = _parse_coords(hole_coords_el.text)
            if len(hole) >= 3:
                if hole[0] != hole[-1]:
                    hole.append(hole[0])
                rings.append(hole)
        return {"type": "Polygon", "coordinates": rings}
    if name == "MultiGeometry":
        children: list[dict[str, Any]] = []
        for sub in geom:
            sub_geom = _parse_geometry(sub)
            if sub_geom is not None:
                children.append(sub_geom)
        if not children:
            return None
        return {"type": "GeometryCollection", "geometries": children}
    return None


def _parse_extended_data(placemark: Element) -> dict[str, Any]:
    props: dict[str, Any] = {}
    ext = _find_direct(placemark, "ExtendedData")
    if ext is None:
        return props
    for data in ext:
        if _strip_ns(data.tag) != "Data":
            continue
        key = data.attrib.get("name") or ""
        value_el = _find(data, "value")
        if not key or value_el is None:
            continue
        props[key] = (value_el.text or "").strip()
    return props


def kml_to_geojson(kml_bytes: bytes | str) -> dict[str, Any]:
    """Parse a KML document into a GeoJSON FeatureCollection.

    Raises ``ValueError`` when the input is not well-formed XML or when
    no parseable ``Placemark`` elements are found.
    """
    if isinstance(kml_bytes, str):
        kml_bytes = kml_bytes.encode("utf-8")
    try:
        root = DET.fromstring(kml_bytes)
    except Exception as exc:  # noqa: BLE001 - surface any XML error uniformly
        raise ValueError(f"invalid KML: {exc}") from exc

    features: list[dict[str, Any]] = []
    for placemark in root.iter():
        if _strip_ns(placemark.tag) != "Placemark":
            continue
        # Best-effort geometry pick - KML allows multiple direct
        # geometry children. We take the first parseable one.
        geom: dict[str, Any] | None = None
        for child in placemark:
            geom = _parse_geometry(child)
            if geom is not None:
                break
        if geom is None:
            continue

        props = _parse_extended_data(placemark)
        name_el = _find_direct(placemark, "name")
        if name_el is not None and name_el.text:
            props["name"] = name_el.text.strip()
        descr_el = _find_direct(placemark, "description")
        if descr_el is not None and descr_el.text:
            props["description"] = descr_el.text.strip()
        features.append(
            {
                "type": "Feature",
                "geometry": geom,
                "properties": props,
            },
        )

    if not features:
        raise ValueError("KML contained no parseable Placemarks")

    return {"type": "FeatureCollection", "features": features}


# ── GeoJSON validation & export ─────────────────────────────────────────


_VALID_GEOM_TYPES = {
    "Point",
    "LineString",
    "Polygon",
    "MultiPoint",
    "MultiLineString",
    "MultiPolygon",
    "GeometryCollection",
}

# DoS cap: a 50 k-feature FeatureCollection is already > 5 MB serialised
# and slows down the JSONB column writes. Real surveying / boundary
# imports rarely exceed a few hundred features; the cap is generous.
MAX_GEOJSON_FEATURES = 50_000


def validate_geojson(payload: Any) -> dict[str, Any]:
    """Lightly validate a payload as a GeoJSON FeatureCollection.

    We don't ship a full RFC 7946 validator (too heavy for too little
    upside) but we DO enforce the FeatureCollection shape so importers
    cannot stash arbitrary blobs in the overlay column. Caps the feature
    count at :data:`MAX_GEOJSON_FEATURES` so a multi-MB payload cannot
    DoS the JSON column or fill the project's row budget.
    """
    if not isinstance(payload, dict):
        raise ValueError("geojson must be an object")
    kind = payload.get("type")
    if kind == "Feature":
        # Auto-wrap a bare Feature into a FeatureCollection so casual
        # one-off imports work.
        return {"type": "FeatureCollection", "features": [payload]}
    if kind != "FeatureCollection":
        raise ValueError(
            f"geojson type must be FeatureCollection (got {kind!r})",
        )
    features = payload.get("features")
    if not isinstance(features, list):
        raise ValueError("geojson features must be a list")
    if len(features) > MAX_GEOJSON_FEATURES:
        raise ValueError(
            f"geojson features over cap ({len(features)} > {MAX_GEOJSON_FEATURES})",
        )
    for idx, feat in enumerate(features):
        if not isinstance(feat, dict):
            raise ValueError(f"feature[{idx}] not an object")
        if feat.get("type") != "Feature":
            raise ValueError(f"feature[{idx}] type must be 'Feature'")
        geom = feat.get("geometry")
        if geom is None:
            continue  # GeoJSON allows null geometries
        if not isinstance(geom, dict):
            raise ValueError(f"feature[{idx}].geometry not an object")
        gt = geom.get("type")
        if gt not in _VALID_GEOM_TYPES:
            raise ValueError(
                f"feature[{idx}].geometry.type {gt!r} not a valid GeoJSON type",
            )
    return payload


# ── Magic-byte / structural sniff for KML upload payloads ───────────────


def kml_looks_like_kml(payload: str | bytes) -> bool:
    """Return True iff *payload* looks like a KML / XML document.

    A real KML document starts with either ``<?xml`` (the XML prolog -
    KML 2.x always emits one) or ``<kml`` (some hand-edited or
    application-emitted files skip the prolog). We strip the UTF-8 BOM
    and leading whitespace before checking so well-formed inputs from
    common GIS and survey tools all pass.

    The check is intentionally permissive: anything XML-looking falls
    through to :func:`kml_to_geojson` which then runs ``defusedxml``'s
    full parser and returns a precise error. The point here is to reject
    obvious non-KML bytes (PDF, PNG, raw JSON, binary garbage) at the
    edge with HTTP 415 rather than 422 - the former tells the client
    "you sent the wrong content type", the latter would mean "I tried to
    parse it and it broke".
    """
    if isinstance(payload, bytes):
        head = payload[:64]
    else:
        # Encode lazily so we don't materialise the whole string just to
        # peek at the first few bytes.
        head = payload[:64].encode("utf-8", errors="ignore")
    # Strip the BOM + ASCII whitespace.
    head = head.lstrip(b"\xef\xbb\xbf \t\r\n\x00")
    if not head:
        return False
    if head.startswith(b"<?xml"):
        return True
    # ``<kml`` or ``<Kml`` (case-insensitive) - handle the bare-root case.
    if head[:1] == b"<":
        # Use casefold of the next few bytes; cheaper than a full
        # ``lower()`` call on the whole payload.
        tag = head[1:5].lower()
        if tag.startswith(b"kml"):
            return True
    return False


__all__ = [
    "MAX_GEOJSON_FEATURES",
    "kml_looks_like_kml",
    "kml_to_geojson",
    "validate_geojson",
]

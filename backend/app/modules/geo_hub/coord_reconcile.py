"""One source of truth for a project's map location.

A project carries two coordinate pairs: ``project.address`` ``lat``/``lng``
(written by the client when an address suggestion is picked or the pin is
moved) and the geo-hub anchor (written by the server geocoder). They used to be
written independently and never compared, so the project card map and the geo
page could show different places. :func:`reconcile` picks one pair, the callers
write it to both stores together with where it came from and when, and a large
disagreement is kept as ``coord_conflict`` on the address so the user can
choose the other point.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

#: ``coord_source`` values written when a person chose the point themselves.
USER_SOURCES = frozenset({"suggestion", "pin", "user_pick"})

#: Subset of :data:`USER_SOURCES` that is a deliberate decision about the final point (the pin was
#: moved, or the user answered a conflict warning). Nothing is flagged against these.
CONFIRMED_SOURCES = frozenset({"pin", "user_pick"})

#: Two points further apart than this are a disagreement worth showing.
CONFLICT_KM = 5.0

_Point = tuple[Decimal, Decimal]


@dataclass(frozen=True)
class Decision:
    """The reconciled point, where it came from and the point it overrode."""

    lat: Decimal
    lon: Decimal
    source: str
    conflict: dict[str, Any] | None = None


def distance_km(a: _Point, b: _Point) -> float:
    """Great-circle distance between two WGS-84 points in kilometres."""
    lat1, lon1, lat2, lon2 = (math.radians(float(v)) for v in (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(h)))


def _conflict(other: _Point, source: str, km: float) -> dict[str, Any]:
    return {"lat": float(other[0]), "lng": float(other[1]), "source": source, "distance_km": round(km, 1)}


def reconcile(
    saved: _Point | None,
    saved_source: str | None,
    geocoded: _Point | None,
    *,
    threshold_km: float = CONFLICT_KM,
) -> Decision | None:
    """Choose the project's location from the saved pair and the server geocode.

    A point the user picked or moved wins; otherwise the server geocode of the
    saved address text wins, because a coordinate nobody chose may be a client
    geocoder's guess. Either way a disagreement beyond ``threshold_km`` is
    returned as ``conflict`` carrying the point that lost.
    """
    if saved is None and geocoded is None:
        return None
    if geocoded is None:
        assert saved is not None
        return Decision(saved[0], saved[1], saved_source or "project_coordinates")
    if saved is None:
        return Decision(geocoded[0], geocoded[1], "geocoder")
    km = distance_km(saved, geocoded)
    if saved_source in USER_SOURCES:
        conflict = None
        if km > threshold_km and saved_source not in CONFIRMED_SOURCES:
            conflict = _conflict(geocoded, "geocoder", km)
        return Decision(saved[0], saved[1], saved_source, conflict)
    conflict = _conflict(saved, saved_source or "client", km) if km > threshold_km else None
    return Decision(geocoded[0], geocoded[1], "geocoder", conflict)


def apply_to_address(address: dict[str, Any] | None, decision: Decision, now_iso: str) -> dict[str, Any]:
    """Return a copy of ``address`` carrying the reconciled point and its provenance."""
    merged = dict(address or {})
    merged["lat"] = float(decision.lat)
    merged["lng"] = float(decision.lon)
    merged["coord_source"] = decision.source
    merged["coord_at"] = now_iso
    if decision.conflict is not None:
        merged["coord_conflict"] = decision.conflict
    else:
        merged.pop("coord_conflict", None)
    return merged


def anchor_metadata(decision: Decision, now_iso: str) -> dict[str, Any]:
    """Provenance keys merged into the anchor's metadata."""
    return {
        "coord_source": decision.source,
        "coord_at": now_iso,
        "coord_conflict": decision.conflict,
    }

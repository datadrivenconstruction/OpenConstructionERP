# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Country hooks for parcels. Core holds no national cadastre rule.

A country pack registers a :class:`ParcelProfile` with
:func:`register_parcel_profile`: the label of the parcel id (a locale key),
the id format, how areas are rounded, the area tolerance formula of its
cadastre law and any register export it ships. A profile is used only while
the caller's market profile activates that country; otherwise parcels get the
neutral defaults below (0.01 m2 rounding, a percentage tolerance set per
project, no id format, GeoJSON / Shapefile / DXF only).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

#: ``(parcels, project) -> (file bytes, filename, media type)``; parcels are plain export dicts.
Exporter = Callable[[list[dict[str, Any]], dict[str, Any]], tuple[bytes, str, str]]


@dataclass(frozen=True)
class MarkType:
    """A boundary mark a surveyor can record at a corner; ``monumented`` = a physical mark in the ground."""

    key: str
    monumented: bool


#: Offered when neither the country data nor a pack gives a list.
NEUTRAL_MARKS: tuple[MarkType, ...] = (
    MarkType("monument", True),
    MarkType("stone", True),
    MarkType("pipe", True),
    MarkType("pin", True),
    MarkType("nail", True),
    MarkType("unmarked", False),
)


@dataclass(frozen=True)
class ParcelProfile:
    """What one country's cadastre adds to the neutral parcel register."""

    country: str
    #: Locale key and English default for the parcel id column, e.g. "Cadastral number".
    id_label_key: str = "survey.parcels.col.parcel_id"
    id_label_default: str = "Parcel ID"
    id_pattern: str = ""
    id_example: str = ""
    area_decimals: int = 2
    #: ``legal area (m2) -> allowed difference (m2)``; None means the project percentage.
    area_tolerance: Callable[[Decimal], Decimal] | None = None
    #: Where the tolerance comes from (law, clause), shown next to every PAR-001 finding.
    area_tolerance_source: str = ""
    exporters: dict[str, Exporter] = field(default_factory=dict)
    #: Boundary mark types of this cadastre, in the order the picker shows them.
    marks: tuple[MarkType, ...] = NEUTRAL_MARKS

    def id_valid(self, parcel_ref: str) -> bool:
        """Whether a parcel id matches the country's format (always, without one)."""
        return not self.id_pattern or re.fullmatch(self.id_pattern, parcel_ref.strip()) is not None


NEUTRAL = ParcelProfile(country="")
_PROFILES: dict[str, ParcelProfile] = {}


def register_parcel_profile(profile: ParcelProfile) -> None:
    """Register (or replace) a country's parcel profile; called from the pack."""
    _PROFILES[profile.country.strip().upper()] = profile


def unregister_parcel_profile(country: str) -> None:
    """Drop a country's profile (tests, pack uninstall)."""
    _PROFILES.pop(country.strip().upper(), None)


def profile_for(markets: Iterable[str], project_country: str | None = None) -> ParcelProfile:
    """The profile of an active market, the project's own country first; neutral otherwise."""
    wanted = [m.strip().upper() for m in markets]
    if "*" in wanted:
        return NEUTRAL
    country = (project_country or "").strip().upper()
    if country and country in wanted and country in _PROFILES:
        return _PROFILES[country]
    for code in wanted:
        if code in _PROFILES:
            return _PROFILES[code]
    return NEUTRAL


def k_mt_sqrt_area(k: Decimal, mt: Decimal) -> Callable[[Decimal], Decimal]:
    """Tolerance of the form ``k * Mt * sqrt(P)``, the shape several cadastre laws use."""

    def tolerance(area: Decimal) -> Decimal:
        return (k * mt * area.sqrt()).quantize(Decimal("0.01"))

    return tolerance


__all__ = [
    "NEUTRAL",
    "NEUTRAL_MARKS",
    "Exporter",
    "MarkType",
    "ParcelProfile",
    "k_mt_sqrt_area",
    "profile_for",
    "register_parcel_profile",
    "unregister_parcel_profile",
]

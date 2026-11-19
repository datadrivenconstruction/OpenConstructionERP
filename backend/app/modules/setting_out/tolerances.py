# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tolerance profiles for setting-out.

Core ships no national tolerance. It ships one global demo profile, labelled
"Demo values, not a standard", for the Riverside Yard course. Country packs
register their own profiles with :func:`register_pack_tolerance`; a pack's
profiles are offered only while that pack's market is active. Projects can add
their own profiles (stored in ``oe_setting_out_tolerance_profile``).

A profile maps an item type to a horizontal (radial) and a vertical tolerance
in millimetres, plus a ``default`` row for item types it does not name.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

ITEM_TYPES: tuple[str, ...] = (
    "column",
    "wall",
    "pile",
    "anchor_bolt",
    "kerb",
    "centreline",
    "grid_line",
    "boundary_corner",
    "other",
)

DEMO_KEY = "demo"


@dataclass(frozen=True)
class Tolerance:
    """Horizontal and vertical tolerance in mm; ``v_mm`` None skips the height check."""

    h_mm: float
    v_mm: float | None = None


@dataclass(frozen=True)
class ToleranceProfile:
    """A named set of tolerances per item type, with where its values come from."""

    key: str
    name: str
    #: ``demo`` | ``pack`` | ``project``
    source: str
    items: Mapping[str, Tolerance] = field(default_factory=dict)
    #: Country of a pack profile, empty otherwise.
    country: str = ""
    #: Where the values come from (standard and clause), shown next to the name.
    reference: str = ""

    def for_item(self, item_type: str) -> Tolerance | None:
        """The tolerance for ``item_type``, else the profile's ``default`` row, else None."""
        return self.items.get(item_type) or self.items.get("default")


DEMO_PROFILE = ToleranceProfile(
    key=DEMO_KEY,
    name="Demo 10 mm",
    source="demo",
    items={"default": Tolerance(h_mm=10.0, v_mm=10.0)},
    reference="Demo values, not a standard",
)

#: Country code -> profiles registered by country packs.
_PACK_PROFILES: dict[str, list[ToleranceProfile]] = {}


def register_pack_tolerance(country: str, profiles: Iterable[ToleranceProfile]) -> None:
    """Called by a country pack to offer its tolerance profiles (keys must start with ``pack:``)."""
    code = country.strip().upper()
    bucket = _PACK_PROFILES.setdefault(code, [])
    for p in profiles:
        if not p.key.startswith("pack:"):
            raise ValueError("pack tolerance keys start with 'pack:'")
        bucket[:] = [b for b in bucket if b.key != p.key]
        bucket.append(ToleranceProfile(p.key, p.name, "pack", dict(p.items), code, p.reference))


def clear_pack_tolerances() -> None:
    """Forget every pack profile (tests)."""
    _PACK_PROFILES.clear()


def pack_profiles_for(markets: Iterable[str]) -> list[ToleranceProfile]:
    """Profiles from the packs of the caller's markets only; ``*`` activates none."""
    from app.core.active_markets import pack_active  # noqa: PLC0415

    markets = list(markets)
    return [p for country, ps in sorted(_PACK_PROFILES.items()) if pack_active(markets, [country]) for p in ps]


def builtin_profile(key: str, markets: Iterable[str]) -> ToleranceProfile | None:
    """The demo profile or an active pack profile by key."""
    if key == DEMO_KEY:
        return DEMO_PROFILE
    return next((p for p in pack_profiles_for(markets) if p.key == key), None)


def profile_from_items(key: str, name: str, items: Mapping[str, Mapping[str, float | None]]) -> ToleranceProfile:
    """A project profile from its stored JSON ``{item_type: {"h_mm": .., "v_mm": ..}}``."""
    parsed = {
        k: Tolerance(h_mm=float(v["h_mm"]), v_mm=None if v.get("v_mm") is None else float(v["v_mm"]))  # type: ignore[arg-type]
        for k, v in items.items()
        if isinstance(v, Mapping) and v.get("h_mm") is not None
    }
    return ToleranceProfile(key=key, name=name, source="project", items=parsed)


__all__ = [
    "DEMO_KEY",
    "DEMO_PROFILE",
    "ITEM_TYPES",
    "Tolerance",
    "ToleranceProfile",
    "builtin_profile",
    "clear_pack_tolerances",
    "pack_profiles_for",
    "profile_from_items",
    "register_pack_tolerance",
]

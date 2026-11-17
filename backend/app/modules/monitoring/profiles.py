# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Threshold profiles for monitoring.

Core ships no national threshold. It ships one global demo profile, labelled
"Demo values, not a standard", for the Riverside Yard course. Country packs
register their own with :func:`register_pack_profile`; a pack's profiles are
offered only while that pack's market is active. Projects add their own
(stored in ``oe_monitoring_profile``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from app.modules.monitoring.monitoring_math import Thresholds

DEMO_KEY = "demo"


@dataclass(frozen=True)
class MonitoringProfile:
    """A named set of thresholds and where its values come from."""

    key: str
    name: str
    #: ``demo`` | ``pack`` | ``project``
    source: str
    thresholds: Thresholds
    country: str = ""
    #: Standard and clause, or the designer's document, shown next to the name.
    reference: str = ""


DEMO_PROFILE = MonitoringProfile(
    key=DEMO_KEY,
    name="Demo wall profile",
    source="demo",
    thresholds=Thresholds(
        alert_mm=Decimal(10),
        action_mm=Decimal(20),
        alarm_mm=Decimal(30),
        rate_alert=Decimal("1.0"),
    ),
    reference="Demo values, not a standard",
)

_PACK_PROFILES: dict[str, list[MonitoringProfile]] = {}


def register_pack_profile(country: str, profiles: Iterable[MonitoringProfile]) -> None:
    """Called by a country pack to offer its monitoring profiles (keys must start with ``pack:``)."""
    code = country.strip().upper()
    bucket = _PACK_PROFILES.setdefault(code, [])
    for p in profiles:
        if not p.key.startswith("pack:"):
            raise ValueError("pack monitoring profile keys start with 'pack:'")
        bucket[:] = [b for b in bucket if b.key != p.key]
        bucket.append(MonitoringProfile(p.key, p.name, "pack", p.thresholds, code, p.reference))


def clear_pack_profiles() -> None:
    """Forget every pack profile (tests)."""
    _PACK_PROFILES.clear()


def pack_profiles_for(markets: Iterable[str]) -> list[MonitoringProfile]:
    """Profiles from the packs of the caller's markets only; ``*`` activates none."""
    from app.core.active_markets import pack_active  # noqa: PLC0415

    markets = list(markets)
    return [p for country, ps in sorted(_PACK_PROFILES.items()) if pack_active(markets, [country]) for p in ps]


def builtin_profile(key: str, markets: Iterable[str]) -> MonitoringProfile | None:
    """The demo profile or an active pack profile by key."""
    if key == DEMO_KEY:
        return DEMO_PROFILE
    return next((p for p in pack_profiles_for(markets) if p.key == key), None)

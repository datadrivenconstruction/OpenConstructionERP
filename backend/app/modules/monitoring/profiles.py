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

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

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
    #: Edition year of the source standard.
    edition: str = ""
    #: Clause the thresholds come from (pack profiles).
    clause: str = ""
    #: ``verified`` (clause cited) | ``to_verify`` (not yet checked against the source) | "".
    status: str = ""


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
        bucket.append(replace(p, source="pack", country=code))


COUNTRY_DATA_PATH = Path(__file__).resolve().parents[2] / "core" / "country_data" / "site_tolerances.json"
_THRESHOLD_FIELDS = ("alert_mm", "action_mm", "alarm_mm", "rate_alert", "rate_action", "rate_alarm")


def _profile_from_json(row: Mapping[str, Any]) -> MonitoringProfile:
    raw = row.get("thresholds") or {}
    values = {f: None if raw.get(f) is None else Decimal(str(raw[f])) for f in _THRESHOLD_FIELDS}
    edition = str(row.get("edition") or "")
    return MonitoringProfile(
        key=str(row["key"]),
        name=str(row.get("name") or row["key"]),
        source="pack",
        thresholds=Thresholds(**values),
        reference=f"{row.get('standard') or ''}, {edition}".strip(", ")[:255],
        edition=edition,
        clause=str(row.get("clause") or ""),
        status=str(row.get("status") or "to_verify"),
    )


def load_country_profiles(path: Path = COUNTRY_DATA_PATH) -> int:
    """Register every country's monitoring profiles from the country data; returns how many profiles."""
    data = json.loads(path.read_text(encoding="utf-8"))
    count = 0
    for country, entry in data.items():
        if country.startswith("_"):
            continue
        profiles = [_profile_from_json(row) for row in entry.get("monitoring") or []]
        if profiles:
            register_pack_profile(country, profiles)
            count += len(profiles)
    return count


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

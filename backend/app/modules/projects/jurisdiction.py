# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A project's jurisdiction and measurement system, as the user states them.

Both are optional and both start empty. A project used to have neither: its
measurement system was always derived from the regional pack claiming its
country, and nothing on a project could name a state or a province, so the
subdivision packs' statutes were out of reach. These two fields let a person
say what the derivation cannot know - a crew working in imperial on a project
in a metric country, or the state whose retainage law applies.

They are never filled from the country. An empty field keeps every consumer on
the answer it gave before the field existed, which is the point: a value the
product filled in would read exactly like a value somebody chose, and the
difference is the whole reason to store it.

A jurisdiction is either an ISO 3166-1 alpha-2 country (``"DE"``) or an ISO
3166-2 subdivision (``"US-CA"``). A country is accepted when it is a code the
platform knows (the country-name resolver's table plus every country a regional
pack claims). A subdivision is accepted only when the platform enumerates it,
either through a subdivision pack or through the subdivision registry, because
a subdivision nothing in the product can read would look configured and change
nothing.
"""

from __future__ import annotations

import re
from typing import Any

#: The two measurement systems a project can be set to. Same vocabulary the
#: regional packs declare in ``measurement_system``.
UNIT_SYSTEMS: tuple[str, ...] = ("metric", "imperial")

_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_SUBDIVISION_RE = re.compile(r"^[A-Z]{2}-[A-Z0-9]{1,3}$")

#: Widest code the column must hold: ``XX-XXX``.
JURISDICTION_MAX_LENGTH = 6


def _pack_countries_and_subdivisions() -> tuple[set[str], dict[str, str]]:
    """Countries the regional packs claim, and the subdivisions they carry with their names."""
    from app.core.regional_packs import pack_configs

    countries: set[str] = set()
    subdivisions: dict[str, str] = {}
    for config in pack_configs():
        for code in config.get("countries") or ():
            cc = str(code or "").strip().upper()
            if _COUNTRY_RE.match(cc):
                countries.add(cc)
        sub = str(config.get("subdivision_code") or "").strip().upper()
        if config.get("parent_pack") and _SUBDIVISION_RE.match(sub):
            subdivisions[sub] = str(config.get("subdivision_name") or sub)
    return countries, subdivisions


def known_countries() -> frozenset[str]:
    """Every ISO 3166-1 alpha-2 code a project jurisdiction may name."""
    from app.core.country_resolver import known_country_codes

    countries = {code for code in known_country_codes() if _COUNTRY_RE.match(code)}
    pack_countries, _subs = _pack_countries_and_subdivisions()
    return frozenset(countries | pack_countries)


def known_subdivisions() -> dict[str, str]:
    """Every ISO 3166-2 code a project jurisdiction may name, with an English label.

    The label is data for an API payload, not a UI string.
    """
    _countries, subdivisions = _pack_countries_and_subdivisions()
    try:
        from app.modules.i18n_foundation.subdivisions import KNOWN_SUBDIVISIONS
    except ImportError:  # the i18n foundation module is optional
        registry: dict[str, dict[str, str]] = {}
    else:
        registry = KNOWN_SUBDIVISIONS
    merged = {code: name for per_country in registry.values() for code, name in per_country.items()}
    for code, name in subdivisions.items():
        merged.setdefault(code, name)
    return dict(sorted(merged.items()))


def normalise_jurisdiction(value: str | None) -> str | None:
    """Canonical form of a jurisdiction code, ``None`` for blank.

    Raises:
        ValueError: The code is neither a known country nor a known subdivision.
    """
    if value is None:
        return None
    code = str(value).strip().upper()
    if not code:
        return None
    if _COUNTRY_RE.match(code):
        if code in known_countries():
            return code
        raise ValueError(f"jurisdiction {value!r} is not a known ISO 3166-1 alpha-2 country code")
    if _SUBDIVISION_RE.match(code):
        if code in known_subdivisions():
            return code
        raise ValueError(
            f"jurisdiction {value!r} is not a subdivision the platform carries rules for; "
            "use the country code alone, or one of the codes GET /api/v1/projects/jurisdictions/ lists"
        )
    raise ValueError(f"jurisdiction {value!r} must be a country code such as DE or a subdivision such as US-CA")


def normalise_unit_system(value: str | None) -> str | None:
    """``"metric"``, ``"imperial"`` or ``None`` for blank.

    Raises:
        ValueError: Any other value.
    """
    if value is None:
        return None
    system = str(value).strip().lower()
    if not system:
        return None
    if system not in UNIT_SYSTEMS:
        raise ValueError(f"unit_system must be one of {', '.join(UNIT_SYSTEMS)}, got {value!r}")
    return system


def jurisdiction_country(code: str | None) -> str | None:
    """The country part of a jurisdiction code, or ``None``."""
    if not code:
        return None
    return code.strip().upper()[:2] or None


def jurisdiction_subdivision(code: str | None) -> str | None:
    """The jurisdiction when it names a subdivision, else ``None``."""
    if not code:
        return None
    code = code.strip().upper()
    return code if _SUBDIVISION_RE.match(code) else None


def jurisdiction_conflict(jurisdiction: str | None, country_code: str | None) -> bool:
    """True when both are set and the jurisdiction lies in another country."""
    country = (country_code or "").strip().upper()
    if not jurisdiction or not country:
        return False
    return jurisdiction_country(jurisdiction) != country


def jurisdiction_options() -> list[dict[str, Any]]:
    """The codes a project may be set to, countries first, for the settings picker."""
    countries = [{"code": cc, "country_code": cc, "kind": "country", "name": None} for cc in sorted(known_countries())]
    subdivisions = [
        {"code": code, "country_code": code[:2], "kind": "subdivision", "name": name}
        for code, name in known_subdivisions().items()
    ]
    return countries + subdivisions

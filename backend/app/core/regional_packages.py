# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Regional solution packages read from ``country_data/regional_solution_packages.json``.

A regional package is a worldwide solution package plus the neutral modules and the
country profile one region needs (currency, languages, calendar, VAT, regulator labels,
lease export profile). Only data lives here; installing goes through the module
preferences and the demo installer like any other package.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA = Path(__file__).resolve().parent / "country_data" / "regional_solution_packages.json"


@lru_cache(maxsize=1)
def regional_packages() -> dict[str, dict[str, Any]]:
    """All regional packages, by id."""
    try:
        return dict(json.loads(_DATA.read_text(encoding="utf-8")).get("packages") or {})
    except (OSError, ValueError):
        return {}


def get_regional_package(package_id: str) -> dict[str, Any] | None:
    """One package, or ``None`` when unknown."""
    return regional_packages().get(package_id)


def country_profile(package_id: str, country: str) -> dict[str, Any]:
    """The package's profile for ``country``, or an empty dict."""
    pkg = get_regional_package(package_id) or {}
    return dict((pkg.get("profiles") or {}).get(country.upper()) or {})


def module_closure(package_id: str) -> list[str]:
    """Required then optional modules, de-duplicated in order."""
    pkg = get_regional_package(package_id) or {}
    seen: set[str] = set()
    return [m for m in [*pkg.get("required", []), *pkg.get("optional", [])] if not (m in seen or seen.add(m))]

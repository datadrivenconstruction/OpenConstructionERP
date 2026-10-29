# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Country lease limits read from ``core/country_data/lease_rules.json``.

Neutral by construction: a country appears only with a published source, and a
country or field that is absent means no limit. Packs may add rows at run time
through :func:`register_country_rules` instead of editing core data.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA = Path(__file__).resolve().parents[2] / "core" / "country_data" / "lease_rules.json"
_EXTRA: dict[str, dict[str, Any]] = {}


@lru_cache(maxsize=1)
def _shipped() -> dict[str, dict[str, Any]]:
    try:
        return dict(json.loads(_DATA.read_text(encoding="utf-8")).get("countries") or {})
    except (OSError, ValueError):
        return {}


def register_country_rules(country: str, rules: dict[str, Any]) -> None:
    """Let a pack add or override one country's row (must carry ``source_url``)."""
    if not rules.get("source_url"):
        raise ValueError("a lease rule needs a source_url")
    _EXTRA[country.upper()] = dict(rules)


def rules_for(country: str | None) -> dict[str, Any]:
    """The country's row, or an empty dict when nothing is known."""
    if not country:
        return {}
    code = country.upper()
    return dict(_EXTRA.get(code) or _shipped().get(code) or {})


def deposit_cap_months(country: str | None, lease_kind: str = "default") -> Decimal | None:
    """Deposit cap in months of rent, or ``None`` for no cap."""
    caps = rules_for(country).get("deposit_cap_months")
    if isinstance(caps, dict):
        caps = caps.get(lease_kind, caps.get("default"))
    if caps in (None, ""):
        return None
    try:
        return Decimal(str(caps))
    except InvalidOperation:
        return None


def tenant_identifier_schemes(country: str | None) -> list[str]:
    """Identifier schemes one of which the tenant must carry; empty = none required."""
    return [str(s) for s in rules_for(country).get("tenant_identifier_schemes") or []]

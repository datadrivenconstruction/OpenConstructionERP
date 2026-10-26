# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Default​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ terms for a new guarantee: FIDIC 2017 first, then the country pack.

The register itself names no country. It starts from the FIDIC 2017 Red Book
figures (an open standard) and lets a regional pack override them per country
through a ``guarantee_defaults`` block in its ``PACK_CONFIG``, keyed by ISO code,
read via :func:`app.core.regional_packs.packs_for_country`. A pack that writes no
block for a country changes nothing.
"""

from __future__ import annotations

import copy
from typing import Any

from app.core.regional_packs import packs_for_country

# Per guarantee type: percent of contract value, months the security must outlive
# completion, the call (claim) period after expiry in days, and the source.
FIDIC_2017: dict[str, dict[str, Any]] = {
    "bid_bond": {
        "percent_of_contract": "2",
        "valid_days_after_bid_validity": 28,
        "claim_period_days": 0,
        "source": "FIDIC Procurement Procedures Guide 2011; Instructions to Tenderers (typical entry)",
    },
    "performance_bond": {
        "percent_of_contract": "10",
        "defects_period_months": 12,
        "claim_period_days": 28,
        "source": "FIDIC Red Book 2017, Sub-Clause 4.2 and the Contract Data",
    },
    "advance_payment": {
        "percent_of_advance": "100",
        "advance_recovery_pct": "25",
        "claim_period_days": 28,
        "source": "FIDIC Red Book 2017, Sub-Clause 14.2 (amortisation as a percentage of each IPC)",
    },
    "retention_bond": {
        "percent_of_contract": "5",
        "replaces_cash_retention": True,
        "claim_period_days": 28,
        "source": "FIDIC Red Book 2017, Sub-Clause 14.9 (retention money guarantee)",
    },
    "warranty_bond": {
        "percent_of_contract": "5",
        "defects_period_months": 12,
        "claim_period_days": 28,
        "source": "FIDIC Red Book 2017, Clause 11 (Defects Notification Period)",
    },
    "parent_company": {
        "percent_of_contract": "100",
        "claim_period_days": 0,
        "source": "FIDIC 2017 Annex A (Example Form of Parent Company Guarantee)",
    },
}


def defaults_for(country_code: str | None = None) -> dict[str, Any]:
    """FIDIC 2017 defaults with the country pack's overrides laid over them, per type."""
    merged = copy.deepcopy(FIDIC_2017)
    code = (country_code or "").strip().upper()
    origin = "FIDIC 2017"
    for config in packs_for_country(code) if code else ():
        block = (config.get("guarantee_defaults") or {}).get(code)
        if not isinstance(block, dict):
            continue
        origin = block.get("origin", origin)
        for gtype, values in (block.get("types") or {}).items():
            if gtype in merged and isinstance(values, dict):
                merged[gtype].update(values)
    return {"country": code or None, "origin": origin, "types": merged}

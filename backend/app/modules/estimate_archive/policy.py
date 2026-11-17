# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Which market profile a project's seal follows.

The profile data lives in ``app/core/country_data/estimate_archive.json``; no
country value is written in code. A contract form named on the contract
(FIDIC, JCT, NEC, VOB) wins over the project's country, because a FIDIC
contract in Germany is priced under FIDIC.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA = Path(__file__).resolve().parents[2] / "core" / "country_data" / "estimate_archive.json"


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    return json.loads(_DATA.read_text(encoding="utf-8"))


def profile_ids() -> list[str]:
    """Every profile the data declares."""
    return sorted(_data()["profiles"])


def markets() -> list[str]:
    """Countries whose profile seals estimates; the module is shown only there."""
    data = _data()
    return sorted(c for c, pid in data["countries"].items() if data["profiles"].get(pid, {}).get("enabled"))


def contract_form(contract: Any) -> str:
    """The standard form a contract names, lower case, or ``""``."""
    if contract is None:
        return ""
    meta = getattr(contract, "metadata_", None) or {}
    terms = getattr(contract, "terms", None) or {}
    for value in (
        meta.get("standard_form") if isinstance(meta, dict) else None,
        terms.get("standard_form") if isinstance(terms, dict) else None,
        getattr(contract, "template_code", None),
    ):
        if value:
            return str(value).lower()
    return ""


def resolve_profile_id(country_code: str | None, form: str = "") -> str:
    """Profile id for a project country and a contract form."""
    data = _data()
    for needle, profile in data["contract_forms"].items():
        if needle in (form or ""):
            return str(profile)
    return str(data["countries"].get((country_code or "").upper(), "neutral"))


def policy_for(profile_id: str) -> dict[str, Any]:
    """The profile's settings with its id; unknown ids read as neutral."""
    profiles = _data()["profiles"]
    pid = profile_id if profile_id in profiles else "neutral"
    return {"profile": pid, **profiles[pid]}

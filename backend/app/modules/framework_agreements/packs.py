# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Market facts for framework agreements, read from ``country_data/framework_agreements.json``.

The module itself is neutral. A project's country picks the entries that apply: its own
country first, then the supranational markets it belongs to (a German project reads DE, then
EU). A project with no country, or a country no entry names, gets neutral fields only.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.market_scope import supranational_markets

logger = logging.getLogger(__name__)

_FILE = Path(__file__).resolve().parents[2] / "core" / "country_data" / "framework_agreements.json"


@lru_cache(maxsize=1)
def _markets() -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("framework_agreements: %s unreadable, neutral fields only", _FILE.name)
        return {}
    return {str(k).upper(): v for k, v in (raw.get("markets") or {}).items() if isinstance(v, dict)}


def market_chain(country: str | None) -> list[str]:
    """The market keys that apply to ``country``, most specific first."""
    code = str(country or "").strip().upper()
    if not code:
        return []
    chain = [code]
    for market, members in sorted(supranational_markets().items()):
        if code in members:
            chain.append(market)
    return [m for m in chain if m in _markets()]


def pack_profile(country: str | None, client_kind: str = "classic") -> dict[str, Any]:
    """Everything the agreement screens show for ``country``; empty lists when no pack applies.

    Returns a dict with ``markets``, ``term_variant``, ``term_limit`` (``{"years", "source"}`` or
    None), ``pack_fields``, ``condition_tags``, ``escalation_templates``, ``notes`` and the
    optional ``measurement_preset`` and ``min_value_required``.
    """
    chain = market_chain(country)
    data = _markets()
    out: dict[str, Any] = {
        "markets": chain,
        "term_variant": "neutral",
        "term_limit": None,
        "pack_fields": [],
        "condition_tags": [],
        "escalation_templates": [],
        "notes": [],
        "measurement_preset": None,
        "min_value_required": None,
    }
    for key in chain:
        entry = data[key]
        if out["term_variant"] == "neutral" and entry.get("term_variant"):
            out["term_variant"] = entry["term_variant"]
        if out["term_limit"] is None:
            for limit in entry.get("term_limits") or []:
                if limit.get("client_kind") == client_kind:
                    out["term_limit"] = {"years": int(limit["years"]), "source": str(limit["source"])}
                    break
        for list_key in ("pack_fields", "condition_tags", "escalation_templates", "notes"):
            for value in entry.get(list_key) or []:
                if value not in out[list_key]:
                    out[list_key].append(value)
        if out["measurement_preset"] is None and entry.get("measurement_preset"):
            out["measurement_preset"] = entry["measurement_preset"]
        if out["min_value_required"] is None and entry.get("min_value_required"):
            out["min_value_required"] = entry["min_value_required"]
    return out

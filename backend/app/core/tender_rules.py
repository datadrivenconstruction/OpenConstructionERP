# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tender​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ addenda and clarification defaults per country.

Country-neutral engine over ``country_data/tender_clarification.json``. The
``DEFAULT`` row is neutral practice; a country row overrides only the keys it
names, and a package overrides any key in its own ``metadata.tender_rules``.
No country is hardcoded here.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA = Path(__file__).parent / "country_data" / "tender_clarification.json"

#: Keys a package may override in ``metadata.tender_rules``.
OVERRIDABLE = (
    "addendum_min_days_before_closing",
    "answer_min_days_before_closing",
    "questions_close_days_before_closing",
    "bid_validity_days",
    "extend_deadline_if_late_addendum",
)


@dataclass(frozen=True, slots=True)
class TenderRules:
    """The figures the addenda workflow and its validation rules read."""

    country_code: str
    label: str
    addendum_min_days_before_closing: int
    answer_min_days_before_closing: int
    questions_close_days_before_closing: int
    bid_validity_days: int
    extend_deadline_if_late_addendum: bool
    acknowledgement: str
    public_notice_of_changes: bool
    source: str
    statute_reference: str | None
    confidence: str

    def as_dict(self) -> dict[str, Any]:
        """Plain dict for API responses and validation payloads."""
        return asdict(self)


@lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    return json.loads(_DATA.read_text(encoding="utf-8"))


def jurisdictions() -> list[str]:
    """Country codes that carry their own row (``DEFAULT`` excluded)."""
    return sorted(_load().get("countries", {}))


def rules_for(country_code: str | None, overrides: dict[str, Any] | None = None) -> TenderRules:
    """Resolve the rules for a country, then apply a package's own overrides.

    An unknown or missing country reads the neutral ``DEFAULT`` row.
    """
    data = _load()
    merged: dict[str, Any] = dict(data["DEFAULT"])
    code = (country_code or "").strip().upper()
    row = data.get("countries", {}).get(code)
    if row:
        merged.update(row)
    else:
        code = "DEFAULT"
    for key in OVERRIDABLE:
        if overrides and overrides.get(key) is not None:
            merged[key] = overrides[key]
    return TenderRules(
        country_code=code,
        label=str(merged.get("label", "")),
        addendum_min_days_before_closing=int(merged["addendum_min_days_before_closing"]),
        answer_min_days_before_closing=int(merged["answer_min_days_before_closing"]),
        questions_close_days_before_closing=int(merged["questions_close_days_before_closing"]),
        bid_validity_days=int(merged["bid_validity_days"]),
        extend_deadline_if_late_addendum=bool(merged["extend_deadline_if_late_addendum"]),
        acknowledgement=str(merged.get("acknowledgement", "per_addendum")),
        public_notice_of_changes=bool(merged.get("public_notice_of_changes", False)),
        source=str(merged.get("source", "")),
        statute_reference=merged.get("statute_reference"),
        confidence=str(merged.get("confidence", "M")),
    )

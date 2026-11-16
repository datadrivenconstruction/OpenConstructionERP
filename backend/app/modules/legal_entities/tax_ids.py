# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Which tax identifiers a company carries, per country, and whether a value looks right.

The country data (``core/country_data/entity_tax_ids.json``) says which schemes
a country uses (a German company: VAT id and tax number; a US company: EIN; a
Canadian one: business number), what each looks like, and which the country's
invoice rules require of a seller. Core never names a country itself. A
country the file does not list gets one free ``other`` field and no check.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).resolve().parents[2] / "core" / "country_data" / "entity_tax_ids.json"

#: The scheme of the one free field a country without data gets.
OTHER_SCHEME = "other"


@dataclass(frozen=True)
class TaxScheme:
    """One kind of tax identifier a country issues to companies."""

    scheme: str
    pattern: str | None
    example: str
    mandatory_on_invoice: bool
    legal_reference: str = ""

    def matches(self, value: str) -> bool:
        """Whether *value* has the expected shape; a scheme without a pattern accepts anything."""
        if not self.pattern:
            return True
        return re.match(self.pattern, normalise(value)) is not None


def normalise(value: str) -> str:
    """The value as compared: uppercased, spaces removed."""
    return re.sub(r"\s+", "", value or "").upper()


@lru_cache(maxsize=1)
def _countries() -> dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8")).get("countries", {})


def schemes_for(country_code: str | None) -> list[TaxScheme]:
    """The schemes a company registered in *country_code* carries, in display order."""
    rows = _countries().get((country_code or "").upper(), {}).get("schemes") or []
    if not rows:
        return [TaxScheme(scheme=OTHER_SCHEME, pattern=None, example="", mandatory_on_invoice=False)]
    return [
        TaxScheme(
            scheme=r["scheme"],
            pattern=r.get("pattern"),
            example=r.get("example", ""),
            mandatory_on_invoice=bool(r.get("mandatory_on_invoice")),
            legal_reference=r.get("legal_reference", ""),
        )
        for r in rows
    ]


def value_of(tax_ids: list[dict[str, Any]] | None, scheme: str) -> str:
    """The value stored for *scheme*, or an empty string."""
    for row in tax_ids or []:
        if isinstance(row, dict) and row.get("scheme") == scheme:
            return str(row.get("value") or "").strip()
    return ""


def clean(tax_ids: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Drop blank rows and repeated schemes, keep the first value per scheme, trimmed."""
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for row in tax_ids or []:
        if not isinstance(row, dict):
            continue
        scheme = str(row.get("scheme") or "").strip().lower()
        value = str(row.get("value") or "").strip()
        if not scheme or not value or scheme in seen:
            continue
        seen.add(scheme)
        out.append({"scheme": scheme, "value": value})
    return out


def primary_tax_id(country_code: str | None, tax_ids: list[dict[str, Any]] | None, legacy: str | None = None) -> str:
    """The identifier to show in one column: the country's first scheme that has a value."""
    for scheme in schemes_for(country_code):
        found = value_of(tax_ids, scheme.scheme)
        if found:
            return found
    for row in clean(tax_ids):
        return row["value"]
    return (legacy or "").strip()

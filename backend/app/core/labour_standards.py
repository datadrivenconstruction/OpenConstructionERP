# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Statutory labour facts per country, as sourced and effective-dated data.

Working hours, leave entitlements, minimum wages and the general social
insurance rates are national facts, so they live in
``country_data/labour_standards.json`` rather than in the code or a seed that
reads them. Every row carries its value, unit, effective window, source, URL,
confidence and whether it still needs an expert's review.

Two accessors, on purpose:

* :func:`standard` returns whatever row is in force, reviewed or not, for a
  screen that shows the fact and lets a user correct it.
Rows are country-wide unless they carry an ``area_code`` and ``area_label``
(a US prevailing-wage area, a German Tarifgebiet, a South African bargaining
council area). Lookup with ``area`` tries the exact area first and falls back
to the country-level row.

* :func:`hard_standard` returns only a row that does not need review, for any
  rule that enforces or derives something. A fact the research could not
  confirm can therefore be shown but never enforced.

Pure and stdlib-only, like :mod:`app.core.holiday_observances`.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATA_PATH = Path(__file__).parent / "country_data" / "labour_standards.json"

CONFIDENCE_LEVELS = frozenset({"H", "M", "L"})

_REQUIRED = (
    "country",
    "key",
    "value",
    "unit",
    "effective_from",
    "effective_to",
    "source",
    "source_url",
    "confidence",
    "needs_expert_review",
)


@dataclass(frozen=True)
class LabourStandard:
    """One statutory labour fact for one country over one effective window."""

    country: str
    key: str
    value: Decimal
    unit: str
    effective_from: date
    effective_to: date | None
    source: str
    source_url: str
    confidence: str
    needs_expert_review: bool
    note: str = ""
    area_code: str = ""
    area_label: str = ""

    def in_force(self, on: date) -> bool:
        """Whether the row applies on ``on``; the end date is inclusive."""
        return self.effective_from <= on and (self.effective_to is None or on <= self.effective_to)


def _iso(raw: Any, where: str, field: str) -> date:
    if not isinstance(raw, str):
        raise ValueError(f"{where}: {field} must be an ISO date string")
    day = date.fromisoformat(raw)
    if day.isoformat() != raw:
        raise ValueError(f"{where}: {field} {raw!r} is not an ISO date")
    return day


def parse_standards(rows: Iterable[Mapping[str, Any]]) -> tuple[LabourStandard, ...]:
    """Validate raw rows into :class:`LabourStandard` objects.

    Raises:
        ValueError: on a missing field, a non-numeric value, a non-https
            source, an unknown confidence, a low-confidence row not flagged for
            review, an inverted window, or two windows of one country and key
            that overlap.
    """
    parsed: list[LabourStandard] = []
    for index, row in enumerate(rows):
        where = f"labour standard #{index}"
        if not isinstance(row, Mapping):
            raise ValueError(f"{where}: not an object")
        missing = [k for k in _REQUIRED if k not in row]
        if missing:
            raise ValueError(f"{where}: missing {missing}")
        country = str(row["country"]).strip().upper()
        if len(country) != 2 or not country.isalpha():
            raise ValueError(f"{where}: country {row['country']!r} is not ISO 3166-1 alpha-2")
        try:
            value = Decimal(str(row["value"]))
        except InvalidOperation as exc:
            raise ValueError(f"{where}: value {row['value']!r} is not a number") from exc
        if not value.is_finite():
            raise ValueError(f"{where}: value must be finite")
        start = _iso(row["effective_from"], where, "effective_from")
        end = None if row["effective_to"] is None else _iso(row["effective_to"], where, "effective_to")
        if end is not None and end < start:
            raise ValueError(f"{where}: effective_to precedes effective_from")
        source_url = str(row["source_url"]).strip()
        if not source_url.startswith("https://"):
            raise ValueError(f"{where}: source_url must be an https URL")
        confidence = str(row["confidence"]).strip()
        if confidence not in CONFIDENCE_LEVELS:
            raise ValueError(f"{where}: confidence must be one of {sorted(CONFIDENCE_LEVELS)}")
        review = row["needs_expert_review"]
        if not isinstance(review, bool):
            raise ValueError(f"{where}: needs_expert_review must be a boolean")
        if confidence == "L" and not review:
            raise ValueError(f"{where}: a low-confidence fact must be flagged needs_expert_review")
        area_code = str(row.get("area_code") or "").strip()
        area_label = str(row.get("area_label") or "").strip()
        if bool(area_code) != bool(area_label):
            raise ValueError(f"{where}: area_code and area_label must be given together")
        key = str(row["key"]).strip()
        unit = str(row["unit"]).strip()
        source = str(row["source"]).strip()
        if not key or not unit or not source:
            raise ValueError(f"{where}: key, unit and source must be named")
        parsed.append(
            LabourStandard(
                country=country,
                key=key,
                value=value,
                unit=unit,
                effective_from=start,
                effective_to=end,
                source=source,
                source_url=source_url,
                confidence=confidence,
                needs_expert_review=review,
                note=str(row.get("note", "")),
                area_code=area_code,
                area_label=area_label,
            )
        )

    by_key: dict[tuple[str, str, str], list[LabourStandard]] = {}
    for item in parsed:
        by_key.setdefault((item.country, item.key, item.area_code), []).append(item)
    for (country, key, area), windows in by_key.items():
        if area and (country, key, "") not in by_key and not all(w.note.strip() for w in windows):
            raise ValueError(
                f"labour standard {country}/{key}/{area}: an area row needs a country-level row "
                "for the same key, or a note saying why there is none"
            )
        windows.sort(key=lambda w: w.effective_from)
        for earlier, later in zip(windows, windows[1:], strict=False):
            if earlier.effective_to is None or earlier.effective_to >= later.effective_from:
                where = f"{country}/{key}" + (f"/{area}" if area else "")
                raise ValueError(f"labour standard {where}: effective windows overlap")
    return tuple(parsed)


@lru_cache(maxsize=1)
def load_standards() -> tuple[LabourStandard, ...]:
    """Every shipped labour standard, validated. Raises on a malformed file."""
    rows = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("labour_standards.json must hold a list")
    return parse_standards(rows)


def standard(country: str, key: str, on: date, area: str | None = None) -> LabourStandard | None:
    """The row in force for ``country`` and ``key`` on ``on``, reviewed or not.

    With ``area`` the exact area row wins; without one, or when the area has no
    row in force, the country-level row answers.
    """
    code = (country or "").strip().upper()
    wanted = (area or "").strip()
    rows = [r for r in load_standards() if r.country == code and r.key == key and r.in_force(on)]
    if wanted:
        for row in rows:
            if row.area_code == wanted:
                return row
    for row in rows:
        if not row.area_code:
            return row
    return None


def areas(country: str) -> tuple[tuple[str, str], ...]:
    """Sorted ``(area_code, area_label)`` pairs the catalogue holds for ``country``."""
    code = (country or "").strip().upper()
    return tuple(sorted({(r.area_code, r.area_label) for r in load_standards() if r.country == code and r.area_code}))


def hard_standard(country: str, key: str, on: date, area: str | None = None) -> LabourStandard | None:
    """As :func:`standard`, but ``None`` for a row that still needs expert review.

    The accessor every rule that enforces or derives a number must use.
    """
    row = standard(country, key, on, area)
    return None if row is None or row.needs_expert_review else row


def countries() -> frozenset[str]:
    """The countries the catalogue holds at least one row for."""
    return frozenset(row.country for row in load_standards())

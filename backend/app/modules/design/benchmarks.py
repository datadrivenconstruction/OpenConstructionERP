"""Unit-rate benchmarks (R7 data) as ranges: per cost group, per basis, with their sources.

Nothing is filled in here: a group without a sourced row with low, mid and high is reported as
missing, and a total built from the groups that exist says which ones are absent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "benchmarks"
# First digit of a DIN 276 cost group -> benchmark group that covers it.
GROUP_OF_PREFIX = {"2": "200", "3": "300+400", "4": "300+400", "5": "500", "7": "700"}


@dataclass(frozen=True)
class Band:
    cost_group: str
    basis: str
    unit: str
    low: Decimal
    mid: Decimal
    high: Decimal
    price_level_year: int
    vat_included: bool | None
    source_url: str
    publisher: str
    published: str
    derived: bool
    published_basis: str | None = None

    def times(self, quantity: Decimal) -> tuple[Decimal, Decimal, Decimal]:
        return self.low * quantity, self.mid * quantity, self.high * quantity

    def source(self) -> dict:
        return {
            "source_url": self.source_url,
            "publisher": self.publisher,
            "published": self.published,
            "price_level_year": self.price_level_year,
            "derived": self.derived,
            "published_basis": self.published_basis,
            "vat_included": self.vat_included,
        }


@lru_cache(maxsize=8)
def _doc(country: str, use: str) -> dict | None:
    for f in sorted(DATA.glob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        if doc.get("country") == country and doc.get("use") == use:
            return doc
    return None


def available(country: str, use: str) -> bool:
    return _doc(country, use) is not None


def currency(country: str, use: str) -> str | None:
    """Currency of the benchmark file, so a range is never shown without the unit it is in."""
    doc = _doc(country, use)
    return doc.get("currency") if doc else None


def band(country: str, use: str, cost_group: str, basis: str) -> Band | None:
    """The newest row of the group with all three of low, mid and high; ``None`` if there is none."""
    doc = _doc(country, use)
    if doc is None:
        return None
    best = None
    for r in doc["rows"]:
        if r["cost_group"] != cost_group or r["basis"] != basis:
            continue
        if any(r[k] is None for k in ("low", "mid", "high")):
            continue
        if best is None or r["price_level_year"] >= best["price_level_year"]:
            best = r
    if best is None:
        return None
    return Band(
        cost_group,
        basis,
        best["unit"],
        Decimal(str(best["low"])),
        Decimal(str(best["mid"])),
        Decimal(str(best["high"])),
        best["price_level_year"],
        best["vat_included"],
        best["source_url"],
        best["publisher"],
        best["published"],
        bool(best.get("derived")),
        best.get("published_basis"),
    )


def unused(country: str, use: str, used_urls: set[str]) -> list[dict]:
    """Sources in the data file that no range group reads, each with why (reason codes, stable for the UI)."""
    doc = _doc(country, use)
    out: dict[str, dict] = {}
    for r in (doc or {}).get("rows", []):
        url = r["source_url"]
        if url in used_urls:
            continue
        if r["basis"] != "WFL":
            reason = "other_basis"
        elif any(r[k] is None for k in ("low", "mid", "high")):
            reason = "no_range"
        else:
            reason = "not_selected"
        e = out.setdefault(
            url,
            {
                "source_url": url,
                "publisher": r["publisher"],
                "published": r["published"],
                "price_level_year": r["price_level_year"],
                "vat_included": r["vat_included"],
                "reasons": [],
            },
        )
        e["price_level_year"] = max(e["price_level_year"], r["price_level_year"])
        if reason not in e["reasons"]:
            e["reasons"].append(reason)
    return list(out.values())


def group_for_din276(code: str) -> str | None:
    """Benchmark group of a DIN 276 cost group code such as ``331`` (None: no benchmark exists for it)."""
    return GROUP_OF_PREFIX.get(code[:1])

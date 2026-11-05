"""Market data for the customer offer, read from ``core/country_data/offer_packs.json``.

Nothing country specific lives in the module code: tax rates by date, reverse-charge notes,
default texts, deposit caps and cancellation notices all come from the pack that matches the
project's country (and subdivision). A project with no pack gets the neutral ``_default`` block.
Every block is research marked ``verified=false``; rules built on it warn and never block.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

_PATH = Path(__file__).resolve().parents[2] / "core" / "country_data" / "offer_packs.json"

TEXT_KINDS: tuple[str, ...] = (
    "intro",
    "payment_terms",
    "validity",
    "conditions",
    "warranty",
    "closing",
    "legal_notice",
)


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    with _PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def reload() -> None:
    """Drop the cached file (tests and hot edits)."""
    _data.cache_clear()


def pack_key(country_code: str | None, subdivision_code: str | None = None) -> str | None:
    """The pack block that serves a project, or ``None`` when no pack does.

    A subdivision pack (``US-CA``) wins over its country; a pack lists the markets it serves, so
    Austria and Switzerland read the German block.
    """
    country = (country_code or "").strip().upper()
    sub = (subdivision_code or "").strip().upper()
    full = sub if "-" in sub else (f"{country}-{sub}" if country and sub else "")
    packs = _data().get("packs", {})
    for candidate in (full, country):
        if not candidate:
            continue
        for key, block in packs.items():
            if candidate in block.get("markets", []):
                return key
    return None


def pack_for(country_code: str | None, subdivision_code: str | None = None) -> dict[str, Any]:
    """The block for a project; the neutral default when the market has none."""
    key = pack_key(country_code, subdivision_code)
    block = _data()["packs"][key] if key else _data()["_default"]
    return {**block, "key": key}


def _lang(locale: str | None) -> str:
    return (locale or "en").replace("_", "-").split("-")[0].strip().lower() or "en"


def pick_language(variants: dict[str, str] | None, locale: str | None) -> str:
    """The variant in the document language, else English, else the first one written."""
    if not variants:
        return ""
    lang = _lang(locale)
    if variants.get(lang):
        return variants[lang]
    if variants.get("en"):
        return variants["en"]
    return next((v for v in variants.values() if v), "")


def title_for(pack: dict[str, Any], locale: str | None, *, alternate: bool = False) -> str:
    """Document title in the document language ('Angebot', 'Devis', 'Quotation', 'Proposal')."""
    titles = (pack.get("alternate_title") if alternate else None) or pack.get("titles") or {"en": "Offer"}
    return pick_language(titles, locale) or "Offer"


def default_text(pack: dict[str, Any], kind: str, locale: str | None) -> str:
    """The pack's default body for a text kind in the document language."""
    return pick_language((pack.get("texts") or {}).get(kind), locale)


def tax_rates(pack: dict[str, Any], on: date | None = None) -> list[dict[str, Any]]:
    """Rates in force on a date, as written in the pack (strings, never floats)."""
    day = (on or date.today()).isoformat()
    return [
        r
        for r in (pack.get("tax") or {}).get("rates", [])
        if (r.get("from") or "0000-00-00") <= day and (not r.get("to") or day <= r["to"])
    ]


def standard_rate(pack: dict[str, Any], on: date | None = None) -> Decimal | None:
    """The first dated rate in force, which the pack lists as its standard rate."""
    rates = tax_rates(pack, on)
    return Decimal(str(rates[0]["rate"])) if rates else None


def tax_label(pack: dict[str, Any], rate: Decimal) -> str:
    """The country label for a rate ('MwSt.', 'VAT', 'TVA'), empty when the pack names none."""
    for r in (pack.get("tax") or {}).get("rates", []):
        if Decimal(str(r["rate"])) == rate:
            return str(r.get("label") or "")
    return ""


def reverse_charge(pack: dict[str, Any]) -> dict[str, Any] | None:
    return (pack.get("tax") or {}).get("reverse_charge")


def tax_modes(pack: dict[str, Any]) -> list[str]:
    """Modes the selector offers; a market without reverse charge only has 'standard'."""
    modes = ["standard"]
    if reverse_charge(pack):
        modes.append("reverse_charge")
    if tax_rates(pack):
        modes.append("exempt")
    return modes


def has_consumer_rule(pack: dict[str, Any]) -> bool:
    """Whether the customer-kind switch means anything in this market."""
    consumer = pack.get("consumer") or {}
    return bool(consumer.get("gross_total") or consumer.get("cancellation_notice")) or any(
        r.get("consumer_only") for r in pack.get("rules", [])
    )


def rule_ids(pack: dict[str, Any]) -> set[str]:
    return {str(r["id"]) for r in pack.get("rules", [])}


def rule(pack: dict[str, Any], rule_id: str) -> dict[str, Any] | None:
    return next((r for r in pack.get("rules", []) if r["id"] == rule_id), None)


def address_window(pack: dict[str, Any]) -> dict[str, Any]:
    """Window geometry for the pack; the neutral block falls back to DIN 5008 form B."""
    return pack.get("address_window") or _data()["_default"]["address_window"]


def summary(pack: dict[str, Any], locale: str | None) -> dict[str, Any]:
    """What the page needs to know about a market: titles, caps, modes, defaults."""
    return {
        "pack_key": pack.get("key"),
        "pack_name": pack.get("name") or "",
        "country": str(pack.get("key") or "").split("-")[0],
        "currency": pack.get("currency") or "",
        "paper": pack.get("paper") or "A4",
        "validity_days": int(pack.get("validity_days") or 30),
        "title": title_for(pack, locale),
        "alternate_title": title_for(pack, locale, alternate=True) if pack.get("alternate_title") else None,
        "tax_modes": tax_modes(pack),
        "tax_rates": [{k: r.get(k) for k in ("code", "rate", "label", "source")} for r in tax_rates(pack)],
        "consumer_rule": has_consumer_rule(pack),
        "licence_field": pack.get("licence_field"),
        "rule_ids": sorted(rule_ids(pack)),
        "address_window": address_window(pack),
        "verified": bool(pack.get("verified")),
    }

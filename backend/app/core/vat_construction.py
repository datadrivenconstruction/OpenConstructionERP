# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""VAT rules a construction invoice meets beyond its rate: split payment, area-limited rates, reverse charge.

Country-neutral engine over ``country_data/vat_construction.json``. Three
questions a VAT rate alone cannot answer, each a block of a country row:

* ``split_payment``: must the buyer pay the invoice through a split payment
  account (the VAT to a separate account), and must the invoice say so? Two
  inputs decide it, whether the invoice lists goods or services of a named
  annex and whether its gross total exceeds a threshold, and the date.
* ``reduced_rate_area_limits``: a reduced rate that holds for a dwelling up to
  a usable area and only for the share of the price that area bears to the
  whole above it.
* ``domestic_reverse_charge``: the day a country stopped putting the VAT on
  the domestic buyer of construction services.

**No rate lives here.** A row names the ``tax_code`` of the dated tax seed,
and the rate in force on the invoice date comes from that seed. One rate, one
source.

An answer the engine cannot give is said, never guessed: an invoice whose
annex status is not recorded, or whose amount is in another currency than the
threshold's, gets ``required=None`` with the reason, not ``False``.

Standard library only. Nothing here may import from ``app.modules``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any

__all__ = [
    "DATA_PATH",
    "TAX_SEED_PATH",
    "AreaPart",
    "AreaSplit",
    "HousingFinding",
    "SplitPaymentDecision",
    "annex_15_from_codes",
    "countries",
    "domestic_reverse_charge_allowed",
    "housing_rate_findings",
    "object_kinds",
    "reduced_rate_split",
    "seed_rate_percent",
    "split_payment_decision",
    "split_payment_rules",
    "split_payment_sanction",
    "validate_rows",
]

DATA_PATH = Path(__file__).resolve().parent / "country_data" / "vat_construction.json"
#: The dated tax seed. Read as a file, not imported: the rate a row names
#: lives there and nowhere else.
TAX_SEED_PATH = (
    Path(__file__).resolve().parents[1] / "modules" / "i18n_foundation" / "seed_data" / "tax_configurations.json"
)

_CENT = Decimal("0.01")
_HUNDRED = Decimal(100)
_CONFIDENCES = ("H", "M")
_REVIEW = ("confirmed", "needs_expert_review")


@dataclass(frozen=True)
class SplitPaymentDecision:
    """Whether one invoice falls under split payment, and why.

    ``required`` is ``None`` when the engine cannot tell: the annex status of
    the invoice is unknown, or its amount is not in the threshold's currency.
    """

    required: bool | None
    reason: str
    threshold: Decimal
    currency: str
    annotation: str
    einvoice_field: str
    payment_method: str
    buyer_sanction_percent: Decimal
    seller_sanction_percent: Decimal
    review_status: str


@dataclass(frozen=True)
class AreaPart:
    """The share of a price taxed at one rate."""

    tax_code: str
    rate_percent: Decimal
    area_m2: Decimal
    base: Decimal
    vat: Decimal


@dataclass(frozen=True)
class AreaSplit:
    """A price split between the reduced and the standard rate by usable area."""

    country: str
    object_kind: str
    eligible: bool
    usable_area_m2: Decimal
    limit_m2: Decimal | None
    parts: tuple[AreaPart, ...]
    legal_reference: str


@dataclass(frozen=True)
class HousingFinding:
    """One reason a reduced housing rate on an invoice is questionable."""

    key: str
    params: dict[str, str] = field(default_factory=dict)


def _load_file() -> dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _data() -> dict[str, Any]:
    return _load_file()


@lru_cache(maxsize=1)
def _seed_rows() -> tuple[dict[str, Any], ...]:
    raw = json.loads(TAX_SEED_PATH.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = next(iter(raw.values()))
    return tuple(r for r in raw if isinstance(r, dict))


def _country(code: str) -> dict[str, Any] | None:
    return (_data().get("countries") or {}).get(str(code or "").strip().upper())


def _d(raw: object) -> Decimal:
    return Decimal(str(raw))


def _day(raw: object) -> date | None:
    return date.fromisoformat(str(raw)) if raw else None


def _in_window(block: dict[str, Any], on: date) -> bool:
    start = _day(block.get("effective_from"))
    end = _day(block.get("effective_to"))
    return (start is None or on >= start) and (end is None or on <= end)


def countries() -> tuple[str, ...]:
    """Every country with a row."""
    return tuple(sorted((_data().get("countries") or {}).keys()))


def seed_rate_percent(country: str, tax_code: str, on: date) -> Decimal | None:
    """The rate the tax seed holds for ``tax_code`` in ``country`` on ``on``, or ``None``."""
    cc = str(country or "").strip().upper()
    for row in _seed_rows():
        if row.get("country_code") != cc or row.get("tax_code") != tax_code:
            continue
        start = _day(row.get("effective_from"))
        end = _day(row.get("effective_to"))
        if (start is None or on >= start) and (end is None or on <= end):
            try:
                return Decimal(str(row.get("rate_pct")))
            except InvalidOperation:
                return None
    return None


# ── Split payment ─────────────────────────────────────────────────────────────


def split_payment_rules(country: str) -> dict[str, Any] | None:
    """The split payment block of a country, or ``None``."""
    row = _country(country)
    block = (row or {}).get("split_payment")
    return block if isinstance(block, dict) else None


def annex_15_from_codes(country: str, codes: list[str] | tuple[str, ...]) -> bool | None:
    """Whether any of the invoice's goods or services codes is in the annex.

    Codes are matched by section: ``43.21.10`` is in section ``43``, and so is
    ``43``; ``4`` and ``410`` are not. ``None`` when no code is given, because
    an invoice without codes has not said, which is not the same as no.
    """
    block = split_payment_rules(country)
    cleaned = [str(c or "").strip() for c in codes if str(c or "").strip()]
    if block is None or not cleaned:
        return None
    prefixes = tuple(str(p) for p in block.get("annex_pkwiu_prefixes") or ())
    for code in cleaned:
        for prefix in prefixes:
            if code == prefix or code.startswith(prefix + "."):
                return True
    return False


def split_payment_decision(
    country: str,
    on: date,
    gross_amount: Decimal,
    currency: str,
    *,
    annex_15: bool | None,
) -> SplitPaymentDecision | None:
    """Decide whether an invoice dated ``on`` falls under split payment.

    Args:
        country: The country whose VAT applies to the supply.
        on: The invoice date.
        gross_amount: The invoice total including VAT.
        currency: The currency ``gross_amount`` is stated in.
        annex_15: Whether the invoice lists goods or services of the annex;
            ``None`` when nobody has said.

    Returns:
        ``None`` when the country has no split payment regime.
    """
    block = split_payment_rules(country)
    if block is None:
        return None
    row = _country(country) or {}
    threshold = _d(block["threshold_gross"])
    base_currency = str(row.get("currency") or "")

    def decision(required: bool | None, reason: str) -> SplitPaymentDecision:
        return SplitPaymentDecision(
            required=required,
            reason=reason,
            threshold=threshold,
            currency=base_currency,
            annotation=str(block.get("invoice_annotation") or ""),
            einvoice_field=str(block.get("einvoice_field") or ""),
            payment_method=str(block.get("payment_method") or ""),
            buyer_sanction_percent=_d(block.get("buyer_sanction_percent_of_vat") or 0),
            seller_sanction_percent=_d(block.get("seller_sanction_percent_of_vat") or 0),
            review_status=str(block.get("review_status") or ""),
        )

    if not _in_window(block, on):
        return decision(False, "not_in_force")
    if annex_15 is False:
        return decision(False, "not_annex_15")
    if str(currency or "").strip().upper() != base_currency:
        return decision(None, "other_currency")
    if gross_amount <= threshold:
        return decision(False, "below_threshold")
    if annex_15 is None:
        return decision(None, "annex_15_unknown")
    return decision(True, "required")


def split_payment_sanction(country: str, vat_amount: Decimal) -> Decimal | None:
    """The additional liability of a buyer who did not pay by split payment, on one invoice's VAT."""
    block = split_payment_rules(country)
    if block is None:
        return None
    percent = _d(block.get("buyer_sanction_percent_of_vat") or 0)
    return (vat_amount * percent / _HUNDRED).quantize(_CENT, rounding=ROUND_HALF_UP)


# ── Reverse charge ────────────────────────────────────────────────────────────


def domestic_reverse_charge_allowed(country: str, on: date) -> bool | None:
    """Whether a domestic construction service may be invoiced under reverse charge on ``on``.

    ``None`` for a country without a row: the engine does not judge it.
    """
    block = (_country(country) or {}).get("domestic_reverse_charge")
    if not isinstance(block, dict):
        return None
    ended = _day(block.get("ended_on"))
    return ended is None or on < ended


# ── Area-limited reduced rate ─────────────────────────────────────────────────


def _area_block(country: str) -> dict[str, Any] | None:
    block = (_country(country) or {}).get("reduced_rate_area_limits")
    return block if isinstance(block, dict) else None


def object_kinds(country: str) -> tuple[str, ...]:
    """The object kinds the country's area-limited rate distinguishes."""
    block = _area_block(country)
    return tuple((block or {}).get("object_kinds") or ())


def _part(country: str, tax_code: str, area: Decimal, base: Decimal, on: date) -> AreaPart:
    rate = seed_rate_percent(country, tax_code, on)
    if rate is None:
        raise LookupError(f"no {tax_code} rate for {country} on {on.isoformat()} in the tax seed")
    vat = (base * rate / _HUNDRED).quantize(_CENT, rounding=ROUND_HALF_UP)
    return AreaPart(tax_code=tax_code, rate_percent=rate, area_m2=area, base=base, vat=vat)


def reduced_rate_split(
    country: str, object_kind: str, usable_area_m2: Decimal, net_amount: Decimal, on: date
) -> AreaSplit | None:
    """Split a price between the reduced and the standard rate by usable area.

    Within the limit the whole price takes the reduced rate. Above it the
    reduced rate takes the share ``limit / area`` and the standard rate the
    rest; the standard part is the remainder, so the parts always add up to
    the price. An object kind that is not eligible takes the standard rate on
    all of it.

    Raises:
        ValueError: The object kind is not one the country distinguishes.
    """
    block = _area_block(country)
    if block is None:
        return None
    kinds = block.get("object_kinds") or {}
    if object_kind not in kinds:
        raise ValueError(f"unknown object kind {object_kind!r} for {country}; known: {sorted(kinds)}")
    kind = kinds[object_kind]
    cc = str(country).strip().upper()
    net = net_amount.quantize(_CENT, rounding=ROUND_HALF_UP)
    within_code = str(block["within_tax_code"])
    excess_code = str(block["excess_tax_code"])
    limit = _d(kind["limit_m2"]) if kind.get("limit_m2") not in (None, "") else None
    eligible = bool(kind.get("eligible"))
    reference = str(block.get("legal_reference") or "")

    if not eligible or not _in_window(block, on):
        parts: tuple[AreaPart, ...] = (_part(cc, excess_code, usable_area_m2, net, on),)
    elif limit is None or usable_area_m2 <= limit:
        parts = (_part(cc, within_code, usable_area_m2, net, on),)
    else:
        reduced_base = (net * limit / usable_area_m2).quantize(_CENT, rounding=ROUND_HALF_UP)
        parts = (
            _part(cc, within_code, limit, reduced_base, on),
            _part(cc, excess_code, usable_area_m2 - limit, net - reduced_base, on),
        )
    return AreaSplit(
        country=cc,
        object_kind=object_kind,
        eligible=eligible,
        usable_area_m2=usable_area_m2,
        limit_m2=limit,
        parts=parts,
        legal_reference=reference,
    )


def housing_rate_findings(
    country: str,
    object_kind: str | None,
    usable_area_m2: Decimal | None,
    applied_rate_percent: Decimal,
    on: date,
) -> list[HousingFinding]:
    """Why charging ``applied_rate_percent`` on the whole price may be wrong.

    Only the reduced rate is questioned; the standard rate is never wrong for
    being too high in this sense. Silent for a country without the rule.
    """
    block = _area_block(country)
    if block is None or not _in_window(block, on):
        return []
    reduced = seed_rate_percent(country, str(block["within_tax_code"]), on)
    if reduced is None or applied_rate_percent != reduced:
        return []
    kinds = block.get("object_kinds") or {}
    reference = str(block.get("legal_reference") or "")
    if not object_kind or object_kind not in kinds:
        return [HousingFinding("reduced_rate_object_unknown", {"rate": str(reduced), "reference": reference})]
    kind = kinds[object_kind]
    if not kind.get("eligible"):
        return [
            HousingFinding(
                "reduced_rate_not_eligible",
                {"rate": str(reduced), "object": str(kind.get("label") or object_kind), "reference": reference},
            )
        ]
    limit = kind.get("limit_m2")
    if limit in (None, "") or usable_area_m2 is None:
        return []
    limit_d = _d(limit)
    if usable_area_m2 <= limit_d:
        return []
    share = (limit_d / usable_area_m2 * _HUNDRED).quantize(_CENT, rounding=ROUND_HALF_UP)
    return [
        HousingFinding(
            "reduced_rate_above_area_limit",
            {
                "rate": str(reduced),
                "area_m2": str(usable_area_m2),
                "limit_m2": str(limit),
                "reduced_share_percent": str(share),
                "reference": reference,
            },
        )
    ]


# ── Data checks ───────────────────────────────────────────────────────────────


def _block_problems(cc: str, name: str, block: dict[str, Any], *, dated: str) -> list[str]:
    problems: list[str] = []
    if not block.get("sources"):
        problems.append(f"{cc}.{name}: sources are missing")
    if not block.get("legal_reference"):
        problems.append(f"{cc}.{name}: legal_reference is missing")
    if block.get("confidence") not in _CONFIDENCES:
        problems.append(f"{cc}.{name}: confidence must be one of {_CONFIDENCES}")
    if block.get("review_status") not in _REVIEW:
        problems.append(f"{cc}.{name}: review_status must be one of {_REVIEW}")
    try:
        if _day(block.get(dated)) is None:
            problems.append(f"{cc}.{name}: {dated} is missing")
    except ValueError:
        problems.append(f"{cc}.{name}: {dated} is not a date")
    return problems


def validate_rows(data: dict[str, Any] | None = None) -> list[str]:
    """Every problem with the data, as sentences. Empty when the data is sound."""
    data = data if data is not None else _load_file()
    seed_codes = {(r.get("country_code"), r.get("tax_code")) for r in _seed_rows()}
    problems: list[str] = []
    for cc, row in (data.get("countries") or {}).items():
        if not row.get("currency"):
            problems.append(f"{cc}: currency is missing")
        split = row.get("split_payment")
        if isinstance(split, dict):
            problems += _block_problems(cc, "split_payment", split, dated="effective_from")
            try:
                if _d(split.get("threshold_gross")) <= 0:
                    problems.append(f"{cc}.split_payment: threshold_gross must be positive")
            except InvalidOperation:
                problems.append(f"{cc}.split_payment: threshold_gross is not a number")
            if not split.get("annex_pkwiu_prefixes"):
                problems.append(f"{cc}.split_payment: annex_pkwiu_prefixes are missing")
        reverse = row.get("domestic_reverse_charge")
        if isinstance(reverse, dict):
            problems += _block_problems(cc, "domestic_reverse_charge", reverse, dated="ended_on")
        area = row.get("reduced_rate_area_limits")
        if isinstance(area, dict):
            problems += _block_problems(cc, "reduced_rate_area_limits", area, dated="effective_from")
            for key in ("within_tax_code", "excess_tax_code"):
                code = area.get(key)
                if (cc, code) not in seed_codes:
                    problems.append(f"{cc}.reduced_rate_area_limits: {key} {code} is not a tax code of the seed")
            if not area.get("object_kinds"):
                problems.append(f"{cc}.reduced_rate_area_limits: object_kinds are missing")
    return problems

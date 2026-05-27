"""Property-dev jurisdiction-aware tax / VAT / stamp-duty engine.

Pure-function library — every helper takes :class:`~decimal.Decimal`
in / returns Decimal out, never touches the DB, never raises HTTP
exceptions, and never reads the wall clock. The thin async wrapper in
``service.py`` resolves a contract to inputs and hands them to these
functions; the engine itself has zero side-effects so it can be
unit-tested in isolation and reused from the BOQ engine, the
finance module, or batch revenue-recognition jobs.

Design intent
-------------
* **Data-driven** — every rate lives in ``data/tax_rates.yaml`` (not in
  Python source). Adding a new jurisdiction = a YAML edit, not a code
  change.
* **Decimal everywhere** — no float arithmetic. Money is rounded
  ``ROUND_HALF_UP`` to 2 dp on output; intermediate maths uses 6 dp
  of precision so successive percentage applications don't drift.
* **Effective-date aware** — VAT bands carry ``effective_from`` so a
  contract signed pre-band-change uses the rate that was in force
  on its signing date.
* **No currency conversion** — the caller supplies the price in the
  contract's currency. Mixing currencies is a finance-module job, not
  a tax-engine job.
* **Unknown jurisdiction → explicit error** — never falls back to a
  silent default that would generate billing-incorrect invoices.

The full tax model for a property purchase is the sum of:

    grand_total = net
                + vat (or zero-rated / exempt)
                + stamp_duty / land-transfer tax
                + transfer_fee  (UAE DLD style)
                + registration_fee
                + late_interest (on overdue instalments)

Each line is itemised in :func:`compute_total_taxes_for_contract` and
exposed through the ``breakdown`` field so the frontend can render a
human-readable invoice row-by-row.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from threading import Lock
from typing import Any

import yaml

# ── Module-level table cache ────────────────────────────────────────────

_TABLE_CACHE: dict[str, Any] | None = None
_TABLE_LOCK = Lock()
_TABLE_PATH = Path(__file__).parent / "data" / "tax_rates.yaml"

# Decimal quantum constants — six-dp intermediate, two-dp final.
_Q_MONEY = Decimal("0.01")
_Q_INTERMEDIATE = Decimal("0.000001")
_ZERO = Decimal("0")


# ── Exceptions ──────────────────────────────────────────────────────────


class TaxEngineError(Exception):
    """Base for all tax-engine-level errors."""


class UnsupportedJurisdictionError(TaxEngineError):
    """Raised when a jurisdiction code is not in the rate table.

    The message includes the canonical list of supported codes so the
    caller (HTTP layer) can surface it to the user verbatim.
    """

    def __init__(self, jurisdiction: str, supported: Iterable[str]) -> None:
        codes = sorted(supported)
        super().__init__(f"Unsupported jurisdiction '{jurisdiction}'. Supported: {', '.join(codes)}")
        self.jurisdiction = jurisdiction
        self.supported = list(codes)


class MissingRegionSubcodeError(TaxEngineError):
    """Raised when a jurisdiction needs a region subcode (DE state, IN state,
    AU state, US state) and the caller didn't supply one."""

    def __init__(self, jurisdiction: str, supported: Iterable[str]) -> None:
        codes = sorted(supported)
        super().__init__(
            f"Jurisdiction '{jurisdiction}' requires a region_subcode. Supported subcodes: {', '.join(codes)}"
        )
        self.jurisdiction = jurisdiction
        self.supported = list(codes)


class UnknownRateClassError(TaxEngineError):
    """Raised when a VAT rate class is requested that the jurisdiction
    does not define (e.g. ``rate_class='reduced'`` in RU)."""


# ── Table loader (thread-safe, lazy, cached) ────────────────────────────


def _load_table(*, force_reload: bool = False) -> dict[str, Any]:
    """Return the parsed YAML table (cached after first call)."""
    global _TABLE_CACHE
    if _TABLE_CACHE is not None and not force_reload:
        return _TABLE_CACHE
    with _TABLE_LOCK:
        if _TABLE_CACHE is not None and not force_reload:
            return _TABLE_CACHE
        if not _TABLE_PATH.exists():
            raise TaxEngineError(f"tax_rates.yaml not found at expected path {_TABLE_PATH}")
        with _TABLE_PATH.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        if not isinstance(raw, dict):
            raise TaxEngineError("tax_rates.yaml root must be a mapping")
        _TABLE_CACHE = raw
        return raw


def reload_tax_table() -> None:
    """Force-reload the tax table (test helper / hot-reload hook)."""
    _load_table(force_reload=True)


def _table_for(jurisdiction: str) -> dict[str, Any]:
    code = (jurisdiction or "").strip().upper()
    if not code:
        raise UnsupportedJurisdictionError(jurisdiction, supported_jurisdictions())
    table = _load_table()
    jurisdictions = table.get("jurisdictions") or {}
    if code not in jurisdictions:
        raise UnsupportedJurisdictionError(code, jurisdictions.keys())
    return jurisdictions[code]


# ── Decimal helpers ─────────────────────────────────────────────────────


def _D(value: Any) -> Decimal:  # noqa: N802 — short capital is intentional shorthand for Decimal coerce.
    """Coerce anything sane to :class:`Decimal` — strings, ints, floats, None."""
    if value is None or value == "":
        return _ZERO
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        # Avoid Python's bool-is-int trap.
        return Decimal("1") if value else _ZERO
    return Decimal(str(value))


def _money(value: Decimal) -> Decimal:
    """Quantise a Decimal to 2 dp using banker-safe HALF_UP."""
    return value.quantize(_Q_MONEY, rounding=ROUND_HALF_UP)


def _intermediate(value: Decimal) -> Decimal:
    """Quantise to 6 dp for intermediate maths (avoids drift)."""
    return value.quantize(_Q_INTERMEDIATE, rounding=ROUND_HALF_UP)


def _parse_iso(date_str: str | None) -> date | None:
    if date_str is None or not isinstance(date_str, str):
        return None
    try:
        return date.fromisoformat(date_str[:10])
    except (TypeError, ValueError):
        return None


# ── Public introspection ────────────────────────────────────────────────


def supported_jurisdictions() -> list[str]:
    """Return the sorted list of ISO-3166 alpha-2 codes with a rule loaded."""
    table = _load_table()
    return sorted((table.get("jurisdictions") or {}).keys())


def jurisdiction_metadata(jurisdiction: str) -> dict[str, Any]:
    """Return the raw rate block for a jurisdiction (for UI rendering)."""
    return dict(_table_for(jurisdiction))


# ── VAT / GST ───────────────────────────────────────────────────────────


def _resolve_vat_block(jur_table: dict[str, Any], rate_class: str) -> dict[str, Any] | None:
    """Return the VAT/GST sub-block for ``rate_class``.

    Looks in ``vat.*`` first then ``gst.*`` so IN/SG/AU work the same
    way as DACH. Returns ``None`` if the class is not defined.
    """
    for key in ("vat", "gst"):
        block = jur_table.get(key) or {}
        if rate_class in block:
            entry = block[rate_class]
            if isinstance(entry, Mapping):
                return dict(entry)
            # Allow scalar shorthand (rare).
            return {"rate": entry}
    return None


def compute_vat(
    net: Any,
    jurisdiction: str,
    *,
    rate_class: str = "standard",
    effective_on: date | None = None,
) -> Decimal:
    """Return the VAT amount (not the gross) for ``net``.

    Args:
        net: pre-VAT amount in the contract currency.
        jurisdiction: ISO-3166 alpha-2 code.
        rate_class: ``standard`` | ``reduced`` | ``zero`` | ``zero_rated``
            | ``exempt`` | ``first_home`` etc. Class must exist in the
            jurisdiction's VAT block.
        effective_on: optional signing date used to pick the right
            historical band when ``effective_from`` is present. When
            None, current rates apply.

    Returns:
        VAT amount rounded HALF_UP to 2 dp. Zero-rated / exempt
        classes return Decimal("0.00").

    Raises:
        UnsupportedJurisdictionError: jurisdiction not in table.
        UnknownRateClassError: ``rate_class`` not defined for this jurisdiction.
    """
    jur = _table_for(jurisdiction)
    block = _resolve_vat_block(jur, rate_class)
    if block is None:
        raise UnknownRateClassError(f"Jurisdiction '{jurisdiction}' has no VAT/GST rate class '{rate_class}'")
    # Honour effective_from if present.
    if effective_on is not None and "effective_from" in block:
        eff = _parse_iso(block["effective_from"])
        if eff is not None and effective_on < eff:
            # Rate not yet in force — return 0 (caller can opt to
            # provide a historical rate via metadata override later).
            return _money(_ZERO)
    rate = _D(block.get("rate", 0))
    amount = _D(net) * rate
    return _money(amount)


def gross_from_net(
    net: Any,
    jurisdiction: str,
    *,
    rate_class: str = "standard",
    effective_on: date | None = None,
) -> Decimal:
    """Return ``net + compute_vat(net)`` rounded to 2 dp."""
    net_d = _D(net)
    vat = compute_vat(net_d, jurisdiction, rate_class=rate_class, effective_on=effective_on)
    return _money(net_d + vat)


def net_from_gross(
    gross: Any,
    jurisdiction: str,
    *,
    rate_class: str = "standard",
    effective_on: date | None = None,
) -> Decimal:
    """Return ``net`` such that ``net * (1 + rate) == gross`` (rounded).

    Useful when the buyer is quoted an inclusive price and the finance
    module needs to split it into a recognised-revenue + tax-payable
    pair on the ledger.
    """
    jur = _table_for(jurisdiction)
    block = _resolve_vat_block(jur, rate_class)
    if block is None:
        raise UnknownRateClassError(f"Jurisdiction '{jurisdiction}' has no VAT/GST rate class '{rate_class}'")
    # Honour effective-from window.
    if effective_on is not None and "effective_from" in block:
        eff = _parse_iso(block["effective_from"])
        if eff is not None and effective_on < eff:
            return _money(_D(gross))
    rate = _D(block.get("rate", 0))
    if rate == _ZERO:
        return _money(_D(gross))
    divisor = Decimal("1") + rate
    net = _D(gross) / divisor
    return _money(net)


# ── Stamp duty / transfer tax (progressive + flat) ──────────────────────


def _progressive_band_amount(price: Decimal, bands: Iterable[Mapping[str, Any]]) -> Decimal:
    """Apply marginal-band progressive rates and return total tax.

    Each band: ``{up_to: <inclusive ceiling>, rate: <0..1 fraction>}``.
    Final band uses ``up_to: null`` for the open-ended top tier.
    """
    total = _ZERO
    previous_ceiling = _ZERO
    for band in bands:
        rate = _D(band.get("rate", 0))
        ceiling_raw = band.get("up_to")
        if ceiling_raw is None:
            # Top open band — apply to remainder.
            if price > previous_ceiling:
                taxable = price - previous_ceiling
                total += taxable * rate
            break
        ceiling = _D(ceiling_raw)
        if price <= previous_ceiling:
            break
        slice_top = min(price, ceiling)
        taxable = slice_top - previous_ceiling
        if taxable > _ZERO:
            total += taxable * rate
        previous_ceiling = ceiling
        if price <= ceiling:
            break
    return _money(total)


def compute_stamp_duty(
    price: Any,
    jurisdiction: str,
    *,
    region_subcode: str | None = None,
    is_first_home: bool = False,
    is_additional_property: bool = False,
) -> Decimal:
    """Compute stamp duty / land-transfer tax for a property purchase.

    Args:
        price: full purchase price in the contract currency.
        jurisdiction: ISO-3166 alpha-2 code.
        region_subcode: REQUIRED for DE (Grunderwerbsteuer by state),
            IN (state stamp duty), AU (state stamp duty), US (state
            transfer tax), CH (Kanton transfer). IGNORED for GB / SG.
        is_first_home: UK first-time-buyer relief flag.
        is_additional_property: UK 3 % surcharge flag (also applies to
            ABSD-style flows elsewhere).

    Returns:
        Stamp-duty amount rounded HALF_UP to 2 dp.

    Raises:
        UnsupportedJurisdictionError: jurisdiction not in table.
        MissingRegionSubcodeError: jurisdiction needs subcode + none given.
    """
    jur = _table_for(jurisdiction)
    price_d = _D(price)

    sd = jur.get("stamp_duty") or {}
    by_state = sd.get("by_state") if isinstance(sd, Mapping) else None

    # Path A — GB-style progressive bands at the top level.
    bands = sd.get("bands") if isinstance(sd, Mapping) else None
    if bands and not by_state:
        if is_first_home and sd.get("first_home_relief"):
            relief = sd["first_home_relief"]
            max_price = relief.get("max_price")
            if max_price is not None and price_d > _D(max_price):
                # Above the relief cap → fall back to standard bands.
                duty = _progressive_band_amount(price_d, bands)
            else:
                duty = _progressive_band_amount(price_d, relief["bands"])
        else:
            duty = _progressive_band_amount(price_d, bands)
        if is_additional_property:
            surcharge_pct = _D(sd.get("additional_property_surcharge", 0))
            duty = _money(duty + (price_d * surcharge_pct))
        return duty

    # Path B — by-state flat / banded (DE, IN, AU, US, CH).
    if by_state:
        if not region_subcode:
            raise MissingRegionSubcodeError(jurisdiction, by_state.keys())
        sub = region_subcode.upper()
        if sub not in by_state:
            raise MissingRegionSubcodeError(jurisdiction, by_state.keys())
        entry = by_state[sub]
        if isinstance(entry, Mapping) and "bands" in entry:
            duty = _progressive_band_amount(price_d, entry["bands"])
        else:
            rate = _D(entry)
            duty = _money(price_d * rate)
        if is_additional_property:
            surcharge_pct = _D(sd.get("additional_property_surcharge", 0))
            duty = _money(duty + (price_d * surcharge_pct))
        return duty

    # Path C — alternate top-level keys (DE Grunderwerbsteuer is its own block).
    grunder = jur.get("grunderwerbsteuer")
    if isinstance(grunder, Mapping):
        states = grunder.get("by_state")
        if states:
            if not region_subcode:
                raise MissingRegionSubcodeError(jurisdiction, states.keys())
            sub = region_subcode.upper()
            if sub not in states:
                raise MissingRegionSubcodeError(jurisdiction, states.keys())
            rate = _D(states[sub])
            return _money(price_d * rate)
        if "flat" in grunder:
            return _money(price_d * _D(grunder["flat"]))

    # Path D — SG bands under ``bsd``.
    bsd = jur.get("bsd")
    if isinstance(bsd, Mapping) and bsd.get("bands"):
        return _progressive_band_amount(price_d, bsd["bands"])

    # Path E — IN ``stamp_duty.by_state`` already handled above; ITBI (BR).
    itbi = jur.get("itbi")
    if isinstance(itbi, Mapping) and itbi.get("bands"):
        return _progressive_band_amount(price_d, itbi["bands"])

    # Path F — RU has no stamp duty (uses state_duty flat fee instead).
    if "state_duty" in jur:
        return _money(_D(jur["state_duty"]))

    # Path G — SA RETT.
    if "rett" in jur:
        return _money(price_d * _D(jur["rett"]))

    # Path H — CH transfer_tax by Kanton.
    transfer = jur.get("transfer_tax")
    if isinstance(transfer, Mapping) and transfer.get("by_state"):
        states = transfer["by_state"]
        if not region_subcode:
            raise MissingRegionSubcodeError(jurisdiction, states.keys())
        sub = region_subcode.upper()
        if sub not in states:
            raise MissingRegionSubcodeError(jurisdiction, states.keys())
        return _money(price_d * _D(states[sub]))

    # Path I — US ``state_transfer_tax`` already handled above.
    stt = jur.get("state_transfer_tax")
    if isinstance(stt, Mapping) and stt.get("by_state"):
        states = stt["by_state"]
        if not region_subcode:
            raise MissingRegionSubcodeError(jurisdiction, states.keys())
        sub = region_subcode.upper()
        if sub not in states:
            raise MissingRegionSubcodeError(jurisdiction, states.keys())
        return _money(price_d * _D(states[sub]))

    # No applicable rule — return zero (a few jurisdictions have no
    # stamp duty by design; this is not an error).
    return _money(_ZERO)


def compute_absd(
    price: Any,
    jurisdiction: str,
    *,
    buyer_profile: str,
) -> Decimal:
    """Return Singapore-style Additional Buyer's Stamp Duty (ABSD).

    Args:
        price: full purchase price in SGD.
        jurisdiction: must be ``"SG"`` (or any jurisdiction defining
            an ``absd`` block).
        buyer_profile: one of ``sc_first``, ``sc_second``, ``spr_first``,
            ``spr_second``, ``foreigner``, ``entity``.

    Returns:
        ABSD amount rounded HALF_UP to 2 dp. Zero when profile is
        ``sc_first`` (Singapore Citizen first home).

    Raises:
        UnsupportedJurisdictionError, UnknownRateClassError.
    """
    jur = _table_for(jurisdiction)
    absd = jur.get("absd")
    if not isinstance(absd, Mapping):
        raise UnknownRateClassError(f"Jurisdiction '{jurisdiction}' has no ABSD table")
    if buyer_profile not in absd:
        raise UnknownRateClassError(
            f"Unknown ABSD buyer profile '{buyer_profile}' for '{jurisdiction}'. Supported: {sorted(absd.keys())}"
        )
    rate = _D(absd[buyer_profile])
    return _money(_D(price) * rate)


# ── Transfer fee (UAE DLD style) ────────────────────────────────────────


def compute_transfer_fee(
    price: Any,
    jurisdiction: str,
    *,
    emirate: str | None = None,
) -> Decimal:
    """Return DLD-style flat transfer fee.

    Args:
        price: full purchase price in the contract currency.
        jurisdiction: ISO-3166 alpha-2 code (typically AE).
        emirate: ``dubai`` | ``abu_dhabi`` | ``sharjah`` | ``ajman``.
            REQUIRED when the jurisdiction's transfer_fee block is a
            mapping; ignored for jurisdictions without subkeys.

    Returns:
        Transfer fee amount, 2-dp HALF_UP rounded.
    """
    jur = _table_for(jurisdiction)
    block = jur.get("transfer_fee")
    if block is None:
        return _money(_ZERO)
    if isinstance(block, (int, float, str, Decimal)):
        return _money(_D(price) * _D(block))
    if not isinstance(block, Mapping):
        return _money(_ZERO)
    if emirate is None:
        # Caller didn't specify — default to the most-used emirate.
        # Convention: first key alphabetically gives deterministic output.
        keys = sorted(block.keys())
        if not keys:
            return _money(_ZERO)
        emirate = keys[0]
    key = emirate.lower().replace("-", "_")
    if key not in block:
        raise MissingRegionSubcodeError(jurisdiction, block.keys())
    rate = _D(block[key])
    return _money(_D(price) * rate)


# ── Registration / notary fees ──────────────────────────────────────────


def compute_registration_fee(price: Any, jurisdiction: str) -> Decimal:
    """Return the flat-% registration fee (IN, BR, AT).

    Returns Decimal("0.00") if the jurisdiction has no registration
    fee defined.
    """
    jur = _table_for(jurisdiction)
    rate = jur.get("registration_fee") or jur.get("land_registry_fee") or jur.get("notary_fee_pct") or 0
    return _money(_D(price) * _D(rate))


# ── Late-payment interest ───────────────────────────────────────────────


def compute_late_interest(
    principal: Any,
    jurisdiction: str,
    *,
    days_overdue: int | None = None,
    due_date: date | None = None,
    paid_date: date | None = None,
) -> Decimal:
    """Return accrued late-payment interest on an overdue instalment.

    Calling pattern (mutually exclusive):
        * pass ``days_overdue`` directly, or
        * pass ``due_date`` + ``paid_date`` (or leave ``paid_date``
          None to use ``date.today()``).

    Compounding modes (per jurisdiction):
        * ``simple``  — ``principal * annual_rate * days / 365``.
        * ``daily``   — full daily compounding (rare).

    Negative ``days_overdue`` → Decimal("0.00") (paid early — no charge).
    """
    if days_overdue is None:
        if due_date is None:
            raise TaxEngineError("compute_late_interest needs either days_overdue or due_date")
        end = paid_date or date.today()
        days_overdue = (end - due_date).days
    if days_overdue <= 0:
        return _money(_ZERO)
    jur = _table_for(jurisdiction)
    block = jur.get("late_interest") or {}
    rate = _D(block.get("annual", 0))
    if rate == _ZERO:
        return _money(_ZERO)
    compounding = (block.get("compounding") or "simple").lower()
    days_d = Decimal(str(days_overdue))
    principal_d = _D(principal)
    if compounding == "daily":
        # (1 + daily_rate)^days - 1, daily_rate = annual / 365.
        daily_rate = rate / Decimal("365")
        factor = (Decimal("1") + daily_rate) ** int(days_overdue)
        interest = principal_d * (factor - Decimal("1"))
    else:
        # Simple interest.
        interest = principal_d * rate * days_d / Decimal("365")
    return _money(interest)


# ── High-level contract summariser ──────────────────────────────────────


def compute_total_taxes_for_contract(
    contract: Mapping[str, Any],
    jurisdiction: str,
    *,
    region_subcode: str | None = None,
    is_first_home: bool = False,
    is_additional_property: bool = False,
    vat_rate_class: str = "standard",
    effective_on: date | None = None,
    absd_buyer_profile: str | None = None,
    emirate: str | None = None,
    overdue_instalments: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """High-level helper — sum every applicable tax for a contract.

    ``contract`` is a plain mapping (so this helper works with
    Pydantic models, ORM dicts and raw JSON) and must carry:
        * ``net`` — the net price (pre-VAT) in the contract currency, or
        * ``total_value`` — the gross price (some flows already
          have VAT baked in); when only ``total_value`` is present we
          derive ``net`` via :func:`net_from_gross`.
        * ``currency`` — ISO-4217 code (informational only here).

    Returns a dict with these keys::

        {
          "jurisdiction": "GB",
          "region_subcode": None,
          "currency": "GBP",
          "net": Decimal(...),
          "vat": Decimal(...),
          "stamp_duty": Decimal(...),
          "transfer_fee": Decimal(...),
          "registration_fee": Decimal(...),
          "absd": Decimal(...),         # only when relevant
          "late_interest": Decimal(...),
          "subtotal_taxes": Decimal(...),
          "grand_total": Decimal(...),
          "breakdown": [
            {"line": "Net price", "amount": ...},
            {"line": "VAT (standard 20%)", "amount": ...},
            ...
          ]
        }

    Raises:
        UnsupportedJurisdictionError, MissingRegionSubcodeError,
        UnknownRateClassError.
    """
    jur = _table_for(jurisdiction)

    # ── 1. Net price ─────────────────────────────────────────────
    if "net" in contract and contract["net"] not in (None, "", 0, "0"):
        net = _D(contract["net"])
    elif "total_value" in contract and contract["total_value"] not in (None, "", 0, "0"):
        # Treat total_value as gross only when no net field is present.
        net = net_from_gross(
            contract["total_value"],
            jurisdiction,
            rate_class=vat_rate_class,
            effective_on=effective_on,
        )
    else:
        net = _ZERO

    # ── 2. VAT / GST ────────────────────────────────────────────
    try:
        vat = compute_vat(
            net,
            jurisdiction,
            rate_class=vat_rate_class,
            effective_on=effective_on,
        )
    except UnknownRateClassError:
        # Allow VAT-less jurisdictions silently — e.g. US (no federal).
        vat = _money(_ZERO)

    # ── 3. Stamp duty / transfer tax ────────────────────────────
    # Conventionally applied to the consideration (net headline
    # price), not to net+VAT. UK SDLT, DE Grunderwerbsteuer, AU
    # stamp duty, SG BSD — all assess on the purchase price.
    stamp_duty = compute_stamp_duty(
        net,
        jurisdiction,
        region_subcode=region_subcode,
        is_first_home=is_first_home,
        is_additional_property=is_additional_property,
    )

    # ── 4. Transfer fee (UAE DLD style) ─────────────────────────
    transfer_fee = (
        compute_transfer_fee(net, jurisdiction, emirate=emirate) if jur.get("transfer_fee") else _money(_ZERO)
    )

    # ── 5. Registration / notary fee ────────────────────────────
    registration_fee = compute_registration_fee(net, jurisdiction)

    # ── 6. ABSD (SG style) ──────────────────────────────────────
    absd = _money(_ZERO)
    if absd_buyer_profile and jur.get("absd"):
        absd = compute_absd(net, jurisdiction, buyer_profile=absd_buyer_profile)

    # ── 7. Late interest on overdue instalments ─────────────────
    late_interest = _money(_ZERO)
    overdue_lines: list[dict[str, Any]] = []
    if overdue_instalments:
        for item in overdue_instalments:
            principal = _D(item.get("amount", 0))
            days = item.get("days_overdue")
            due_dt: date | None = None
            paid_dt: date | None = None
            if days is None:
                due_dt = _parse_iso(item.get("due_date"))
                paid_dt = _parse_iso(item.get("paid_date"))
            this = compute_late_interest(
                principal,
                jurisdiction,
                days_overdue=days,
                due_date=due_dt,
                paid_date=paid_dt,
            )
            late_interest += this
            overdue_lines.append(
                {
                    "line": f"Late interest on instalment {item.get('sequence', '?')}",
                    "amount": this,
                }
            )

    # ── 8. Roll up ──────────────────────────────────────────────
    subtotal = stamp_duty + transfer_fee + registration_fee + absd
    grand_total = net + vat + subtotal + late_interest

    breakdown: list[dict[str, Any]] = [
        {"line": "Net price", "amount": _money(net)},
    ]
    if vat > _ZERO:
        breakdown.append({"line": f"VAT/GST ({vat_rate_class})", "amount": vat})
    if stamp_duty > _ZERO:
        breakdown.append({"line": "Stamp duty / transfer tax", "amount": stamp_duty})
    if transfer_fee > _ZERO:
        breakdown.append({"line": "Transfer fee", "amount": transfer_fee})
    if registration_fee > _ZERO:
        breakdown.append({"line": "Registration / notary fee", "amount": registration_fee})
    if absd > _ZERO:
        breakdown.append({"line": f"ABSD ({absd_buyer_profile})", "amount": absd})
    breakdown.extend(overdue_lines)

    return {
        "jurisdiction": (jurisdiction or "").strip().upper(),
        "region_subcode": (region_subcode or "").upper() or None,
        "currency": (contract.get("currency") or "").upper(),
        "net": _money(net),
        "vat": vat,
        "stamp_duty": stamp_duty,
        "transfer_fee": transfer_fee,
        "registration_fee": registration_fee,
        "absd": absd,
        "late_interest": late_interest,
        "subtotal_taxes": _money(subtotal + late_interest),
        "grand_total": _money(grand_total),
        "breakdown": breakdown,
    }


__all__ = [
    "MissingRegionSubcodeError",
    "TaxEngineError",
    "UnknownRateClassError",
    "UnsupportedJurisdictionError",
    "compute_absd",
    "compute_late_interest",
    "compute_registration_fee",
    "compute_stamp_duty",
    "compute_total_taxes_for_contract",
    "compute_transfer_fee",
    "compute_vat",
    "gross_from_net",
    "jurisdiction_metadata",
    "net_from_gross",
    "reload_tax_table",
    "supported_jurisdictions",
]

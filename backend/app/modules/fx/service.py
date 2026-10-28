# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Currency / FX service: rate history, provenance, conversion and revaluation.

A construction project is estimated in one currency, procured in a second and
reported in a third, and the three move against each other for the whole of a
multi-year programme. This service is what keeps that honest:

* **A rate valid on a date.** Rates are stored as published sets
  (:class:`~app.modules.fx.models.FxRateSet`), so any figure can be repriced at
  the rates that actually applied when it was agreed, not at today's.
* **Provenance.** Every set records where it came from, what it was read from
  and when it was captured, and can be locked so a pinned estimate reprices
  identically a year later.
* **Movement attribution.** :meth:`FxService.revalue` splits a change in a
  reported figure into the part that came from scope and the part that came
  from the exchange rate, which is the question a cost report is actually asked.

Market rates come from the European Central Bank daily reference feed, which is
EUR based (``rate`` = units of a currency per 1 EUR). Resolution falls back in a
fixed order - the applicable rate set, then the legacy latest-rate cache, then
the bundled ``fx_seed.json`` - so conversion works offline and on an
installation upgraded from a version that only had the cache. The result always
says which of the three it used.

Optional purchasing-power-parity conversion uses World Bank factors (indicator
``PA.NUS.PPP``). It is best-effort: a missing factor is reported as unavailable
rather than raised.

All network access is wrapped with a timeout and cannot propagate out of a
public method.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.money import money_quantum
from app.core.validation.engine import ValidationReport, validation_engine
from app.modules.fx import repository as repo
from app.modules.fx.models import (
    RATE_MODE_PINNED,
    RATE_MODES,
    SOURCE_ECB,
    SOURCE_MANUAL,
    SOURCE_SEED,
    FxPolicy,
    FxRateSet,
)
from app.modules.fx.validators import FX_RULE_SET

logger = logging.getLogger(__name__)

# ECB publishes today's euro reference rates as a small XML document. It is
# EUR-based and covers roughly 30 major currencies (it does NOT include some
# currencies the platform ships, such as VND, which is why the bundled seed
# exists as the ultimate fallback).
ECB_DAILY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

# World Bank PPP conversion factor (GDP), local currency units per international
# dollar. ``mrnev=1`` asks for the most recent non-empty value for the country.
WORLD_BANK_PPP_URL = "https://api.worldbank.org/v2/country/{iso3}/indicator/PA.NUS.PPP?format=json&mrnev=1"

# Generous connect/read timeout. Every call that uses it is wrapped so a slow or
# unreachable host degrades to cache/seed instead of failing the request.
_HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

_RATE_MIN_Q = Decimal("0.000001")
# Rates are ratios, and the inverse of a rate against a weak currency is very
# small: 1 VND is 0.0000363 EUR. Rounding that to six decimals throws away
# roughly one percent, and construction budgets are converted in both
# directions, so small rates keep twelve significant digits instead.
_RATE_SIGNIFICANT_DIGITS = 12

#: Where a resolved rate map was read from, as opposed to who published it.
ORIGIN_RATE_SET = "rate_set"
ORIGIN_LEGACY_CACHE = "legacy_cache"
ORIGIN_SEED = "seed"

# Currency to ISO 3166-1 alpha-3 country, for the optional PPP path. PPP factors
# are published per country, not per currency, so a currency shared by several
# countries (notably EUR) is mapped to a single representative country and the
# result is approximate; that caveat is surfaced in the response note. Only the
# currencies the platform is likely to deal with are listed; an unlisted
# currency simply makes the PPP path return "unavailable".
CURRENCY_TO_ISO3: dict[str, str] = {
    "EUR": "DEU",
    "USD": "USA",
    "GBP": "GBR",
    "CHF": "CHE",
    "JPY": "JPN",
    "TRY": "TUR",
    "CNY": "CHN",
    "BRL": "BRA",
    "VND": "VNM",
    "IDR": "IDN",
    "INR": "IND",
    "PLN": "POL",
    "CZK": "CZE",
    "RON": "ROU",
    "SEK": "SWE",
    "NOK": "NOR",
    "DKK": "DNK",
    "HUF": "HUN",
    "BGN": "BGR",
    "MXN": "MEX",
    "ZAR": "ZAF",
    "KRW": "KOR",
    "AUD": "AUS",
    "CAD": "CAN",
    "SGD": "SGP",
    "HKD": "HKG",
    "THB": "THA",
    "MYR": "MYS",
    "PHP": "PHL",
    "NZD": "NZL",
    "ILS": "ISR",
    "ISK": "ISL",
    "SAR": "SAU",
    "AED": "ARE",
    "RUB": "RUS",
    "UAH": "UKR",
    "NGN": "NGA",
    "EGP": "EGY",
}

#: Reverse of :data:`CURRENCY_TO_ISO3`, so a stored PPP row can record which
#: local currency its factor is denominated in.
ISO3_TO_CURRENCY: dict[str, str] = {iso3: ccy for ccy, iso3 in CURRENCY_TO_ISO3.items()}


class UnknownCurrencyError(ValueError):
    """Raised when a currency code is unknown to the active rate set.

    Subclasses :class:`ValueError` so the router can translate it to a 422
    (bad input) rather than letting it surface as a 500.
    """


class RateSetUnavailableError(LookupError):
    """Raised when an explicitly requested rate set cannot be resolved.

    Only raised for a *pinned* request - a policy that names a rate set, or a
    caller that names one by id. Falling back silently would defeat the purpose
    of pinning, which is that the figure cannot move without someone deciding it
    should.
    """


def _to_decimal(value: object, default: Decimal = Decimal("0")) -> Decimal:
    """Parse a number/str value to :class:`~decimal.Decimal`, tolerant of junk."""
    if isinstance(value, Decimal):
        return value
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _norm_ccy(code: str) -> str:
    """Normalise and validate a 3-letter ISO 4217 code (uppercased).

    Raises:
        UnknownCurrencyError: If the code is not three alphabetic characters.
    """
    cleaned = (code or "").strip().upper()
    if len(cleaned) != 3 or not cleaned.isalpha():
        raise UnknownCurrencyError(code or "")
    return cleaned


def _q_money(value: Decimal, currency: str) -> Decimal:
    """Round a converted amount to the minor unit of ``currency`` (half up).

    The currency argument carries no default on purpose. This is the value
    layer: what comes out of here is the amount, not a rendering of it, so a
    quantum that ignores the currency does not change how a figure looks, it
    changes what it is worth.

    Both directions were wrong and they are different faults. Rounded to two
    decimals a Kuwaiti dinar, a Bahraini dinar or a Tunisian dinar loses its
    third digit, and the fils it names is a real subunit that a real payment
    carries, so precision was being destroyed on the way out. In the other
    direction a yen, a won, a forint or a Chilean peso came back with two
    decimals that the currency has no way to settle, which is a figure nobody
    can pay and a total that stops agreeing with the invoice written from it.

    ``MoneyValue.convert`` in ``app.core.money`` had exactly this hardcoded
    ``Decimal("0.01")`` and it was fixed there; this was the same rounding on a
    second conversion path, left behind. Both now ask
    :func:`app.core.money.money_quantum`, so neither can drift from the other.

    Args:
        value: The converted amount.
        currency: ISO 4217 code the amount is denominated in.

    Returns:
        The amount rounded to that currency's own precision.
    """
    return value.quantize(money_quantum(currency), rounding=ROUND_HALF_UP)


def _q_rate(value: Decimal) -> Decimal:
    """Round an exchange rate: 6 dp, extended below 1 to keep it meaningful.

    A rate at or above 1 keeps the module's original six decimals. Below 1 that
    scale can be destructive - a VND-to-EUR rate of 0.0000363636 becomes
    0.000036, a one percent error on every line it touches - so a small rate is
    rounded to twelve significant digits instead, and then pulled back to six
    decimals when the extra digits carry nothing. A rate of 0.845 still reads as
    ``0.845000``; only a rate that six decimals would truncate keeps the tail.
    """
    if value.is_zero() or value.copy_abs() >= 1:
        return value.quantize(_RATE_MIN_Q, rounding=ROUND_HALF_UP)
    exponent = Decimal(1).scaleb(value.adjusted() - (_RATE_SIGNIFICANT_DIGITS - 1))
    fine = value.quantize(exponent, rounding=ROUND_HALF_UP)
    coarse = fine.quantize(_RATE_MIN_Q, rounding=ROUND_HALF_UP)
    return coarse if coarse == fine else fine


@lru_cache(maxsize=1)
def _load_seed() -> tuple[str, date, dict[str, Decimal], str]:
    """Load and cache the bundled fallback rates from ``fx_seed.json``.

    Returns:
        ``(base_currency, as_of_date, {currency: rate}, note)``. The rate map is
        cached; callers must copy it before mutating.
    """
    path = Path(__file__).with_name("fx_seed.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.exception("Could not read FX seed file at %s; using empty seed", path)
        return "EUR", date.today(), {}, ""
    base = str(data.get("base", "EUR")).upper()
    try:
        seed_date = date.fromisoformat(str(data.get("date")))
    except (ValueError, TypeError):
        seed_date = date.today()
    rates: dict[str, Decimal] = {}
    for ccy, val in (data.get("rates") or {}).items():
        parsed = _to_decimal(val)
        if parsed > 0:
            rates[str(ccy).upper()] = parsed
    return base, seed_date, rates, str(data.get("note", ""))


def parse_ecb_xml(xml: str | bytes) -> tuple[dict[str, Decimal], date]:
    """Parse an ECB eurofxref-daily XML document into rates and its date.

    The document is EUR-based; each leaf ``Cube`` carries a ``currency`` and a
    ``rate`` attribute, and the enclosing ``Cube`` carries the ``time`` date.
    Parsing is namespace-agnostic (it reads attributes, not tag names) so it is
    resilient to namespace-prefix changes in the feed.

    Args:
        xml: Raw XML text or bytes.

    Returns:
        ``({currency: rate}, reference_date)`` with rates as units per 1 EUR.

    Raises:
        ValueError: If no currency rates could be parsed.
    """
    # defusedxml rejects the entity-expansion and external-entity attacks a
    # plain ElementTree would accept. Feed it bytes so an XML encoding
    # declaration in a decoded str cannot trip "unicode with encoding decl".
    from defusedxml.ElementTree import fromstring

    root = fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    rates: dict[str, Decimal] = {}
    ref_date: date | None = None
    for el in root.iter():
        attrib = el.attrib
        if ref_date is None and "time" in attrib:
            try:
                ref_date = date.fromisoformat(str(attrib["time"]))
            except (ValueError, TypeError):
                ref_date = None
        if "currency" in attrib and "rate" in attrib:
            parsed = _to_decimal(attrib["rate"])
            if parsed > 0:
                rates[str(attrib["currency"]).upper()] = parsed
    if not rates:
        raise ValueError("No currency rates found in ECB XML")
    return rates, ref_date or date.today()


# ── Pure conversion maths ────────────────────────────────────────────────────


def cross_rate(
    from_currency: str,
    to_currency: str,
    base_rates: Mapping[str, Decimal],
    *,
    base_currency: str = "EUR",
) -> Decimal:
    """The rate to multiply a ``from_currency`` amount by to get ``to_currency``.

    ``base_rates`` maps a currency to its units per one ``base_currency`` (the
    ECB shape). The base is implicit at 1, so the cross rate is
    ``rate[to] / rate[from]``. Pure function, no I/O.

    Args:
        from_currency: ISO 4217 source code.
        to_currency: ISO 4217 target code.
        base_rates: Currency to units-per-base map.
        base_currency: The base the rates are quoted against.

    Returns:
        Target units per one source unit, unrounded.

    Raises:
        UnknownCurrencyError: If either currency is neither the base nor quoted.
    """
    frm = _norm_ccy(from_currency)
    to = _norm_ccy(to_currency)
    base = _norm_ccy(base_currency)

    def rate_of(ccy: str) -> Decimal:
        if ccy == base:
            return Decimal("1")
        found = base_rates.get(ccy)
        if found is None:
            raise UnknownCurrencyError(ccy)
        value = _to_decimal(found)
        if value <= 0:
            raise UnknownCurrencyError(ccy)
        return value

    return rate_of(to) / rate_of(frm)


def convert_via_base(
    amount: object,
    from_currency: str,
    to_currency: str,
    base_rates: Mapping[str, Decimal],
    *,
    base_currency: str = "EUR",
) -> tuple[Decimal, Decimal]:
    """Convert ``amount`` from one currency to another through a base currency.

    This is a pure function - no I/O - so the conversion maths can be exercised
    offline with a seed rate map.

    Args:
        amount: Number or numeric string to convert.
        from_currency: ISO 4217 source code.
        to_currency: ISO 4217 target code.
        base_rates: Currency to units-per-base map.
        base_currency: The base the rates are quoted against (default EUR).

    Returns:
        ``(converted_amount, effective_rate)`` as unrounded Decimals.

    Raises:
        UnknownCurrencyError: If either currency is not the base and not in
            ``base_rates``.
    """
    effective = cross_rate(from_currency, to_currency, base_rates, base_currency=base_currency)
    return _to_decimal(amount) * effective, effective


@dataclass(frozen=True)
class MovementSplit:
    """How much of a reported movement came from scope and how much from the rate.

    All six figures are money in the reporting currency, already rounded, and
    the three components sum to ``total_delta`` exactly. That identity is the
    whole point: a cost report that says "up 240k" is only useful if it can also
    say how much of that nobody in the project team caused.
    """

    baseline_value: Decimal
    current_value: Decimal
    total_delta: Decimal
    scope_delta: Decimal
    rate_delta: Decimal
    joint_delta: Decimal


def decompose_movement(
    baseline_amount: Decimal,
    current_amount: Decimal,
    baseline_rate: Decimal,
    current_rate: Decimal,
    reporting_currency: str,
) -> MovementSplit:
    """Split a movement in a converted figure into scope, rate and joint effects.

    With ``A`` the amount in its own currency and ``k`` the cross rate into the
    reporting currency, the reported value is ``A * k`` and the movement
    decomposes exactly:

    * scope ``(A1 - A0) * k0`` - what changed because the work changed,
      valued at the rate that applied when the baseline was set.
    * rate  ``A0 * (k1 - k0)`` - what changed because the currency moved,
      on the scope that was already there.
    * joint ``(A1 - A0) * (k1 - k0)`` - the interaction: new scope, revalued.

    Each part is rounded to the reporting currency's own minor unit, and the
    joint term absorbs the rounding residual so ``scope + rate + joint ==
    total`` holds for every input rather than for the convenient ones. Rounding
    each component independently would leave the three disagreeing with the
    total by a cent on most real figures, which is exactly the kind of "nearly
    adds up" report nobody trusts. Every figure here is stated in the reporting
    currency, so the currency is a parameter rather than an assumption: a
    revaluation reported in yen used to come back with sub-yen components that
    then had to add up to a sub-yen total.

    Args:
        baseline_amount: Amount in its own currency at the baseline.
        current_amount: Amount in its own currency now.
        baseline_rate: Cross rate into the reporting currency at the baseline.
        current_rate: Cross rate into the reporting currency now.
        reporting_currency: ISO 4217 code every returned figure is stated in.

    Returns:
        The rounded :class:`MovementSplit`.
    """
    baseline_value = _q_money(baseline_amount * baseline_rate, reporting_currency)
    current_value = _q_money(current_amount * current_rate, reporting_currency)
    total = current_value - baseline_value
    scope = _q_money((current_amount - baseline_amount) * baseline_rate, reporting_currency)
    rate = _q_money(baseline_amount * (current_rate - baseline_rate), reporting_currency)
    return MovementSplit(
        baseline_value=baseline_value,
        current_value=current_value,
        total_delta=total,
        scope_delta=scope,
        rate_delta=rate,
        joint_delta=total - scope - rate,
    )


@dataclass(frozen=True)
class RevaluationLine:
    """One figure to revalue: an amount in its own currency, then and now."""

    currency: str
    baseline_amount: Decimal
    current_amount: Decimal
    ref: str = ""
    description: str = ""


@dataclass(frozen=True)
class ResolvedRates:
    """A rate map plus everything needed to say where it came from."""

    base_currency: str
    rates: dict[str, Decimal]
    as_of: date | None
    source: str
    origin: str
    source_ref: str = ""
    fetched_at: datetime | None = None
    rate_set_id: uuid.UUID | None = None
    is_locked: bool = False
    requested_date: date | None = None
    covers_requested_date: bool = True

    def provenance(self) -> dict[str, object]:
        """The provenance block shared by every response that applies a rate."""
        return {
            "as_of": self.as_of,
            "source": self.source,
            "origin": self.origin,
            "source_ref": self.source_ref,
            "fetched_at": self.fetched_at,
            "rate_set_id": str(self.rate_set_id) if self.rate_set_id else None,
            "is_locked": self.is_locked,
            "covers_requested_date": self.covers_requested_date,
        }

    def coverage_note(self) -> str:
        """A plain sentence when the rates do not actually cover the date asked for."""
        if self.covers_requested_date or self.requested_date is None:
            return ""
        as_of = self.as_of.isoformat() if self.as_of else "an unknown date"
        return (
            f"No rate set is on file for {self.requested_date.isoformat()}; "
            f"applied the {as_of} rates from {self.source} instead."
        )


class FxService:
    """Resolve, store and apply foreign-exchange rates for cost figures.

    A ``session`` is optional: without one the service still converts using the
    bundled seed, which keeps the pure conversion maths usable before the
    register has ever been populated and lets the offline path be exercised on
    its own.
    """

    def __init__(self, session: AsyncSession | None = None) -> None:
        self.session = session

    # ── rate resolution ──────────────────────────────────────────────────────

    async def resolve_rates(
        self,
        *,
        base_currency: str = "EUR",
        on_date: date | None = None,
        rate_set_id: uuid.UUID | None = None,
        source: str | None = None,
    ) -> ResolvedRates:
        """Resolve the rate map to apply, with its provenance.

        Resolution order is fixed: the rate set applicable on the date, then the
        legacy latest-rate cache, then the bundled seed. The middle step matters
        on an installation upgraded from a version that only had the cache -
        skipping it would silently demote a working deployment to seed rates.

        Args:
            base_currency: Base the rates must be quoted against.
            on_date: Date the rates must be valid on; ``None`` means latest.
            rate_set_id: Pin to one specific set. When given, nothing else is
                consulted and a missing set is an error, not a fallback.
            source: Restrict to one provenance (e.g. only hand-entered sets).

        Returns:
            The resolved rates and where they came from.

        Raises:
            RateSetUnavailableError: If ``rate_set_id`` does not resolve.
        """
        base = _norm_ccy(base_currency)

        if rate_set_id is not None:
            rate_set = await self._require_rate_set(rate_set_id)
            return self._from_rate_set(rate_set, requested_date=on_date)

        if self.session is not None:
            rate_set = await repo.latest_rate_set(
                self.session,
                base_currency=base,
                on_date=on_date,
                source=source,
            )
            if rate_set is not None:
                return self._from_rate_set(rate_set, requested_date=on_date)

            legacy = await repo.list_latest_rates(self.session, base)
            rates = {row.currency.upper(): Decimal(row.rate) for row in legacy if Decimal(row.rate) > 0}
            if rates:
                as_of = max((row.rate_date for row in legacy if row.rate_date is not None), default=None)
                covers = on_date is None or as_of is None or as_of <= on_date
                legacy_source = SOURCE_ECB if any(row.source == SOURCE_ECB for row in legacy) else legacy[0].source
                return ResolvedRates(
                    base_currency=base,
                    rates=rates,
                    as_of=as_of,
                    source=legacy_source or "cache",
                    origin=ORIGIN_LEGACY_CACHE,
                    source_ref="",
                    requested_date=on_date,
                    covers_requested_date=covers,
                )

        seed_base, seed_date, seed_rates, seed_note = _load_seed()
        rates = dict(seed_rates)
        if base != seed_base:
            rates = _rebase(rates, seed_base, base)
        covers = on_date is None or seed_date <= on_date
        return ResolvedRates(
            base_currency=base,
            rates=rates,
            as_of=seed_date,
            source=SOURCE_SEED,
            origin=ORIGIN_SEED,
            source_ref=seed_note,
            requested_date=on_date,
            covers_requested_date=covers,
        )

    async def _require_rate_set(self, rate_set_id: uuid.UUID) -> FxRateSet:
        """Load a rate set by id or raise :class:`RateSetUnavailableError`."""
        if self.session is None:
            raise RateSetUnavailableError(f"Rate set {rate_set_id} cannot be read without a database session")
        rate_set = await repo.get_rate_set(self.session, rate_set_id)
        if rate_set is None:
            raise RateSetUnavailableError(f"Rate set {rate_set_id} does not exist")
        return rate_set

    @staticmethod
    def _from_rate_set(rate_set: FxRateSet, *, requested_date: date | None) -> ResolvedRates:
        """Build a :class:`ResolvedRates` from a loaded set (no SQL)."""
        covers = requested_date is None or rate_set.rate_date <= requested_date
        return ResolvedRates(
            base_currency=rate_set.base_currency.upper(),
            rates=repo.quotes_as_map(rate_set),
            as_of=rate_set.rate_date,
            source=rate_set.source,
            origin=ORIGIN_RATE_SET,
            source_ref=rate_set.source_ref,
            fetched_at=rate_set.fetched_at,
            rate_set_id=rate_set.id,
            is_locked=rate_set.is_locked,
            requested_date=requested_date,
            covers_requested_date=covers,
        )

    async def effective_rates(self) -> tuple[dict[str, Decimal], date | None, str]:
        """Resolve the EUR-based rate map to use right now.

        Returns:
            ``({currency: units-per-EUR}, as_of, source)``. The map never
            includes EUR itself (it is the implicit base at rate 1).
        """
        resolved = await self.resolve_rates()
        return resolved.rates, resolved.as_of, resolved.source

    async def _rates_for_request(
        self,
        *,
        on_date: date | None,
        project_id: uuid.UUID | None,
        rate_set_id: uuid.UUID | None,
        base_currency: str = "EUR",
    ) -> tuple[ResolvedRates, FxPolicy | None]:
        """Resolve rates honouring a project's policy when one is given.

        A project pinned to a rate set always gets that set, whatever date is
        asked for: that is what pinning means. A project on live rates behaves
        exactly like an unattached caller.
        """
        policy: FxPolicy | None = None
        if project_id is not None and self.session is not None:
            policy = await repo.get_policy(self.session, project_id)
        if rate_set_id is None and policy is not None and policy.rate_mode == RATE_MODE_PINNED:
            if policy.pinned_rate_set_id is None:
                raise RateSetUnavailableError(
                    f"Project {project_id} is pinned to a rate set but none is configured",
                )
            rate_set_id = policy.pinned_rate_set_id
        resolved = await self.resolve_rates(
            base_currency=base_currency,
            on_date=on_date,
            rate_set_id=rate_set_id,
        )
        return resolved, policy

    # ── market conversion ────────────────────────────────────────────────────

    async def convert(
        self,
        amount: object,
        from_currency: str,
        to_currency: str,
        *,
        mode: str = "market",
        on_date: date | None = None,
        project_id: uuid.UUID | None = None,
        rate_set_id: uuid.UUID | None = None,
    ) -> dict[str, object]:
        """Convert an amount between two currencies.

        Args:
            amount: Number or numeric string to convert.
            from_currency: ISO 4217 source code.
            to_currency: ISO 4217 target code.
            mode: ``market`` (reference rates, the default) or ``ppp``
                (World Bank purchasing-power-parity).
            on_date: Value the amount at the rates that applied on this date.
            project_id: Apply this project's FX policy, so a pinned project
                reprices at its pinned set rather than at today's rates.
            rate_set_id: Use one named rate set, overriding date and policy.

        Returns:
            A dict matching the ``ConvertResponse`` schema. For PPP the result
            may be ``available=False`` when no factor is on file.

        Raises:
            UnknownCurrencyError: For market mode when a currency is unknown to
                the resolved rate set.
            RateSetUnavailableError: When a pinned set cannot be resolved.
        """
        if mode == "ppp":
            return await self.ppp_convert(amount, from_currency, to_currency)

        resolved, _policy = await self._rates_for_request(
            on_date=on_date,
            project_id=project_id,
            rate_set_id=rate_set_id,
        )
        converted, effective = convert_via_base(
            amount,
            from_currency,
            to_currency,
            resolved.rates,
            base_currency=resolved.base_currency,
        )
        return {
            "amount": _to_decimal(amount),
            "converted": _q_money(converted, to_currency),
            "rate": _q_rate(effective),
            "from_currency": _norm_ccy(from_currency),
            "to_currency": _norm_ccy(to_currency),
            "mode": "market",
            "available": True,
            "note": resolved.coverage_note(),
            **resolved.provenance(),
        }

    async def get_rates(
        self,
        base: str = "EUR",
        *,
        on_date: date | None = None,
        rate_set_id: uuid.UUID | None = None,
    ) -> dict[str, object]:
        """Return the rate map for ``base`` (units per 1 base) on a date.

        Rates are resolved through the register, the legacy cache and then the
        seed, and rebased when a non-EUR base is requested.

        Args:
            base: Base currency to quote against.
            on_date: Date the rates must be valid on; ``None`` means latest.
            rate_set_id: Quote one named rate set instead.

        Raises:
            UnknownCurrencyError: If ``base`` is unknown to the resolved rates.
            RateSetUnavailableError: If ``rate_set_id`` does not resolve.
        """
        base_ccy = _norm_ccy(base)
        resolved = await self.resolve_rates(on_date=on_date, rate_set_id=rate_set_id)
        rates = _rebase(resolved.rates, resolved.base_currency, base_ccy)
        return {
            "base": base_ccy,
            "count": len(rates),
            "rates": {ccy: _q_rate(value) for ccy, value in sorted(rates.items())},
            "note": resolved.coverage_note(),
            **resolved.provenance(),
        }

    # ── revaluation: scope movement versus rate movement ─────────────────────

    async def revalue(
        self,
        lines: Iterable[RevaluationLine],
        *,
        reporting_currency: str,
        baseline_date: date | None = None,
        current_date: date | None = None,
        baseline_rate_set_id: uuid.UUID | None = None,
        current_rate_set_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
    ) -> dict[str, object]:
        """Revalue figures between two rate dates and attribute the movement.

        For each line the reported value is computed at the baseline rates and
        at the current rates, and the difference is split into the part caused
        by the amount changing, the part caused by the rate changing, and the
        interaction between them. Line totals are summed from the rounded line
        figures, so the totals row equals the sum of the rows on screen.

        A line in a currency neither rate set quotes is reported as unpriced
        rather than failing the whole request: one exotic currency in a
        two-hundred-line commitment register must not cost the estimator the
        other hundred and ninety-nine answers.

        Args:
            lines: Figures to revalue.
            reporting_currency: Currency to report all values in.
            baseline_date: Date of the baseline rates.
            current_date: Date of the current rates; ``None`` means latest.
            baseline_rate_set_id: Name the baseline set explicitly.
            current_rate_set_id: Name the current set explicitly.
            project_id: Apply this project's policy to the current rates.

        Returns:
            A dict matching the ``RevaluationResponse`` schema.

        Raises:
            RateSetUnavailableError: When a named or pinned set cannot resolve.
        """
        target = _norm_ccy(reporting_currency)
        baseline = await self.resolve_rates(on_date=baseline_date, rate_set_id=baseline_rate_set_id)
        current, _policy = await self._rates_for_request(
            on_date=current_date,
            project_id=project_id,
            rate_set_id=current_rate_set_id,
        )

        results: list[dict[str, object]] = []
        totals = dict.fromkeys(
            ("baseline_value", "current_value", "total_delta", "scope_delta", "rate_delta", "joint_delta"),
            Decimal("0"),
        )
        unpriced = 0
        for line in lines:
            currency = _norm_ccy(line.currency)
            try:
                k0 = cross_rate(currency, target, baseline.rates, base_currency=baseline.base_currency)
                k1 = cross_rate(currency, target, current.rates, base_currency=current.base_currency)
            except UnknownCurrencyError as exc:
                unpriced += 1
                results.append(
                    {
                        "ref": line.ref,
                        "description": line.description,
                        "currency": currency,
                        "baseline_amount": line.baseline_amount,
                        "current_amount": line.current_amount,
                        "baseline_rate": None,
                        "current_rate": None,
                        "baseline_value": None,
                        "current_value": None,
                        "total_delta": None,
                        "scope_delta": None,
                        "rate_delta": None,
                        "joint_delta": None,
                        "available": False,
                        "note": f"No rate is quoted for {exc} in both rate sets, so this line cannot be revalued.",
                    }
                )
                continue

            split = decompose_movement(line.baseline_amount, line.current_amount, k0, k1, target)
            results.append(
                {
                    "ref": line.ref,
                    "description": line.description,
                    "currency": currency,
                    "baseline_amount": line.baseline_amount,
                    "current_amount": line.current_amount,
                    "baseline_rate": _q_rate(k0),
                    "current_rate": _q_rate(k1),
                    "baseline_value": split.baseline_value,
                    "current_value": split.current_value,
                    "total_delta": split.total_delta,
                    "scope_delta": split.scope_delta,
                    "rate_delta": split.rate_delta,
                    "joint_delta": split.joint_delta,
                    "available": True,
                    "note": "",
                }
            )
            totals["baseline_value"] += split.baseline_value
            totals["current_value"] += split.current_value
            totals["total_delta"] += split.total_delta
            totals["scope_delta"] += split.scope_delta
            totals["rate_delta"] += split.rate_delta
            totals["joint_delta"] += split.joint_delta

        notes = [note for note in (baseline.coverage_note(), current.coverage_note()) if note]
        return {
            "reporting_currency": target,
            "baseline": _rate_set_ref(baseline),
            "current": _rate_set_ref(current),
            "lines": results,
            "priced_lines": len(results) - unpriced,
            "unpriced_lines": unpriced,
            "note": " ".join(notes),
            **totals,
        }

    # ── rate sets ────────────────────────────────────────────────────────────

    async def list_rate_sets(
        self,
        *,
        base_currency: str | None = None,
        source: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, object]:
        """List stored rate sets with their quote counts.

        Raises:
            RuntimeError: If the service has no database session.
        """
        session = self._require_session("listing rate sets")
        sets = await repo.list_rate_sets(
            session,
            base_currency=base_currency,
            source=source,
            limit=limit,
            offset=offset,
        )
        total = await repo.count_rate_sets(session, base_currency=base_currency, source=source)
        return {
            "total": total,
            "items": [_rate_set_summary(rate_set) for rate_set in sets],
        }

    async def get_rate_set(self, rate_set_id: uuid.UUID) -> dict[str, object]:
        """Return one rate set with every quote it carries.

        Raises:
            RateSetUnavailableError: If no such set exists.
        """
        rate_set = await self._require_rate_set(rate_set_id)
        detail = _rate_set_summary(rate_set)
        detail["rates"] = {ccy: _q_rate(value) for ccy, value in sorted(repo.quotes_as_map(rate_set).items())}
        return detail

    async def record_rate_set(
        self,
        *,
        base_currency: str,
        rate_date: date,
        rates: Mapping[str, object],
        source: str = SOURCE_MANUAL,
        source_ref: str = "",
        note: str = "",
        lock: bool = False,
    ) -> dict[str, object]:
        """Record a hand-entered rate set - a contract rate, a bank quote.

        The rates a project is actually held to are frequently not a central
        bank's: a contract fixes a rate for the duration, or treasury buys
        forward. Those belong in the register with the same provenance and the
        same point-in-time behaviour as the feed, which is what this records.

        Args:
            base_currency: Base the rates are quoted against.
            rate_date: Date the rates are effective for.
            rates: Currency to units-per-base, as numbers or numeric strings.
            source: Provenance key; defaults to ``manual``.
            source_ref: Contract clause, bank reference or document id.
            note: Free-text remark.
            lock: Lock the set immediately, so it can never be rewritten.

        Returns:
            The stored set, in the same shape as :meth:`get_rate_set`.

        Raises:
            UnknownCurrencyError: If the base or a quoted code is not a
                three-letter alphabetic code, or a rate is not positive.
            RateSetLockedError: If an existing set for this key is locked.
        """
        session = self._require_session("recording a rate set")
        base = _norm_ccy(base_currency)
        parsed: dict[str, Decimal] = {}
        for code, value in rates.items():
            currency = _norm_ccy(str(code))
            amount = _to_decimal(value, default=Decimal("-1"))
            if amount <= 0:
                raise UnknownCurrencyError(f"{currency} (a rate must be a positive number)")
            if currency != base:
                parsed[currency] = amount
        rate_set = await repo.upsert_rate_set(
            session,
            base_currency=base,
            rate_date=rate_date,
            source=source,
            rates=parsed,
            source_ref=source_ref,
            note=note,
            lock=lock,
        )
        await session.commit()
        return await self.get_rate_set(rate_set.id)

    async def set_rate_set_lock(self, rate_set_id: uuid.UUID, *, locked: bool) -> dict[str, object]:
        """Lock or unlock a rate set so pinned estimates stay reproducible."""
        session = self._require_session("locking a rate set")
        rate_set = await self._require_rate_set(rate_set_id)
        await repo.set_rate_set_locked(session, rate_set, locked=locked)
        await session.commit()
        return await self.get_rate_set(rate_set_id)

    async def delete_rate_set(self, rate_set_id: uuid.UUID) -> None:
        """Delete a rate set.

        Raises:
            RateSetUnavailableError: If no such set exists.
            RateSetLockedError: If the set is locked.
        """
        session = self._require_session("deleting a rate set")
        rate_set = await self._require_rate_set(rate_set_id)
        await repo.delete_rate_set(session, rate_set)
        await session.commit()

    # ── project policy ───────────────────────────────────────────────────────

    async def get_policy(self, project_id: uuid.UUID) -> dict[str, object] | None:
        """Return a project's FX policy, or ``None`` when it has none."""
        session = self._require_session("reading an FX policy")
        policy = await repo.get_policy(session, project_id, with_pinned_set=True)
        if policy is None:
            return None
        return _policy_payload(policy)

    async def save_policy(
        self,
        project_id: uuid.UUID,
        *,
        estimating_currency: str,
        procurement_currency: str,
        reporting_currency: str,
        rate_mode: str,
        pinned_rate_set_id: uuid.UUID | None = None,
        max_rate_age_days: int = 30,
        note: str = "",
    ) -> dict[str, object]:
        """Create or update a project's FX policy.

        A pinned policy is checked against the register before it is stored: a
        policy pointing at a set that does not exist would silently fail at the
        moment someone tried to price with it, which is the worst possible time.

        Raises:
            UnknownCurrencyError: If a currency code is malformed.
            ValueError: If ``rate_mode`` is not ``live`` or ``pinned``.
            RateSetUnavailableError: If a pinned set id does not resolve.
        """
        session = self._require_session("saving an FX policy")
        if rate_mode not in RATE_MODES:
            raise ValueError(f"Unknown rate mode: {rate_mode}. Expected one of {sorted(RATE_MODES)}")
        if rate_mode == RATE_MODE_PINNED:
            if pinned_rate_set_id is None:
                raise RateSetUnavailableError("A pinned policy must name the rate set it is pinned to")
            await self._require_rate_set(pinned_rate_set_id)
        policy = await repo.upsert_policy(
            session,
            project_id,
            estimating_currency=_norm_ccy(estimating_currency),
            procurement_currency=_norm_ccy(procurement_currency),
            reporting_currency=_norm_ccy(reporting_currency),
            rate_mode=rate_mode,
            pinned_rate_set_id=pinned_rate_set_id,
            max_rate_age_days=max_rate_age_days,
            note=note,
        )
        await session.commit()
        # Re-read so the pinned set is loaded explicitly rather than walked into
        # from a relationship that refuses implicit SQL.
        stored = await repo.get_policy(session, policy.project_id, with_pinned_set=True)
        return _policy_payload(stored) if stored is not None else _policy_payload(policy)

    async def delete_policy(self, project_id: uuid.UUID) -> bool:
        """Remove a project's FX policy. Returns False when there was none."""
        session = self._require_session("deleting an FX policy")
        policy = await repo.get_policy(session, project_id)
        if policy is None:
            return False
        await repo.delete_policy(session, policy)
        await session.commit()
        return True

    # ── validation ───────────────────────────────────────────────────────────

    async def validate_project(
        self,
        project_id: uuid.UUID,
        *,
        on_date: date | None = None,
    ) -> ValidationReport:
        """Run the ``fx`` rule set over a project's policy and its backing rates.

        Validation is part of the workflow, not a button: a project whose
        reporting currency is not quoted by the set it prices against, or whose
        pinned set was left unlocked, produces figures that look fine and are
        not. The report is the traffic light for exactly that.

        Args:
            project_id: Project to validate.
            on_date: Judge freshness as at this date; defaults to today.

        Returns:
            A :class:`~app.core.validation.engine.ValidationReport`.
        """
        session = self._require_session("validating a project's FX setup")
        policy = await repo.get_policy(session, project_id)
        context = await self.build_validation_context(policy, on_date=on_date)
        return await validation_engine.validate(
            data=context,
            rule_sets=[FX_RULE_SET],
            target_type="fx_policy",
            target_id=str(project_id),
            project_id=str(project_id),
        )

    async def build_validation_context(
        self,
        policy: FxPolicy | None,
        *,
        on_date: date | None = None,
    ) -> dict[str, object]:
        """Assemble the plain-dict context the ``fx`` rules read.

        The rules take dicts and no session, so they stay unit-testable in
        isolation; this method is the one place that turns rows into that shape.

        The rates handed to the rules come from :meth:`resolve_rates`, which is
        the same call pricing makes, so the report judges the figures the
        project will actually be priced with. Reading the register directly for
        the project's own estimating currency would be the quiet failure this
        module exists to prevent: every set on file is EUR-based, so a project
        estimating in TRY would find nothing, every rule would fall through its
        "nothing to check" branch, and the traffic light would go green having
        examined nothing at all.

        Args:
            policy: The project's FX policy, or ``None`` when it has none.
            on_date: Effective date to resolve the backing rates for.

        Returns:
            ``{"policy": ..., "rate_set": ..., "previous_rate_set": ..., "as_of": ...}``.
        """
        as_of = on_date or date.today()
        pinned_id = policy.pinned_rate_set_id if policy is not None else None
        is_pinned = policy is not None and policy.rate_mode == RATE_MODE_PINNED and pinned_id is not None
        resolved: ResolvedRates | None = None
        try:
            if is_pinned:
                resolved = await self.resolve_rates(rate_set_id=pinned_id, on_date=as_of)
            else:
                resolved = await self.resolve_rates(on_date=as_of)
        except RateSetUnavailableError:
            # A pin that no longer resolves is precisely what fx.pinned_set_resolvable
            # reports on, so it has to reach the rules as an absent rate set rather
            # than as a failed request.
            resolved = None
        previous: FxRateSet | None = None
        if resolved is not None and resolved.rate_set_id is not None and self.session is not None:
            current = await repo.get_rate_set(self.session, resolved.rate_set_id)
            if current is not None:
                previous = await repo.preceding_rate_set(self.session, current)
        return {
            "as_of": as_of.isoformat(),
            "policy": _policy_context(policy),
            "rate_set": _resolved_context(resolved),
            "previous_rate_set": _rate_set_context(previous),
        }

    # ── status ───────────────────────────────────────────────────────────────

    async def status(self, *, probe_network: bool = True) -> dict[str, object]:
        """Report where rates come from, how fresh they are, and feed reachability.

        Args:
            probe_network: When true (the default), makes one best-effort call to
                the ECB feed so ``network_ok`` reflects live reachability. Any
                failure is swallowed and reported as ``network_ok=False``.
        """
        resolved = await self.resolve_rates()
        cached_currencies = 0
        ppp_countries = 0
        rate_sets = 0
        if self.session is not None:
            cached_currencies = await repo.count_latest_rates(self.session)
            ppp_countries = await repo.count_ppp_factors(self.session)
            rate_sets = await repo.count_rate_sets(self.session)
        network_ok = False
        if probe_network:
            network_ok = (await self.fetch_ecb_rates()) is not None
        currencies = sorted({*resolved.rates, resolved.base_currency})
        return {
            "source": resolved.source,
            "origin": resolved.origin,
            "rates_as_of": resolved.as_of,
            "cached_currencies": cached_currencies,
            "currencies": currencies,
            "ppp_countries": ppp_countries,
            "rate_sets": rate_sets,
            "network_ok": network_ok,
        }

    # ── refresh (network) ────────────────────────────────────────────────────

    async def _fetch_ecb_xml(self) -> bytes:
        """Fetch the raw ECB daily XML (raises on any network/HTTP failure)."""
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(ECB_DAILY_URL)
            resp.raise_for_status()
            return resp.content

    async def fetch_ecb_rates(self) -> tuple[dict[str, Decimal], date] | None:
        """Fetch and parse the live ECB rates, or ``None`` on any failure.

        Never raises: a network error, a bad HTTP status, or an unparseable body
        all resolve to ``None`` so callers can fall back to cache or seed.
        """
        try:
            xml = await self._fetch_ecb_xml()
            return parse_ecb_xml(xml)
        except Exception as exc:  # noqa: BLE001 - degrade gracefully on any failure
            logger.warning("ECB FX fetch failed (%s); falling back to cache/seed", exc)
            return None

    async def refresh(self) -> dict[str, object]:
        """Fetch the live ECB feed now and store it as a rate set.

        The published set and the legacy latest-rate cache are written in one
        transaction, so the register and the compatibility cache can never
        disagree about what the newest rates are.

        On a network failure the register is seeded from the bundled fallback
        (only when it is still empty, so live rates are never overwritten with
        seed values) and the response records ``network_ok=False``. Never raises
        on a network problem.
        """
        fetched = await self.fetch_ecb_rates()
        if fetched is not None:
            rates, rate_date = fetched
            written, rate_set_id = await self._store_rates(
                rates,
                rate_date,
                source=SOURCE_ECB,
                source_ref=ECB_DAILY_URL,
                note="European Central Bank euro foreign exchange reference rates.",
            )
            return {
                "updated": written,
                "source": SOURCE_ECB,
                "as_of": rate_date,
                "rate_set_id": str(rate_set_id) if rate_set_id else None,
                "network_ok": True,
                "note": f"Stored {written} currencies from the ECB feed for {rate_date.isoformat()}.",
            }

        _base, seed_date, seed_rates, seed_note = _load_seed()
        written, rate_set_id = await self._store_rates(
            seed_rates,
            seed_date,
            source=SOURCE_SEED,
            source_ref="fx_seed.json",
            note=seed_note,
            only_if_empty=True,
        )
        return {
            "updated": written,
            "source": SOURCE_SEED,
            "as_of": seed_date,
            "rate_set_id": str(rate_set_id) if rate_set_id else None,
            "network_ok": False,
            "note": (
                "ECB feed unreachable. "
                + (f"Seeded {written} currencies from the bundled fallback." if written else "Kept the existing rates.")
            ),
        }

    async def _store_rates(
        self,
        rates: Mapping[str, Decimal],
        rate_date: date,
        *,
        source: str,
        source_ref: str,
        note: str,
        only_if_empty: bool = False,
    ) -> tuple[int, uuid.UUID | None]:
        """Write a rate set and refresh the legacy cache in one transaction.

        Args:
            rates: Currency to units-per-EUR.
            rate_date: Date the rates are effective for.
            source: Provenance key.
            source_ref: Feed URL or document reference.
            note: Free-text remark stored on the set.
            only_if_empty: Skip entirely when the register or the legacy cache
                already holds rates. Used on the offline path so bundled values
                cannot displace live ones - including on an installation whose
                rates live only in the legacy cache, where writing a seed set
                would otherwise outrank the real rates on the next lookup.

        Returns:
            ``(currencies_written, rate_set_id)``.
        """
        if self.session is None:
            return 0, None
        if only_if_empty and (
            await repo.count_rate_sets(self.session) > 0 or await repo.count_latest_rates(self.session) > 0
        ):
            return 0, None
        rate_set = await repo.upsert_rate_set(
            self.session,
            base_currency="EUR",
            rate_date=rate_date,
            source=source,
            rates=dict(rates),
            source_ref=source_ref,
            note=note,
            fetched_at=datetime.now(UTC),
        )
        written = len(rate_set.quotes)
        await repo.upsert_latest_rates(
            self.session,
            rates,
            rate_date,
            base_currency="EUR",
            source=source,
            only_if_empty=only_if_empty,
        )
        await self.session.commit()
        return written, rate_set.id

    # ── PPP (optional) ───────────────────────────────────────────────────────

    async def _fetch_ppp(self, iso3: str) -> tuple[Decimal, int] | None:
        """Fetch a country's World Bank PPP factor, or ``None`` on any failure.

        Returns ``(factor, year)`` where factor is local currency units per
        international dollar. Never raises.
        """
        url = WORLD_BANK_PPP_URL.format(iso3=iso3)
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
            if not isinstance(data, list) or len(data) < 2 or not data[1]:
                return None
            row = data[1][0]
            value = row.get("value")
            if value is None:
                return None
            factor = _to_decimal(value)
            if factor <= 0:
                return None
            year = int(str(row.get("date") or "0") or 0)
            return factor, year
        except Exception as exc:  # noqa: BLE001 - PPP is optional, degrade quietly
            logger.warning("World Bank PPP fetch failed for %s (%s)", iso3, exc)
            return None

    async def get_ppp_factor(self, iso3: str) -> tuple[Decimal | None, int]:
        """Return ``(factor, year)`` for a country, from cache then live fetch.

        A retired row is skipped on read and replaced by a fresh fetch, so
        deactivating a superseded observation takes it out of service without
        losing it. A successful fetch is cached when a session is present.
        Returns ``(None, 0)`` when no factor is available.
        """
        code = (iso3 or "").strip().upper()
        if not code:
            return None, 0
        if self.session is not None:
            row = await repo.get_ppp_factor(self.session, code)
            if row is not None:
                return Decimal(row.factor), int(row.year or 0)
        fetched = await self._fetch_ppp(code)
        if fetched is None:
            return None, 0
        factor, year = fetched
        if self.session is not None:
            await repo.upsert_ppp_factor(
                self.session,
                code,
                factor=factor,
                year=year,
                currency=ISO3_TO_CURRENCY.get(code, ""),
            )
            await self.session.commit()
        return factor, year

    async def ppp_convert(self, amount: object, from_currency: str, to_currency: str) -> dict[str, object]:
        """Convert an amount using World Bank purchasing-power-parity factors.

        PPP factors are published per country, so each currency is mapped to a
        representative country (approximate for shared currencies such as EUR).
        When either factor is unavailable the result is ``available=False`` with
        an explanatory note rather than an error.
        """
        frm = _norm_ccy(from_currency)
        to = _norm_ccy(to_currency)
        amt = _to_decimal(amount)
        result: dict[str, object] = {
            "amount": amt,
            "converted": None,
            "rate": None,
            "from_currency": frm,
            "to_currency": to,
            "mode": "ppp",
            "as_of": None,
            "source": "worldbank",
            "origin": "worldbank",
            "source_ref": WORLD_BANK_PPP_URL.split("?", 1)[0],
            "fetched_at": None,
            "rate_set_id": None,
            "is_locked": False,
            "covers_requested_date": True,
            "available": False,
            "note": "",
        }

        iso_from = CURRENCY_TO_ISO3.get(frm)
        iso_to = CURRENCY_TO_ISO3.get(to)
        if not iso_from or not iso_to:
            missing = frm if not iso_from else to
            result["note"] = f"PPP conversion is not available for currency {missing}."
            return result

        factor_from, year_from = await self.get_ppp_factor(iso_from)
        factor_to, year_to = await self.get_ppp_factor(iso_to)
        if factor_from is None or factor_to is None or factor_from <= 0:
            result["note"] = "PPP factors are unavailable (World Bank data could not be fetched)."
            return result

        effective = factor_to / factor_from
        result["converted"] = _q_money(amt * effective, to)
        result["rate"] = _q_rate(effective)
        result["available"] = True
        result["note"] = f"PPP based on World Bank PA.NUS.PPP ({iso_from} {year_from}, {iso_to} {year_to})."
        return result

    # ── internals ────────────────────────────────────────────────────────────

    def _require_session(self, action: str) -> AsyncSession:
        """Return the session, or explain which operation needs one."""
        if self.session is None:
            raise RuntimeError(f"A database session is required for {action}")
        return self.session


# ── Module-level helpers ─────────────────────────────────────────────────────


def _rebase(rates: Mapping[str, Decimal], from_base: str, to_base: str) -> dict[str, Decimal]:
    """Re-express a rate map against a different base currency.

    Args:
        rates: Currency to units per one ``from_base``.
        from_base: Base the input is quoted against.
        to_base: Base the output should be quoted against.

    Returns:
        Currency to units per one ``to_base``, excluding ``to_base`` itself and
        including ``from_base`` once it is no longer the base.

    Raises:
        UnknownCurrencyError: If ``to_base`` is neither ``from_base`` nor quoted.
    """
    source_base = from_base.upper()
    target_base = to_base.upper()
    full = dict(rates)
    full[source_base] = Decimal("1")
    if target_base not in full:
        raise UnknownCurrencyError(target_base)
    divisor = full[target_base]
    return {ccy: value / divisor for ccy, value in full.items() if ccy != target_base}


def _rate_set_ref(resolved: ResolvedRates) -> dict[str, object]:
    """The compact "which rates were these" block used by revaluation."""
    return {
        "as_of": resolved.as_of,
        "source": resolved.source,
        "origin": resolved.origin,
        "source_ref": resolved.source_ref,
        "rate_set_id": str(resolved.rate_set_id) if resolved.rate_set_id else None,
        "is_locked": resolved.is_locked,
        "covers_requested_date": resolved.covers_requested_date,
    }


def _rate_set_summary(rate_set: FxRateSet) -> dict[str, object]:
    """Row-level view of a stored rate set (quote count, not the quotes)."""
    return {
        "id": str(rate_set.id),
        "base_currency": rate_set.base_currency,
        "rate_date": rate_set.rate_date,
        "source": rate_set.source,
        "source_ref": rate_set.source_ref,
        "fetched_at": rate_set.fetched_at,
        "is_locked": rate_set.is_locked,
        "note": rate_set.note,
        "quote_count": len(rate_set.quotes),
        "currencies": sorted(quote.currency for quote in rate_set.quotes),
    }


def _policy_payload(policy: FxPolicy) -> dict[str, object]:
    """API view of a project's FX policy, including its pinned set summary."""
    pinned = policy.pinned_rate_set if policy.pinned_rate_set_id is not None else None
    return {
        "project_id": str(policy.project_id),
        "estimating_currency": policy.estimating_currency,
        "procurement_currency": policy.procurement_currency,
        "reporting_currency": policy.reporting_currency,
        "rate_mode": policy.rate_mode,
        "pinned_rate_set_id": str(policy.pinned_rate_set_id) if policy.pinned_rate_set_id else None,
        "pinned_rate_set": _rate_set_summary(pinned) if pinned is not None else None,
        "max_rate_age_days": policy.max_rate_age_days,
        "note": policy.note,
    }


def _policy_context(policy: FxPolicy | None) -> dict[str, object] | None:
    """Validation-context view of a policy: plain values, no ORM instances."""
    if policy is None:
        return None
    return {
        "project_id": str(policy.project_id),
        "estimating_currency": policy.estimating_currency,
        "procurement_currency": policy.procurement_currency,
        "reporting_currency": policy.reporting_currency,
        "rate_mode": policy.rate_mode,
        "pinned_rate_set_id": str(policy.pinned_rate_set_id) if policy.pinned_rate_set_id else None,
        "max_rate_age_days": policy.max_rate_age_days,
    }


def _resolved_context(resolved: ResolvedRates | None) -> dict[str, object] | None:
    """Validation-context view of resolved rates: rates as strings, no Decimals.

    Deliberately the same shape as :func:`_rate_set_context` so the rules cannot
    tell whether the rates came from a stored set, the legacy cache or the
    bundled seed - all three are rates a project can be priced with, and all
    three are worth checking. ``id`` is empty for the sources that are not a
    stored set, which is what makes ``fx.pinned_set_resolvable`` refuse to
    accept a fallback as a pin.
    """
    if resolved is None:
        return None
    return {
        "id": str(resolved.rate_set_id) if resolved.rate_set_id else "",
        "base_currency": resolved.base_currency,
        "rate_date": resolved.as_of.isoformat() if resolved.as_of else "",
        "source": resolved.source,
        "source_ref": resolved.source_ref,
        "is_locked": resolved.is_locked,
        "quotes": {currency: str(rate) for currency, rate in sorted(resolved.rates.items())},
    }


def _rate_set_context(rate_set: FxRateSet | None) -> dict[str, object] | None:
    """Validation-context view of a rate set: rates as strings, no Decimals."""
    if rate_set is None:
        return None
    return {
        "id": str(rate_set.id),
        "base_currency": rate_set.base_currency,
        "rate_date": rate_set.rate_date.isoformat(),
        "source": rate_set.source,
        "source_ref": rate_set.source_ref,
        "is_locked": rate_set.is_locked,
        "quotes": {quote.currency: str(quote.rate) for quote in rate_set.quotes},
    }


def as_revaluation_lines(rows: Sequence[Mapping[str, object]]) -> list[RevaluationLine]:
    """Build :class:`RevaluationLine` objects from plain mappings.

    Used by the router to keep schema types out of the service signature.
    """
    return [
        RevaluationLine(
            currency=str(row.get("currency") or ""),
            baseline_amount=_to_decimal(row.get("baseline_amount")),
            current_amount=_to_decimal(row.get("current_amount")),
            ref=str(row.get("ref") or ""),
            description=str(row.get("description") or ""),
        )
        for row in rows
    ]

"""Currency / FX service: ECB fetch, cache, market conversion and optional PPP.

The platform ships cost bases in many currencies (EUR, TRY, CNY, BRL, VND, IDR,
and more), so a foreign base's rates have to be shown in the user's own
currency. This service provides that conversion with no hard network dependency:

* Market rates come from the European Central Bank daily reference feed, which
  is EUR-based (``rate`` = units of a currency per 1 EUR). They are cached in
  ``oe_fx_rate`` and refreshed on demand.
* When the ECB feed cannot be reached, conversion falls back first to whatever
  is cached, then to a small bundled seed (``fx_seed.json``) of major
  currencies. A conversion therefore always returns a figure - the ``source``
  field records whether it came from the live feed, the cache, or the seed.
* Optional purchasing-power-parity (PPP) conversion uses World Bank factors
  (indicator ``PA.NUS.PPP``). It is best-effort: when a country's factor is not
  available the PPP path returns a clear "unavailable" result rather than an
  error.

All network access is wrapped in try/except with a timeout; a network failure
never propagates out of a public method.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fx.models import FxRate, PppFactor

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

_MONEY_Q = Decimal("0.01")
_RATE_Q = Decimal("0.000001")

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


class UnknownCurrencyError(ValueError):
    """Raised when a currency code is unknown to the active rate set.

    Subclasses :class:`ValueError` so the router can translate it to a 422
    (bad input) rather than letting it surface as a 500.
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


def _q_money(value: Decimal) -> Decimal:
    """Round a converted amount to 2 dp (half up)."""
    return value.quantize(_MONEY_Q, rounding=ROUND_HALF_UP)


def _q_rate(value: Decimal) -> Decimal:
    """Round an exchange rate to 6 dp (half up)."""
    return value.quantize(_RATE_Q, rounding=ROUND_HALF_UP)


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


def convert_via_base(
    amount: object,
    from_currency: str,
    to_currency: str,
    base_rates: Mapping[str, Decimal],
    *,
    base_currency: str = "EUR",
) -> tuple[Decimal, Decimal]:
    """Convert ``amount`` from one currency to another through a base currency.

    ``base_rates`` maps a currency to its units per one ``base_currency`` (the
    ECB shape, EUR-based). The base currency itself is implicit at rate 1. The
    cross rate is ``rate[to] / rate[from]``.

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
    frm = _norm_ccy(from_currency)
    to = _norm_ccy(to_currency)
    base = _norm_ccy(base_currency)
    amt = _to_decimal(amount)

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

    effective = rate_of(to) / rate_of(frm)
    return amt * effective, effective


class FxService:
    """Fetch, cache and apply foreign-exchange rates (market and optional PPP).

    A ``session`` is optional: without one, the service still converts using the
    bundled seed, which keeps the pure conversion maths testable and lets the
    feature work before the cache has ever been populated.
    """

    def __init__(self, session: AsyncSession | None = None) -> None:
        self.session = session

    # ── rate resolution ──────────────────────────────────────────────────────

    async def _cached_eur_rates(self) -> tuple[dict[str, Decimal], date | None, str]:
        """Read the cached EUR-based rates from the database (empty if none)."""
        if self.session is None:
            return {}, None, ""
        rows = (await self.session.execute(select(FxRate).where(FxRate.base_currency == "EUR"))).scalars().all()
        if not rows:
            return {}, None, ""
        rates = {row.currency.upper(): _to_decimal(row.rate) for row in rows if _to_decimal(row.rate) > 0}
        as_of = max((row.rate_date for row in rows if row.rate_date is not None), default=None)
        source = "ecb" if any(row.source == "ecb" for row in rows) else (rows[0].source or "cache")
        return rates, as_of, source

    async def effective_rates(self) -> tuple[dict[str, Decimal], date | None, str]:
        """Resolve the EUR-based rate map to use, cache first then bundled seed.

        Returns:
            ``({currency: units-per-EUR}, as_of, source)`` where source is one of
            ``ecb`` / ``cache`` / ``seed``. The map never includes EUR itself
            (it is the implicit base at rate 1).
        """
        rates, as_of, source = await self._cached_eur_rates()
        if rates:
            return rates, as_of, source
        _base, seed_date, seed_rates, _note = _load_seed()
        return dict(seed_rates), seed_date, "seed"

    # ── market conversion ────────────────────────────────────────────────────

    async def convert(
        self,
        amount: object,
        from_currency: str,
        to_currency: str,
        *,
        mode: str = "market",
    ) -> dict[str, object]:
        """Convert an amount between two currencies.

        Args:
            amount: Number or numeric string to convert.
            from_currency: ISO 4217 source code.
            to_currency: ISO 4217 target code.
            mode: ``market`` (ECB reference rate, the default) or ``ppp``
                (World Bank purchasing-power-parity).

        Returns:
            A dict matching the ``ConvertResponse`` schema. For PPP the result
            may be ``available=False`` when no factor is on file.

        Raises:
            UnknownCurrencyError: For market mode when a currency is unknown to
                the active rate set.
        """
        if mode == "ppp":
            return await self.ppp_convert(amount, from_currency, to_currency)

        eur_rates, as_of, source = await self.effective_rates()
        converted, effective = convert_via_base(amount, from_currency, to_currency, eur_rates)
        return {
            "amount": _to_decimal(amount),
            "converted": _q_money(converted),
            "rate": _q_rate(effective),
            "from_currency": _norm_ccy(from_currency),
            "to_currency": _norm_ccy(to_currency),
            "mode": "market",
            "as_of": as_of,
            "source": source or "seed",
            "available": True,
            "note": "",
        }

    async def get_rates(self, base: str = "EUR") -> dict[str, object]:
        """Return the latest rate map for ``base`` (units per 1 base).

        Rates are resolved from the cache or the bundled seed and rebased from
        EUR when a non-EUR base is requested.

        Raises:
            UnknownCurrencyError: If ``base`` is unknown to the active rate set.
        """
        base_ccy = _norm_ccy(base)
        eur_rates, as_of, source = await self.effective_rates()
        full = dict(eur_rates)
        full["EUR"] = Decimal("1")
        if base_ccy not in full:
            raise UnknownCurrencyError(base_ccy)
        base_rate = full[base_ccy]
        rates = {ccy: _q_rate(value / base_rate) for ccy, value in full.items() if ccy != base_ccy}
        return {
            "base": base_ccy,
            "as_of": as_of,
            "source": source or "seed",
            "count": len(rates),
            "rates": rates,
        }

    # ── status ───────────────────────────────────────────────────────────────

    async def status(self, *, probe_network: bool = True) -> dict[str, object]:
        """Report where rates come from, how fresh they are, and feed reachability.

        Args:
            probe_network: When true (the default), makes one best-effort call to
                the ECB feed so ``network_ok`` reflects live reachability. Any
                failure is swallowed and reported as ``network_ok=False``.
        """
        eur_rates, as_of, source = await self.effective_rates()
        cached_currencies = 0
        ppp_countries = 0
        if self.session is not None:
            cached_currencies = int(
                (
                    await self.session.execute(
                        select(func.count()).select_from(FxRate).where(FxRate.base_currency == "EUR")
                    )
                ).scalar_one()
            )
            ppp_countries = int((await self.session.execute(select(func.count()).select_from(PppFactor))).scalar_one())
        network_ok = False
        if probe_network:
            network_ok = (await self.fetch_ecb_rates()) is not None
        currencies = sorted({*eur_rates, "EUR"})
        return {
            "source": source or "seed",
            "rates_as_of": as_of,
            "cached_currencies": cached_currencies,
            "currencies": currencies,
            "ppp_countries": ppp_countries,
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

    async def _upsert_eur_rates(
        self,
        rates: Mapping[str, Decimal],
        rate_date: date,
        *,
        source: str,
        only_if_empty: bool = False,
    ) -> int:
        """Upsert EUR-based rates into the cache. Returns the number of rows written."""
        if self.session is None:
            return 0
        existing = {
            row.currency.upper(): row
            for row in (
                (await self.session.execute(select(FxRate).where(FxRate.base_currency == "EUR"))).scalars().all()
            )
        }
        if only_if_empty and existing:
            return 0
        written = 0
        for ccy, value in rates.items():
            code = str(ccy).upper()
            if code == "EUR":
                continue
            dval = _to_decimal(value)
            if dval <= 0:
                continue
            row = existing.get(code)
            if row is None:
                self.session.add(
                    FxRate(base_currency="EUR", currency=code, rate=dval, rate_date=rate_date, source=source)
                )
            else:
                row.rate = dval
                row.rate_date = rate_date
                row.source = source
            written += 1
        await self.session.commit()
        return written

    async def refresh(self) -> dict[str, object]:
        """Fetch the live ECB feed now and upsert the cache.

        On a network failure the cache is seeded from the bundled fallback (only
        when it is still empty, so a live cache is never overwritten with seed
        values) and the response records ``network_ok=False``. Never raises.
        """
        fetched = await self.fetch_ecb_rates()
        if fetched is not None:
            rates, rate_date = fetched
            written = await self._upsert_eur_rates(rates, rate_date, source="ecb")
            return {
                "updated": written,
                "source": "ecb",
                "as_of": rate_date,
                "network_ok": True,
                "note": f"Updated {written} currencies from the ECB feed.",
            }
        _base, seed_date, seed_rates, _note = _load_seed()
        written = await self._upsert_eur_rates(seed_rates, seed_date, source="seed", only_if_empty=True)
        return {
            "updated": written,
            "source": "seed",
            "as_of": seed_date,
            "network_ok": False,
            "note": (
                "ECB feed unreachable. "
                + (f"Seeded {written} currencies from the bundled fallback." if written else "Kept the existing cache.")
            ),
        }

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

        A successful live fetch is cached (upserted) when a session is present.
        Returns ``(None, 0)`` when no factor is available.
        """
        code = (iso3 or "").strip().upper()
        if not code:
            return None, 0
        if self.session is not None:
            row = (
                await self.session.execute(select(PppFactor).where(PppFactor.country_iso3 == code))
            ).scalar_one_or_none()
            if row is not None:
                return _to_decimal(row.factor), int(row.year or 0)
        fetched = await self._fetch_ppp(code)
        if fetched is None:
            return None, 0
        factor, year = fetched
        if self.session is not None:
            row = (
                await self.session.execute(select(PppFactor).where(PppFactor.country_iso3 == code))
            ).scalar_one_or_none()
            if row is None:
                self.session.add(PppFactor(country_iso3=code, factor=factor, year=year, source="worldbank"))
            else:
                row.factor = factor
                row.year = year
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
        result["converted"] = _q_money(amt * effective)
        result["rate"] = _q_rate(effective)
        result["available"] = True
        result["note"] = f"PPP based on World Bank PA.NUS.PPP ({iso_from} {year_from}, {iso_to} {year_to})."
        return result

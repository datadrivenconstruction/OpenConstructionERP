"""FX service: market conversion, ECB parsing, graceful fallback and caching.

The FX service converts cost figures between currencies using ECB EUR-based
reference rates, with no hard network dependency: a conversion resolves rates
from the database cache, then from a small bundled seed, so it always returns a
figure even offline. Optional PPP conversion uses World Bank factors and returns
a clear "unavailable" result rather than an error when data is missing.

These tests pin:

* ``convert_via_base`` / ``FxService.convert`` - EUR-base and cross-rate maths.
* ``parse_ecb_xml`` - the ECB daily XML shape.
* graceful fallback - conversion works from the bundled seed when the cache is
  empty, and ``refresh`` seeds the cache when the network is down.
* caching - ``refresh`` upserts EUR rates in place (no duplicate rows) and later
  conversions read the cache.
* PPP - unavailable factors return ``available=False``; present factors convert.

Pure-maths tests are database-free. DB-touching tests use the shared PostgreSQL
transactional session (``tests._pg.transactional_session``): each runs inside an
outer transaction rolled back on teardown. No test contacts the network - the
ECB and World Bank fetches are always stubbed.

Run:
    cd backend
    python -m pytest tests/unit/test_fx_service.py -v --tb=short
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.modules.fx.models import FxRate, PppFactor
from app.modules.fx.service import (
    FxService,
    UnknownCurrencyError,
    _load_seed,
    convert_via_base,
    parse_ecb_xml,
)
from tests._pg import transactional_session

_ECB_SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                 xmlns="http://www.ecb.int/vocab/2002-08-01/eurofxref">
  <gesmes:subject>Reference rates</gesmes:subject>
  <gesmes:Sender><gesmes:name>European Central Bank</gesmes:name></gesmes:Sender>
  <Cube>
    <Cube time="2026-06-30">
      <Cube currency="USD" rate="1.0800"/>
      <Cube currency="TRY" rate="42.0000"/>
      <Cube currency="JPY" rate="170.00"/>
    </Cube>
  </Cube>
</gesmes:Envelope>"""


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


# ── pure conversion maths (no DB, no network) ────────────────────────────────


def test_convert_via_base_eur_source():
    # EUR is the implicit base at rate 1: 100 EUR -> 108 USD at USD=1.08/EUR.
    converted, rate = convert_via_base("100", "EUR", "USD", {"USD": Decimal("1.08")})
    assert converted == Decimal("108.00")
    assert rate == Decimal("1.08")


def test_convert_via_base_cross_rate():
    # Cross rate goes through EUR: USD -> TRY = rate[TRY] / rate[USD].
    rates = {"USD": Decimal("1.08"), "TRY": Decimal("42.0")}
    converted, rate = convert_via_base("100", "USD", "TRY", rates)
    assert rate == Decimal("42.0") / Decimal("1.08")
    assert converted.quantize(Decimal("0.01")) == Decimal("3888.89")


def test_convert_via_base_to_eur():
    # Converting back into the base currency divides by the source rate.
    converted, rate = convert_via_base("108", "USD", "EUR", {"USD": Decimal("1.08")})
    assert converted == Decimal("100.00")
    assert rate == Decimal("1") / Decimal("1.08")


def test_convert_via_base_same_currency_is_identity():
    converted, rate = convert_via_base("250", "TRY", "TRY", {"TRY": Decimal("42.0")})
    assert converted == Decimal("250")
    assert rate == Decimal("1")


def test_convert_via_base_unknown_currency_raises():
    with pytest.raises(UnknownCurrencyError):
        convert_via_base("100", "EUR", "ZZZ", {"USD": Decimal("1.08")})


def test_norm_currency_rejects_malformed():
    with pytest.raises(UnknownCurrencyError):
        convert_via_base("100", "E", "USD", {"USD": Decimal("1.08")})


# ── ECB XML parsing (pure) ───────────────────────────────────────────────────


def test_parse_ecb_xml_reads_rates_and_date():
    rates, ref_date = parse_ecb_xml(_ECB_SAMPLE_XML)
    assert ref_date == date(2026, 6, 30)
    assert rates["USD"] == Decimal("1.0800")
    assert rates["TRY"] == Decimal("42.0000")
    assert rates["JPY"] == Decimal("170.00")
    # EUR is the implicit base and never appears as a quoted rate.
    assert "EUR" not in rates


def test_parse_ecb_xml_accepts_bytes():
    rates, _ = parse_ecb_xml(_ECB_SAMPLE_XML.encode("utf-8"))
    assert rates["USD"] == Decimal("1.0800")


def test_parse_ecb_xml_empty_raises():
    with pytest.raises(ValueError):
        parse_ecb_xml("<Envelope></Envelope>")


# ── conversion via the service using the bundled seed (no DB, no network) ─────


@pytest.mark.asyncio
async def test_service_converts_from_seed_without_session():
    # A sessionless service still converts, using the bundled seed rates.
    svc = FxService()
    result = await svc.convert("100", "EUR", "USD")
    assert result["mode"] == "market"
    assert result["source"] == "seed"
    assert result["available"] is True
    assert result["converted"] == Decimal("108.00")  # seed USD = 1.08


@pytest.mark.asyncio
async def test_service_cross_rate_from_seed():
    svc = FxService()
    result = await svc.convert("100", "USD", "TRY")
    # seed USD=1.08, TRY=42.0 -> 100 * 42.0/1.08 = 3888.89
    assert result["converted"] == Decimal("3888.89")


@pytest.mark.asyncio
async def test_service_unknown_currency_raises():
    svc = FxService()
    with pytest.raises(UnknownCurrencyError):
        await svc.convert("100", "EUR", "ZZZ")


# ── graceful fallback: empty cache falls back to the seed ────────────────────


@pytest.mark.asyncio
async def test_convert_falls_back_to_seed_when_cache_empty(session):
    # A session is present but the cache is empty: conversion still works.
    svc = FxService(session)
    result = await svc.convert("100", "EUR", "USD")
    assert result["source"] == "seed"
    assert result["converted"] == Decimal("108.00")


@pytest.mark.asyncio
async def test_refresh_seeds_cache_when_network_down(session, monkeypatch):
    svc = FxService(session)

    async def _no_network():
        return None

    monkeypatch.setattr(svc, "fetch_ecb_rates", _no_network)

    result = await svc.refresh()
    assert result["network_ok"] is False
    assert result["source"] == "seed"

    _base, _seed_date, seed_rates, _note = _load_seed()
    assert result["updated"] == len(seed_rates)

    count = (
        await session.execute(select(func.count()).select_from(FxRate).where(FxRate.base_currency == "EUR"))
    ).scalar_one()
    assert count == len(seed_rates)

    # After a seed-fallback refresh the cache is used and labelled "seed".
    convert = await svc.convert("100", "EUR", "USD")
    assert convert["source"] == "seed"
    assert convert["converted"] == Decimal("108.00")


# ── caching: refresh upserts live rates and conversion reads the cache ────────


@pytest.mark.asyncio
async def test_refresh_upserts_live_rates_and_convert_uses_cache(session, monkeypatch):
    svc = FxService(session)

    async def _fake_fetch():
        return {"USD": Decimal("1.10"), "TRY": Decimal("40.0")}, date(2026, 7, 1)

    monkeypatch.setattr(svc, "fetch_ecb_rates", _fake_fetch)

    result = await svc.refresh()
    assert result["network_ok"] is True
    assert result["source"] == "ecb"
    assert result["updated"] == 2
    assert result["as_of"] == date(2026, 7, 1)

    # Conversion now reads the freshly cached ECB rate, not the seed.
    convert = await svc.convert("100", "EUR", "USD")
    assert convert["source"] == "ecb"
    assert convert["as_of"] == date(2026, 7, 1)
    assert convert["converted"] == Decimal("110.00")


@pytest.mark.asyncio
async def test_refresh_upsert_does_not_duplicate_rows(session, monkeypatch):
    svc = FxService(session)

    async def _first():
        return {"USD": Decimal("1.10")}, date(2026, 7, 1)

    monkeypatch.setattr(svc, "fetch_ecb_rates", _first)
    await svc.refresh()

    async def _second():
        return {"USD": Decimal("1.15")}, date(2026, 7, 2)

    monkeypatch.setattr(svc, "fetch_ecb_rates", _second)
    await svc.refresh()

    rows = (await session.execute(select(FxRate).where(FxRate.currency == "USD"))).scalars().all()
    assert len(rows) == 1  # upsert in place, not a second row
    assert Decimal(rows[0].rate) == Decimal("1.15")
    assert rows[0].rate_date == date(2026, 7, 2)


@pytest.mark.asyncio
async def test_get_rates_rebases_to_non_eur_base(session, monkeypatch):
    svc = FxService(session)

    async def _fake_fetch():
        return {"USD": Decimal("1.08"), "TRY": Decimal("42.0")}, date(2026, 6, 30)

    monkeypatch.setattr(svc, "fetch_ecb_rates", _fake_fetch)
    await svc.refresh()

    data = await svc.get_rates("USD")
    assert data["base"] == "USD"
    # EUR per 1 USD = 1 / 1.08 ; TRY per 1 USD = 42.0 / 1.08
    assert data["rates"]["EUR"] == (Decimal("1") / Decimal("1.08")).quantize(Decimal("0.000001"))
    assert data["rates"]["TRY"] == (Decimal("42.0") / Decimal("1.08")).quantize(Decimal("0.000001"))


@pytest.mark.asyncio
async def test_status_reports_cache_without_probing(session, monkeypatch):
    svc = FxService(session)

    async def _fake_fetch():
        return {"USD": Decimal("1.08")}, date(2026, 6, 30)

    monkeypatch.setattr(svc, "fetch_ecb_rates", _fake_fetch)
    await svc.refresh()

    status = await svc.status(probe_network=False)
    assert status["source"] == "ecb"
    assert status["cached_currencies"] == 1
    assert status["network_ok"] is False  # probe skipped
    assert "USD" in status["currencies"]


# ── PPP (optional) ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ppp_unavailable_for_unmapped_currency():
    svc = FxService()
    # BWP is not in the currency->country map, so PPP is unavailable (not an error).
    result = await svc.convert("100", "EUR", "BWP", mode="ppp")
    assert result["mode"] == "ppp"
    assert result["available"] is False
    assert result["converted"] is None
    assert "BWP" in result["note"]


@pytest.mark.asyncio
async def test_ppp_unavailable_when_factor_missing(session, monkeypatch):
    svc = FxService(session)

    async def _no_ppp(_iso3):
        return None

    monkeypatch.setattr(svc, "_fetch_ppp", _no_ppp)

    result = await svc.ppp_convert("100", "EUR", "USD")
    assert result["available"] is False
    assert result["converted"] is None


@pytest.mark.asyncio
async def test_ppp_converts_and_caches_factors(session, monkeypatch):
    svc = FxService(session)

    async def _fake_ppp(iso3):
        table = {"DEU": (Decimal("0.75"), 2021), "USA": (Decimal("1.00"), 2021)}
        return table.get(iso3)

    monkeypatch.setattr(svc, "_fetch_ppp", _fake_ppp)

    result = await svc.ppp_convert("100", "EUR", "USD")
    assert result["available"] is True
    # 100 * (factor_USA / factor_DEU) = 100 * (1.00 / 0.75) = 133.33
    assert result["converted"] == Decimal("133.33")

    # Fetched factors were cached for both representative countries.
    count = (await session.execute(select(func.count()).select_from(PppFactor))).scalar_one()
    assert count == 2

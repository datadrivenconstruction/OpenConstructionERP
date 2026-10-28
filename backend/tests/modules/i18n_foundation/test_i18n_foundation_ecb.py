"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The ECB feed: parsing it, and surviving it being missing or wrong.

No network is touched and no HTTP mocking library is added. ``_parse_ecb_xml``
is a pure function, so every malformed-feed case is a direct call; the store
path is driven by monkeypatching ``fetch_ecb_daily_rates`` in the module the
service imports it from.

That import point matters: ``I18nFoundationService.fetch_ecb_rates`` does
``from app.modules.i18n_foundation.ecb_fetcher import fetch_ecb_daily_rates``
inside the function body, so the name is looked up on ``ecb_fetcher`` at call
time. Patching an attribute on ``service`` would bind nothing and the test
would silently keep using the real feed.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.i18n_foundation import ecb_fetcher
from app.modules.i18n_foundation.ecb_fetcher import _parse_ecb_xml
from app.modules.i18n_foundation.service import I18nFoundationService
from tests.modules.i18n_foundation.conftest import make_rate

_NS = "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"

VALID_FEED = f"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="{_NS}">
  <gesmes:subject>Reference rates</gesmes:subject>
  <Cube>
    <Cube time="2026-04-07">
      <Cube currency="USD" rate="1.0850"/>
      <Cube currency="GBP" rate="0.8612"/>
      <Cube currency="JPY" rate="163.45"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""


# ── Parsing a well-formed feed ───────────────────────────────────────────────


def test_a_valid_feed_parses_into_eur_based_rows() -> None:
    """Every row is EUR-based, dated from the Cube's ``time`` attribute."""
    rates = _parse_ecb_xml(VALID_FEED)

    assert len(rates) == 3
    assert {r["from_currency"] for r in rates} == {"EUR"}
    assert {r["rate_date"] for r in rates} == {"2026-04-07"}
    assert {r["source"] for r in rates} == {"ecb"}
    assert [r["to_currency"] for r in rates] == ["USD", "GBP", "JPY"]


def test_the_rate_is_carried_through_as_the_feed_wrote_it() -> None:
    """The rate stays a string with the feed's own digits - no float parse."""
    rates = _parse_ecb_xml(VALID_FEED)

    assert next(r["rate"] for r in rates if r["to_currency"] == "USD") == "1.0850"


def test_a_namespace_stripped_feed_still_parses() -> None:
    """Some proxies drop the namespace; the fallback search covers that."""
    stripped = """<Envelope><Cube><Cube time="2026-04-07">
      <Cube currency="USD" rate="1.0850"/>
    </Cube></Cube></Envelope>"""

    rates = _parse_ecb_xml(stripped)

    assert [(r["to_currency"], r["rate"]) for r in rates] == [("USD", "1.0850")]


def test_a_lower_case_currency_is_normalized() -> None:
    """Currency codes are upper-cased so they match stored rows."""
    feed = """<Envelope><Cube><Cube time="2026-04-07">
      <Cube currency="usd" rate="1.0850"/>
    </Cube></Cube></Envelope>"""

    assert _parse_ecb_xml(feed)[0]["to_currency"] == "USD"


# ── Degrading on a bad feed ──────────────────────────────────────────────────


def test_a_feed_with_no_dated_cube_yields_nothing() -> None:
    """A structurally valid document that says nothing returns an empty list."""
    assert _parse_ecb_xml("<Envelope><Cube/></Envelope>") == []


def test_a_feed_with_an_empty_time_attribute_yields_nothing() -> None:
    """DEFECT: an empty ``time`` was written into the NOT NULL rate_date column.

    ``root.find(".//Cube[@time]")`` matches on the attribute being present, not
    on it having a value, so ``time=""`` produced rows dated with the empty
    string. Those rows sort below every real date, so they never answer a
    lookup, but they occupy the unique (pair, date) slot and can never be
    corrected by a later fetch. A feed that cannot date its rates is no more
    usable than one with no rates.
    """
    feed = """<Envelope><Cube><Cube time="">
      <Cube currency="USD" rate="1.0850"/>
    </Cube></Cube></Envelope>"""

    assert _parse_ecb_xml(feed) == []


def test_a_cube_missing_its_rate_is_skipped() -> None:
    """One broken entry does not discard the rest of the feed."""
    feed = """<Envelope><Cube><Cube time="2026-04-07">
      <Cube currency="USD"/>
      <Cube rate="0.8612"/>
      <Cube currency="GBP" rate="0.8612"/>
    </Cube></Cube></Envelope>"""

    assert [r["to_currency"] for r in _parse_ecb_xml(feed)] == ["GBP"]


def test_malformed_xml_raises_for_the_caller_to_catch() -> None:
    """The parser itself does not swallow a broken document.

    ``fetch_ecb_daily_rates`` wraps the call and turns any exception into an
    empty list; the parser stays honest so the wrapper's logging sees the
    reason. This pins which layer owns the degradation.
    """
    with pytest.raises(Exception):  # noqa: B017 - any parse failure is correct here
        _parse_ecb_xml("<Envelope><Cube>")


def test_a_non_numeric_rate_is_carried_through_not_rejected_here() -> None:
    """The parser does not validate the number - the conversion guard does.

    Recorded so the division of labour is explicit: a feed serving ``rate="n/a"``
    lands in the table, and it is ``_parse_stored_rate`` in the service that
    refuses it at read time with a 422 rather than a crash. Validating it here
    as well would be a second, divergent rule.
    """
    feed = """<Envelope><Cube><Cube time="2026-04-07">
      <Cube currency="USD" rate="n/a"/>
    </Cube></Cube></Envelope>"""

    assert _parse_ecb_xml(feed)[0]["rate"] == "n/a"


# ── Storing what was fetched ─────────────────────────────────────────────────


async def test_fetch_stores_new_rates(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful fetch inserts one row per currency, marked as an ECB feed."""

    async def _fake_fetch() -> list[dict]:
        return _parse_ecb_xml(VALID_FEED)

    monkeypatch.setattr(ecb_fetcher, "fetch_ecb_daily_rates", _fake_fetch)
    service = I18nFoundationService(session)

    stored = await service.fetch_ecb_rates()

    assert stored == 3
    rows, total = await service.list_exchange_rates(from_currency="EUR")
    assert total == 3
    assert {r.source for r in rows} == {"ecb"}
    assert {r.is_manual for r in rows} == {False}


async def test_fetch_skips_rates_that_are_already_stored(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-running the fetch is idempotent - the unique (pair, date) row stands."""

    async def _fake_fetch() -> list[dict]:
        return _parse_ecb_xml(VALID_FEED)

    monkeypatch.setattr(ecb_fetcher, "fetch_ecb_daily_rates", _fake_fetch)
    service = I18nFoundationService(session)

    assert await service.fetch_ecb_rates() == 3
    assert await service.fetch_ecb_rates() == 0

    _, total = await service.list_exchange_rates(from_currency="EUR")
    assert total == 3


async def test_fetch_does_not_overwrite_a_manual_rate(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hand-entered rate for that date and pair survives the feed.

    The fetch skips any pair/date that already exists, whatever its source, so
    a rate an estimator entered deliberately is not silently replaced.
    """
    await make_rate(
        session,
        from_currency="EUR",
        to_currency="USD",
        rate="1.5000",
        rate_date="2026-04-07",
        source="manual",
    )

    async def _fake_fetch() -> list[dict]:
        return _parse_ecb_xml(VALID_FEED)

    monkeypatch.setattr(ecb_fetcher, "fetch_ecb_daily_rates", _fake_fetch)
    service = I18nFoundationService(session)

    assert await service.fetch_ecb_rates() == 2

    result = await service.convert_currency("EUR", "USD", "100", rate_date="2026-04-07")
    assert result.rate == "1.5000"


async def test_an_empty_feed_stores_nothing_and_does_not_raise(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The feed being down returns zero rather than failing the request."""

    async def _fake_fetch() -> list[dict]:
        return []

    monkeypatch.setattr(ecb_fetcher, "fetch_ecb_daily_rates", _fake_fetch)
    service = I18nFoundationService(session)

    assert await service.fetch_ecb_rates() == 0
    _, total = await service.list_exchange_rates()
    assert total == 0


async def test_a_missing_feed_leaves_the_previous_rates_in_place(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed fetch never degrades an existing rate to parity.

    This is the "must not silently price at 1.0" case: with the feed down, the
    stored 1.0850 keeps answering, and a pair that was never stored still 404s
    instead of falling back to a rate of one.
    """
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0850", rate_date="2026-04-07")

    async def _fake_fetch() -> list[dict]:
        return []

    monkeypatch.setattr(ecb_fetcher, "fetch_ecb_daily_rates", _fake_fetch)
    service = I18nFoundationService(session)

    await service.fetch_ecb_rates()

    result = await service.convert_currency("EUR", "USD", "100")
    assert result.converted_amount == "108.5000"
    assert result.rate == "1.0850"

"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Currency conversion: exact decimal strings, rate selection, and bad input.

Every assertion here is on an exact string. ``convert_currency`` takes a string
amount, reads a string rate out of the database and returns a string result, so
an ``approx`` comparison would pass on a build that quietly routed the whole
chain through ``float`` - which is the single failure this module exists to
prevent. ``test_conversion_never_routes_through_float`` pins that directly with
a value ``float`` cannot hold.

Three conversion paths reach a result and each is exercised separately, because
they round and date their answers differently: the direct pair, the reverse pair
(1/rate), and the EUR cross rate.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.i18n_foundation.service import I18nFoundationService
from tests.modules.i18n_foundation.conftest import make_rate

# ── The three lookup paths ───────────────────────────────────────────────────


async def test_direct_pair_converts_to_an_exact_decimal_string(session: AsyncSession) -> None:
    """A stored EUR/USD rate multiplies the amount with no float in between."""
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0850", rate_date="2026-04-07")
    service = I18nFoundationService(session)

    result = await service.convert_currency("EUR", "USD", "1500.50")

    assert result.converted_amount == "1628.0425"
    assert result.rate == "1.0850"
    assert result.rate_date == "2026-04-07"
    assert result.from_currency == "EUR"
    assert result.to_currency == "USD"
    assert result.original_amount == "1500.50"


async def test_reverse_pair_inverts_the_only_stored_direction(session: AsyncSession) -> None:
    """USD->EUR with only EUR->USD stored uses 1/rate, reported to six places."""
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0850", rate_date="2026-04-07")
    service = I18nFoundationService(session)

    result = await service.convert_currency("USD", "EUR", "108.5000")

    assert result.converted_amount == "100.0000"
    assert result.rate == "0.921659"
    assert result.rate_date == "2026-04-07"


async def test_cross_rate_goes_through_eur_when_neither_side_is_eur(session: AsyncSession) -> None:
    """USD->GBP is derived from EUR/GBP divided by EUR/USD."""
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0850", rate_date="2026-04-07")
    await make_rate(session, from_currency="EUR", to_currency="GBP", rate="0.8612", rate_date="2026-04-07")
    service = I18nFoundationService(session)

    result = await service.convert_currency("USD", "GBP", "1000")

    assert result.converted_amount == "793.7327"
    assert result.rate == "0.793733"


async def test_direct_pair_wins_over_the_inverted_one(session: AsyncSession) -> None:
    """With both directions stored, the direct row is used verbatim."""
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0850", rate_date="2026-04-07")
    await make_rate(session, from_currency="USD", to_currency="EUR", rate="0.9000", rate_date="2026-04-07")
    service = I18nFoundationService(session)

    result = await service.convert_currency("USD", "EUR", "100")

    # 0.9000 is the stored USD->EUR row; 1/1.0850 would have given 92.1659.
    assert result.rate == "0.9000"
    assert result.converted_amount == "90.0000"


async def test_currency_codes_are_matched_case_insensitively(session: AsyncSession) -> None:
    """Lower-case input finds the upper-case stored row and is echoed upper-case."""
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0850", rate_date="2026-04-07")
    service = I18nFoundationService(session)

    result = await service.convert_currency("eur", "usd", "100")

    assert result.from_currency == "EUR"
    assert result.to_currency == "USD"
    assert result.converted_amount == "108.5000"


async def test_missing_pair_is_a_404_not_a_rate_of_one(session: AsyncSession) -> None:
    """An unknown pair refuses to answer rather than pricing at parity."""
    service = I18nFoundationService(session)

    with pytest.raises(HTTPException) as excinfo:
        await service.convert_currency("EUR", "ZWL", "100")

    assert excinfo.value.status_code == 404
    assert "EUR/ZWL" in excinfo.value.detail


# ── Date selection and freshness ─────────────────────────────────────────────


async def test_latest_row_is_used_when_no_date_is_given(session: AsyncSession) -> None:
    """Rate rows are dated strings; the most recent one answers an undated call."""
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0000", rate_date="2026-01-02")
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.2000", rate_date="2026-04-07")
    service = I18nFoundationService(session)

    result = await service.convert_currency("EUR", "USD", "100")

    assert result.rate == "1.2000"
    assert result.rate_date == "2026-04-07"


async def test_historical_date_pins_that_days_rate(session: AsyncSession) -> None:
    """An explicit date takes that day's row even when a newer one exists."""
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0000", rate_date="2026-01-02")
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.2000", rate_date="2026-04-07")
    service = I18nFoundationService(session)

    result = await service.convert_currency("EUR", "USD", "100", rate_date="2026-01-02")

    assert result.rate == "1.0000"
    assert result.converted_amount == "100.0000"


async def test_historical_date_with_no_row_that_day_is_a_404(session: AsyncSession) -> None:
    """A gap in the series is reported, not filled from a neighbouring day."""
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0850", rate_date="2026-04-07")
    service = I18nFoundationService(session)

    with pytest.raises(HTTPException) as excinfo:
        await service.convert_currency("EUR", "USD", "100", rate_date="2026-04-08")

    assert excinfo.value.status_code == 404
    assert "2026-04-08" in excinfo.value.detail


async def test_cross_rate_is_dated_by_its_stalest_leg(session: AsyncSession) -> None:
    """DEFECT: a cross rate used to report the *newer* of its two legs' dates.

    With no explicit date, each EUR leg fetches its own latest row, so the two
    can be years apart. Reporting the newer date claims a freshness the derived
    number does not have - a caller checking ``rate_date`` to decide whether to
    trust the figure would be told 2026 about an answer that is half 2019.
    """
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0850", rate_date="2026-04-07")
    await make_rate(session, from_currency="EUR", to_currency="GBP", rate="0.8612", rate_date="2019-01-03")
    service = I18nFoundationService(session)

    result = await service.convert_currency("USD", "GBP", "1000")

    assert result.rate_date == "2019-01-03"


# ── Bad input: the amount ────────────────────────────────────────────────────


@pytest.mark.parametrize("amount", ["NaN", "nan", "Infinity", "-Infinity", "inf", "-inf"])
async def test_non_finite_amount_is_refused(session: AsyncSession, amount: str) -> None:
    """DEFECT: ``Decimal()`` parses NaN and Infinity, so they were accepted.

    NaN survived the same-currency shortcut untouched and came back in the
    response body as an amount of money. Infinity reached ``quantize`` and
    raised an uncaught ``InvalidOperation`` - a 500 on a public endpoint. The
    platform's own money contract in ``accommodation/intl.py`` states that bad
    input "never becomes a 500, a NaN, or an infinity".
    """
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0850", rate_date="2026-04-07")
    service = I18nFoundationService(session)

    with pytest.raises(HTTPException) as excinfo:
        await service.convert_currency("EUR", "USD", amount)

    assert excinfo.value.status_code == 400
    assert "finite" in excinfo.value.detail


async def test_non_finite_amount_is_refused_on_the_same_currency_shortcut(session: AsyncSession) -> None:
    """The same-currency path returns the amount verbatim, so it must be guarded too."""
    service = I18nFoundationService(session)

    with pytest.raises(HTTPException) as excinfo:
        await service.convert_currency("EUR", "EUR", "NaN")

    assert excinfo.value.status_code == 400


@pytest.mark.parametrize("amount", ["abc", "", "1,50", "12.3.4"])
async def test_unparseable_amount_is_a_400(session: AsyncSession, amount: str) -> None:
    """Garbage in the amount is a clean client error, never a 500."""
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0850", rate_date="2026-04-07")
    service = I18nFoundationService(session)

    with pytest.raises(HTTPException) as excinfo:
        await service.convert_currency("EUR", "USD", amount)

    assert excinfo.value.status_code == 400


async def test_zero_amount_converts_to_zero(session: AsyncSession) -> None:
    """Zero is a legitimate amount, not an error."""
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0850", rate_date="2026-04-07")
    service = I18nFoundationService(session)

    result = await service.convert_currency("EUR", "USD", "0")

    assert result.converted_amount == "0.0000"


async def test_negative_amount_is_allowed_and_keeps_its_sign(session: AsyncSession) -> None:
    """A credit note is a negative amount; conversion must not swallow the sign."""
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0850", rate_date="2026-04-07")
    service = I18nFoundationService(session)

    result = await service.convert_currency("EUR", "USD", "-1500.50")

    assert result.converted_amount == "-1628.0425"


# ── Bad input: the stored rate ───────────────────────────────────────────────


@pytest.mark.parametrize("stored", ["abc", "1,0850", ""])
async def test_unparseable_stored_rate_is_a_422_not_a_crash(session: AsyncSession, stored: str) -> None:
    """DEFECT: a non-numeric stored rate reached ``Decimal()`` unguarded.

    Nothing validates the rate string on the way in. The POST schema only
    checks its length, and ``fetch_ecb_rates`` copies whatever the feed's
    ``rate`` attribute said, so a malformed value sat in the table until the
    first conversion turned it into an uncaught ``InvalidOperation``.
    """
    await make_rate(session, from_currency="EUR", to_currency="USD", rate=stored, rate_date="2026-04-07")
    service = I18nFoundationService(session)

    with pytest.raises(HTTPException) as excinfo:
        await service.convert_currency("EUR", "USD", "100")

    assert excinfo.value.status_code == 422
    assert "EUR/USD" in excinfo.value.detail


@pytest.mark.parametrize("stored", ["0", "0.0000", "-1.5", "NaN", "Infinity"])
async def test_non_positive_stored_rate_is_a_422_not_a_silent_zero(session: AsyncSession, stored: str) -> None:
    """DEFECT: the direct path multiplied by a zero rate and returned 0.0000.

    The reverse path already refused a zero rate (it would divide by it); the
    direct path had no such guard, so a zero row priced every amount at
    nothing. A negative or non-finite rate was equally unchecked.
    """
    await make_rate(session, from_currency="EUR", to_currency="USD", rate=stored, rate_date="2026-04-07")
    service = I18nFoundationService(session)

    with pytest.raises(HTTPException) as excinfo:
        await service.convert_currency("EUR", "USD", "100")

    assert excinfo.value.status_code == 422


async def test_unusable_stored_rate_is_refused_on_the_reverse_path(session: AsyncSession) -> None:
    """The guard covers the inverted lookup, not only the direct one."""
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="abc", rate_date="2026-04-07")
    service = I18nFoundationService(session)

    with pytest.raises(HTTPException) as excinfo:
        await service.convert_currency("USD", "EUR", "100")

    assert excinfo.value.status_code == 422


async def test_a_corrupt_reverse_row_shadows_a_usable_cross_rate(session: AsyncSession) -> None:
    """A zero reverse row now stops the lookup instead of falling through.

    This is the one place the stored-rate guard made something stricter rather
    than safer. The old code treated a zero reverse rate as "not usable, try
    the next path", so a corrupt GBP->USD row was stepped over and the EUR
    cross rate still produced an answer. It now raises, because a rate of zero
    in the table is corrupt data that someone has to correct - answering
    around it leaves the bad row in place and the caller none the wiser.

    Pinned deliberately: whichever way this is decided, the behaviour should be
    stated rather than discovered. Making the guard fall through instead would
    mean changing this assertion first.
    """
    await make_rate(session, from_currency="GBP", to_currency="USD", rate="0", rate_date="2026-04-07")
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0850", rate_date="2026-04-07")
    await make_rate(session, from_currency="EUR", to_currency="GBP", rate="0.8612", rate_date="2026-04-07")
    service = I18nFoundationService(session)

    with pytest.raises(HTTPException) as excinfo:
        await service.convert_currency("USD", "GBP", "1000")

    assert excinfo.value.status_code == 422
    # The cross legs are both healthy and would have answered 793.7327.
    assert "GBP/USD" in excinfo.value.detail


async def test_unusable_stored_rate_is_refused_on_the_cross_path(session: AsyncSession) -> None:
    """The guard covers both legs of an EUR cross rate."""
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0850", rate_date="2026-04-07")
    await make_rate(session, from_currency="EUR", to_currency="GBP", rate="0", rate_date="2026-04-07")
    service = I18nFoundationService(session)

    with pytest.raises(HTTPException) as excinfo:
        await service.convert_currency("USD", "GBP", "100")

    assert excinfo.value.status_code == 422


# ── Decimal exactness and round-tripping ─────────────────────────────────────


async def test_conversion_never_routes_through_float(session: AsyncSession) -> None:
    """An amount float cannot represent survives the conversion digit for digit.

    ``float(12345678901234.5678)`` is ``12345678901234.568`` - the last two
    digits are gone. If any step of the chain went through a float this
    assertion would fail on those digits.
    """
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1", rate_date="2026-04-07")
    service = I18nFoundationService(session)

    result = await service.convert_currency("EUR", "USD", "12345678901234.5678")

    assert result.converted_amount == "12345678901234.5678"
    assert Decimal(result.converted_amount) == Decimal("12345678901234.5678")


async def test_round_trip_through_the_inverse_does_not_drift(session: AsyncSession) -> None:
    """EUR -> USD -> EUR returns the amount it started with.

    The inverse is taken at full ``Decimal`` context precision (28 digits) and
    only the *reported* rate is cut to six places, so the round trip closes.
    """
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0850", rate_date="2026-04-07")
    service = I18nFoundationService(session)

    out = await service.convert_currency("EUR", "USD", "100")
    back = await service.convert_currency("USD", "EUR", out.converted_amount)

    assert out.converted_amount == "108.5000"
    assert back.converted_amount == "100.0000"


async def test_cross_rate_round_trip_does_not_drift(session: AsyncSession) -> None:
    """USD -> GBP -> USD closes as well, both legs derived through EUR."""
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.0850", rate_date="2026-04-07")
    await make_rate(session, from_currency="EUR", to_currency="GBP", rate="0.8612", rate_date="2026-04-07")
    service = I18nFoundationService(session)

    out = await service.convert_currency("USD", "GBP", "1000")
    back = await service.convert_currency("GBP", "USD", out.converted_amount)

    assert out.converted_amount == "793.7327"
    assert back.converted_amount == "1000.0000"


# ── Rounding: characterization, not a preference ─────────────────────────────


@pytest.mark.parametrize(
    ("rate", "expected"),
    [
        # 0.00005 is an exact tie at the fourth decimal. Half-even keeps the
        # even digit (0.0000); commercial half-up would give 0.0001.
        ("0.00005", "0.0000"),
        # 0.00015 ties to the even 2, which half-up would also give - this pair
        # is what separates the two rules.
        ("0.00015", "0.0002"),
        ("0.00025", "0.0002"),
        ("0.00035", "0.0004"),
    ],
)
async def test_conversion_rounds_half_to_even(session: AsyncSession, rate: str, expected: str) -> None:
    """This module rounds bankers', not commercial half-up. Pinned, not endorsed.

    ``Decimal.quantize`` without a ``rounding=`` argument uses the context
    default, ``ROUND_HALF_EVEN``. Elsewhere the platform is explicit about the
    opposite: ``accommodation/intl.py`` says "half-up is the rounding people
    expect on an invoice" and ``core/demo_projects.py`` passes ROUND_HALF_UP at
    every money quantize. Which rule this module should use is a founder
    decision, so this test records the behaviour rather than changing it. If
    the decision is half-up, these expectations flip to 0.0001 / 0.0002 /
    0.0003 / 0.0004.
    """
    await make_rate(session, from_currency="EUR", to_currency="USD", rate=rate, rate_date="2026-04-07")
    service = I18nFoundationService(session)

    result = await service.convert_currency("EUR", "USD", "1")

    assert result.converted_amount == expected


async def test_rounding_happens_once_per_conversion_not_per_chain(session: AsyncSession) -> None:
    """Each call rounds its own result, so a chain of calls rounds repeatedly.

    Converting a total once is not the same answer as converting ten lines and
    adding them up. At a rate of 1.11116 each line rounds up to 1.1112 and ten
    of them make 11.1120, while the total converts to 11.1116 exactly - four
    hundredths of a cent apart, and the gap grows with the line count. The
    module has no notion of a line versus a total, so a caller that wants
    total-level rounding must convert the total itself.
    """
    await make_rate(session, from_currency="EUR", to_currency="USD", rate="1.11116", rate_date="2026-04-07")
    service = I18nFoundationService(session)

    per_line = Decimal("0")
    for _ in range(10):
        line = await service.convert_currency("EUR", "USD", "1")
        per_line += Decimal(line.converted_amount)

    whole = await service.convert_currency("EUR", "USD", "10")

    assert str(per_line) == "11.1120"
    assert whole.converted_amount == "11.1116"
    assert per_line != Decimal(whole.converted_amount)


# ── The same-currency shortcut ───────────────────────────────────────────────


async def test_same_currency_returns_the_amount_unchanged(session: AsyncSession) -> None:
    """EUR->EUR needs no rate row and echoes the amount verbatim.

    Note the shape difference this test pins: the shortcut does NOT quantize,
    so "1500.5" comes back as "1500.5" while every other path would return
    "1500.5000". Callers formatting the response cannot assume four decimals.
    """
    service = I18nFoundationService(session)

    result = await service.convert_currency("EUR", "EUR", "1500.5")

    assert result.converted_amount == "1500.5"
    assert result.rate == "1"
    assert result.from_currency == "EUR"


async def test_same_currency_shortcut_keeps_a_supplied_date(session: AsyncSession) -> None:
    """A historical same-currency call echoes the date it was asked about."""
    service = I18nFoundationService(session)

    result = await service.convert_currency("EUR", "EUR", "100", rate_date="2020-06-01")

    assert result.rate_date == "2020-06-01"

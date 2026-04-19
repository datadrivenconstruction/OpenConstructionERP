"""ECB exchange rate fetcher.

Fetches daily exchange rates from the European Central Bank's public XML feed.
All rates are EUR-based (from_currency=EUR). Handles network errors gracefully
by returning an empty list on failure.

Usage:
    rates = await fetch_ecb_daily_rates()
    # [{"from_currency": "EUR", "to_currency": "USD", "rate": "1.0850", ...}, ...]
"""

import logging

import defusedxml.ElementTree as ElementTree
import httpx

logger = logging.getLogger(__name__)

# ECB daily reference rates XML feed (lightweight, no auth required)
ECB_DAILY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

# XML namespace used by ECB feed
_ECB_NS = "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"


async def fetch_ecb_daily_rates() -> list[dict]:
    """Fetch daily EUR exchange rates from the ECB XML feed.

    Parses the ECB's eurofxref-daily.xml response and extracts currency
    pairs. All rates are EUR-based (EUR -> target currency).

    Returns:
        List of dicts with keys:
            - from_currency: always "EUR"
            - to_currency: target currency code (e.g. "USD", "GBP")
            - rate: exchange rate as string (e.g. "1.0850")
            - rate_date: ISO date string (e.g. "2026-04-07")
            - source: always "ecb"

        Returns an empty list on any network or parsing error.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(ECB_DAILY_URL)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Failed to fetch ECB rates: %s", exc)
        return []
    except Exception:
        logger.exception("Unexpected error fetching ECB rates")
        return []

    try:
        return _parse_ecb_xml(response.text)
    except Exception:
        logger.exception("Failed to parse ECB XML response")
        return []


def _parse_ecb_xml(xml_text: str) -> list[dict]:
    """Parse ECB eurofxref-daily.xml into a list of rate dicts.

    The XML structure is:
        <Cube>
          <Cube time="2026-04-07">
            <Cube currency="USD" rate="1.0850"/>
            <Cube currency="GBP" rate="0.8612"/>
            ...
          </Cube>
        </Cube>

    Args:
        xml_text: Raw XML response body.

    Returns:
        List of rate dicts ready for storage.
    """
    root = ElementTree.fromstring(xml_text)
    rates: list[dict] = []

    # Find the time-stamped Cube element
    # Namespace-aware search
    ns = {"ecb": _ECB_NS}
    time_cube = root.find(f".//{{{_ECB_NS}}}Cube[@time]")

    if time_cube is None:
        # Fallback: try without namespace (some proxy responses strip namespaces)
        time_cube = root.find(".//Cube[@time]")

    if time_cube is None:
        logger.warning("ECB XML: no Cube element with 'time' attribute found")
        return []

    rate_date = time_cube.get("time", "")

    # Iterate over currency Cube elements
    for cube in time_cube:
        currency = cube.get("currency")
        rate = cube.get("rate")
        if currency and rate:
            rates.append(
                {
                    "from_currency": "EUR",
                    "to_currency": currency.upper(),
                    "rate": rate,
                    "rate_date": rate_date,
                    "source": "ecb",
                }
            )

    logger.info("Parsed %d ECB exchange rates for date %s", len(rates), rate_date)
    return rates

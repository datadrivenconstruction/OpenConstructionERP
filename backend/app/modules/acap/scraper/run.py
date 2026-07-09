"""Runnable end-to-end scraper — fetch, parse, and persist Batam price data.

Run from the container: ``python -m app.modules.acap.scraper.run``
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.modules.acap.scraper.arsiteqi import parse_arsiteqi
from app.modules.acap.scraper.persist import persist_prices
from app.modules.acap.scraper.sobatbangun import parse_sobatbangun

ADAPTERS: list[tuple[str, Any]] = [
    (
        "https://arsiteqi.or.id/upah/tukang-bangunan-batam/",
        parse_arsiteqi,
    ),
    (
        "https://sobatbangun.com/artikel/harga-material-bangunan-terbaru/",
        parse_sobatbangun,
    ),
]

USER_AGENT = (
    "Mozilla/5.0 (compatible; ACAP-Scraper/0.1; +https://github.com/datadrivenconstruction/OpenConstructionERP)"
)


async def scrape_all(session) -> dict[str, Any]:
    """Fetch every adapter's page, parse, and persist records.

    Returns a summary: ``{"persisted": n, "failures": [...], "failure_rate": f}``.
    """
    from app.modules.acap.scraper.base import PriceRecord

    all_records: list[PriceRecord] = []
    failures: list[dict[str, str]] = []

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=30.0,
        follow_redirects=True,
    ) as client:
        for url, parser in ADAPTERS:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                records = parser(resp.text, url)
                all_records.extend(records)
            except Exception as exc:
                failures.append({"url": url, "error": str(exc)})

    total_adapters = len(ADAPTERS)
    failure_rate = len(failures) / total_adapters if total_adapters > 0 else 0.0

    if all_records:
        persisted = await persist_prices(session, region_code="BATAM", records=all_records)
    else:
        persisted = 0

    return {
        "persisted": persisted,
        "failures": failures,
        "failure_rate": failure_rate,
    }


async def _main() -> None:
    from app.database import async_session_factory

    async with async_session_factory() as session:
        summary = await scrape_all(session)
        print(f"Persisted: {summary['persisted']}")
        if summary["failures"]:
            print(f"Failures ({summary['failure_rate']:.0%}):")
            for f in summary["failures"]:
                print(f"  {f['url']}: {f['error']}")
        else:
            print("All adapters succeeded.")


if __name__ == "__main__":
    asyncio.run(_main())

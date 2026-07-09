"""Gated weekly scheduler for ACAP Batam price scraping.

Only activates when env ``ACAP_SCRAPER_ENABLED=true``.  Keeps dev/test
environments from hitting the network on boot.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)

_TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
_TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()


async def _alert(message: str) -> None:
    """Send a Telegram alert or log a warning if not configured."""
    if _TELEGRAM_TOKEN and _TELEGRAM_CHAT_ID:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"https://api.telegram.org/bot{_TELEGRAM_TOKEN}/sendMessage",
                    json={
                        "chat_id": _TELEGRAM_CHAT_ID,
                        "text": f"[ACAP Scraper] {message}",
                        "parse_mode": "Markdown",
                    },
                )
        except Exception:
            logger.exception("Failed to send Telegram alert")
    else:
        logger.warning("[ACAP Scraper Alert] %s", message)


async def _scheduled_scrape() -> None:
    """Run the full scrape and alert on high failure rate."""
    from app.database import async_session_factory
    from app.modules.acap.scraper.run import scrape_all

    async with async_session_factory() as session:
        summary = await scrape_all(session)

    logger.info(
        "Weekly scrape: persisted=%d failures=%d rate=%.0f%%",
        summary["persisted"],
        len(summary["failures"]),
        summary["failure_rate"] * 100,
    )

    if summary["failure_rate"] > 0.5:
        await _alert(
            f"ACAP scraper failure rate {summary['failure_rate']:.0%} — "
            f"{len(summary['failures'])}/{len(summary.get('adapters', ['?','?']))} adapters failed.\n"
            + "\n".join(f"- `{f['url']}`: {f['error']}" for f in summary["failures"])
        )


def register_weekly(scheduler) -> None:
    """Add a Monday 03:00 weekly scrape job to *scheduler*."""
    scheduler.add_job(
        _scheduled_scrape,
        "cron",
        day_of_week="mon",
        hour=3,
        minute=0,
        id="acap_weekly_scrape",
        replace_existing=True,
    )
    logger.info("Registered weekly ACAP scrape (Mon 03:00)")


def maybe_start_scheduler() -> None:
    """Start the APScheduler background scheduler if ``ACAP_SCRAPER_ENABLED=true``.

    Safe to call on every startup — does nothing when the flag is not set.
    """
    if os.environ.get("ACAP_SCRAPER_ENABLED", "").strip().lower() != "true":
        logger.debug("ACAP_SCRAPER_ENABLED is not set — scheduler stays off")
        return

    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()
    register_weekly(scheduler)
    scheduler.start()
    logger.info("ACAP weekly scraper scheduler started")

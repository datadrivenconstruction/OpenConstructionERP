"""AI Civil Architecture Platform (ACAP) module — layout generation, RAB, timeline, render."""


async def on_startup() -> None:
    """Module startup hook — start the scraper scheduler if enabled."""
    from app.modules.acap.scraper.schedule import maybe_start_scheduler

    maybe_start_scheduler()

"""Dashboards module — analytical layer over snapshots.

Tasks in scope (see ``CLAUDE-DASHBOARDS.md`` in the repo root):
    T01 Data Snapshot Registry
    T02 Quick-Insight Panel
    T03 Smart Value Autocomplete
    T04 Cascade Filter Engine
    T05 Dashboards & Collections
    T06 Tabular Data I/O
    T07 Dataset Integrity Overview
    T09 Model-Dashboard Sync Protocol
    T10 Multi-Source Project Federation
    T11 Historical Snapshot Navigator

Architecture overview (ADR-001): SQLAlchemy + alembic for metadata, the
configured ``StorageBackend`` for Parquet blobs, DuckDB read-only
connection pool for analytical queries.
"""

from __future__ import annotations

import logging

from app.core.events import event_bus
from app.modules.dashboards import events as event_taxonomy

logger = logging.getLogger(__name__)

_SUBSCRIBERS_REGISTERED = False


def _on_snapshot_refreshed(event):  # type: ignore[no-untyped-def]
    """T09 sync protocol — mark every preset pointing at the refreshed
    snapshot as ``sync_status='stale'``.

    The handler is intentionally minimal: it opens its own session via
    the application factory, runs one bulk update, and returns. Errors
    are logged but never re-raised — a sync-status bookkeeping miss
    must not break snapshot creation.
    """
    import asyncio

    snapshot_id = event.data.get("snapshot_id") if hasattr(event, "data") else None
    tenant_id = event.data.get("tenant_id") if hasattr(event, "data") else None
    if not snapshot_id:
        return

    async def _run() -> None:
        try:
            from app.database import async_session_factory
            from app.modules.dashboards.presets_repository import (
                DashboardPresetRepository,
            )

            async with async_session_factory() as session:
                repo = DashboardPresetRepository(session)
                moved = await repo.mark_stale_for_snapshot(
                    snapshot_id, tenant_id=tenant_id,
                )
                if moved:
                    await session.commit()
                    logger.info(
                        "dashboards.sync.marked_stale snapshot_id=%s count=%d",
                        snapshot_id,
                        moved,
                    )
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning(
                "dashboards.sync.mark_stale_failed snapshot_id=%s: %s",
                snapshot_id,
                type(exc).__name__,
                exc_info=True,
            )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Sync context — block until done. Only happens when an event
        # is published from a non-async test or CLI script.
        asyncio.run(_run())
    else:
        loop.create_task(_run())


def register_subscribers() -> None:
    """Idempotent — call multiple times safely (tests do)."""
    global _SUBSCRIBERS_REGISTERED
    if _SUBSCRIBERS_REGISTERED:
        return
    event_bus.subscribe(
        event_taxonomy.SNAPSHOT_REFRESHED, _on_snapshot_refreshed,
    )
    _SUBSCRIBERS_REGISTERED = True


# Register on import — the module loader pulls in models.py which
# imports this package, so this fires at startup.
register_subscribers()

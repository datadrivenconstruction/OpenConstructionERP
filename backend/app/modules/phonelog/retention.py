# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Time-based retention for call recordings.

A recording is kept so a doubtful transcript can be checked against it, which
matters in the weeks after the call, not forever. Recordings older than the
retention window are deleted from storage and the row's ``audio_storage_key``
is cleared; the phone log itself, its transcript and extracted items stay.

``OE_PHONELOG_AUDIO_RETENTION_DAYS`` sets the window (default 90). ``0`` keeps
recordings until their phone log is deleted.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DEFAULT_AUDIO_RETENTION_DAYS = 90
SWEEP_INTERVAL_SECONDS = 24 * 3600


def audio_retention_days() -> int:
    """The configured retention window in days; 0 means no time-based expiry."""
    raw = os.environ.get("OE_PHONELOG_AUDIO_RETENTION_DAYS", "").strip()
    if not raw:
        return DEFAULT_AUDIO_RETENTION_DAYS
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning(
            "OE_PHONELOG_AUDIO_RETENTION_DAYS=%r is not a number, using %d", raw, DEFAULT_AUDIO_RETENTION_DAYS
        )
        return DEFAULT_AUDIO_RETENTION_DAYS


async def prune_expired_recordings(
    session: AsyncSession,
    *,
    retention_days: int | None = None,
    now: datetime | None = None,
) -> int:
    """Delete recordings older than the window and clear their keys.

    Returns how many recordings were removed. A storage delete that fails
    leaves that row's key in place so the next sweep retries it. The caller
    commits.
    """
    from app.core.storage import get_storage_backend
    from app.modules.phonelog.models import PhoneLog

    days = audio_retention_days() if retention_days is None else retention_days
    if days <= 0:
        return 0
    threshold = (now or datetime.now(UTC)) - timedelta(days=days)
    rows = (
        (
            await session.execute(
                select(PhoneLog).where(PhoneLog.audio_storage_key != "", PhoneLog.created_at < threshold)
            )
        )
        .scalars()
        .all()
    )
    storage = get_storage_backend()
    removed = 0
    for row in rows:
        try:
            await storage.delete(row.audio_storage_key)
        except Exception:  # noqa: BLE001 - retry on the next sweep
            logger.warning("phonelog retention: could not delete recording of %s", row.id)
            continue
        row.audio_storage_key = ""
        removed += 1
    await session.flush()
    if removed:
        logger.info("phonelog retention: removed %d recordings older than %d days", removed, days)
    return removed


async def retention_loop() -> None:
    """Daily sweep for the lifetime of the process. Safe to cancel."""
    import asyncio

    from app.database import async_session_factory

    while True:
        try:
            async with async_session_factory() as session:
                await prune_expired_recordings(session)
                await session.commit()
        except Exception:
            logger.exception("phonelog retention sweep failed")
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)

"""TTL cache for the project ``region`` string used by match boosts.

The ranker calls ``ProjectRepository(db).get_by_id(project_uuid)`` on every
match request just to read ``project.region`` — a single string used by the
region boost. Under 50× concurrent load this turns into 50 hot SELECTs.

This cache stores ``(region, expires_at)`` per project_uuid, keyed in-process.
A 60-second staleness window is fine: project regions virtually never change
mid-session, and even when they do, the boost is a small score adjustment
that recovers on the next cache rotation.

Concurrency:
    The cache is read by the asyncio loop only. We never block on the event
    loop — the lookup is dict-bound. Inflight DB fetches are de-duplicated
    via a per-key ``asyncio.Future`` so we don't get a thundering herd of
    50 concurrent SELECTs on a cold key.

The cache is cleared on demand by :func:`clear_project_region_cache` (used
by tests and by the project-update path so a region change is observable
within one request after the PATCH commits).
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# (region_or_None, expires_at_monotonic)
_cache: dict[uuid.UUID, tuple[str | None, float]] = {}
_inflight: dict[uuid.UUID, asyncio.Future[str | None]] = {}
_lock = asyncio.Lock()

# 60 seconds — a region change shows up on the next request; the staleness
# only affects the boost magnitude, never correctness.
DEFAULT_TTL_SECONDS = 60.0


async def region_for(
    db: AsyncSession,
    project_uuid: uuid.UUID,
    *,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
) -> str | None:
    """Return ``project.region`` for ``project_uuid`` with a TTL cache.

    Returns ``None`` if the project doesn't exist, the row has no region,
    or the DB lookup fails — callers should treat ``None`` as "skip the
    region boost".
    """
    now = time.monotonic()
    cached = _cache.get(project_uuid)
    if cached is not None:
        region, expires_at = cached
        if now < expires_at:
            return region

    # Coalesce concurrent misses. Multiple requests arriving in the same
    # event loop must share one DB fetch — otherwise a 50× concurrent
    # cold start re-issues 50 SELECTs (the very thing this cache exists
    # to prevent).
    async with _lock:
        # Re-check inside the lock — another coroutine may have populated
        # the cache while we were awaiting it.
        cached = _cache.get(project_uuid)
        if cached is not None and time.monotonic() < cached[1]:
            return cached[0]

        existing = _inflight.get(project_uuid)
        if existing is not None:
            fut = existing
        else:
            fut = asyncio.get_running_loop().create_future()
            _inflight[project_uuid] = fut
            asyncio.create_task(_load(db, project_uuid, ttl_seconds, fut))

    try:
        return await fut
    except Exception as exc:
        logger.debug("region_for(%s) failed: %s", project_uuid, exc)
        return None


async def _load(
    db: AsyncSession,
    project_uuid: uuid.UUID,
    ttl_seconds: float,
    fut: asyncio.Future[str | None],
) -> None:
    """Run the DB fetch, populate the cache, fulfil the future."""
    region: str | None = None
    try:
        from app.modules.projects.repository import ProjectRepository

        project = await ProjectRepository(db).get_by_id(project_uuid)
        if project is not None:
            region = getattr(project, "region", None)
            if region is not None:
                region = str(region)
    except Exception as exc:
        # Don't poison the cache for a transient DB hiccup — store None
        # for the TTL so the burst doesn't hammer the DB but recovery
        # happens within a minute.
        logger.debug("region_for: DB fetch failed for %s: %s", project_uuid, exc)
        region = None

    _cache[project_uuid] = (region, time.monotonic() + ttl_seconds)
    _inflight.pop(project_uuid, None)
    if not fut.done():
        fut.set_result(region)


def clear_project_region_cache(project_uuid: uuid.UUID | None = None) -> None:
    """Drop one or all entries from the region cache.

    Called by the project-update path so a ``PATCH /projects/{id}`` that
    changes ``region`` becomes observable on the very next match request,
    not after the 60-second TTL.
    """
    if project_uuid is None:
        _cache.clear()
    else:
        _cache.pop(project_uuid, None)


def cache_stats() -> dict[str, Any]:
    """Return basic stats for observability/tests."""
    now = time.monotonic()
    fresh = sum(1 for _, exp in _cache.values() if exp > now)
    return {
        "entries": len(_cache),
        "fresh": fresh,
        "stale": len(_cache) - fresh,
        "inflight": len(_inflight),
    }

"""A broker that is up but has no worker would keep a queued job for good; refuse it up front instead."""

from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException, status

log = logging.getLogger(__name__)

PING_TIMEOUT_S = 1.5
NO_WORKER = "no_worker"


def _worker_state() -> str:
    """'inline' (no broker or eager: core runs the job in-process), 'worker' or 'none'."""
    try:
        from kombu.exceptions import OperationalError

        from app.core.jobs import get_celery_app
    except ImportError:
        return "inline"
    app = get_celery_app()
    if app.conf.task_always_eager:
        return "inline"
    try:
        with app.connection_for_write() as conn:
            conn.ensure_connection(max_retries=0, timeout=2.0)
    except (OperationalError, ConnectionError, OSError, TimeoutError):
        return "inline"  # core falls back to in-process when the broker is unreachable
    try:
        replies = app.control.ping(timeout=PING_TIMEOUT_S)
    except Exception:  # noqa: BLE001
        log.exception("design job: worker ping failed")
        return "none"
    return "worker" if replies else "none"


async def require_runner() -> None:
    if await asyncio.to_thread(_worker_state) == "none":
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {
                "code": NO_WORKER,
                "message": "A job queue is configured but no worker is running, so the job would never start",
            },
        )

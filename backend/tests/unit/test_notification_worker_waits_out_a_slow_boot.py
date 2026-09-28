"""The notification worker waits out a database that is still booting.

A flush that times out reaching the database during a slow boot used to log a
full traceback on every tick. It now logs one warning, retries on a short
backoff, and says once when the database answers again. A real bug in the
flush is still logged with its traceback.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from app.modules.notifications.notification_worker import _is_transient_db_error, _run_periodically

_LOGGER = "app.modules.notifications.notification_worker"


async def _drive(factory, shutdown: asyncio.Event, *, interval: float, retry_base: float) -> None:
    await asyncio.wait_for(
        _run_periodically("probe", factory, interval, shutdown, retry_base_sec=retry_base),
        timeout=5,
    )


async def test_transient_failures_log_one_warning_then_recover(caplog: pytest.LogCaptureFixture) -> None:
    shutdown = asyncio.Event()
    calls = 0

    async def factory() -> int:
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise TimeoutError("connect timed out")
        shutdown.set()
        return 0

    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    await _drive(factory, shutdown, interval=0.05, retry_base=0.001)

    records = [r for r in caplog.records if r.name == _LOGGER]
    assert calls == 3
    assert [r.levelno for r in records if r.levelno >= logging.WARNING] == [logging.WARNING]
    assert not any(r.exc_info for r in records)
    assert sum("reached the database after 3 attempts" in r.getMessage() for r in records) == 1


async def test_retry_comes_before_the_interval() -> None:
    shutdown = asyncio.Event()
    calls = 0

    async def factory() -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PoolTimeoutError("QueuePool limit reached")
        shutdown.set()
        return 0

    loop = asyncio.get_running_loop()
    # Interval of 2 s: the first run lands after it, the retry must not wait
    # another 2 s.
    started = loop.time()
    await _drive(factory, shutdown, interval=2.0, retry_base=0.01)
    assert calls == 2
    assert loop.time() - started < 3.5


async def test_a_real_bug_is_still_logged_with_its_traceback(caplog: pytest.LogCaptureFixture) -> None:
    shutdown = asyncio.Event()

    async def factory() -> int:
        shutdown.set()
        raise ValueError("bad row")

    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    await _drive(factory, shutdown, interval=0.01, retry_base=0.001)

    errors = [r for r in caplog.records if r.name == _LOGGER and r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert errors[0].exc_info is not None


def test_only_connection_trouble_counts_as_transient() -> None:
    assert _is_transient_db_error(TimeoutError())
    assert _is_transient_db_error(ConnectionRefusedError())
    assert _is_transient_db_error(PoolTimeoutError("pool"))
    assert not _is_transient_db_error(ValueError())
    assert not _is_transient_db_error(KeyError("x"))

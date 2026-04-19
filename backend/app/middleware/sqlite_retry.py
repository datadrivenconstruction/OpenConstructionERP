"""SQLite lock-retry middleware.

SQLite serializes writers on a single file lock. Under concurrent load
(two requests mutating the same DB at once) the second one fails with
``sqlite3.OperationalError: database is locked``. This is a transient
failure — the correct response is to retry after a short jitter, not
return 500 to the client (Part 5 BUG-118/119, ENH-091).

The middleware wraps every request:
  - First attempt: straight through.
  - On OperationalError whose message contains "locked", retry up to
    ``_MAX_ATTEMPTS`` times with exponential backoff + small random jitter.
  - Anything non-lock-related re-raises immediately.

Only engaged when the underlying engine dialect is sqlite — on PostgreSQL
this is a no-op (MVCC, no file lock).
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Awaitable, Callable

from sqlalchemy.exc import OperationalError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Three attempts total: first try + 2 retries. 100ms → 200ms backoff + ±25ms jitter.
_MAX_ATTEMPTS = 3
_BASE_BACKOFF_SECONDS = 0.1


def _is_sqlite_lock(exc: BaseException) -> bool:
    """True iff the exception is a SQLite busy/locked signal."""
    msg = str(getattr(exc, "orig", exc) or exc).lower()
    return "database is locked" in msg or "database table is locked" in msg


class SQLiteLockRetryMiddleware(BaseHTTPMiddleware):
    """Retry the request pipeline when SQLite reports a lock contention."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        last_exc: OperationalError | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                return await call_next(request)
            except OperationalError as exc:
                if not _is_sqlite_lock(exc):
                    raise
                last_exc = exc
                if attempt == _MAX_ATTEMPTS:
                    # Out of retries — fall through and re-raise below.
                    break
                backoff = _BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
                jitter = random.uniform(0, backoff * 0.25)
                logger.warning(
                    "SQLite lock contention on %s %s (attempt %d/%d) — retry in %.3fs",
                    request.method,
                    request.url.path,
                    attempt,
                    _MAX_ATTEMPTS,
                    backoff + jitter,
                )
                await asyncio.sleep(backoff + jitter)

        assert last_exc is not None  # unreachable — loop always sets it
        logger.error(
            "SQLite lock contention on %s %s exhausted %d retries",
            request.method,
            request.url.path,
            _MAX_ATTEMPTS,
        )
        raise last_exc

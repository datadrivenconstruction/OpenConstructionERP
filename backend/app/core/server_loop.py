# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Which asyncio event loop the HTTP server runs on.

On Windows the server keeps the proactor loop that uvicorn picks there by
default, with one change: a failed accept is retried instead of ending the
server. Linux and macOS are untouched and keep whatever uvicorn chooses.

The defect. CPython's proactor loop closes the LISTENING socket when one accept
fails. ``BaseProactorEventLoop._start_serving`` (Lib/asyncio/proactor_events.py
in 3.12) catches any ``OSError`` from the accept future, logs "Accept failed on
a socket" and calls ``sock.close()`` on the listener, and nothing opens it
again. The process stays up, the port refuses every connection, and to a
desktop user the app is frozen until it is restarted. One client that resets
its connection while it waits in the listen backlog is enough: Windows then
completes the next ``AcceptEx`` with ``ERROR_NETNAME_DELETED`` (WinError 64).
Browsers do that when the server is slow to accept, which is when it happened
in the field: a test server logged the WinError 64 at 11:45:08 and never
accepted another connection.

The fix. The loop gets a proactor whose ``accept`` hides those per-connection
errors from ``_start_serving``: when the pending ``AcceptEx`` fails because the
client went away, it posts a new one on the same listener and the future
``_start_serving`` holds simply resolves later, with the next client. Any other
error, a closed listener, or a cancellation still reaches ``_start_serving``
unchanged, so shutting the server down works as before.

Why not the selector loop, which has no such accept path: on Windows it loses
outgoing data. ``_SelectorSocketTransport._write_send`` pops a buffer off the
queue before ``send()`` and drops it when ``send()`` raises
``BlockingIOError``. Windows sockets have no ``sendmsg``, so that is the only
write path there, and asyncpg's ``executemany`` feeds it through
``writelines``. Measured on Windows 11 / CPython 3.12.11 against PostgreSQL:
an ``executemany`` of 346 UPDATE statements applied 313 of them and reported
success. A server that silently skips writes is worse than one that stops
answering.
``backend/tests/unit/test_the_windows_server_loop_survives_a_reset_client.py``
replays the accept failure with real sockets.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

logger = logging.getLogger(__name__)

#: Windows error codes that end one pending accept because of the client, not
#: the listener: the connection was reset (WSAECONNRESET 10054), aborted
#: (WSAECONNABORTED 10053, ERROR_CONNECTION_ABORTED 1236) or its peer vanished
#: from the backlog (ERROR_NETNAME_DELETED 64).
TRANSIENT_ACCEPT_ERRORS = frozenset({64, 1236, 10053, 10054})

#: How many failed accepts in a row one pending accept absorbs before it hands
#: the error on. A listener that fails every time is broken, and the stock
#: behaviour (log and close) is then the honest outcome.
MAX_ACCEPT_RETRIES = 100


def is_transient_accept_error(exc: BaseException) -> bool:
    """True for an accept error caused by the client rather than the listener."""
    return isinstance(exc, OSError) and getattr(exc, "winerror", None) in TRANSIENT_ACCEPT_ERRORS


if sys.platform == "win32":
    import _overlapped
    import socket
    import struct
    from asyncio import windows_events

    class AcceptRetryingProactor(asyncio.IocpProactor):
        """IOCP proactor whose ``accept`` survives clients that reset in the backlog."""

        def accept(self, listener: Any) -> asyncio.Future[Any]:
            """Accept the next client, re-posting the accept when one fails transiently.

            Args:
                listener: The listening socket.

            Returns:
                A future for ``(conn, address)``, as ``IocpProactor.accept``.
            """
            loop: asyncio.AbstractEventLoop = self._loop  # type: ignore[attr-defined]
            outer: asyncio.Future[Any] = loop.create_future()
            pending: list[asyncio.Future[Any]] = []
            failures = 0

            def post() -> None:
                try:
                    inner = self._accept_once(listener)
                except BaseException as exc:
                    if not outer.done():
                        outer.set_exception(exc)
                    return
                pending[:] = [inner]
                inner.add_done_callback(finished)

            def finished(inner: asyncio.Future[Any]) -> None:
                nonlocal failures
                if outer.done():
                    return
                if inner.cancelled():
                    outer.cancel()
                    return
                exc = inner.exception()
                if exc is None:
                    outer.set_result(inner.result())
                    return
                if is_transient_accept_error(exc) and listener.fileno() != -1 and failures < MAX_ACCEPT_RETRIES:
                    failures += 1
                    logger.warning("A client left before its connection was accepted (%s); still listening", exc)
                    post()
                    return
                outer.set_exception(exc)

            def cancel_pending(fut: asyncio.Future[Any]) -> None:
                if fut.cancelled():
                    for inner in pending:
                        if not inner.done():
                            inner.cancel()

            outer.add_done_callback(cancel_pending)
            post()
            return outer

        def _accept_once(self, listener: Any) -> asyncio.Future[Any]:
            """``IocpProactor.accept`` from CPython 3.12, without its orphan task.

            The stock method hands the future to a task that exists only to close
            the unused socket on cancellation. When the accept fails instead, that
            task ends with the error nobody awaits, and asyncio logs "Task
            exception was never retrieved" once per reset client. Here a done
            callback closes the socket on every outcome but success and leaves
            the error on the future, where :meth:`accept` reads it.
            """
            self._register_with_iocp(listener)  # type: ignore[attr-defined]
            conn = self._get_accept_socket(listener.family)  # type: ignore[attr-defined]
            try:
                ov = _overlapped.Overlapped(windows_events.NULL)
                ov.AcceptEx(listener.fileno(), conn.fileno())
            except BaseException:
                conn.close()
                raise

            def finish_accept(trans: Any, key: Any, ov: Any) -> tuple[Any, Any]:
                ov.getresult()
                # SO_UPDATE_ACCEPT_CONTEXT makes getsockname() and friends work on conn.
                buf = struct.pack("@P", listener.fileno())
                conn.setsockopt(socket.SOL_SOCKET, _overlapped.SO_UPDATE_ACCEPT_CONTEXT, buf)
                conn.settimeout(listener.gettimeout())
                return conn, conn.getpeername()

            def close_unused(fut: asyncio.Future[Any]) -> None:
                if fut.cancelled() or fut.exception() is not None:
                    conn.close()

            future: asyncio.Future[Any] = self._register(ov, listener, finish_accept)  # type: ignore[attr-defined]
            future.add_done_callback(close_unused)
            return future


def server_loop_factory() -> asyncio.AbstractEventLoop:
    """Create the event loop the server runs on under Windows.

    uvicorn calls this with no arguments through ``asyncio.Runner`` when it is
    named in ``loop=`` (see :func:`uvicorn_loop_option`).

    Returns:
        A proactor event loop built on :class:`AcceptRetryingProactor`.
    """
    return asyncio.ProactorEventLoop(proactor=AcceptRetryingProactor())


def uvicorn_loop_option() -> str:
    """Return the ``loop=`` value to pass to ``uvicorn.run`` on this platform.

    Off Windows this is ``"auto"``, uvicorn's own default, so nothing changes
    there. On Windows it is the import string of :func:`server_loop_factory`,
    built from the function itself so a rename cannot leave a stale string
    behind. The caller has imported this module to call this function, so
    uvicorn's ``import_from_string`` always resolves it, frozen bundle included.

    uvicorn reads a ``module:callable`` loop value as a loop factory from 0.36
    on (``Config.get_loop_factory``). Older releases, still allowed by the
    ``>=0.32`` pin, raise on a value they do not know, so there the server
    starts on uvicorn's default loop as before and a warning says why.

    Returns:
        The value for ``uvicorn.run(..., loop=...)``.
    """
    if sys.platform != "win32":
        return "auto"

    import uvicorn

    if not hasattr(uvicorn.Config, "get_loop_factory"):
        logger.warning(
            "uvicorn %s cannot take a custom event loop; the server keeps the stock proactor loop, which "
            "stops accepting connections after a client resets one. Upgrade uvicorn to 0.36 or later.",
            getattr(uvicorn, "__version__", "?"),
        )
        return "auto"
    return f"{server_loop_factory.__module__}:{server_loop_factory.__qualname__}"

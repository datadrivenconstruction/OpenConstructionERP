"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Keep the bytes the selector transport could not send yet.

CPython's ``_SelectorSocketTransport._write_send`` (3.12, still so in 3.12.11)
pops the head of the write buffer before calling ``send()``. When the socket
answers ``BlockingIOError`` or ``InterruptedError`` the popped chunk is never
put back, so those bytes are gone and nothing raises. The transport only takes
this path when ``socket.sendmsg`` is missing, which is Windows, and only under
the selector loop, which ``tests/conftest.py`` installs on Windows. Production
runs the proactor loop there and is not affected.

It is not a theoretical loss. asyncpg's executemany pipelines its rows through
``transport.writelines()``, and a 346-row UPDATE fan-out on a 2080-line project
reached PostgreSQL as 313 statements while the call reported all of them
written. A test that loses rows this way can pass or fail for the wrong reason,
so the test run patches the method before any transport exists (the transport
picks its writer in ``__init__``).

The replacement is the stdlib method with the one fix: a chunk ``send()``
refused goes back to the head of the buffer, and the writer stays registered
so the next write-ready event retries it.
"""

from __future__ import annotations

import socket
from asyncio import selector_events
from typing import Any


def write_send_keeping_the_buffer(self: Any) -> None:
    """``_SelectorSocketTransport._write_send`` that re-queues an unsent chunk."""
    assert self._buffer, "Data should not be empty"
    if self._conn_lost:
        return
    buffer = self._buffer.popleft()
    try:
        n = self._sock.send(buffer)
    except (BlockingIOError, InterruptedError):
        self._buffer.appendleft(buffer)
        return
    except (SystemExit, KeyboardInterrupt):
        self._buffer.appendleft(buffer)
        raise
    except BaseException as exc:
        self._loop._remove_writer(self._sock_fd)
        self._buffer.clear()
        self._fatal_error(exc, "Fatal write error on socket transport")
        if self._empty_waiter is not None:
            self._empty_waiter.set_exception(exc)
        return
    if n != len(buffer):
        # Not all data was written
        self._buffer.appendleft(buffer[n:])
    self._maybe_resume_protocol()  # May append to buffer.
    if not self._buffer:
        self._loop._remove_writer(self._sock_fd)
        if self._empty_waiter is not None:
            self._empty_waiter.set_result(None)
        if self._closing:
            self._call_connection_lost(None)
        elif self._eof:
            self._sock.shutdown(socket.SHUT_WR)


def install() -> None:
    """Swap the fixed method in. Must run before the first transport is built."""
    selector_events._SelectorSocketTransport._write_send = write_send_keeping_the_buffer  # type: ignore[method-assign]

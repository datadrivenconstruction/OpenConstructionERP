"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The test run's selector transport must not lose a chunk send() refused.

See ``tests/_asyncio_write_send.py``. These tests drive the replacement on
every platform (the stdlib only takes this path on Windows), through a real
selector loop and a socket pair, with a socket whose ``send`` refuses the
first attempts the way a full Windows socket buffer does.
"""

from __future__ import annotations

import asyncio
import collections
import socket
import sys
import types
from asyncio import selector_events

import pytest

from tests import _asyncio_write_send


class _RefusingSocket:
    """Delegates to a real socket, but its first ``refusals`` sends raise."""

    def __init__(self, sock: socket.socket, refusals: int) -> None:
        self._sock = sock
        self.refusals = refusals
        self.sends = 0

    def send(self, data: bytes) -> int:
        self.sends += 1
        if self.refusals > 0:
            self.refusals -= 1
            raise BlockingIOError
        return self._sock.send(data)

    def __getattr__(self, name: str) -> object:
        return getattr(self._sock, name)


async def _send_through_a_refusing_socket(payload: list[bytes], refusals: int) -> bytes:
    loop = asyncio.get_running_loop()
    ours, theirs = socket.socketpair()
    theirs.setblocking(False)
    transport, _ = await loop.create_connection(asyncio.Protocol, sock=ours)
    try:
        # Force the send() writer the stdlib only picks where sendmsg is missing.
        transport._write_ready = types.MethodType(_asyncio_write_send.write_send_keeping_the_buffer, transport)
        refusing = _RefusingSocket(transport._sock, refusals)
        transport._sock = refusing
        for chunk in payload:
            transport.write(chunk)
        for _ in range(200):
            if transport.get_write_buffer_size() == 0:
                break
            await asyncio.sleep(0.01)
        assert transport.get_write_buffer_size() == 0, "the buffer never drained"
        assert refusing.sends > refusals, "the write-ready path never ran"
        received = b""
        while True:
            try:
                chunk = theirs.recv(65536)
            except BlockingIOError:
                break
            if not chunk:
                break
            received += chunk
        return received
    finally:
        transport.close()
        theirs.close()


@pytest.mark.parametrize("refusals", [1, 2, 3])
def test_a_chunk_the_socket_refused_is_sent_later_not_dropped(refusals: int) -> None:
    payload = [b"BEGIN;", b"UPDATE 1;", b"UPDATE 2;", b"UPDATE 3;", b"COMMIT;"]
    loop = asyncio.SelectorEventLoop()
    try:
        received = loop.run_until_complete(_send_through_a_refusing_socket(payload, refusals))
    finally:
        loop.close()
    assert received == b"".join(payload)


def test_a_partial_send_keeps_the_rest_at_the_head() -> None:
    sent: list[bytes] = []

    class _HalfSocket:
        def send(self, data: bytes) -> int:
            half = max(1, len(data) // 2)
            sent.append(bytes(data[:half]))
            return half

    transport = types.SimpleNamespace(
        _buffer=collections.deque([b"abcdef", b"gh"]),
        _conn_lost=0,
        _sock=_HalfSocket(),
        _maybe_resume_protocol=lambda: None,
    )
    _asyncio_write_send.write_send_keeping_the_buffer(transport)
    assert sent == [b"abc"]
    assert list(transport._buffer) == [b"def", b"gh"]


@pytest.mark.skipif(sys.platform != "win32", reason="the test run patches the transport on Windows only")
def test_the_test_run_uses_the_fixed_writer_on_windows() -> None:
    assert selector_events._SelectorSocketTransport._write_send is _asyncio_write_send.write_send_keeping_the_buffer

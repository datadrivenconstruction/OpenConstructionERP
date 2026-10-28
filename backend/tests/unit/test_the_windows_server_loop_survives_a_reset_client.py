"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The server must keep accepting after a client resets in the listen backlog.

On Windows uvicorn runs on asyncio's proactor loop unless told otherwise, and
CPython's proactor loop closes the listening socket when one accept fails
(``BaseProactorEventLoop._start_serving``: "Accept failed on a socket", then
``sock.close()``). A client that resets its connection while waiting to be
accepted makes the next ``AcceptEx`` fail with WinError 64, so one impatient
browser was enough to leave the desktop backend alive but refusing every
connection: the app looked frozen until restarted. ``app.core.server_loop``
keeps the proactor loop on Windows but gives it a proactor that re-posts an
accept a vanished client made fail. It deliberately does not switch to the
selector loop, which drops outgoing data on Windows.

The socket tests replay that with real sockets and no mocks: reset a client in
the backlog, start serving, then connect a healthy client. The proactor leg is
the control. It shows the reproduction actually reproduces, so the server leg
passing means something. The loop under test is built the way the server builds
it, through ``uvicorn.Config(loop=uvicorn_loop_option()).get_loop_factory()``,
and each run uses an explicit ``asyncio.Runner`` so the loop policy the test
conftest installs cannot stand in for the fix.
"""

from __future__ import annotations

import asyncio
import socket
import struct
import sys
import time
from collections.abc import Callable
from types import SimpleNamespace

import pytest
import uvicorn

from app.core import server_loop
from app.core.server_loop import server_loop_factory, uvicorn_loop_option

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="the proactor loop and WinError 64 are Windows-only")


def _loop_factory_uvicorn_would_use() -> Callable[[], asyncio.AbstractEventLoop]:
    """Resolve ``uvicorn_loop_option()`` the way ``uvicorn.run`` does."""
    factory = uvicorn.Config("app.main:create_app", factory=True, loop=uvicorn_loop_option()).get_loop_factory()
    assert factory is not None
    return factory


def _reset_a_client_in_the_backlog(port: int) -> None:
    """Connect, then abort with RST (linger 0) before the server accepts."""
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect(("127.0.0.1", port))
    client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("hh", 1, 0))
    client.close()


def _healthy_client(port: int) -> bytes | str:
    """Connect and read the two bytes the server writes, or name the failure."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as conn:
            return conn.recv(2)
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"


async def _serve_after_reset_clients(resets: int = 1) -> dict[str, object]:
    """Serve on the running loop after ``resets`` clients reset in the backlog."""
    loop = asyncio.get_running_loop()
    reported: list[str] = []
    loop.set_exception_handler(lambda _loop, context: reported.append(str(context.get("message"))))

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(100)
    listener.setblocking(False)
    port = listener.getsockname()[1]

    for _ in range(resets):
        _reset_a_client_in_the_backlog(port)
    time.sleep(0.2)  # Let the RSTs land before anything accepts.

    class _SayOk(asyncio.Protocol):
        def connection_made(self, transport: asyncio.BaseTransport) -> None:
            assert isinstance(transport, asyncio.WriteTransport)
            transport.write(b"ok")
            transport.close()

    server = await loop.create_server(_SayOk, sock=listener)
    try:
        await asyncio.sleep(0.3)  # Give the loop its chance to trip over the reset client.
        answer = await asyncio.wait_for(asyncio.to_thread(_healthy_client, port), timeout=15)
        second = await asyncio.wait_for(asyncio.to_thread(_healthy_client, port), timeout=15)
        listener_open = listener.fileno() != -1
    finally:
        server.close()
        await server.wait_closed()
    return {"answer": answer, "second": second, "listener_open": listener_open, "reported": reported}


def _run_on(factory: Callable[[], asyncio.AbstractEventLoop], resets: int = 1) -> dict[str, object]:
    with asyncio.Runner(loop_factory=factory) as runner:
        return runner.run(_serve_after_reset_clients(resets))


def test_off_windows_uvicorn_keeps_its_own_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only the module's view of the platform, not ``sys.platform`` for the whole process.
    monkeypatch.setattr(server_loop, "sys", SimpleNamespace(platform="linux"))
    assert uvicorn_loop_option() == "auto"


@windows_only
def test_on_windows_uvicorn_resolves_the_option_to_the_retrying_proactor_loop() -> None:
    assert uvicorn_loop_option() == "app.core.server_loop:server_loop_factory"
    factory = _loop_factory_uvicorn_would_use()
    assert factory is server_loop_factory
    loop = factory()
    try:
        # Never the selector loop: on Windows it drops a write that meets a full send buffer.
        assert isinstance(loop, asyncio.ProactorEventLoop)
        assert not isinstance(loop, asyncio.SelectorEventLoop)
        assert isinstance(loop._proactor, server_loop.AcceptRetryingProactor)  # type: ignore[attr-defined]
    finally:
        loop.close()


@pytest.mark.parametrize(
    ("exc", "transient"),
    [
        (OSError(22, "gone", None, 64), True),
        (OSError(22, "aborted", None, 1236), True),
        (OSError(22, "reset", None, 10054), True),
        (OSError(22, "aborted", None, 10053), True),
        (OSError(22, "bad handle", None, 6), False),
        (OSError(22, "no winerror"), False),
        (ValueError("not an OSError"), False),
    ],
)
@windows_only  # ``OSError`` reads its fourth argument as ``winerror`` only on Windows.
def test_only_errors_caused_by_the_client_are_retried(exc: BaseException, transient: bool) -> None:
    assert server_loop.is_transient_accept_error(exc) is transient


@windows_only
def test_the_stock_proactor_loop_goes_deaf_after_one_reset_client() -> None:
    """Control: if this starts failing, CPython fixed the proactor accept path.

    Then the retrying proactor in app/core/server_loop.py is no longer needed
    for this defect and can be reconsidered, and this control should go with it.
    """
    outcome = _run_on(asyncio.ProactorEventLoop)
    assert outcome["listener_open"] is False
    assert "Accept failed on a socket" in outcome["reported"]
    assert outcome["answer"] != b"ok"


@windows_only
def test_the_server_loop_keeps_accepting_after_a_reset_client() -> None:
    outcome = _run_on(_loop_factory_uvicorn_would_use())
    assert outcome["answer"] == b"ok", f"the healthy client was not served: {outcome}"
    assert outcome["second"] == b"ok", f"the next client was not served: {outcome}"
    assert outcome["listener_open"] is True
    # Nothing at all: not "Accept failed on a socket", and not "Task exception was
    # never retrieved" from an accept helper left holding the client's error.
    assert outcome["reported"] == []


@windows_only
def test_the_server_loop_keeps_accepting_after_several_reset_clients() -> None:
    outcome = _run_on(_loop_factory_uvicorn_would_use(), resets=5)
    assert outcome["answer"] == b"ok", f"the healthy client was not served: {outcome}"
    assert outcome["second"] == b"ok", f"the next client was not served: {outcome}"
    assert outcome["listener_open"] is True
    assert outcome["reported"] == []

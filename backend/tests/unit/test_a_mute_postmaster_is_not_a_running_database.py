# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A listen socket is not a database, and the readiness probe has to know that.

A released build announced "Embedded PostgreSQL ready" and then failed every
connection it made in the next breath. The cluster it attached to was a
postmaster left alive by an earlier run that had died after starting it: the
process still held its listen socket, so a bare ``connect`` succeeded and the
probe reported a healthy database, while nothing behind that socket could serve
a session.

These tests pin both halves of the answer. The probe has to speak the protocol
rather than open a socket, and the recovery has to end a postmaster that only
listens - detection alone would leave the user exactly as stuck, with a better
worded failure.

The three states are deliberately distinguished, because two of them must never
be acted on: a cluster replaying WAL has not opened its socket yet, and a
cluster too busy to take another client answers with an error, which is an
answer. Only "accepts and says nothing" is the broken one.

The third thing pinned here is who the recovery is allowed to end. Deciding to
stop something is not the same as deciding what to stop, and the check that
answers the second question reads the operating system, which answers it
differently on each of the three platforms. So the ownership tests below assert
the same property on all of them, including with the machine-wide socket table
refusing to answer the way macOS refuses it.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple, NoReturn

import pytest

from app.core import embedded_pg


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _write_pidfile(
    pgdata: Path,
    pid: int,
    port: int,
    socket_dir: Path | str = "",
    listen_addresses: str = "127.0.0.1",
) -> None:
    """Write a postmaster.pid in PostgreSQL's own layout.

    Line 4 is the port and line 6 is the first ``listen_addresses`` entry, which
    is what the probe reads to decide whether to try TCP at all. Line 5 is the
    unix socket directory; it defaults to empty, the way Windows writes it, so
    the TCP branch is the one under test on every platform unless a test asks
    for the other family.
    """
    pgdata.mkdir(parents=True, exist_ok=True)
    (pgdata / "postmaster.pid").write_text(
        f"{pid}\n{pgdata}\n{int(time.time())}\n{port}\n{socket_dir}\n{listen_addresses}\n  1234567 0\n",
        encoding="utf-8",
    )


class _FakeServer:
    """A socket that behaves like a postmaster in one of three ways."""

    def __init__(self, behaviour: str) -> None:
        self.behaviour = behaviour
        self.port = _free_port()
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", self.port))
        self._sock.listen(8)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                self._sock.settimeout(0.3)
                conn, _ = self._sock.accept()
            except OSError:
                continue
            with conn:
                if self.behaviour == "mute":
                    # Accept and drop it. This is the shipped failure: the TCP
                    # handshake completes, so a bare connect is satisfied, and
                    # the client's startup packet is answered by a reset.
                    continue
                if self.behaviour == "silent":
                    # Accept and hold it open saying nothing, the other way a
                    # wedged server looks from outside.
                    time.sleep(2.0)
                    continue
                try:
                    conn.recv(1024)
                except OSError:
                    continue
                if self.behaviour == "authenticating":
                    conn.sendall(b"R\x00\x00\x00\x08\x00\x00\x00\x00")
                elif self.behaviour == "erroring":
                    # "the database system is starting up" - a refusal, and
                    # therefore proof that a live server is there to refuse.
                    body = b"SFATAL\x00C57P03\x00Mthe database system is starting up\x00\x00"
                    conn.sendall(b"E" + (len(body) + 4).to_bytes(4, "big") + body)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=3)
        self._sock.close()


@pytest.fixture
def server(request: pytest.FixtureRequest):
    srv = _FakeServer(request.param)
    yield srv
    srv.close()


@pytest.mark.parametrize("server", ["mute", "silent"], indirect=True)
def test_a_socket_that_opens_and_never_speaks_is_not_a_running_database(
    server: _FakeServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression. Both shapes of a wedged server read as ``mute``.

    The bare-connect assertion below is the point: it is what the probe used to
    do, it passes against this server, and that is precisely how a launcher came
    to announce a database that could not answer.
    """
    monkeypatch.setattr(embedded_pg, "_PROBE_REPLY_SECONDS", 0.5)
    _write_pidfile(tmp_path, pid=999_999_999, port=server.port)

    with socket.create_connection(("127.0.0.1", server.port), timeout=2):
        pass  # The old probe's whole test, and it succeeds here.

    assert embedded_pg._probe_cluster(tmp_path) == embedded_pg._MUTE
    assert embedded_pg._accepts_a_connection(tmp_path) is False


@pytest.mark.parametrize("server", ["authenticating"], indirect=True)
def test_a_server_that_speaks_the_protocol_is_reported_answering(server: _FakeServer, tmp_path: Path) -> None:
    _write_pidfile(tmp_path, pid=999_999_999, port=server.port)

    assert embedded_pg._probe_cluster(tmp_path) == embedded_pg._ANSWERING
    assert embedded_pg._accepts_a_connection(tmp_path) is True


@pytest.mark.parametrize("server", ["erroring"], indirect=True)
def test_a_refusal_counts_as_alive(server: _FakeServer, tmp_path: Path) -> None:
    """A cluster that says "starting up" or "too many clients" is alive.

    This is the guard against the opposite and larger mistake. Reading an error
    reply as death would let the recovery path end a healthy cluster that was
    merely busy, or one still finishing its own start.
    """
    _write_pidfile(tmp_path, pid=999_999_999, port=server.port)

    assert embedded_pg._probe_cluster(tmp_path) == embedded_pg._ANSWERING


def test_nothing_listening_reads_as_closed_not_mute(tmp_path: Path) -> None:
    """A cluster still replaying WAL has no socket open, and must not be touched.

    ``closed`` is the state the patient recovery wait already handles, so it has
    to stay distinguishable from ``mute``; collapsing the two would put a
    recovering database on the path that stops one.
    """
    _write_pidfile(tmp_path, pid=999_999_999, port=_free_port())

    assert embedded_pg._probe_cluster(tmp_path) == embedded_pg._CLOSED


@pytest.mark.parametrize("server", ["authenticating", "erroring"], indirect=True)
def test_the_recovery_refuses_a_cluster_that_answers(server: _FakeServer, tmp_path: Path) -> None:
    """The safety property, asserted with a pid that is alive and is ours.

    If the guard were ever wrong in this direction the test process itself would
    be the thing it ended, which is the most direct way to state that a cluster
    which answers is never stopped.
    """
    _write_pidfile(tmp_path, pid=os.getpid(), port=server.port)

    assert embedded_pg._stop_mute_postmaster(tmp_path) is False
    assert (tmp_path / "postmaster.pid").exists()


def test_the_recovery_refuses_when_the_pid_is_already_gone(tmp_path: Path) -> None:
    _write_pidfile(tmp_path, pid=999_999_999, port=_free_port())

    assert embedded_pg._stop_mute_postmaster(tmp_path) is False


class _Listener(NamedTuple):
    """A live process that holds a TCP port open and never speaks on it."""

    pid: int
    port: int


#: The stand-in orphaned postmaster: bind, listen, say who you are, say nothing
#: else. It announces its own pid because the process that runs this body is the
#: process that binds the socket, so it is the one thing here that can name the
#: owner without being asked the very question under test.
_LISTENER_SOURCE = """\
import os, socket, time
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", {port}))
s.listen(8)
print(os.getpid(), flush=True)
time.sleep(120)
"""


def _announced_pid(child: subprocess.Popen) -> int:
    """The pid the stand-in listener printed for itself.

    It has to be asked rather than assumed: measured on Windows, a virtualenv
    launcher re-executes, and the pid ``Popen`` returned reported no sockets at
    all while its grandchild held the port. PostgreSQL's postmaster is its own
    listener, so a real pidfile names the owner, and the guard under test is the
    thing that checks that - which is also why the owner may not be read out of
    the machine's socket table here. That is the guard's own question, answered
    with the guard's own call, and a test that asks it can only agree with
    itself.
    """
    assert child.stdout is not None
    line = child.stdout.readline().strip()
    if not line.isdigit():
        pytest.fail(f"the stand-in listener did not announce its pid (got {line!r})")
    return int(line)


def _end_process(pid: int) -> None:
    """Stop a process this file started, if anything of it is left."""
    try:
        import psutil

        proc = psutil.Process(pid)
        proc.kill()
        proc.wait(timeout=10)
    except Exception:  # already gone, already reaped, or psutil is not installed
        pass


@pytest.fixture
def listener() -> Iterator[_Listener]:
    """A real process holding a real port, named by the process itself.

    This is the orphaned postmaster reduced to what the guard reads: a live pid
    that genuinely holds the port a pidfile names. One test stops it and leaves
    the teardown nothing to do; the others only interrogate it, which is why the
    teardown ends the pid that answered as well as the pid that was spawned -
    on Windows those are not the same process.
    """
    port = _free_port()
    child = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", _LISTENER_SOURCE.format(port=port)],
        stdout=subprocess.PIPE,
        text=True,
    )
    owner: int | None = None
    try:
        owner = _announced_pid(child)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("the stand-in listener never came up")
        yield _Listener(pid=owner, port=port)
    finally:
        if owner is not None:
            _end_process(owner)
        if child.poll() is None:
            child.kill()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover - a wedged child
            pass
        if child.stdout is not None:
            child.stdout.close()


def test_the_port_guard_names_the_owner_and_refuses_a_stranger(listener: _Listener, tmp_path: Path) -> None:
    """The guard's own question, asked in both directions against one live port.

    Nothing else in this file pinned it. Every other refusal here is earned by a
    different check - the cluster answered, or the pid was gone - so a guard that
    had stopped reading the socket table and fallen back to "is this process
    called postgres" would satisfy all of them. That is exactly what macOS was
    doing: psutil's machine-wide ``net_connections`` needs root there and raises
    for an ordinary user, the whole reading fell through to the name, and the
    only test that noticed failed for what looked like an unrelated reason.

    Both pids below are alive and neither is called postgres, so the name guess
    cannot answer either of them. Only a real reading of what the processes hold
    tells the owner from the stranger.
    """
    _write_pidfile(tmp_path, pid=listener.pid, port=listener.port)

    assert embedded_pg._owns_the_blocked_port(listener.pid, tmp_path) is True
    assert embedded_pg._owns_the_blocked_port(os.getpid(), tmp_path) is False


def test_the_guard_names_the_owner_without_the_machine_wide_table(
    listener: _Listener, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """macOS's refusal, reproduced on whatever platform is running this file.

    psutil documents its machine-wide ``net_connections`` as requiring root on
    macOS, and its implementation there is the per-process call in a loop over
    every pid on the box catching only ``NoSuchProcess`` - so the first
    root-owned process brings the whole enumeration down with ``AccessDenied``.
    That is not "nobody is listening" and the guard must not read it as one. It
    used to, silently, which left the port check on that platform reduced to the
    process name: a real orphaned postmaster is called postgres, so the recovery
    still fired and the feature still looked like it worked, with the check that
    exists to stop us ending the WRONG process not running at all.

    Making the machine-wide call raise is a simulation of that platform and is
    stated as one. What it pins is not macOS but the property macOS needs: the
    guard has a reading that does not go through the machine-wide table, and
    that reading still tells the owner from a stranger.
    """
    psutil = pytest.importorskip("psutil")

    def _refuse(*args: object, **kwargs: object) -> NoReturn:
        raise psutil.AccessDenied(msg="simulating the macOS machine-wide refusal")

    monkeypatch.setattr(psutil, "net_connections", _refuse)
    _write_pidfile(tmp_path, pid=listener.pid, port=listener.port)

    assert embedded_pg._owns_the_blocked_port(listener.pid, tmp_path) is True
    assert embedded_pg._owns_the_blocked_port(os.getpid(), tmp_path) is False


def test_the_recovery_stops_a_real_process_that_only_listens(listener: _Listener, tmp_path: Path) -> None:
    """End to end on the half that makes the user's machine start again.

    A process holds a socket open and never speaks, exactly as the orphaned
    postmaster did, and is named by a pidfile the way PostgreSQL names one. The
    assertion is that the process is gone and the pidfile with it, so the next
    boot attempt starts a cluster instead of attaching to this one.
    """
    psutil = pytest.importorskip("psutil")
    _write_pidfile(tmp_path, pid=listener.pid, port=listener.port)
    assert embedded_pg._probe_cluster(tmp_path) == embedded_pg._MUTE

    assert embedded_pg._stop_mute_postmaster(tmp_path) is True
    assert not psutil.pid_exists(listener.pid)
    assert not (tmp_path / "postmaster.pid").exists()


def _names_a_unix_socket(pid: int) -> bool:
    """Whether this platform's socket table reports unix socket paths at all.

    A platform that cannot answer becomes a skip rather than a failure. Linux
    and macOS are both documented to report the bound path, and psutil converts
    it to the same string either way, but no machine this suite runs on can
    verify the macOS half - so it asks the platform instead of assuming it.
    """
    try:
        import psutil

        proc = psutil.Process(pid)
        reader = getattr(proc, "net_connections", None) or getattr(proc, "connections", None)
        if reader is None:
            return False
        return any(isinstance(getattr(conn, "laddr", None), str) and conn.laddr for conn in reader(kind="unix"))
    except Exception:
        return False


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="this platform has no unix sockets")
def test_a_unix_socket_cluster_can_still_name_its_owner(tmp_path: Path) -> None:
    """The only endpoint a real cluster has on Linux and macOS.

    pixeltable-pgserver starts the embedded postmaster with no TCP listener on
    those platforms, so no reading of a machine's inet table has anything to
    find for a genuine cluster there and the ownership question can only be
    asked of the socket file the pidfile names. The TCP tests above cover the
    shape that only Windows runs in production.

    The socket is opened by this process, because self-inspection is the one
    reading every platform permits and a foreign holder is already covered by
    the TCP tests, which spawn one. What is under test here is the path
    plumbing: line 5 of the pidfile plus the port becoming a socket path, and
    that path being matched against what the process reports holding.
    """
    pytest.importorskip("psutil")
    port = _free_port()
    # A short directory of its own. A unix socket path is limited to about 104
    # bytes on macOS, which a pytest tmp_path named after this test can spend
    # before the socket name is even added.
    socket_dir = Path(tempfile.mkdtemp(prefix="oepg"))
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        try:
            sock.bind(str(socket_dir / f".s.PGSQL.{port}"))
        except OSError as exc:
            pytest.skip(f"this platform would not bind a unix socket at {socket_dir}: {exc!r}")
        sock.listen(8)
        _write_pidfile(tmp_path, pid=os.getpid(), port=port, socket_dir=socket_dir, listen_addresses="")

        if not _names_a_unix_socket(os.getpid()):
            pytest.skip("this platform's socket table does not name unix socket paths")

        assert embedded_pg._owns_the_blocked_port(os.getpid(), tmp_path) is True
    finally:
        sock.close()
        shutil.rmtree(socket_dir, ignore_errors=True)

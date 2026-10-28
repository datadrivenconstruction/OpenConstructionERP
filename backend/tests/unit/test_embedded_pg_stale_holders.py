"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A holder that was killed must not stop the next process from stopping the cluster.

``pixeltable-pgserver`` records one process identifier per process that opens
the embedded cluster and stops the postmaster on the way out only when the list
it reads back names the exiting process and nothing else. It appends on the way
in and edits on the way out, so a holder that was killed never removes itself,
and nothing in the library prunes what is left.

Until this release the only way this application stopped on Windows was by
ending its process tree, so every machine that has already run it carries
identifiers of processes that no longer exist. That makes the graceful stop a
one-time event: it can fire on a data directory nobody has ever force-killed
and is skipped on every machine it was actually written for. It is skipped
silently, too, because from outside a skipped stop and a completed one look the
same, which is why this is a test and not an observation.

Deciding which recorded holders are gone rests on ``_pid_alive``, so the second
half of this file pins that down as well, in particular that it keeps answering
without ``psutil``. psutil is not a declared dependency of this project, and a
liveness check that quietly stops checking disarms the whole thing.

The live and dead identifiers here are real processes this test starts, rather
than numbers assumed to be free. The stand-in server implements the library's
decision rather than a paraphrase of it, and the last test fails if a future
version of the library changes that decision.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core import embedded_pg


class _DiskList:
    """The library's on-disk list of integers, same file and same semantics.

    ``get_and_remove`` returns the values as they were *before* the removal,
    which is what makes the library's own check read the way it does.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def get(self) -> list[int]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text())

    def put(self, values: list[int]) -> None:
        self.path.write_text(json.dumps(values))

    def get_and_remove(self, value: int) -> list[int]:
        old_values = self.get()
        values = old_values.copy()
        if value in values:
            values.remove(value)
            self.put(values)
        return old_values


class _FakeServer:
    """Stands in for the pgserver handle and makes its stop-or-skip decision."""

    def __init__(self, pid_file: Path, recorded: list[int]) -> None:
        self.global_process_id_list = _DiskList(pid_file)
        self.global_process_id_list.put(recorded)
        self.stopped = False
        self.skipped = False

    def cleanup(self) -> None:
        pids = self.global_process_id_list.get_and_remove(os.getpid())
        if pids != [os.getpid()]:  # the library's own early return
            self.skipped = True
            return
        self.stopped = True


@pytest.fixture
def pid_file(tmp_path: Path) -> Path:
    return tmp_path / ".handle_pids.json"


@pytest.fixture
def live_pid() -> Iterator[int]:
    """A process that genuinely exists for the length of the test."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        assert embedded_pg._pid_alive(proc.pid), "a process we just started did not read as alive"
        yield proc.pid
    finally:
        proc.kill()
        proc.wait(timeout=30)


@pytest.fixture
def dead_pid() -> Iterator[int]:
    """A process that genuinely no longer exists.

    The yield is what keeps ``proc`` referenced for the length of the test, and
    with it the process handle Windows uses to reserve the identifier. Return
    the number instead and the handle can be collected, the identifier becomes
    reusable, and the premise these tests rest on can quietly stop holding part
    way through one of them. So the yield here is the point, not a habit.
    """
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=60)
    assert not embedded_pg._pid_alive(proc.pid), "a process that has exited still reads as alive"
    yield proc.pid  # noqa: PT022


def _install(monkeypatch: pytest.MonkeyPatch, server: object) -> None:
    monkeypatch.setattr(embedded_pg, "_server", server)
    monkeypatch.setattr(embedded_pg, "_retained", False)


def _hide_psutil(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``import psutil`` fail, which is the state of an install without it."""
    monkeypatch.setitem(sys.modules, "psutil", None)


def test_a_holder_that_no_longer_exists_does_not_block_the_stop(
    monkeypatch: pytest.MonkeyPatch, pid_file: Path, dead_pid: int
) -> None:
    """The regression: this is the state every upgrading machine is already in."""
    server = _FakeServer(pid_file, [dead_pid, os.getpid()])
    _install(monkeypatch, server)

    embedded_pg.shutdown()

    assert server.stopped, "the cluster was left running, so the next start replays the log"
    assert not server.skipped


def test_the_stop_still_happens_without_psutil(monkeypatch: pytest.MonkeyPatch, pid_file: Path, dead_pid: int) -> None:
    """psutil is not a declared dependency, so the fix must not rest on it.

    Before this release the liveness check answered "may be alive" whenever
    psutil could not be imported, which on an install without it would have
    left every recorded holder in place and skipped every stop.
    """
    _hide_psutil(monkeypatch)
    server = _FakeServer(pid_file, [dead_pid, os.getpid()])
    _install(monkeypatch, server)

    embedded_pg.shutdown()

    assert server.stopped, "without psutil the prune stopped working"


def test_several_dead_holders_are_all_dropped(monkeypatch: pytest.MonkeyPatch, pid_file: Path, dead_pid: int) -> None:
    """A machine that has been upgraded a few times carries more than one."""
    extra = []
    for _ in range(3):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait(timeout=60)
        extra.append(proc.pid)
    dead = [dead_pid, *extra]
    server = _FakeServer(pid_file, [*dead, os.getpid()])
    _install(monkeypatch, server)

    embedded_pg.shutdown()

    assert server.stopped
    assert json.loads(pid_file.read_text()) == [], "an identifier was left behind for the next run to trip over"


def test_a_holder_that_is_alive_still_blocks_the_stop(
    monkeypatch: pytest.MonkeyPatch, pid_file: Path, live_pid: int
) -> None:
    """The control, and the mistake worth avoiding.

    A second live process using this cluster is the one case where the stop
    must not happen, so the prune has to leave a live identifier alone even
    though dropping it would make the stop fire.
    """
    server = _FakeServer(pid_file, [live_pid, os.getpid()])
    _install(monkeypatch, server)

    embedded_pg.shutdown()

    assert server.skipped, "the cluster was stopped underneath a process still using it"
    assert not server.stopped
    assert live_pid in json.loads(pid_file.read_text())


def test_a_live_holder_is_kept_without_psutil_too(
    monkeypatch: pytest.MonkeyPatch, pid_file: Path, live_pid: int
) -> None:
    """The dangerous direction has to survive the same removal."""
    _hide_psutil(monkeypatch)
    server = _FakeServer(pid_file, [live_pid, os.getpid()])
    _install(monkeypatch, server)

    embedded_pg.shutdown()

    assert server.skipped
    assert live_pid in json.loads(pid_file.read_text())


def test_our_own_identifier_is_never_dropped(monkeypatch: pytest.MonkeyPatch, pid_file: Path) -> None:
    """The library removes it itself, and removing it twice would read as a mismatch."""
    server = _FakeServer(pid_file, [os.getpid()])
    _install(monkeypatch, server)

    embedded_pg.shutdown()

    assert server.stopped


def test_an_unreadable_holder_list_does_not_prevent_the_stop_attempt(
    monkeypatch: pytest.MonkeyPatch, pid_file: Path
) -> None:
    """The prune is advisory: a failure in it leaves the old behaviour, not a worse one."""
    server = _FakeServer(pid_file, [os.getpid()])
    pid_file.write_text("not json at all")
    _install(monkeypatch, server)

    embedded_pg.shutdown()

    assert embedded_pg._server is None, "shutdown gave up before it asked the library to stop"


def test_pruning_is_skipped_when_the_holder_list_cannot_be_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Older handles, and the stand-in used by the other suites, have no such list."""

    class _Bare:
        def __init__(self) -> None:
            self.cleanup_calls = 0

        def cleanup(self) -> None:
            self.cleanup_calls += 1

    server = _Bare()
    _install(monkeypatch, server)

    embedded_pg.shutdown()

    assert server.cleanup_calls == 1


def test_a_retained_cluster_is_still_left_alone(monkeypatch: pytest.MonkeyPatch, pid_file: Path, dead_pid: int) -> None:
    """The prune must not run for a cluster this process does not own."""
    server = _FakeServer(pid_file, [dead_pid, os.getpid()])
    _install(monkeypatch, server)
    embedded_pg.retain()

    embedded_pg.shutdown()

    assert not server.stopped
    assert not server.skipped
    assert dead_pid in json.loads(pid_file.read_text()), "a cluster we do not own had its holder list edited"


def test_a_skipped_stop_says_so_in_the_log(
    monkeypatch: pytest.MonkeyPatch, pid_file: Path, live_pid: int, caplog: pytest.LogCaptureFixture
) -> None:
    """The failure this release is about was invisible, so leaving it invisible is not a fix."""
    server = _FakeServer(pid_file, [live_pid, os.getpid()])
    _install(monkeypatch, server)

    with caplog.at_level("INFO", logger=embedded_pg.logger.name):
        embedded_pg.shutdown()

    assert any("held by" in record.message for record in caplog.records), (
        "the cluster was left running and nothing said so"
    )


class TestPidLiveness:
    """``_pid_alive`` decides what the prune drops, so it answers for itself here."""

    def test_this_process_is_alive(self) -> None:
        assert embedded_pg._pid_alive(os.getpid())

    def test_this_process_is_alive_without_psutil(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _hide_psutil(monkeypatch)
        assert embedded_pg._pid_alive(os.getpid())

    def test_a_finished_process_is_not_alive(self, dead_pid: int) -> None:
        assert not embedded_pg._pid_alive(dead_pid)

    def test_a_finished_process_is_not_alive_without_psutil(
        self, monkeypatch: pytest.MonkeyPatch, dead_pid: int
    ) -> None:
        """The whole point. Previously this answered "may be alive" and the check was gone."""
        _hide_psutil(monkeypatch)
        assert not embedded_pg._pid_alive(dead_pid)

    def test_a_running_child_is_alive_without_psutil(self, monkeypatch: pytest.MonkeyPatch, live_pid: int) -> None:
        _hide_psutil(monkeypatch)
        assert embedded_pg._pid_alive(live_pid)

    @pytest.mark.parametrize("pid", [0, -1, -999])
    def test_an_identifier_that_cannot_name_a_process_is_not_alive(self, pid: int) -> None:
        """Zero and negatives mean process groups to ``os.kill``, which is not the question."""
        assert not embedded_pg._pid_alive(pid)

    def test_an_unanswerable_platform_call_reads_as_alive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Uncertainty must keep the entry, because dropping a live holder is the costly mistake."""
        _hide_psutil(monkeypatch)
        if os.name == "nt":
            monkeypatch.setattr(embedded_pg, "_pid_alive_windows", lambda _pid: None)
        else:

            def _refuse(*_args: object, **_kwargs: object) -> None:
                raise OSError("cannot answer")

            monkeypatch.setattr(os, "kill", _refuse)

        assert embedded_pg._pid_alive(os.getpid()) is True


def test_the_library_still_decides_the_way_this_assumes() -> None:
    """A canary on the real library, so a version bump cannot quietly invalidate the fix.

    Everything above exercises our code against a stand-in. That stand-in is
    only meaningful while the real ``_cleanup`` still reads the holder list and
    returns early when it names anyone else, so read the real one and check.
    """
    import inspect

    postgres_server = pytest.importorskip("pixeltable_pgserver.postgres_server")
    source = inspect.getsource(postgres_server.PostgresServer._cleanup)

    assert "global_process_id_list.get_and_remove" in source, "the library no longer consults the holder list"
    after_read = source.split("get_and_remove", 1)[1]
    assert "return" in after_read.split("\n\n", 1)[0], (
        "the library no longer returns early on a holder list naming someone else"
    )

    utils = pytest.importorskip("pixeltable_pgserver.utils")
    probe = utils.DiskList(Path(inspect.getfile(utils)).parent / "does-not-exist.json")
    assert probe.get() == [], "a missing holder list no longer reads as empty"

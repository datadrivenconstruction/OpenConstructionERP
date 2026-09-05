# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A start echoes the PostgreSQL log lines it wrote, not the ones it inherited.

``pixeltable-pgserver`` gives ``pg_ctl`` the cluster log with ``-l``, which
appends, and logs the WHOLE of that file when the start fails or times out
(``ensure_postgres_running`` in ``postgres_server.py``). Nothing truncates or
rotates it, so the tenth start replays nine earlier ones. The desktop launcher
pumps this process's output into its own log, so the user was shown every FATAL
line the installation had ever produced, and a reader counting those lines
measured how old the installation was rather than what was wrong with it.

These tests drive the cap directly against a temporary directory, so they need
no cluster and cannot disturb the session's own. They assert the mechanism, not
the size of the output: a fresh installation with no history would satisfy a
size check while the defect was untouched.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core import embedded_pg

#: Long enough that a record carrying it is over the cap on its own, which is
#: what a real cluster log reaches after a few weeks of failed starts.
OLD = "".join(f"2026-06-{1 + day % 28:02d} 09:00:00 GMT FATAL: an error from a previous run\n" for day in range(200))

OLD_LINES = OLD.count("\n")

NEW = "2026-09-05 09:00:00 GMT FATAL: the error this start produced\n"

DUMP = "Failed to start server.\nShowing contents of postgres server log ({}) below:\n{}"


@pytest.fixture(autouse=True)
def _uninstall_cap() -> Iterator[None]:
    """The cap lives on a process-wide logger, so a test must take its own away."""
    yield
    pgserver_logger = logging.getLogger(embedded_pg._PGSERVER_LOGGER)
    for installed in list(pgserver_logger.filters):
        if isinstance(installed, embedded_pg._PgLogEchoCap):
            pgserver_logger.removeFilter(installed)
    embedded_pg._pg_log_echo_cap = None


@pytest.fixture
def echoed() -> Iterator[list[str]]:
    """Everything the library's logger puts on the stream, after filtering."""
    seen: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record.getMessage())

    pgserver_logger = logging.getLogger(embedded_pg._PGSERVER_LOGGER)
    handler = Capture()
    previous_level = pgserver_logger.level
    pgserver_logger.setLevel(logging.DEBUG)
    pgserver_logger.addHandler(handler)
    try:
        yield seen
    finally:
        pgserver_logger.removeHandler(handler)
        pgserver_logger.setLevel(previous_level)


@pytest.fixture
def pgdata(tmp_path: Path) -> Path:
    """A cluster directory whose log already holds months of earlier starts."""
    (tmp_path / "log").write_text(OLD, encoding="utf-8")
    return tmp_path


def dump_the_whole_log(pgdata: Path) -> None:
    """Exactly what pixeltable-pgserver does when pg_ctl will not start.

    Including the shape: the library builds this with an f-string, so the record
    arrives already formatted with no args, rather than as a lazy template.
    """
    log = pgdata / "log"
    logging.getLogger(embedded_pg._PGSERVER_LOGGER).error(DUMP.format(log, log.read_text(encoding="utf-8")))


def test_a_start_echoes_only_the_lines_it_wrote(pgdata: Path, echoed: list[str]) -> None:
    embedded_pg._cap_pg_log_echo(pgdata)
    with (pgdata / "log").open("a", encoding="utf-8") as handle:
        handle.write(NEW)

    dump_the_whole_log(pgdata)

    assert len(echoed) == 1
    assert NEW.strip() in echoed[0]
    assert "an error from a previous run" not in echoed[0]


def test_the_inherited_lines_are_counted_rather_than_dropped_silently(pgdata: Path, echoed: list[str]) -> None:
    """A reader has to be able to tell there is more, and where it is."""
    embedded_pg._cap_pg_log_echo(pgdata)
    with (pgdata / "log").open("a", encoding="utf-8") as handle:
        handle.write(NEW)

    dump_the_whole_log(pgdata)

    assert f"{OLD_LINES} earlier lines" in echoed[0]
    assert str(pgdata / "log") in echoed[0]


def test_the_history_stays_on_disk_for_support(pgdata: Path, echoed: list[str]) -> None:
    """Capping the echo must not cost the file a user is asked to send in."""
    embedded_pg._cap_pg_log_echo(pgdata)
    with (pgdata / "log").open("a", encoding="utf-8") as handle:
        handle.write(NEW)

    dump_the_whole_log(pgdata)

    on_disk = (pgdata / "log").read_text(encoding="utf-8")
    assert OLD in on_disk
    assert NEW in on_disk


def test_a_start_with_no_history_keeps_its_own_lines(tmp_path: Path, echoed: list[str]) -> None:
    """The cap removes what a start inherited, never what it wrote itself.

    The same text that is stripped above survives here, because here the start
    produced it. Identical input, opposite outcome, and the only difference is
    the baseline, which is the mechanism this whole change turns on.
    """
    embedded_pg._cap_pg_log_echo(tmp_path)
    (tmp_path / "log").write_text(OLD + NEW, encoding="utf-8")

    dump_the_whole_log(tmp_path)

    assert NEW.strip() in echoed[0]
    assert "an error from a previous run" in echoed[0]


def test_a_log_that_was_replaced_is_not_mistaken_for_history(pgdata: Path) -> None:
    """A file smaller than the baseline was replaced, so none of it is inherited.

    The cluster directory is emptied wholesale when a half-finished initdb is
    cleared, and that is the start most in need of its own log. Trusting the
    baseline as a byte count alone would take this start's first lines for
    somebody else's and drop exactly the ones being asked for.
    """
    cap = embedded_pg._cap_pg_log_echo(pgdata)

    (pgdata / "log").write_text(NEW * 100, encoding="utf-8")

    assert cap._history() == ""


def test_the_cap_finds_its_prefix_in_a_log_written_with_windows_line_endings(pgdata: Path, echoed: list[str]) -> None:
    """The reported fault is a Windows one, and CRLF is how that log is written.

    pg_ctl writes the log in text mode there, so the bytes hold CRLF while the
    library reads them back through universal newlines and gets bare newlines.
    Comparing the two spellings without normalising finds no prefix at all, and
    the cap degrades to a length trim exactly where it is needed.
    """
    log = pgdata / "log"
    log.write_bytes(OLD.replace("\n", "\r\n").encode("utf-8"))
    embedded_pg._cap_pg_log_echo(pgdata)
    with log.open("ab") as handle:
        handle.write(NEW.replace("\n", "\r\n").encode("utf-8"))

    dump_the_whole_log(pgdata)

    assert NEW.strip() in echoed[0]
    assert "an error from a previous run" not in echoed[0]


def test_the_failure_screen_refuses_to_present_old_lines_as_this_fault(pgdata: Path) -> None:
    """The launcher renders this string, and it is all a stuck user can read.

    A pg_ctl that dies before the postmaster writes anything leaves the end of
    the file belonging to a run months ago. Offered as "postgres log:" under
    today's failure, those lines are read as today's cause, which is the exact
    misreading this change exists to stop.
    """
    embedded_pg._cap_pg_log_echo(pgdata)

    detail = embedded_pg._pg_failure_detail(pgdata, RuntimeError("pg_ctl did not start"))

    assert "an error from a previous run" not in detail
    assert "wrote nothing to the postgres log" in detail


def test_the_failure_screen_quotes_the_lines_this_start_did_write(pgdata: Path) -> None:
    """Naming the real cause is the whole point of the string; it must survive."""
    embedded_pg._cap_pg_log_echo(pgdata)
    with (pgdata / "log").open("a", encoding="utf-8") as handle:
        handle.write(NEW)

    detail = embedded_pg._pg_failure_detail(pgdata, RuntimeError("pg_ctl did not start"))

    assert "the error this start produced" in detail
    assert "an error from a previous run" not in detail


def test_an_ordinary_record_is_left_alone(pgdata: Path, echoed: list[str]) -> None:
    """The library's other lines are how a boot is followed; they must survive."""
    embedded_pg._cap_pg_log_echo(pgdata)

    logging.getLogger(embedded_pg._PGSERVER_LOGGER).info("running pg_ctl... pg_ctl_args=('-w', 'start')")

    assert echoed == ["running pg_ctl... pg_ctl_args=('-w', 'start')"]


def test_arming_it_on_every_boot_installs_one_filter(pgdata: Path) -> None:
    """boot() runs more than once per process, and filters stack."""
    embedded_pg._cap_pg_log_echo(pgdata)
    embedded_pg._cap_pg_log_echo(pgdata)

    installed = [
        f for f in logging.getLogger(embedded_pg._PGSERVER_LOGGER).filters if isinstance(f, embedded_pg._PgLogEchoCap)
    ]
    assert len(installed) == 1


def test_a_record_over_the_cap_with_no_history_to_strip_is_still_trimmed(tmp_path: Path, echoed: list[str]) -> None:
    """The cap is what stands between the launcher log and unbounded growth."""
    embedded_pg._cap_pg_log_echo(tmp_path)

    logging.getLogger(embedded_pg._PGSERVER_LOGGER).error("%s", "x" * (embedded_pg._PG_LOG_ECHO_LIMIT * 3))

    assert len(echoed[0]) < embedded_pg._PG_LOG_ECHO_LIMIT * 2
    assert "characters trimmed" in echoed[0]


def test_a_log_that_could_not_be_measured_is_unknown_rather_than_all_this_starts_own(
    pgdata: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failing to size the log must not be recorded as the log being empty.

    Both end in a baseline of zero, and one of them is a lie: a file held open
    by another process is months old, so answering "everything after byte zero
    is new" hands the whole history back as this start's own work. Falling back
    to the older behaviour is honest about not knowing. Reading the answer as
    the number alone cannot tell the two apart.
    """
    log = pgdata / "log"
    real_stat = Path.stat

    def refuse_to_size_the_log(self: Path, *args: object, **kwargs: object) -> object:
        if self == log:
            raise PermissionError(13, "the file is in use by another process")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", refuse_to_size_the_log)
    cap = embedded_pg._cap_pg_log_echo(pgdata)
    monkeypatch.undo()

    # Not the empty string either: that one is a claim, and the failure screen
    # would print "this start wrote nothing" over a log holding months of lines.
    assert cap.appended_since_rebase(log) is None
    assert "wrote nothing to the postgres log" not in embedded_pg._pg_failure_detail(pgdata, RuntimeError("no start"))


def test_a_cluster_with_no_log_yet_still_gets_its_own_lines(tmp_path: Path) -> None:
    """The pair to the test above, and the reason it cannot be fixed by refusing on zero.

    A first ever start finds no log, which is a definite answer rather than a
    missing one, and the lines it then writes are the only ones there are. They
    are also the lines whose absence would leave the launcher's failure screen
    with nothing to say on the one start most likely to fail.
    """
    cap = embedded_pg._cap_pg_log_echo(tmp_path)

    (tmp_path / "log").write_text(NEW, encoding="utf-8")

    assert cap.appended_since_rebase(tmp_path / "log") == NEW

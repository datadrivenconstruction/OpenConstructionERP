"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The backup guard complains about the artefact, not about the run.

Production went nine days with no database dump and nothing said so. The job
was refusing correctly and writing that refusal to a log nobody reads, so the
missing alarm got read as evidence the backup had run.

The test that matters here is not "a fresh backup passes". That case proves
nothing, because a guard that returns 0 unconditionally also passes it. What
has to be proved is that every shape of "we cannot restore" comes back
non-zero, including the two that a failure-watcher never sees:

  * the job stopped being scheduled, so the directory is empty or gone and no
    failure event was ever emitted;
  * the dump died part-way through, so the newest file has a current mtime and
    a pure age check waves it past.

And the shape this codebase keeps getting wrong: "cannot tell" must not be
success. An unreadable directory is a fact about the reader, not about the
backup, and it exits 2 rather than 0.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "check_backup_freshness.py"

HOUR = 3600.0
NOW = 1_770_000_000.0


def _load_guard():
    spec = importlib.util.spec_from_file_location("check_backup_freshness", _SCRIPT)
    assert spec and spec.loader, f"cannot load {_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    # Registered before exec: a ``slots=True`` dataclass resolves its own
    # module out of sys.modules while the decorator runs, and blows up with an
    # AttributeError if the entry is not there yet.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


guard = _load_guard()


def _artefact(name: str, *, age_hours: float, size_bytes: int = 500_000_000):
    return guard.Artefact(name=name, size_bytes=size_bytes, mtime_epoch=NOW - age_hours * HOUR)


def _assess(artefacts, *, max_age_hours: float = 26.0, min_bytes: int = 1_000_000):
    return guard.assess_backups(
        artefacts,
        now_epoch=NOW,
        max_age_hours=max_age_hours,
        min_bytes=min_bytes,
        where="the backup directory matching '*.dump'",
    )


def _write_dump(directory: Path, name: str, *, age_hours: float, size_bytes: int) -> Path:
    # Against the real clock, not ``NOW``: ``main`` reads ``time.time()``, and
    # a fixture stamped from a frozen constant would make every file look
    # years old and every one of these assertions pass for the wrong reason.
    path = directory / name
    path.write_bytes(b"x" * size_bytes)
    mtime = time.time() - age_hours * HOUR
    os.utime(path, (mtime, mtime))
    return path


class TestTheVerdict:
    """Every shape of "we cannot restore" has to come back non-zero."""

    def test_a_recent_dump_above_the_floor_is_the_only_passing_case(self):
        verdict = _assess([_artefact("db-20260825.dump", age_hours=6.0)])
        assert verdict.status == "fresh"
        assert verdict.exit_code == 0

    def test_a_dump_older_than_the_threshold_is_stale(self):
        # The nine-day shape: the job failed every night and said so only in
        # its own log.
        verdict = _assess([_artefact("db-20260816.dump", age_hours=9 * 24)])
        assert verdict.status == "stale"
        assert verdict.exit_code == 1

    def test_an_empty_directory_is_missing_not_fine(self):
        # A job that stopped being scheduled emits no failure at all. Nothing
        # that watches for failures ever fires; the empty directory is the
        # only evidence there is.
        verdict = _assess([])
        assert verdict.status == "missing"
        assert verdict.exit_code == 1

    def test_a_fresh_but_truncated_dump_does_not_pass_on_its_mtime(self):
        # A dump killed part-way through has a current mtime. Age alone waves
        # it through and the operator learns the truth at restore time.
        verdict = _assess([_artefact("db-20260825.dump", age_hours=0.5, size_bytes=4096)])
        assert verdict.status == "truncated"
        assert verdict.exit_code == 1

    def test_a_truncated_newest_alarms_even_when_an_older_good_dump_exists(self):
        # The recovery point is still fine, but the job is broken *now*.
        # Waiting for the good dump to age out would delay the alarm by a full
        # retention window.
        verdict = _assess(
            [
                _artefact("db-20260825.dump", age_hours=0.5, size_bytes=4096),
                _artefact("db-20260824.dump", age_hours=24.5),
            ],
        )
        assert verdict.status == "truncated"
        assert verdict.exit_code == 1
        # ...and it must not read as "we have nothing".
        assert "db-20260824.dump" in verdict.message

    def test_the_newest_dump_decides_not_the_count(self):
        # A directory full of old dumps is not a fresh backup. Counting files
        # would call this healthy.
        verdict = _assess([_artefact(f"db-2026081{n}.dump", age_hours=(9 + n) * 24) for n in range(5)])
        assert verdict.status == "stale"
        assert verdict.exit_code == 1

    def test_the_message_names_the_place_the_age_and_the_threshold(self):
        # An alert that says "stale" without saying what it measured sends the
        # next person back to the box to work it out again.
        verdict = _assess([_artefact("db-20260816.dump", age_hours=216.0)], max_age_hours=26.0)
        assert "the backup directory matching '*.dump'" in verdict.message
        assert "216.0h" in verdict.message
        assert "26.0h" in verdict.message
        assert "db-20260816.dump" in verdict.message


class TestTheExitCodeAMonitorReads:
    """End to end through ``main``, because the exit code is the whole product."""

    def test_a_fresh_dump_exits_zero(self, tmp_path: Path):
        _write_dump(tmp_path, "db.dump", age_hours=3.0, size_bytes=2048)
        assert guard.main(["--dir", str(tmp_path), "--min-bytes", "1024"]) == 0

    def test_a_stale_dump_exits_one(self, tmp_path: Path):
        _write_dump(tmp_path, "db.dump", age_hours=9 * 24, size_bytes=2048)
        assert guard.main(["--dir", str(tmp_path), "--min-bytes", "1024"]) == 1

    def test_a_dump_written_minutes_ago_but_truncated_exits_one(self, tmp_path: Path):
        _write_dump(tmp_path, "db.dump", age_hours=0.1, size_bytes=16)
        assert guard.main(["--dir", str(tmp_path), "--min-bytes", "1024"]) == 1

    def test_a_directory_that_does_not_exist_exits_one(self, tmp_path: Path):
        # Never scheduled, host rebuilt, path renamed: all indistinguishable
        # from here, and all of them mean there is nothing to restore from.
        assert guard.main(["--dir", str(tmp_path / "never-created")]) == 1

    def test_a_dump_still_being_written_does_not_satisfy_the_pattern(self, tmp_path: Path):
        # The producer writes to a temporary name and renames on success. A
        # partial file under the temporary name must not read as a backup.
        _write_dump(tmp_path, "db.dump.tmp", age_hours=0.1, size_bytes=2048)
        _write_dump(tmp_path, "db.dump", age_hours=9 * 24, size_bytes=2048)
        assert guard.main(["--dir", str(tmp_path), "--pattern", "*.dump", "--min-bytes", "1024"]) == 1

    def test_a_path_that_is_not_a_directory_cannot_tell_and_exits_two(self, tmp_path: Path):
        not_a_dir = tmp_path / "db.dump"
        not_a_dir.write_bytes(b"x" * 2048)
        assert guard.main(["--dir", str(not_a_dir)]) == 2

    def test_a_directory_the_guard_cannot_read_exits_two(self, tmp_path: Path, monkeypatch):
        # The failure this whole guard exists to catch is a reader that answers
        # with its own default. A directory it cannot open must come back as
        # "could not tell" and never as success - and never as "no backup"
        # either, which would be the empty default wearing a fact's clothes.
        #
        # Denied by monkeypatch rather than by chmod(0o000): POSIX permission
        # bits do not deny the owner on Windows, so a chmod test would skip
        # here and go unrun. A test that has never executed reads as covered
        # and proves nothing.
        _write_dump(tmp_path, "db.dump", age_hours=3.0, size_bytes=2048)

        def _deny(_path):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(guard.os, "scandir", _deny)
        assert guard.main(["--dir", str(tmp_path)]) == 2

    def test_a_nonsense_threshold_cannot_tell_and_exits_two(self, tmp_path: Path):
        _write_dump(tmp_path, "db.dump", age_hours=3.0, size_bytes=2048)
        assert guard.main(["--dir", str(tmp_path), "--max-age-hours", "0"]) == 2

    def test_the_alarm_goes_to_stderr_and_the_all_clear_does_not(self, tmp_path: Path, capsys):
        _write_dump(tmp_path, "db.dump", age_hours=9 * 24, size_bytes=2048)
        guard.main(["--dir", str(tmp_path), "--min-bytes", "1024"])
        captured = capsys.readouterr()
        assert "STALE" in captured.err
        assert captured.out == ""

#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Backup freshness guard: complain when the newest database dump is too old.

Production ran nine days with no database backup and nothing said so. The
nightly job was refusing correctly - it checked for free disk, found too
little, appended a line to its own log and exited. A refusal that is logged
and not delivered is worse than a crash: a crash wakes somebody, a refusal
accumulates, and the missing alarm gets read as evidence that the backup ran.

The obvious response is to alert when the backup fails, and on its own that
response is wrong. A job that stops being scheduled never fails. It emits no
exit code, no log line and no event, so anything watching for a failure waits
forever and stays green. The same is true of a unit that was disabled, a host
that was rebuilt without its cron, and a script somebody renamed.

So this guard does not watch the run. It watches the artefact, and asks the
opposite question: how old is the newest thing we could actually restore from.
That question has an answer whether the job failed, was never scheduled, or
never existed, which is the only phrasing that covers all three.

Four ways the answer can be bad, and all four are non-zero here:

  * ``stale``     - the newest dump is older than the threshold.
  * ``missing``   - there is no dump at all, or the directory is not there.
  * ``truncated`` - the newest dump is below the size floor. A dump killed
                    part-way through leaves a file with a *current* mtime, so
                    a check that only looks at age passes a torn file and the
                    operator finds out at restore time. One size comparison
                    closes that.
  * ``unknown``   - the check could not tell. Unreadable directory, a path
                    that is not a directory, bad arguments. This exits 2, not
                    0. A reader that returns a default when it fails reports a
                    fact about itself rather than about the backup, and this
                    codebase has been bitten by exactly that shape before.

Only ``fresh`` exits 0.

Where to run it. On the machine that writes the backups this guard is worth
little: it dies with the host it was meant to report on, and a host that is
gone reports nothing rather than reporting badly. Run it wherever the second
copy of the dumps lands - the object store, the standby box, the workstation
that pulls them - and let the exit code drive whatever already pages you. It
imports nothing from the application, so a monitoring box needs a Python and
this file and nothing else.

One requirement on the producer: it must write to a temporary name and rename
into place once the dump is complete. A dump written directly under its final
name is visible to this guard while it is still growing, and would be read as
a truncated artefact every night. Point ``--pattern`` at the finished name.

Usage (``--min-bytes`` is a placeholder: take it from the size of a good dump
on the install you are watching, not from this line):

    check_backup_freshness.py --dir /var/backups/postgresql \\
        --pattern '*.dump' --max-age-hours 26 --min-bytes 50000000

Exit codes: 0 fresh, 1 the backup is not good, 2 the check could not tell.

The operational half - prerequisites, cadence, choosing the threshold, and what
whoever receives the alert must do differently for exit 1 and exit 2 - is in
``docs/backup-monitoring.md``.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Literal

EXIT_FRESH = 0
EXIT_ALARM = 1
EXIT_UNKNOWN = 2

#: Where the operational half lives: what has to exist on a host to run this,
#: how often to run it, and what the receiving end must do with each exit code.
MONITORING_DOC = "docs/backup-monitoring.md"

#: This default assumes a daily dump. A nightly job needs more than 24 hours of
#: room: the age of the newest dump reaches ~24h just before the next one
#: starts, and the dump itself takes minutes. 26 leaves roughly two hours of
#: grace before the guard speaks. Change the backup schedule and this number
#: has to change with it - a threshold left too wide is silent by construction,
#: producing no warning of any kind while the outage runs.
DEFAULT_MAX_AGE_HOURS = 26.0

#: Any zero-length artefact is a complaint whatever else is true. This is a
#: floor, not a target - set it from the real dump size on your install, so a
#: dump that dies after a few megabytes is caught rather than counted.
DEFAULT_MIN_BYTES = 1

Status = Literal["fresh", "stale", "missing", "truncated", "unknown"]


class BackupScanError(Exception):
    """The directory could not be read, so the guard has no facts to judge."""


@dataclass(frozen=True, slots=True)
class Artefact:
    """One candidate backup file on disk.

    Attributes:
        name: File name as it appears in the directory, without the path.
        size_bytes: Size in bytes, used against the floor.
        mtime_epoch: Last-modified time in seconds since the epoch.
    """

    name: str
    size_bytes: int
    mtime_epoch: float


@dataclass(frozen=True, slots=True)
class Verdict:
    """What the guard concluded, and what it wants the caller to do.

    Attributes:
        status: One of fresh, stale, missing, truncated, unknown.
        exit_code: 0 fresh, 1 the backup is not good, 2 could not tell.
        message: One line naming the location, the measurement and the
            threshold it was measured against.
    """

    status: Status
    exit_code: int
    message: str


def collect_artefacts(directory: Path, pattern: str) -> list[Artefact]:
    """List the backup artefacts in ``directory`` matching ``pattern``.

    An absent directory returns an empty list: "no backup has ever been
    written here" is a real and important answer, and the caller turns it into
    a ``missing`` verdict. Anything that stops the guard from reading what is
    there - a permission error, a path that is a file, a broken entry - raises
    instead, so it can never be mistaken for an empty directory.

    Args:
        directory: Directory holding the finished dumps.
        pattern: Glob matched against file names, e.g. ``*.dump``.

    Returns:
        Every matching regular file, in arbitrary order.

    Raises:
        BackupScanError: The path exists but is not a readable directory, or a
            matching entry could not be stat'd.
    """
    if not directory.exists():
        return []
    if not directory.is_dir():
        raise BackupScanError(f"{directory} exists but is not a directory")

    # scandir rather than Path.glob: glob's selector has historically swallowed
    # a PermissionError and returned no matches, which would hand this guard an
    # empty listing for a directory it was never allowed to read, and it would
    # report "no backup" - the reader's own default dressed up as a fact about
    # the backup. That is the exact defect this file exists to catch, so the
    # listing has to come from a call that raises.
    artefacts: list[Artefact] = []
    try:
        with os.scandir(directory) as scan:
            entries = sorted(Path(item.path) for item in scan if fnmatch(item.name, pattern))
    except OSError as exc:
        raise BackupScanError(f"cannot list {directory}: {exc}") from exc

    for entry in entries:
        try:
            if not entry.is_file():
                continue
            stat = entry.stat()
        except OSError as exc:
            raise BackupScanError(f"cannot read {entry}: {exc}") from exc
        artefacts.append(Artefact(name=entry.name, size_bytes=stat.st_size, mtime_epoch=stat.st_mtime))
    return artefacts


def _hours(seconds: float) -> str:
    return f"{seconds / 3600.0:.1f}h"


def assess_backups(
    artefacts: list[Artefact],
    *,
    now_epoch: float,
    max_age_hours: float,
    min_bytes: int,
    where: str,
) -> Verdict:
    """Judge a listing of artefacts against an age and a size floor.

    Pure: it does no I/O and takes the clock as an argument, so every branch is
    reachable from a test without waiting or touching a filesystem.

    The subject is the newest artefact, because that is what sets the recovery
    point. When the newest one is below the floor the verdict is ``truncated``
    even if an older usable dump exists - a torn file written last night means
    the job is broken now, and waiting for the good dump to age out would delay
    the alarm by exactly one retention window. The message names the older
    usable dump when there is one, so nobody reads ``truncated`` as "we have
    nothing".

    Args:
        artefacts: Candidate files. An empty list yields ``missing``.
        now_epoch: Current time in seconds since the epoch.
        max_age_hours: Age at which the newest usable dump becomes stale.
        min_bytes: Smallest size a dump may have and still be considered usable.
        where: Human-readable description of what was scanned, echoed into the
            message so an alert names the place it looked.

    Returns:
        A :class:`Verdict`.
    """
    threshold = f"threshold {max_age_hours:.1f}h"

    if not artefacts:
        return Verdict(
            status="missing",
            exit_code=EXIT_ALARM,
            message=(
                f"MISSING: no backup found in {where}. Either nothing has ever been written "
                f"there, or the path is wrong. Nothing to restore from ({threshold})."
            ),
        )

    newest = max(artefacts, key=lambda a: a.mtime_epoch)
    newest_age = now_epoch - newest.mtime_epoch

    if newest.size_bytes < min_bytes:
        usable = [a for a in artefacts if a.size_bytes >= min_bytes]
        if usable:
            fallback = max(usable, key=lambda a: a.mtime_epoch)
            tail = f" Newest usable backup is {fallback.name}, {_hours(now_epoch - fallback.mtime_epoch)} old."
        else:
            tail = " No artefact in this directory reaches the floor, so there is nothing to restore from."
        return Verdict(
            status="truncated",
            exit_code=EXIT_ALARM,
            message=(
                f"TRUNCATED: newest backup in {where} is {newest.name}, "
                f"{_hours(newest_age)} old but only {newest.size_bytes} bytes, "
                f"below the {min_bytes}-byte floor.{tail}"
            ),
        )

    if newest_age > max_age_hours * 3600.0:
        return Verdict(
            status="stale",
            exit_code=EXIT_ALARM,
            message=(
                f"STALE: newest backup in {where} is {newest.name}, {_hours(newest_age)} old, "
                f"past the {max_age_hours:.1f}h threshold. No backup has completed since then."
            ),
        )

    return Verdict(
        status="fresh",
        exit_code=EXIT_FRESH,
        message=(
            f"FRESH: newest backup in {where} is {newest.name}, {_hours(newest_age)} old, "
            f"{newest.size_bytes} bytes, within the {max_age_hours:.1f}h threshold."
        ),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Complain when the newest database backup is older, smaller or scarcer than it should be.",
        epilog=(
            "Exit codes: 0 fresh, 1 the backup is not good, 2 the check could not tell. "
            f"Exit 1 and exit 2 must reach different people; see {MONITORING_DOC} for how to run this "
            "and what the receiving end has to do with each answer."
        ),
    )
    parser.add_argument(
        "--dir",
        required=True,
        type=Path,
        help="Directory holding the finished dumps.",
    )
    parser.add_argument(
        "--pattern",
        default="*.dump",
        help="Glob for finished dumps (default: %(default)s). Must not match a dump still being written.",
    )
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=DEFAULT_MAX_AGE_HOURS,
        help=(
            "Age at which the newest backup counts as stale (default: %(default)s, which assumes a "
            "daily dump plus about two hours of slack). Raise or lower it to match your schedule."
        ),
    )
    parser.add_argument(
        "--min-bytes",
        type=int,
        default=DEFAULT_MIN_BYTES,
        help=(
            "Smallest usable dump size (default: %(default)s, which catches only empty files). "
            "Set this from the real dump size so a dump that died part-way through is caught."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Scan a backup directory and return the exit code a monitor should read."""
    args = _build_parser().parse_args(argv)

    if args.max_age_hours <= 0:
        print("UNKNOWN: --max-age-hours must be positive", file=sys.stderr)
        return EXIT_UNKNOWN
    if args.min_bytes < 0:
        print("UNKNOWN: --min-bytes cannot be negative", file=sys.stderr)
        return EXIT_UNKNOWN

    where = f"{args.dir} matching {args.pattern!r}"
    try:
        artefacts = collect_artefacts(args.dir, args.pattern)
    except BackupScanError as exc:
        print(f"UNKNOWN: cannot inspect {where}: {exc}", file=sys.stderr)
        return EXIT_UNKNOWN

    verdict = assess_backups(
        artefacts,
        now_epoch=time.time(),
        max_age_hours=args.max_age_hours,
        min_bytes=args.min_bytes,
        where=where,
    )
    print(verdict.message, file=sys.stderr if verdict.exit_code else sys.stdout)
    return verdict.exit_code


if __name__ == "__main__":
    sys.exit(main())

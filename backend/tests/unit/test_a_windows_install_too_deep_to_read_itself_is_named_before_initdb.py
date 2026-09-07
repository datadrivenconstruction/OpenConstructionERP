"""A Windows path over MAX_PATH is named, not reported as a corrupted install.

Windows caps a fully qualified path at 259 characters for programs that do not
declare long-path support, and the bundled PostgreSQL binaries do not declare it,
so the machine-wide LongPathsEnabled switch does nothing for them. An
installation deep enough to push its own support files past that cap therefore
cannot open them, and ``initdb`` reports them as missing::

    initdb: error: file ".../pginstall/share/postgresql/postgres.bki" does not exist
    initdb: hint: This might mean you have a corrupted installation or identified
            the wrong directory with the invocation option -L.

Measured on a real 16.8.0 install from PyPI: the support directory was 257
characters, ``postgres.bki`` under it 270, the file present and 944104 bytes, and
readable by any long-path-aware tool. Nothing downstream could tell that apart
from a damaged wheel, so the reader was told their installation might be corrupt
and sent to ``--force-reinstall``, which downloads 84 MB into the same directory
to fail the same way.

These tests drive the arithmetic against synthetic paths that are never created
on disk, and the platform gate through :func:`path_limit_applies`, so they run
and mean the same thing on Linux and macOS, where the whole feature must stay a
no-op and where nearly all of our CI runs.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from pathlib import Path

import pytest

from app.cli import check_path_length, run_preflight
from app.core import embedded_pg


class InitdbAttempted(Exception):
    """Stands in for ``initdb``, so a boot that should have refused says so loudly.

    ``_pre_initialize_cluster`` is called outside any ``try`` in ``boot``, so
    raising here leaves the test with a named failure instead of a real cluster
    bring-up against a path the code was supposed to have measured first.
    """


class AnOperatingSystemThatIsNotWindows:
    """The real :mod:`os` with one attribute answered differently.

    ``os.name`` cannot be patched in place. :class:`pathlib.Path` reads it on
    every instantiation to choose which flavour to build, so a boot run under a
    patched ``os.name`` would assemble POSIX paths on a Windows machine and fail
    for a reason with nothing to do with what is being tested. Replacing the
    module binding inside ``embedded_pg`` moves the platform for the code under
    test and for nothing else.
    """

    name = "posix"

    def __getattr__(self, attribute: str) -> object:
        return getattr(os, attribute)


def longest_relative_path(root: Path, subtrees: Sequence[str]) -> tuple[int, str]:
    """Walk *subtrees* of *root* and return the longest path relative to *root*.

    Separators are counted, not spelled: ``as_posix`` only settles which of the
    two one-character separators is written, and the length is what this is for.
    """
    longest = ""
    for name in subtrees:
        subtree = root / name
        if not subtree.is_dir():
            continue
        for path in subtree.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if len(relative) > len(longest):
                longest = relative
    return len(longest), longest


def record_initdb_instead_of_running_it(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Stub the bring-up down to ``initdb`` and record every path that reaches it.

    Everything except the platform gate, which the two callers disagree about
    deliberately: the fixture below forces it on, and the test that owns the
    no-op away from Windows leaves the real one in place.
    """
    attempts: list[Path] = []

    def record_and_refuse_to_run(pgdata: Path) -> bool:
        attempts.append(pgdata)
        raise InitdbAttempted(pgdata)

    monkeypatch.setattr(embedded_pg, "_server", None)
    monkeypatch.setattr(embedded_pg, "_fatal_detail", None)
    monkeypatch.setattr(embedded_pg, "_bundled_install_dir", lambda: Path("C:\\" + "i" * 254))
    monkeypatch.setattr(embedded_pg, "_bundled_major", lambda: "16")
    monkeypatch.setattr(embedded_pg, "_apply_ascii_locale_env", lambda: None)
    monkeypatch.setattr(embedded_pg, "_pre_initialize_cluster", record_and_refuse_to_run)
    return attempts


@pytest.fixture
def on_a_windows_installed_too_deep(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Put ``boot`` on a Windows whose installation is too deep, and record initdb.

    Returns the list every ``initdb`` attempt is appended to, which is the whole
    point: the assertion this fixture exists to support is about what was NOT
    run. ``_apply_ascii_locale_env`` is stubbed because it writes five variables
    into ``os.environ`` and a boot that fails to refuse would reach it.
    """
    attempts = record_initdb_instead_of_running_it(monkeypatch)
    monkeypatch.setattr(embedded_pg, "path_limit_applies", lambda: True)
    return attempts


#: The longest ``pginstall`` path that leaves room for the files under it.
#:
#: Derived here rather than written as 195, so the boundary tests below follow a
#: change to either constant instead of quietly measuring the wrong side of it.
INSTALL_LIMIT = embedded_pg._WINDOWS_MAX_PATH - 1 - embedded_pg._PGINSTALL_LONGEST_RELATIVE


def an_install_directory_of(length: int) -> Path:
    """A synthetic ``pginstall`` path of exactly *length* characters.

    Never created on disk: what is under test is arithmetic and a branch, and a
    real directory of this depth cannot be made by the API that would have to
    make it.
    """
    directory = Path("C:\\" + "i" * (length - len("C:\\")))
    assert len(str(directory)) == length, "the synthetic path is not the length the case asked for"
    return directory


def a_data_directory(tmp_path: Path, *, with_cluster: bool) -> Path:
    """The path ``boot`` will use, with or without the ``PG_VERSION`` that gates it.

    The version written matches the ``_bundled_major`` stub, so the version
    conflict check further down ``boot`` stays out of the way of what is measured
    here.
    """
    pgdata = tmp_path / "pgdata"
    if with_cluster:
        pgdata.mkdir()
        (pgdata / "PG_VERSION").write_text("16\n", encoding="utf-8")
    return pgdata


@pytest.fixture
def on_windows_installed_at(monkeypatch: pytest.MonkeyPatch):
    """Boot on Windows with the install depth chosen per case, recording initdb.

    Separate from ``on_a_windows_installed_too_deep``, which pins one path 62
    characters over the limit. That is the depth at which every branch looks the
    same, so it cannot show which input decides between them.

    A fixture rather than a helper called inside the test body because ``boot``
    early-returns ``True`` while ``_server`` is set and keeps ``_fatal_detail`` at
    module scope. Both are reset by ``record_initdb_instead_of_running_it``, and
    parametrised cases get that reset once each only if it runs per case.
    """
    attempts = record_initdb_instead_of_running_it(monkeypatch)
    monkeypatch.setattr(embedded_pg, "path_limit_applies", lambda: True)

    def install_at(length: int) -> list[Path]:
        monkeypatch.setattr(embedded_pg, "_bundled_install_dir", lambda: an_install_directory_of(length))
        return attempts

    return install_at


# ── The constants, re-derived from what actually ships ───────────────────────


def test_the_install_limit_still_covers_every_file_the_binaries_read() -> None:
    """The margin is measured out of the shipped tree, and stays measured.

    A ``skipif`` here would be the trap this whole guard is about: green on a
    population of nothing. If the bundled PostgreSQL cannot be located then the
    constant below is unverified, and saying so is the useful answer.
    """
    install = embedded_pg._bundled_install_dir()
    assert install is not None, "the bundled PostgreSQL could not be located, so the install-depth margin is unverified"

    measured, deepest = longest_relative_path(install, embedded_pg._PGINSTALL_SUBTREES_IN_USE)
    assert measured > 0, f"no files at all under {install}, so nothing was measured"
    assert measured <= embedded_pg._PGINSTALL_LONGEST_RELATIVE, (
        f"{deepest} is {measured} characters below {install} and the margin allows only "
        f"{embedded_pg._PGINSTALL_LONGEST_RELATIVE}, so a PostgreSQL bump has shipped a deeper "
        f"file and the limit is now too generous by {measured - embedded_pg._PGINSTALL_LONGEST_RELATIVE}"
    )


def test_the_data_limit_covers_the_longest_name_postgresql_writes_below_pgdata() -> None:
    """An archive-status marker is the longest form a default cluster produces.

    Longer than anything on a live cluster from this application, which tops out
    at ``pg_logical/replorigin_checkpoint``, and reachable without replication
    slots or logical decoding, neither of which this application configures.
    """
    wal_segment = "0" * 24
    marker = f"pg_wal/archive_status/{wal_segment}.ready"
    assert len(marker) <= embedded_pg._PGDATA_LONGEST_RELATIVE
    assert len("pg_logical/replorigin_checkpoint") <= embedded_pg._PGDATA_LONGEST_RELATIVE


# ── The arithmetic ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("longest_relative", [0, 12, 41, 52, 63])
def test_the_limit_is_max_path_less_a_separator_and_the_longest_name_below(longest_relative: int) -> None:
    """What has to fit is the directory, a separator, and the deepest name under it.

    A directory that is itself under MAX_PATH proves nothing, which is the whole
    reason the limit is not simply 259: ``initdb`` is handed a directory and
    opens names below it.
    """
    limit = embedded_pg._WINDOWS_MAX_PATH - 1 - longest_relative
    at_the_limit = Path("C:\\" + "d" * (limit - len("C:\\")))
    assert len(str(at_the_limit)) == limit

    assert embedded_pg._path_limit_problem(at_the_limit, longest_relative, "opening.", "fix.") is None

    one_over = Path(str(at_the_limit) + "d")
    problem = embedded_pg._path_limit_problem(one_over, longest_relative, "opening.", "fix.")
    assert problem is not None
    assert (problem.length, problem.limit) == (limit + 1, limit)
    assert problem.longest_relative == longest_relative
    # The directory at the limit puts its deepest file at exactly MAX_PATH, and
    # one character more puts it one over. That equality is the derivation.
    assert limit + len("\\") + longest_relative == embedded_pg._WINDOWS_MAX_PATH


def test_the_extended_length_prefix_is_not_counted_as_part_of_the_name() -> None:
    """``\\\\?\\`` asks a caller to switch the limit off; it is not part of the path.

    ``Path.resolve`` can hand it back for a path that is already long. Counting
    it would report a number four larger than the one the user sees in the error
    they are holding, and the PostgreSQL binaries do not understand the prefix
    anyway.
    """
    plain = "C:\\" + "d" * 200
    assert embedded_pg._measured_path_text(Path(plain)) == plain
    assert embedded_pg._measured_path_text(Path("\\\\?\\" + plain)) == plain


# ── Which directory is measured, and on which platform ───────────────────────


def test_the_gate_is_the_operating_system_and_nothing_else() -> None:
    import os

    assert embedded_pg.path_limit_applies() == (os.name == "nt")


def test_the_measurement_is_a_no_op_away_from_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedded_pg, "path_limit_applies", lambda: False)
    monkeypatch.setattr(embedded_pg, "_bundled_install_dir", lambda: Path("C:\\" + "i" * 254))
    assert embedded_pg.windows_path_limit_problem(Path("/" + "d" * 4000)) is None


def test_a_deep_installation_is_reported_even_when_the_data_directory_is_short(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    deep_install = Path("C:\\" + "i" * 254)
    monkeypatch.setattr(embedded_pg, "path_limit_applies", lambda: True)
    monkeypatch.setattr(embedded_pg, "_bundled_install_dir", lambda: deep_install)

    problem = embedded_pg.windows_path_limit_problem(tmp_path / "pgdata")
    assert problem is not None
    assert problem.directory == deep_install
    assert problem.longest_relative == embedded_pg._PGINSTALL_LONGEST_RELATIVE


def test_a_deep_data_directory_is_reported_when_the_installation_is_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deep_data = Path("C:\\" + "d" * 250)
    monkeypatch.setattr(embedded_pg, "path_limit_applies", lambda: True)
    monkeypatch.setattr(embedded_pg, "_bundled_install_dir", lambda: Path("C:\\pginstall"))

    problem = embedded_pg.windows_path_limit_problem(deep_data)
    assert problem is not None
    assert problem.directory == deep_data
    assert problem.longest_relative == embedded_pg._PGDATA_LONGEST_RELATIVE


def test_an_installation_we_cannot_locate_is_not_evidence_of_anything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fails open, the way ``_bundled_major`` does.

    A check that cannot find our own installation has nothing to say about how
    deep it sits, and refusing on that would break working machines to guard
    against a broken one.
    """
    monkeypatch.setattr(embedded_pg, "path_limit_applies", lambda: True)
    monkeypatch.setattr(embedded_pg, "_bundled_install_dir", lambda: None)
    assert embedded_pg.windows_path_limit_problem(tmp_path / "pgdata") is None


# ── What the bring-up does with it ───────────────────────────────────────────


def test_boot_refuses_before_it_attempts_initdb(on_a_windows_installed_too_deep: list[Path], tmp_path: Path) -> None:
    """The measurement replaces the attempt, rather than explaining it afterwards.

    Without the guard this raises :class:`InitdbAttempted`: the bring-up walks
    into ``initdb`` on paths it could have measured first, then spends three
    attempts and a retry backoff arriving at "the local database could not be
    started" plus advice to reinstall.
    """
    assert embedded_pg.boot(tmp_path) is False
    assert on_a_windows_installed_too_deep == [], (
        "the bring-up ran initdb on paths it had already measured as too long for Windows"
    )

    detail = embedded_pg.last_fatal_detail()
    assert detail is not None, (
        "boot refused without naming a reason, so the CLI falls back to its generic advice to "
        "reinstall - the one action that cannot help here"
    )
    problem = embedded_pg.windows_path_limit_problem(tmp_path / "pgdata")
    assert problem is not None
    assert detail == problem.message
    assert problem.length > problem.limit


def test_an_existing_cluster_is_not_refused_for_a_path_it_already_lives_with(
    on_a_windows_installed_too_deep: list[Path],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The named exception to the refusal, asserted so nobody tidies it away.

    A ``PG_VERSION`` on disk is proof these paths were once short enough to work,
    and refusing to open a database that opened yesterday would be a worse bug
    than the one the guard fixes. The measurement still reaches the log, and
    ``doctor`` reports it with no gate at all.
    """
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    (pgdata / "PG_VERSION").write_text("16\n", encoding="utf-8")

    caplog.set_level(logging.WARNING, logger=embedded_pg.__name__)
    with pytest.raises(InitdbAttempted):
        embedded_pg.boot(tmp_path)

    assert on_a_windows_installed_too_deep == [pgdata.resolve()], (
        "an existing cluster was refused for a path length it has already been living with"
    )
    assert embedded_pg.last_fatal_detail() is None

    problem = embedded_pg.windows_path_limit_problem(pgdata)
    assert problem is not None
    assert any(record.getMessage() == problem.message for record in caplog.records), (
        "the path length went unmentioned on a boot that let it through"
    )


def test_boot_does_not_refuse_where_the_limit_does_not_exist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The no-op on Linux and macOS, asserted through ``boot`` and the real gate.

    Both tests above reach the refusal by forcing ``path_limit_applies`` to
    ``True``, so neither would notice the guard being called without it. This one
    leaves the real gate in place and moves the platform underneath it, which is
    the only thing that gate reads. An installation far over the Windows limit is
    therefore offered to a bring-up that must measure nothing and run initdb
    anyway, which is what has to keep happening where nearly all of our CI runs.
    """
    attempts = record_initdb_instead_of_running_it(monkeypatch)
    monkeypatch.setattr(embedded_pg, "os", AnOperatingSystemThatIsNotWindows())
    assert embedded_pg.path_limit_applies() is False

    with pytest.raises(InitdbAttempted):
        embedded_pg.boot(tmp_path)

    assert attempts == [(tmp_path / "pgdata").resolve()], (
        "the bring-up refused to reach initdb on a platform that has no such path limit"
    )
    assert embedded_pg.last_fatal_detail() is None, (
        "a path length was recorded as the reason a boot failed on a platform where it is not a reason"
    )


# ── Which input actually picks the branch ────────────────────────────────────


@pytest.mark.parametrize("cluster_exists", [False, True], ids=["fresh", "cluster on disk"])
@pytest.mark.parametrize("install_length", [INSTALL_LIMIT, INSTALL_LIMIT + 1], ids=["at the limit", "one over"])
def test_the_outcome_at_the_boundary_turns_on_the_cluster_and_not_on_the_length(
    on_windows_installed_at,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    install_length: int,
    cluster_exists: bool,
) -> None:
    """Both inputs, both sides of the boundary, in one table.

    Measured on one Windows machine across three real installs: 213 characters
    refused, 207 refused, 211 started and ran to healthy. All three were over the
    same limit, and the message quoted that limit as though it were the rule -
    which made 195 look wrong to the reader at 211, and made shortening 213 to
    207 look like a fix.

    The other tests around this one pin a path 62 characters over, where refusing
    and warning cannot be told apart by anything, so they would pass whichever
    input the branch read. This one moves each input by one step. Length moves the
    limit boundary and nothing else; the cluster moves the outcome.
    """
    attempts = on_windows_installed_at(install_length)
    pgdata = a_data_directory(tmp_path, with_cluster=cluster_exists)
    caplog.set_level(logging.INFO, logger=embedded_pg.__name__)

    over_the_limit = install_length > INSTALL_LIMIT
    should_refuse = over_the_limit and not cluster_exists

    if should_refuse:
        assert embedded_pg.boot(tmp_path) is False
        assert attempts == [], "the bring-up ran initdb on an install it had measured as too deep"
    else:
        with pytest.raises(InitdbAttempted):
            embedded_pg.boot(tmp_path)
        assert attempts == [pgdata.resolve()], (
            f"an install of {install_length} characters was refused with cluster_exists="
            f"{cluster_exists}, where the same code accepts it in the neighbouring case"
        )

    measured = [record.getMessage() for record in caplog.records if "characters long" in record.getMessage()]
    failures = [record.getMessage() for record in caplog.records if record.getMessage().startswith("STAGE:pg:fail")]
    problem = embedded_pg.windows_path_limit_problem(pgdata)

    if not over_the_limit:
        assert problem is None, (
            f"{install_length} characters is exactly the limit, so the deepest file under it lands on "
            f"character {embedded_pg._WINDOWS_MAX_PATH} and still fits"
        )
        assert measured == [] and failures == []
        assert embedded_pg.last_fatal_detail() is None
        return

    assert problem is not None
    assert measured, "a boot that measured the path over the limit said nothing about it"

    if should_refuse:
        assert embedded_pg.last_fatal_detail() == problem.message
        assert len(failures) == 1, f"expected one STAGE:pg:fail marker, got {failures}"
        assert str(problem.length) in failures[0] and str(problem.limit) in failures[0]
        assert "create the local database" in failures[0], (
            "the checklist line quotes a limit without saying what needs the room, which is the "
            "reading that makes a neighbouring machine over the same limit look like a contradiction"
        )
    else:
        assert embedded_pg.last_fatal_detail() is None
        assert failures == [], "a cluster that already exists was refused for the depth of the install"
        warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
        assert problem.message in warnings
        assert any("already exists" in warning for warning in warnings), (
            "the boot that let a path over the limit through never named what let it through, so "
            "the length and the limit read as the whole rule"
        )


@pytest.mark.parametrize("install_length", [207, 211, 213])
def test_no_length_over_the_limit_is_special_on_a_machine_with_no_cluster_yet(
    on_windows_installed_at, tmp_path: Path, install_length: int
) -> None:
    """The three lengths measured in the field, held to one answer.

    211 booting was not a property of 211. Written against the reported numbers
    rather than against the limit so that a change which lets one of them through
    on its length has to come here and say so.
    """
    attempts = on_windows_installed_at(install_length)
    assert install_length > INSTALL_LIMIT, "the reported lengths no longer straddle the limit under test"

    assert embedded_pg.boot(tmp_path) is False
    assert attempts == []
    assert embedded_pg.last_fatal_detail() is not None


@pytest.mark.parametrize("install_length", [207, 211, 213])
def test_the_same_three_lengths_all_start_once_the_cluster_is_there(
    on_windows_installed_at, tmp_path: Path, install_length: int
) -> None:
    """The other half of the pair above, which is what makes the pair mean anything."""
    attempts = on_windows_installed_at(install_length)
    pgdata = a_data_directory(tmp_path, with_cluster=True)

    with pytest.raises(InitdbAttempted):
        embedded_pg.boot(tmp_path)
    assert attempts == [pgdata.resolve()]
    assert embedded_pg.last_fatal_detail() is None


def test_moving_only_the_installation_is_not_the_advice_when_the_data_directory_is_deep_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Advice that leaves a second refusal waiting is advice that does not work.

    The install problem is still the one returned, because a user with both has
    to move the install anyway. Returning it alone sent them to do exactly that
    and then refused them a second time with a different number and a different
    directory.
    """
    deep_install = an_install_directory_of(INSTALL_LIMIT + 1)
    data_limit = embedded_pg._WINDOWS_MAX_PATH - 1 - embedded_pg._PGDATA_LONGEST_RELATIVE
    deep_data = Path("C:\\" + "d" * (data_limit + 1 - len("C:\\")))

    monkeypatch.setattr(embedded_pg, "path_limit_applies", lambda: True)
    monkeypatch.setattr(embedded_pg, "_bundled_install_dir", lambda: deep_install)

    problem = embedded_pg.windows_path_limit_problem(deep_data)
    assert problem is not None
    assert problem.directory == deep_install
    assert problem.longest_relative == embedded_pg._PGINSTALL_LONGEST_RELATIVE
    assert str(deep_data) in problem.message, "the second directory that will refuse them went unnamed"
    assert str(data_limit) in problem.message


# ── What doctor does with it ─────────────────────────────────────────────────


def test_doctor_reports_the_measurement_with_no_cluster_gate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Reinstalling deeper under a fixed data directory lands exactly here.

    The bring-up stays quiet for that user because their cluster exists, so
    doctor is the surface that has to answer, and it answers whatever the
    cluster's state is.
    """
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    (pgdata / "PG_VERSION").write_text("16\n", encoding="utf-8")

    monkeypatch.setattr(embedded_pg, "path_limit_applies", lambda: True)
    monkeypatch.setattr(embedded_pg, "_bundled_install_dir", lambda: Path("C:\\" + "i" * 254))

    check = check_path_length(tmp_path)
    assert check is not None
    assert check.status == "error"
    problem = embedded_pg.windows_path_limit_problem(pgdata)
    assert problem is not None
    assert check.hint == problem.message

    names = [c.name for c in run_preflight("127.0.0.1", 8931, tmp_path, verbose=False)]
    assert check.name in names, "doctor measured the path length and then did not report it"


def test_doctor_says_nothing_about_path_length_away_from_windows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(embedded_pg, "path_limit_applies", lambda: False)
    monkeypatch.setattr(embedded_pg, "_bundled_install_dir", lambda: Path("C:\\" + "i" * 254))

    assert check_path_length(tmp_path) is None
    names = [c.name for c in run_preflight("127.0.0.1", 8931, tmp_path, verbose=False)]
    assert "Path length" not in names

"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A cluster written by another PostgreSQL major is named, not just refused.

PostgreSQL will not open a data directory that a different major version wrote,
in either direction. Until this guard existed the code read only whether
``PG_VERSION`` was *present*, which answers "does initdb still have to run" and
says nothing about compatibility, so a user whose cluster predated a PostgreSQL
bump got the postmaster's raw refusal after three retries, wrapped in advice to
reinstall - the very act that had caused it - and the only recovery anyone could
name was ``init-db --reset``, which deletes the cluster.

These tests drive the pure check against a temporary directory with the bundled
version stubbed, so they need no cluster, cannot disturb the session's own, and
cannot skip: a test that only runs where the real PostgreSQL binaries are
installed would be absent exactly on the machines this guard is written for.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core import embedded_pg


@pytest.fixture
def bundled_16(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the bundled binaries at major 16 for the duration of one test."""
    monkeypatch.setattr(embedded_pg, "_bundled_major", lambda: "16")


def write_cluster(pgdata: Path, pg_version: str) -> Path:
    """Lay down the one file that decides which PostgreSQL owns a directory."""
    pgdata.mkdir(parents=True, exist_ok=True)
    (pgdata / "PG_VERSION").write_text(pg_version, encoding="utf-8")
    return pgdata


# ── The version strings themselves ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("written", "major"),
    [
        ("16\n", "16"),
        ("16", "16"),
        ("16.11", "16"),
        ("10\n", "10"),
        # Before 10 the second component was part of the major, so 9.5 and 9.6
        # are as incompatible as 15 and 16 and both digits have to survive.
        ("9.6\n", "9.6"),
        ("9.5", "9.5"),
    ],
)
def test_a_version_string_reduces_to_the_major_that_decides_the_file_format(written: str, major: str) -> None:
    assert embedded_pg._postgres_major(written) == major


@pytest.mark.parametrize("written", ["", "   \n", "not a version", "\x00\x00"])
def test_an_unreadable_version_string_yields_no_major(written: str) -> None:
    """No number means no claim. The alternative is a guard that guesses."""
    assert embedded_pg._postgres_major(written) is None


# ── What the check decides ───────────────────────────────────────────────────


def test_a_matching_major_is_not_a_conflict(tmp_path: Path, bundled_16: None) -> None:
    write_cluster(tmp_path / "pgdata", "16\n")

    assert embedded_pg.data_dir_version_conflict(tmp_path / "pgdata") is None


def test_a_directory_that_is_not_a_cluster_yet_is_not_a_conflict(tmp_path: Path, bundled_16: None) -> None:
    """The fresh-install path: initdb has not run, so there is nothing to compare."""
    (tmp_path / "pgdata").mkdir()

    assert embedded_pg.data_dir_version_conflict(tmp_path / "pgdata") is None


def test_a_bundled_version_we_cannot_read_never_blocks_a_boot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail open. Refusing to start because we could not interrogate our own
    installation would break working machines to guard against a broken one."""
    write_cluster(tmp_path / "pgdata", "15\n")
    monkeypatch.setattr(embedded_pg, "_bundled_major", lambda: None)

    assert embedded_pg.data_dir_version_conflict(tmp_path / "pgdata") is None


# ── What the message says ────────────────────────────────────────────────────


def test_the_message_names_what_was_found_what_was_expected_and_where(tmp_path: Path, bundled_16: None) -> None:
    pgdata = write_cluster(tmp_path / "pgdata", "15\n")

    conflict = embedded_pg.data_dir_version_conflict(pgdata)

    assert conflict is not None, "a PostgreSQL 15 directory under PostgreSQL 16 binaries is a conflict"
    message = conflict.message
    print(f"\nmismatch message:\n{message}")
    assert "PostgreSQL 15" in message, f"the message does not say what was found: {message}"
    assert "PostgreSQL 16" in message, f"the message does not say what was expected: {message}"
    assert str(pgdata) in message, f"the message does not say which directory it is about: {message}"


def test_the_message_offers_a_recovery_that_keeps_the_data(tmp_path: Path, bundled_16: None) -> None:
    """The point of answering early is that the data is still there to save."""
    conflict = embedded_pg.data_dir_version_conflict(write_cluster(tmp_path / "pgdata", "15\n"))

    assert conflict is not None
    message = conflict.message
    assert "DATABASE_URL" in message, f"the message never mentions pointing at the existing cluster: {message}"
    assert "pg_dump" in message, f"the message never mentions taking the data out: {message}"
    # is_requested() honours an explicit truthy OE_USE_EMBEDDED_PG ahead of
    # DATABASE_URL, and cli.py sets exactly that for --embedded-pg. Somebody who
    # reached this wall by passing that flag would set DATABASE_URL, be routed
    # straight back to the same directory, and read the recovery as broken.
    assert "OE_USE_EMBEDDED_PG" in message and "--embedded-pg" in message, (
        f"the message offers DATABASE_URL without saying what overrides it, so the recovery is "
        f"inert for anybody who arrived here with the embedded flag set: {message}"
    )


def test_the_message_never_recommends_reset_without_saying_it_destroys_the_data(
    tmp_path: Path, bundled_16: None
) -> None:
    """``--reset`` does clear the conflict, by deleting every project in the
    cluster. Naming it without that is how a support answer turns into data
    loss, so the two are checked as one thing: the sentence carrying ``--reset``
    has to be the sentence that says what it deletes."""
    conflict = embedded_pg.data_dir_version_conflict(write_cluster(tmp_path / "pgdata", "15\n"))

    assert conflict is not None
    message = conflict.message
    assert "--reset" in message, "the message should still name the reset, so the user is not left without one"
    sentences = [sentence for sentence in message.split(". ") if "--reset" in sentence]
    assert sentences, f"'--reset' appears in no sentence, which means this test is misreading: {message}"
    for sentence in sentences:
        assert "DELETING" in sentence or "deletes" in sentence, (
            f"a sentence recommends '--reset' without saying it destroys the cluster: {sentence!r}"
        )
    assert "permanently" in message, f"the message never says the loss is unrecoverable: {message}"


def test_a_data_directory_newer_than_the_binaries_is_the_same_wall(tmp_path: Path, bundled_16: None) -> None:
    """PostgreSQL refuses in both directions, and the cause differs: a newer
    directory means the application went backwards, so the repair does too."""
    conflict = embedded_pg.data_dir_version_conflict(write_cluster(tmp_path / "pgdata", "17\n"))

    assert conflict is not None, "a PostgreSQL 17 directory under PostgreSQL 16 binaries is a conflict"
    message = conflict.message
    print(f"\ndowngrade message:\n{message}")
    assert "PostgreSQL 17" in message and "PostgreSQL 16" in message
    assert "downgraded" in message, f"the message does not name the likely cause: {message}"


def test_the_two_majors_survive_as_values_not_only_as_prose(tmp_path: Path, bundled_16: None) -> None:
    """Anything that has to render the pair shorter must not parse the paragraph.

    The launcher checklist gets one line per stage, and the only honest way to
    build it is from the numbers themselves. A caller reduced to a regex over
    the message is a caller that breaks the next time the wording is improved.
    """
    conflict = embedded_pg.data_dir_version_conflict(write_cluster(tmp_path / "pgdata", "15\n"))

    assert conflict is not None
    assert (conflict.found, conflict.expected) == ("15", "16"), conflict


# ── What boot does with it ───────────────────────────────────────────────────


def test_boot_refuses_the_mismatched_cluster_and_records_why(
    tmp_path: Path, bundled_16: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check has to be reached, not merely written.

    ``boot`` returns False for every failure it has, so a False on its own does
    not show that this guard fired; the recorded detail is what separates
    "refused because of the version" from "refused because the package is
    missing". Monkeypatch restores the module handle afterwards, so a session
    that already has a cluster running keeps it.
    """
    write_cluster(tmp_path / "pgdata", "15\n")
    monkeypatch.setattr(embedded_pg, "_server", None)

    assert embedded_pg.boot(tmp_path) is False

    detail = embedded_pg.last_fatal_detail()
    assert detail is not None, "boot refused without recording a reason, so the CLI prints generic advice"
    assert "PostgreSQL 15" in detail and "PostgreSQL 16" in detail, detail


def test_the_launcher_checklist_line_names_both_versions(
    tmp_path: Path, bundled_16: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The desktop user sees the STAGE marker and nothing else.

    This failure's home is the desktop app, where a bundled-PG bump strands the
    cluster an earlier release created. What that user gets is the launcher's
    boot checklist, drawn from these markers; the paragraph goes to
    ``logger.error`` and into a log file nobody stuck on a window that will not
    open is reading. A marker saying only that the versions differ would put the
    two numbers - the whole point of the guard - on the surface nobody sees.
    """
    write_cluster(tmp_path / "pgdata", "15\n")
    monkeypatch.setattr(embedded_pg, "_server", None)

    assert embedded_pg.boot(tmp_path) is False

    markers = [line for line in capsys.readouterr().out.splitlines() if line.startswith("STAGE:pg:fail")]
    assert len(markers) == 1, f"expected one pg failure marker, got {markers}"
    print(f"\nlauncher sees: {markers[0]}")
    assert "PostgreSQL 15" in markers[0], f"the checklist does not say what was found: {markers[0]}"
    assert "PostgreSQL 16" in markers[0], f"the checklist does not say what was expected: {markers[0]}"


def test_boot_leaves_no_stale_diagnosis_behind(
    tmp_path: Path, bundled_16: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A diagnosis from an earlier call must not be printed against a later one.

    The second boot here fails on its data directory rather than on a version -
    the path handed to it is a regular file, so the ``pgdata`` mkdir raises -
    and the CLI would attach the previous run's version message to it if the
    detail were not cleared on the way in.
    """
    write_cluster(tmp_path / "pgdata", "15\n")
    monkeypatch.setattr(embedded_pg, "_server", None)
    assert embedded_pg.boot(tmp_path) is False
    assert embedded_pg.last_fatal_detail() is not None, "the version conflict was not recorded"

    not_a_directory = tmp_path / "a-file"
    not_a_directory.write_text("", encoding="utf-8")
    monkeypatch.setattr(embedded_pg, "_server", None)
    assert embedded_pg.boot(not_a_directory) is False
    assert embedded_pg.last_fatal_detail() is None, (
        "boot carried the previous call's version message into a failure that has nothing "
        "to do with versions, so the CLI would print the wrong cause"
    )

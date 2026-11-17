"""A database folder that never started must not block every later start.

initdb killed after its bootstrap (antivirus lock, power loss, a forced close)
leaves ``PG_VERSION`` and ``global/pg_control`` behind. ``_pre_initialize_cluster``
reads ``PG_VERSION`` as "already created" and skips initdb, the postmaster then
refuses the half-made cluster, and the next start does the same: users saw
"initdb fails" on a new PC on every launch, and reinstalling did not help
because the data folder survives an uninstall.

``postmaster.opts`` is written on every postmaster start and never by initdb,
so a folder without it has never held data. It is moved aside, never deleted.
"""

from __future__ import annotations

from pathlib import Path

from app.core.embedded_pg import _set_aside_never_started_cluster


def _debris(pgdata: Path) -> None:
    (pgdata / "global").mkdir(parents=True)
    (pgdata / "global" / "pg_control").write_bytes(b"\x00" * 16)
    (pgdata / "PG_VERSION").write_text("16\n", encoding="utf-8")


def test_debris_from_a_killed_initdb_is_moved_aside(tmp_path: Path) -> None:
    pgdata = tmp_path / "pgdata"
    _debris(pgdata)
    moved = _set_aside_never_started_cluster(pgdata)
    assert moved is not None
    assert moved.parent == tmp_path
    assert moved.name.startswith("pgdata.incomplete-")
    assert (moved / "PG_VERSION").is_file(), "moved, not deleted"
    assert not pgdata.exists()


def test_a_cluster_that_has_run_is_never_touched(tmp_path: Path) -> None:
    pgdata = tmp_path / "pgdata"
    _debris(pgdata)
    (pgdata / "postmaster.opts").write_text("postgres\n", encoding="utf-8")
    assert _set_aside_never_started_cluster(pgdata) is None
    assert (pgdata / "PG_VERSION").is_file()


def test_a_cluster_with_a_pidfile_is_left_to_the_pidfile_logic(tmp_path: Path) -> None:
    pgdata = tmp_path / "pgdata"
    _debris(pgdata)
    (pgdata / "postmaster.pid").write_text("4242\n", encoding="utf-8")
    assert _set_aside_never_started_cluster(pgdata) is None
    assert pgdata.is_dir()


def test_a_fresh_or_empty_folder_is_left_alone(tmp_path: Path) -> None:
    assert _set_aside_never_started_cluster(tmp_path / "missing") is None
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _set_aside_never_started_cluster(empty) is None
    assert empty.is_dir()

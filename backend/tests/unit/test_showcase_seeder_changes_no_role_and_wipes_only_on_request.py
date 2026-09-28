# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""The CAD showcase seeder leaves every role alone and wipes only when asked.

``seed_demo_showcase`` used to write ``role = 'admin'`` onto its seed account
straight into the database, and then deleted every project on the
installation, not only its own three, on every run and with no question
asked. Run once against a database where that account is a demo login, it
turned the demo login into an administrator and removed everyone's work.

The promotion is gone, and both deletions now refuse unless the operator
passes ``--wipe-all-projects``.
"""

from __future__ import annotations

import ast
import inspect
import sqlite3
from pathlib import Path

import pytest

from app.scripts import seed_demo_showcase as showcase


def _sqlite_with_projects(path: Path, n: int) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE oe_projects_project (id TEXT PRIMARY KEY)")
        conn.executemany("INSERT INTO oe_projects_project VALUES (?)", [(str(i),) for i in range(n)])
        conn.commit()
    finally:
        conn.close()


def _project_count(path: Path) -> int:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute("SELECT COUNT(*) FROM oe_projects_project").fetchone()[0]
    finally:
        conn.close()


def test_the_seeder_writes_no_role() -> None:
    source = inspect.getsource(showcase)
    literals = [
        node.value.lower()
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert not hasattr(showcase, "promote_admin")
    assert not [s for s in literals if "oe_users_user" in s], "the seeder must not touch the users table"


def test_the_flag_is_off_unless_named() -> None:
    assert showcase.parse_args([]).wipe_all_projects is False
    assert showcase.parse_args([showcase.WIPE_FLAG]).wipe_all_projects is True


def test_the_project_wipe_refuses_without_the_flag(tmp_path: Path) -> None:
    db = tmp_path / "openestimate.db"
    _sqlite_with_projects(db, 3)

    with pytest.raises(showcase.WipeNotConfirmedError):
        showcase.wipe_all_projects_direct(confirmed=False, db_path=db)

    assert _project_count(db) == 3


def test_the_project_wipe_runs_with_the_flag(tmp_path: Path) -> None:
    db = tmp_path / "openestimate.db"
    _sqlite_with_projects(db, 3)

    assert showcase.wipe_all_projects_direct(confirmed=True, db_path=db) == 3
    assert _project_count(db) == 0


def test_a_rerun_without_the_wipe_does_not_duplicate_the_showcase() -> None:
    specs = showcase.DEMO_PROJECTS
    first_code = specs[0]["create"]["project_code"]

    assert showcase.specs_not_yet_seeded(specs, []) == specs
    remaining = showcase.specs_not_yet_seeded(specs, [{"project_code": first_code}, {"project_code": None}])
    assert [s["create"]["project_code"] for s in remaining] == [s["create"]["project_code"] for s in specs[1:]]
    everything = [{"project_code": s["create"]["project_code"]} for s in specs]
    assert showcase.specs_not_yet_seeded(specs, everything) == []


def test_the_bim_wipe_refuses_without_the_flag(tmp_path: Path) -> None:
    (tmp_path / "model-a").mkdir()

    with pytest.raises(showcase.WipeNotConfirmedError):
        showcase.wipe_orphan_bim_files(confirmed=False, bim_dir=tmp_path)

    assert (tmp_path / "model-a").is_dir()
    assert showcase.wipe_orphan_bim_files(confirmed=True, bim_dir=tmp_path) == 1
    assert not (tmp_path / "model-a").exists()

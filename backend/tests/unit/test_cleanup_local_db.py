"""Tests for the local-DB cleanup script (BUG-D02 / BUG-USERS-POLLUTION).

The cleanup script identifies QA / test cruft project rows by name
pattern and deletes them together with their FK-child rows. These tests
build a synthetic SQLite database with:

* a few real "keeper" demo projects
* a flock of test / QA cruft rows matching every blacklist pattern
* a couple of "uncertain" rows (unrecognised names)
* child rows in project_id and boq_id FK tables

…then run the script in dry-run mode (no rows touched), in execute mode
(everything matched is gone, keepers untouched), and with the
``--include-uncertain`` flag (uncertain rows folded in).
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from app.scripts.cleanup_local_db import _classify, main


@pytest.fixture
def synthetic_db(tmp_path: Path) -> Path:
    """Build a tiny SQLite DB that mirrors the production schema for the
    columns we care about. Only the tables actually touched by the
    cleanup script need to exist here.
    """
    db_path = tmp_path / "synth.db"
    con = sqlite3.connect(str(db_path))
    cur = con.cursor()

    # Minimal projects table — id, name, status, metadata (JSON), created_at
    cur.execute(
        """
        CREATE TABLE oe_projects_project (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
    )

    # A direct-FK child table (mimics oe_documents_document etc.)
    cur.execute(
        """
        CREATE TABLE oe_documents_document (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            name TEXT NOT NULL
        )
        """
    )

    # BOQ table — has project_id FK + is parent of positions
    cur.execute(
        """
        CREATE TABLE oe_boq_boq (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            name TEXT NOT NULL
        )
        """
    )

    # Position table — has boq_id FK only (indirect child of project)
    cur.execute(
        """
        CREATE TABLE oe_boq_position (
            id TEXT PRIMARY KEY,
            boq_id TEXT NOT NULL,
            description TEXT NOT NULL
        )
        """
    )

    # ── Seed data ──
    rows = [
        # KEEP — uniquely-named demo projects
        ("Wohnpark Friedrichshain — Berlin", "active", "{}"),
        ("Library Center", "active", "{}"),
        # KEEP via demo_id metadata
        ("Downtown Medical Center", "active", '{"demo_id":"medical-us"}'),
        # DELETE — matches blacklist patterns
        ("Test Project abc123", "active", "{}"),
        ("Test Project def456", "active", "{}"),
        ("CrossMod Project 9a8b7c", "active", "{}"),
        ("Smoke Test Project 111111", "active", "{}"),
        ("BOQ Test", "active", "{}"),
        ("Schedule Test", "active", "{}"),
        ("ReqBIM Project deadbe", "active", "{}"),
        ("BIMPre Project caf3f3", "active", "{}"),
        ("Regression Project 222222", "active", "{}"),
        ("ExcelQuality 333333", "active", "{}"),
        ("Export Integrity 444444", "active", "{}"),
        ("TenderingSmoke", "active", "{}"),
        ("Unified Markups E2E", "active", "{}"),
        ("DWG Debug", "active", "{}"),
        ("CDE Audit Project 555555", "active", "{}"),
        ("Audit Probe Project", "active", "{}"),
        ("test", "active", "{}"),
        # UNCERTAIN — uniquely-named, doesn't match keep / delete heuristics
        ("Some Custom User Project", "active", "{}"),
        ("Another One The User Made", "active", "{}"),
    ]
    for idx, (name, status, meta) in enumerate(rows):
        cur.execute(
            "INSERT INTO oe_projects_project VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), name, status, meta, f"2026-04-{(idx % 28) + 1:02d}"),
        )

    # Add child rows under a few projects so we can verify cascade.
    cur.execute("SELECT id FROM oe_projects_project WHERE name = ?", ("Test Project abc123",))
    test_proj_id = cur.fetchone()[0]
    cur.execute("SELECT id FROM oe_projects_project WHERE name = ?", ("Library Center",))
    keeper_proj_id = cur.fetchone()[0]

    # Documents under both
    for proj_id, label in [(test_proj_id, "doc-A"), (test_proj_id, "doc-B"), (keeper_proj_id, "keeper-doc")]:
        cur.execute(
            "INSERT INTO oe_documents_document VALUES (?, ?, ?)",
            (str(uuid.uuid4()), proj_id, label),
        )

    # BOQ + positions under the test project (so the cleanup walks both
    # project_id and boq_id branches)
    test_boq_id = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO oe_boq_boq VALUES (?, ?, ?)",
        (test_boq_id, test_proj_id, "Test BOQ"),
    )
    for label in ("pos-1", "pos-2", "pos-3"):
        cur.execute(
            "INSERT INTO oe_boq_position VALUES (?, ?, ?)",
            (str(uuid.uuid4()), test_boq_id, label),
        )

    # BOQ + positions under the keeper project (must survive)
    keeper_boq_id = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO oe_boq_boq VALUES (?, ?, ?)",
        (keeper_boq_id, keeper_proj_id, "Keeper BOQ"),
    )
    cur.execute(
        "INSERT INTO oe_boq_position VALUES (?, ?, ?)",
        (str(uuid.uuid4()), keeper_boq_id, "keeper-pos"),
    )

    con.commit()
    con.close()
    return db_path


def _count(db_path: Path, table: str) -> int:
    with sqlite3.connect(str(db_path)) as con:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ─────────────────────────────────────────────────────────────────────────
# _classify — name-pattern heuristic
# ─────────────────────────────────────────────────────────────────────────


def test_classify_keeper_names():
    assert _classify("Wohnpark Friedrichshain — Berlin") == "KEEP"
    assert _classify("Library Center") == "KEEP"
    assert _classify("Downtown Medical Center") == "KEEP"


def test_classify_blacklist_names():
    assert _classify("Test Project abc123") == "DELETE"
    assert _classify("CrossMod Project 9a8b7c") == "DELETE"
    assert _classify("Smoke Test Project 0001") == "DELETE"
    assert _classify("BOQ Test") == "DELETE"
    assert _classify("Schedule Test") == "DELETE"
    assert _classify("ReqBIM Project deadbe") == "DELETE"
    assert _classify("BIMPre Project caf3f3") == "DELETE"
    assert _classify("Regression Project 222222") == "DELETE"
    assert _classify("ExcelQuality 333333") == "DELETE"
    assert _classify("Export Integrity 444444") == "DELETE"
    assert _classify("TenderingSmoke") == "DELETE"
    assert _classify("Unified Markups E2E") == "DELETE"
    assert _classify("DWG Debug") == "DELETE"
    assert _classify("CDE Audit Project abc123") == "DELETE"
    assert _classify("Audit Probe Project") == "DELETE"
    assert _classify("test") == "DELETE"


def test_classify_uncertain_names():
    """Anything that doesn't hit either list is flagged for review."""
    assert _classify("Some Custom User Project") == "UNCERTAIN"
    assert _classify("Brand New Project Name") == "UNCERTAIN"


# ─────────────────────────────────────────────────────────────────────────
# Task #238 — Wave-3 agent-test cruft patterns. Each new pattern must
# match its example name AND must NOT swallow legit user projects with
# similar prefixes. The "negative" test is the load-bearing one — a
# greedy regex here would silently delete real customer data.
# ─────────────────────────────────────────────────────────────────────────


def test_classify_wave3_csv_injection_project_matches_hex_suffix():
    assert _classify("CSV Injection Project abc123") == "DELETE"
    assert _classify("CSV Injection Project deadbe") == "DELETE"
    # No hex suffix — should NOT match (only the suffixed agent-test rows
    # are cruft; a hand-typed legit name without a hex tail must survive).
    assert _classify("CSV Injection Project") == "UNCERTAIN"
    # Trailing extra text after the hex must NOT match (the regex is anchored).
    assert _classify("CSV Injection Project abc123 — Berlin") == "UNCERTAIN"


def test_classify_wave3_cycle_test_matches_hex_suffix():
    assert _classify("Cycle Test 4d1c6c") == "DELETE"
    assert _classify("Cycle Test ffffff") == "DELETE"
    # The bare phrase must not be caught — could plausibly be a real name.
    assert _classify("Cycle Test") == "UNCERTAIN"
    # Distinct project that just happens to contain the words: keep alone.
    assert _classify("Cycle Test Plant — Munich") == "UNCERTAIN"


def test_classify_wave3_xss_storage_matches_hex_suffix():
    assert _classify("XSS Storage 8776fd") == "DELETE"
    assert _classify("XSS Storage 0000aa") == "DELETE"
    assert _classify("XSS Storage") == "UNCERTAIN"


def test_classify_wave3_import_safety_project_matches():
    """``^Import Safety Project`` is intentionally permissive — the
    earlier wave produced both hex-suffixed and free-text variants
    (``Import Safety Project deadbe``, ``Import Safety Project (corrupt CSV)``).
    Anything that *starts* with the literal phrase is cruft.
    """
    assert _classify("Import Safety Project") == "DELETE"
    assert _classify("Import Safety Project abc123") == "DELETE"
    assert _classify("Import Safety Project (corrupt CSV)") == "DELETE"


def test_classify_wave3_module_routes_project_matches():
    assert _classify("Module Routes Project") == "DELETE"
    assert _classify("Module Routes Project a1b2c3") == "DELETE"
    assert _classify("Module Routes Project — variant") == "DELETE"


def test_classify_mitte_tower_phase_1_duplicate_cruft():
    """The legit demo is "Mitte Tower Phase 2 (Berlin)" — the bare
    "Phase 1" sibling without a city qualifier is a known seed-pollution
    duplicate that should be cleaned. The legitimate row must survive.
    """
    assert _classify("Mitte Tower Phase 1") == "DELETE"
    # The real demo project must be left alone — different name shape.
    assert _classify("Mitte Tower Phase 2 (Berlin)") == "UNCERTAIN"
    # Defence-in-depth: a hand-renamed user project must also survive.
    assert _classify("Mitte Tower Phase 1 — Berlin") == "UNCERTAIN"


def test_classify_wave3_does_not_match_legit_projects_with_similar_prefix():
    """Real customer projects sometimes share a prefix word with the
    cruft patterns. None of these must classify as DELETE.
    """
    legit_names = [
        "Mitte Tower Phase 2 (Berlin)",
        "Cycle Track Bridge — Amsterdam",
        "Storage Unit Renovation",
        "Module Plant Conversion (Hamburg)",
        "Safety Project — Site B",
    ]
    for name in legit_names:
        assert _classify(name) != "DELETE", (
            f"{name!r} must NOT be classified DELETE — would destroy real data"
        )


# ─────────────────────────────────────────────────────────────────────────
# main() — end-to-end behaviour against the synthetic DB
# ─────────────────────────────────────────────────────────────────────────


def test_dry_run_does_not_modify_db(synthetic_db: Path, capsys):
    """Default invocation prints a plan but changes nothing."""
    before_projects = _count(synthetic_db, "oe_projects_project")
    before_docs = _count(synthetic_db, "oe_documents_document")
    before_boqs = _count(synthetic_db, "oe_boq_boq")
    before_pos = _count(synthetic_db, "oe_boq_position")

    rc = main(["--db", str(synthetic_db)])

    assert rc == 0
    assert _count(synthetic_db, "oe_projects_project") == before_projects
    assert _count(synthetic_db, "oe_documents_document") == before_docs
    assert _count(synthetic_db, "oe_boq_boq") == before_boqs
    assert _count(synthetic_db, "oe_boq_position") == before_pos

    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    assert "KEEP" in out
    assert "DELETE" in out
    assert "UNCERTAIN" in out


def test_execute_deletes_blacklist_keeps_keepers(synthetic_db: Path, capsys):
    """``--execute`` removes blacklist + their children, keepers survive."""
    rc = main(["--db", str(synthetic_db), "--execute", "--no-backup"])
    assert rc == 0

    with sqlite3.connect(str(synthetic_db)) as con:
        kept_names = {row[0] for row in con.execute("SELECT name FROM oe_projects_project")}

    # Three keepers (two unique-named + one with demo_id metadata)
    assert "Wohnpark Friedrichshain — Berlin" in kept_names
    assert "Library Center" in kept_names
    assert "Downtown Medical Center" in kept_names
    # Two uncertain names default to keep
    assert "Some Custom User Project" in kept_names
    assert "Another One The User Made" in kept_names
    # All blacklist names are gone
    for blacklisted in [
        "Test Project abc123",
        "CrossMod Project 9a8b7c",
        "Smoke Test Project 111111",
        "BOQ Test",
        "Schedule Test",
        "TenderingSmoke",
        "test",
    ]:
        assert blacklisted not in kept_names

    # Children of deleted project are gone, children of keeper survive
    with sqlite3.connect(str(synthetic_db)) as con:
        # The Library Center keeper had 1 doc; the Test Project had 2.
        # Only the keeper doc should survive.
        doc_labels = {row[0] for row in con.execute("SELECT name FROM oe_documents_document")}
        assert doc_labels == {"keeper-doc"}

        # BOQ rows: only keeper-BOQ survives
        boq_names = {row[0] for row in con.execute("SELECT name FROM oe_boq_boq")}
        assert boq_names == {"Keeper BOQ"}

        # Position rows: 3 from test BOQ gone, 1 from keeper survives
        pos_labels = {row[0] for row in con.execute("SELECT description FROM oe_boq_position")}
        assert pos_labels == {"keeper-pos"}


def test_execute_creates_backup_unless_disabled(synthetic_db: Path):
    """Backup file is created next to the DB during ``--execute``."""
    rc = main(["--db", str(synthetic_db), "--execute"])
    assert rc == 0

    siblings = list(synthetic_db.parent.iterdir())
    backups = [p for p in siblings if p.name.startswith(synthetic_db.name + ".cleanup-backup-")]
    assert len(backups) == 1
    assert backups[0].stat().st_size > 0


def test_execute_no_backup_flag_skips_backup(synthetic_db: Path):
    rc = main(["--db", str(synthetic_db), "--execute", "--no-backup"])
    assert rc == 0
    siblings = list(synthetic_db.parent.iterdir())
    assert all("cleanup-backup-" not in p.name for p in siblings)


def test_include_uncertain_folds_them_into_delete(synthetic_db: Path):
    """``--include-uncertain`` deletes the unrecognised single-named rows too."""
    rc = main(
        ["--db", str(synthetic_db), "--execute", "--no-backup", "--include-uncertain"]
    )
    assert rc == 0
    with sqlite3.connect(str(synthetic_db)) as con:
        kept = {row[0] for row in con.execute("SELECT name FROM oe_projects_project")}
    assert "Some Custom User Project" not in kept
    assert "Another One The User Made" not in kept
    # Keepers still kept
    assert "Wohnpark Friedrichshain — Berlin" in kept
    assert "Downtown Medical Center" in kept


def test_demo_id_metadata_overrides_pattern(synthetic_db: Path):
    """A row with metadata.demo_id set is always KEEP, even if its name
    happens to match a blacklist pattern. Defends against an operator
    accidentally renaming a demo project to something test-like.
    """
    with sqlite3.connect(str(synthetic_db)) as con:
        con.execute(
            "INSERT INTO oe_projects_project VALUES (?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                "Test Project zzzzzz",  # would normally be DELETE
                "active",
                '{"demo_id":"warehouse-dubai"}',  # metadata override
                "2026-04-26",
            ),
        )
        con.commit()

    rc = main(["--db", str(synthetic_db), "--execute", "--no-backup"])
    assert rc == 0

    with sqlite3.connect(str(synthetic_db)) as con:
        kept = [
            row[0]
            for row in con.execute("SELECT name FROM oe_projects_project")
        ]
    assert "Test Project zzzzzz" in kept


def test_missing_db_returns_error(tmp_path: Path):
    rc = main(["--db", str(tmp_path / "does-not-exist.db")])
    assert rc == 2


def test_idempotent_second_run_is_a_noop(synthetic_db: Path):
    """After cleanup, running again finds nothing to delete (dry-run shows 0)."""
    main(["--db", str(synthetic_db), "--execute", "--no-backup"])

    rc = main(["--db", str(synthetic_db)])
    assert rc == 0
    # Snapshot row count remains stable on subsequent dry-runs.
    n1 = _count(synthetic_db, "oe_projects_project")
    main(["--db", str(synthetic_db)])
    n2 = _count(synthetic_db, "oe_projects_project")
    assert n1 == n2

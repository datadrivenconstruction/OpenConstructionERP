"""Local SQLite cleanup — delete QA / test cruft, keep deeply-worked demos.

Why this exists
---------------
``BUG-D02`` and ``BUG-USERS-POLLUTION`` from the v2.5.0 QA report describe
the same root cause: ``~/.openestimate/openestimate.db`` (and the dev
copy at ``backend/openestimate.db``) accumulates rows from every install,
test run, and `make seed` invocation. After a few months the DB has
hundreds of "Test Project ...", "CrossMod Project ...", "Smoke Test ..."
rows that obscure the actual seeded demo content.

This script identifies those cruft rows by name pattern, walks every
table with a ``project_id`` foreign key, and deletes the matched rows
together with their children. It defaults to **dry-run** — it prints
what would be deleted, takes no action, and exits 0. Pass ``--execute``
to actually perform the deletes (a backup is taken automatically).

Safety properties
-----------------
* **Default is dry-run.** No row is touched unless ``--execute`` is set.
* **Backup before delete.** A timestamped copy of the DB file is created
  in the same directory.
* **Three categories.** ``KEEP``, ``DELETE``, ``UNCERTAIN``. Uncertain
  rows are NOT deleted by default; pass ``--include-uncertain`` to fold
  them into the delete batch (after reviewing the dry-run output).
* **Cascade by hand.** SQLite's ``ON DELETE CASCADE`` is only honoured
  when ``PRAGMA foreign_keys=ON`` is set per-connection — and many of
  our project_id columns don't even have an FK constraint declared.
  This script enumerates every table with a ``project_id`` column and
  deletes from each one in dependency order.
* **BOQ children.** For each surviving BOQ row, position, section,
  markup, snapshot, and activity-log rows are also cleaned. Activity
  logs are a separate FK target (``boq_id``) that wouldn't be reached
  by deleting just the project.

Patterns
--------
The blacklist is conservative. It only matches names that are obvious
QA / test artefacts:

* ``Test Project ...``
* ``CrossMod Project ...``
* ``Smoke Test ...``
* ``Schedule Test``
* ``BOQ Test``
* ``BIMPre Project ...``
* ``ReqBIM Project ...``
* ``Regression Project ...``
* ``ExcelQuality ...``
* ``Export Integrity ...``
* ``TenderingSmoke``
* ``Unified Markups E2E``
* ``DWG Debug``
* ``CDE Audit Project ...``
* ``Audit Probe Project``
* literal ``test``
* ``CSV Injection Project ...`` (Task #238 — agent test cruft)
* ``Cycle Test ...`` (Task #238)
* ``XSS Storage ...`` (Task #238)
* ``Import Safety Project ...`` (Task #238)
* ``Module Routes Project ...`` (Task #238)
* ``Mitte Tower Phase 1`` (Task #238 — duplicate-seed cruft)

Anything else (including the deeply-worked demos like *Wohnpark
Friedrichshain — Berlin*, *Boylston Crossing — Boston Mixed-Use*,
*Residencial Salamanca — Madrid*, *Residencial Vila Madalena — São
Paulo*, *Library Center*, *Portland Technical School*, *Downtown
Medical Center*) is treated as a keeper unless the operator says
otherwise.

Usage
-----

    # Dry-run (default) — prints what would happen
    python -m app.scripts.cleanup_local_db --db backend/openestimate.db

    # Actually delete + backup
    python -m app.scripts.cleanup_local_db --db backend/openestimate.db --execute

    # Add ``--include-uncertain`` to also delete unidentified single-name
    # projects that didn't match a known good pattern.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Patterns that match QA / test cruft project names. Each entry is a regex
# anchored at the start. The optional trailing ``\s+[0-9a-f]{6,}`` clause
# matches the random hex suffix that test-runner factories append.
_BLACKLIST_PATTERNS: tuple[str, ...] = (
    r"^Test Project(\s+[0-9a-f]{6,})?$",
    r"^CrossMod Project(\s+[0-9a-f]{6,})?$",
    r"^Smoke Test Project(\s+[0-9a-f]{6,})?$",
    r"^Smoke Test\s.*$",
    r"^Schedule Test$",
    r"^BOQ Test$",
    r"^BIMPre Project(\s+[0-9a-f]{6,})?$",
    r"^ReqBIM Project(\s+[0-9a-f]{6,})?$",
    r"^Regression Project(\s+[0-9a-f]{6,})?$",
    r"^ExcelQuality(\s+[0-9a-f]{6,})?$",
    r"^Export Integrity(\s+[0-9a-f]{6,})?$",
    r"^TenderingSmoke$",
    r"^Unified Markups E2E$",
    r"^DWG Debug$",
    r"^CDE Audit Project(\s+[0-9a-f]{6,})?$",
    r"^Audit Probe Project$",
    r"^test$",
    # Wave 3 agent-test artefacts (Task #238 — extends to cover the rows
    # earlier waves of agent-generated integration tests left behind in
    # ``backend/openestimate.db`` before per-test SQLite isolation became
    # mandatory). All anchored & strict so they don't accidentally swallow
    # legitimate user projects whose names start with the same prefix.
    r"^CSV Injection Project [0-9a-f]+$",
    r"^Cycle Test [0-9a-f]+$",
    r"^XSS Storage [0-9a-f]+$",
    r"^Import Safety Project.*$",
    r"^Module Routes Project.*$",
    # Test-pollution duplicate of the *Mitte Tower Phase 2 (Berlin)* demo —
    # an earlier seeder bug created a no-suffix "Phase 1" sibling that
    # never had real BOQ data attached. The legitimate row is "Phase 2
    # (Berlin)"; "Phase 1" without parens is the cruft.
    r"^Mitte Tower Phase 1$",
)

# Names of the deeply-worked demo projects that are always kept regardless
# of any other heuristic.
_KEEPER_NAMES: frozenset[str] = frozenset(
    {
        "Residential Complex Berlin",
        "Office Tower London",
        "Downtown Medical Center",
        "Logistics Warehouse Dubai",
        "Primary School Paris",
        "Wohnpark Friedrichshain — Berlin",
        "Boylston Crossing — Boston Mixed-Use",
        "Residencial Salamanca — Madrid",
        "Residencial Vila Madalena — São Paulo",
        "Library Center",
        "Portland Technical School",
    }
)


def _classify(name: str) -> str:
    """Return one of KEEP / DELETE / UNCERTAIN."""
    if name in _KEEPER_NAMES:
        return "KEEP"
    for pattern in _BLACKLIST_PATTERNS:
        if re.match(pattern, name):
            return "DELETE"
    return "UNCERTAIN"


def _project_id_tables(con: sqlite3.Connection) -> list[str]:
    """Return all table names that have a ``project_id`` column."""
    cur = con.execute(
        "SELECT m.name FROM sqlite_master m, pragma_table_info(m.name) p "
        "WHERE m.type='table' AND p.name='project_id' "
        "ORDER BY m.name"
    )
    return [row[0] for row in cur.fetchall()]


def _boq_id_tables(con: sqlite3.Connection) -> list[str]:
    """Return all tables with a ``boq_id`` column.

    These are the indirect children — BOQ rows live in ``oe_boq_boq``
    which has a project_id, but their positions / sections / markups
    only know about boq_id.
    """
    cur = con.execute(
        "SELECT m.name FROM sqlite_master m, pragma_table_info(m.name) p "
        "WHERE m.type='table' AND p.name='boq_id' AND m.name != 'oe_boq_boq' "
        "ORDER BY m.name"
    )
    return [row[0] for row in cur.fetchall()]


def _ids_in(con: sqlite3.Connection, table: str, where_col: str, values: list[str]) -> list[str]:
    """Return the ``id`` of every row in ``table`` whose ``where_col`` is in
    ``values``. Used to collect BOQ ids before they're deleted so we can
    delete their child rows from the boq_id-FK tables.
    """
    if not values:
        return []
    placeholders = ",".join(["?"] * len(values))
    cur = con.execute(
        f"SELECT id FROM \"{table}\" WHERE {where_col} IN ({placeholders})",
        values,
    )
    return [row[0] for row in cur.fetchall()]


def _delete_in(con: sqlite3.Connection, table: str, where_col: str, values: list[str]) -> int:
    """``DELETE FROM table WHERE where_col IN values``. Returns row count."""
    if not values:
        return 0
    placeholders = ",".join(["?"] * len(values))
    cur = con.execute(
        f"DELETE FROM \"{table}\" WHERE {where_col} IN ({placeholders})",
        values,
    )
    return cur.rowcount


def _backup_db(db_path: Path) -> Path:
    """Snapshot the DB file before any destructive operation."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = db_path.with_name(f"{db_path.name}.cleanup-backup-{timestamp}")
    shutil.copy2(db_path, backup_path)
    return backup_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--db",
        type=Path,
        required=True,
        help="Path to the SQLite database file to clean",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform the deletes (default is dry-run)",
    )
    parser.add_argument(
        "--include-uncertain",
        action="store_true",
        help="Also delete uncertain rows (unrecognised names). Off by default.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip the timestamped backup. Combine with --execute at your own risk.",
    )
    args = parser.parse_args(argv)

    # Project names contain U+2014 em-dash and accented chars (e.g. "São Paulo").
    # On Windows the default console code page is cp1252 and ``print`` raises
    # UnicodeEncodeError on those characters. Reconfigure stdout/stderr to
    # UTF-8 with a fallback so the script never aborts mid-report.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    db_path: Path = args.db
    if not db_path.is_file():
        print(f"[ERROR] Database not found: {db_path}", file=sys.stderr)
        return 2

    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA foreign_keys = ON")

    # ── 1. Classify every project ───────────────────────────────────
    cur = con.execute(
        "SELECT id, name, status, "
        "json_extract(metadata, '$.demo_id') AS demo_id, created_at "
        "FROM oe_projects_project ORDER BY created_at"
    )
    classified: dict[str, list[tuple]] = {"KEEP": [], "DELETE": [], "UNCERTAIN": []}
    for pid, name, status, demo_id, created in cur.fetchall():
        bucket = _classify(name)
        # ``demo_id`` set by the official seeder always wins — keepers.
        if demo_id is not None:
            bucket = "KEEP"
        classified[bucket].append((pid, name, status, demo_id, created))

    print(f"Database: {db_path}")
    print(f"Total projects: {sum(len(v) for v in classified.values())}")
    print(f"  KEEP:      {len(classified['KEEP'])}")
    print(f"  DELETE:    {len(classified['DELETE'])}")
    print(f"  UNCERTAIN: {len(classified['UNCERTAIN'])}")
    print()

    # Show the keepers explicitly so the operator can sanity-check.
    if classified["KEEP"]:
        print("=== KEEP ===")
        for pid, name, status, demo_id, _ in classified["KEEP"]:
            tag = f"demo={demo_id}" if demo_id else "user"
            print(f"  [{status:8s}] {name}  ({tag})")
        print()

    if classified["UNCERTAIN"]:
        print("=== UNCERTAIN (kept by default; pass --include-uncertain to delete) ===")
        for _, name, status, _, _ in classified["UNCERTAIN"]:
            print(f"  [{status:8s}] {name}")
        print()

    if classified["DELETE"]:
        print("=== DELETE (matched a blacklist pattern) ===")
        # Cluster identical base names for compact output.
        clusters: dict[str, int] = {}
        for _, name, _, _, _ in classified["DELETE"]:
            base = re.sub(r"\s+[0-9a-f]{6,}\s*$", " <suffix>", name).strip()
            clusters[base] = clusters.get(base, 0) + 1
        for base, count in sorted(clusters.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f"  [{count:3d}] {base}")
        print()

    # Build the final delete list.
    delete_set = list(classified["DELETE"])
    if args.include_uncertain:
        delete_set.extend(classified["UNCERTAIN"])

    if not delete_set:
        print("Nothing to delete.")
        con.close()
        return 0

    project_ids = [row[0] for row in delete_set]

    # ── 2. Compute child counts (for dry-run accounting) ────────────
    proj_tables = _project_id_tables(con)
    boq_ids = _ids_in(con, "oe_boq_boq", "project_id", project_ids)
    boq_child_tables = _boq_id_tables(con)

    print("Cascade plan:")
    total_rows = 0
    for tbl in proj_tables:
        cur = con.execute(
            f"SELECT COUNT(*) FROM \"{tbl}\" WHERE project_id IN ({','.join(['?'] * len(project_ids))})",
            project_ids,
        )
        n = cur.fetchone()[0]
        if n:
            print(f"  {tbl:50s} {n} row(s) (via project_id)")
            total_rows += n
    for tbl in boq_child_tables:
        if not boq_ids:
            continue
        cur = con.execute(
            f"SELECT COUNT(*) FROM \"{tbl}\" WHERE boq_id IN ({','.join(['?'] * len(boq_ids))})",
            boq_ids,
        )
        n = cur.fetchone()[0]
        if n:
            print(f"  {tbl:50s} {n} row(s) (via boq_id)")
            total_rows += n
    print(f"  {'oe_projects_project':50s} {len(project_ids)} row(s)")
    total_rows += len(project_ids)
    print(f"  {'TOTAL':50s} {total_rows} row(s)")
    print()

    if not args.execute:
        print("[DRY-RUN] No changes made. Pass --execute to perform the cleanup.")
        con.close()
        return 0

    # ── 3. Execute ─────────────────────────────────────────────────
    if not args.no_backup:
        backup = _backup_db(db_path)
        print(f"[BACKUP] Snapshot saved to: {backup}")

    deleted_rows = 0
    try:
        con.execute("BEGIN")

        # Children-of-BOQ first (positions / markups / activity_log / etc.)
        for tbl in boq_child_tables:
            n = _delete_in(con, tbl, "boq_id", boq_ids)
            if n:
                print(f"  - deleted {n:5d} from {tbl} (boq_id)")
                deleted_rows += n

        # All project_id-FK tables
        for tbl in proj_tables:
            n = _delete_in(con, tbl, "project_id", project_ids)
            if n:
                print(f"  - deleted {n:5d} from {tbl} (project_id)")
                deleted_rows += n

        # Finally, the project rows themselves
        n = _delete_in(con, "oe_projects_project", "id", project_ids)
        deleted_rows += n
        print(f"  - deleted {n:5d} from oe_projects_project (id)")

        con.execute("COMMIT")
    except sqlite3.Error as exc:
        con.execute("ROLLBACK")
        print(f"[ERROR] DB error during cleanup, rolled back: {exc}", file=sys.stderr)
        con.close()
        return 1

    # Reclaim the freed pages
    con.execute("VACUUM")
    con.close()

    print()
    print(f"[DONE] Deleted {deleted_rows} row(s) across project + child tables.")
    print("Run again to verify the dry-run is empty.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

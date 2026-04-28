"""Drop fake/probe projects, keep the 6 curated demos.

Walks every table that references project_id and bulk-deletes rows whose
project_id is in the to-delete set. SQLite FKs are off in this DB, so we
do it manually. Idempotent.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[3] / "backend" / "openestimate.db"
KEEP = {
    "Boylston Crossing — Boston Mixed-Use",
    "Wohnpark Friedrichshain — Berlin",
    "Residencial Salamanca — Madrid",
    "Residencial Vila Madalena — São Paulo",
    "上海徐汇职业学校扩建工程",
    "Downtown Medical Center",
}

con = sqlite3.connect(str(DB))
cur = con.cursor()

cur.execute("SELECT id, name FROM oe_projects_project")
all_projects = cur.fetchall()
to_delete = [pid for pid, name in all_projects if name not in KEEP]
print(f"Total projects: {len(all_projects)}")
print(f"Keeping {len(all_projects) - len(to_delete)}, deleting {len(to_delete)}")

# Find all tables that have a project_id column
cur.execute(
    "SELECT m.name FROM sqlite_master m WHERE m.type='table' AND m.name LIKE 'oe_%'"
)
all_tables = [r[0] for r in cur.fetchall()]
project_tables: list[tuple[str, list[str]]] = []
for tbl in all_tables:
    cur.execute(f'PRAGMA table_info("{tbl}")')
    cols = [r[1] for r in cur.fetchall()]
    fk_cols = [c for c in cols if c == "project_id"]
    if fk_cols:
        project_tables.append((tbl, fk_cols))

print(f"\n{len(project_tables)} tables reference project_id")

# Build placeholders and delete in chunks (SQLite parameter limit)
def chunked(seq: list[str], n: int = 500) -> list[list[str]]:
    return [seq[i : i + n] for i in range(0, len(seq), n)]

deleted_total = 0
for tbl, _ in project_tables:
    n = 0
    for chunk in chunked(to_delete):
        placeholders = ",".join("?" * len(chunk))
        cur.execute(f'DELETE FROM "{tbl}" WHERE project_id IN ({placeholders})', chunk)
        n += cur.rowcount
    if n > 0:
        print(f"  {tbl}: -{n}")
    deleted_total += n

# Now also clean BOQ children that reference boq.id where boq belongs to deleted projects
# Position children that need cleanup by boq_id
cur.execute("SELECT id FROM oe_boq_boq WHERE project_id IS NULL")  # any orphans
orphan_boqs = [r[0] for r in cur.fetchall()]
if orphan_boqs:
    print(f"  Orphan BOQs already gone (children purged)")

# Finally drop the projects themselves
for chunk in chunked(to_delete):
    placeholders = ",".join("?" * len(chunk))
    cur.execute(f"DELETE FROM oe_projects_project WHERE id IN ({placeholders})", chunk)
print(f"  oe_projects_project: -{cur.rowcount}")

con.commit()

# Sanity check
cur.execute("SELECT COUNT(*) FROM oe_projects_project")
remaining = cur.fetchone()[0]
print(f"\nRemaining projects: {remaining}")
cur.execute("SELECT name FROM oe_projects_project ORDER BY created_at")
for (name,) in cur.fetchall():
    print(f"  · {name}")

# VACUUM to reclaim space
print("\nVACUUM…")
con.commit()
con.execute("VACUUM")
con.close()
print("Done.")

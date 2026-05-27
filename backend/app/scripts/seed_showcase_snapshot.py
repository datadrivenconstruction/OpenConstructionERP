"""‌⁠‍Install the 7-project localized showcase from the committed snapshot.

A fresh install ships ``showcase_snapshot.json.gz`` (built by
``export_showcase_snapshot``). When the demo account has no projects yet
this loader bulk-restores that snapshot so a new user immediately sees
the whole platform working end-to-end in seven languages — a real
CWICR-resource estimate, linked BIM model, WBS, cost-model / EVM and
every operational module filled, each in the project's own language and
currency.

Design constraints (this runs inside application boot):

* **Never raises.** Any problem returns ``{"status": ...}`` so the
  caller can fall back to the classic 5 ORM demo projects. Boot must
  not break.
* **Idempotent.** ``INSERT OR REPLACE`` keyed on the deterministic ids;
  re-running repairs rather than duplicates. If all 7 projects already
  exist it is a no-op.
* **No prerequisites.** The snapshot is self-contained — it does not
  need the CWICR base, per-language CSVs or any network access. Every
  BOQ position embeds its localized resource breakdown already.
* **Owner re-mapping.** The snapshot's demo/estimator/manager user ids
  are rewritten to this installation's freshly created demo users.
* **SQLite only.** The deployment DB is SQLite; on any other backend
  the loader skips and the caller uses the ORM demos.

CLI (manual one-off, e.g. seeding an existing prod DB):

    python -m app.scripts.seed_showcase_snapshot <db_path> <owner_id> \
        [estimator_id] [manager_id]
"""

from __future__ import annotations

import base64
import gzip
import json
import logging
import sqlite3
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

SNAPSHOT_PATH = Path(__file__).resolve().parent / "showcase_snapshot.json.gz"

SHOWCASE_PIDS = [
    "da481707-a571-4367-a7b7-6b5211a912e1",
    "24c3ddfb-00db-44f0-b0b8-9d7ad4078cf2",
    "6128e9de-cb94-4278-9fbc-d2eeae77b4a6",
    "afe169f9-0e4a-4b2f-b2a6-344f3a7a79c1",
    "8646ba9e-257d-477b-a3e0-db05b9b40578",
    "311bcdd8-111e-4d41-9e25-c1bdc953d016",
    "0cefc29a-4e20-4287-be24-8ea0c2e4343b",
]


def _dec(v: object) -> object:
    """‌⁠‍Reverse ``export_showcase_snapshot._enc``."""
    if isinstance(v, dict) and "__b64__" in v:
        return base64.b64decode(v["__b64__"])
    return v


def seed_showcase_from_snapshot(
    db_path: str,
    owner_id: str,
    estimator_id: str = "",
    manager_id: str = "",
    *,
    force: bool = False,
    snapshot_path: Path = SNAPSHOT_PATH,
) -> dict:
    """‌⁠‍Bulk-load the showcase snapshot into ``db_path``.

    Returns a status dict. ``status`` is one of:
    ``ok`` (loaded), ``already`` (all 7 present, nothing to do),
    ``skipped`` (no artifact / not sqlite — caller should fall back),
    ``error`` (unexpected — caller should fall back).
    """
    # ``con`` is hoisted so the ``finally`` can always release the SQLite
    # write lock. If a per-table INSERT trips a NOT NULL/constraint mid-
    # snapshot (e.g. when a model gained a NOT NULL column whose default
    # is Python-side only — see #154 / oe_safety_incident.osha_recordable),
    # leaving the implicit transaction open keeps SQLite write-locked.
    # Subsequent boot steps then cascade as "database is locked".
    con: sqlite3.Connection | None = None
    try:
        if not snapshot_path.exists():
            return {"status": "skipped", "reason": "no-snapshot-artifact"}
        dbp = Path(db_path)
        if not dbp.exists():
            return {"status": "skipped", "reason": f"db-missing:{db_path}"}

        raw = gzip.decompress(snapshot_path.read_bytes()).decode("utf-8")
        art = json.loads(raw)
        if art.get("schema") != 1:
            return {"status": "skipped", "reason": f"schema:{art.get('schema')}"}

        con = sqlite3.connect(str(dbp), timeout=120)
        con.row_factory = sqlite3.Row
        cur = con.cursor()

        # sqlite sanity — a non-sqlite file would already have failed to
        # connect, but be explicit about the project table existing.
        have_proj = cur.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='oe_projects_project'"
        ).fetchone()[0]
        if not have_proj:
            return {"status": "skipped", "reason": "schema-not-initialised"}

        qp = ",".join("?" * len(SHOWCASE_PIDS))
        present = cur.execute(
            f"SELECT count(*) FROM oe_projects_project WHERE id IN ({qp})",
            SHOWCASE_PIDS,
        ).fetchone()[0]
        if present >= len(SHOWCASE_PIDS) and not force:
            return {"status": "already", "projects": present}

        # user-id remap: snapshot old ids -> this install's demo users
        su = art.get("users", {})
        remap: dict[str, str] = {}
        if su.get("demo"):
            remap[su["demo"]] = owner_id
        if su.get("estimator"):
            remap[su["estimator"]] = estimator_id or owner_id
        if su.get("manager"):
            remap[su["manager"]] = manager_id or owner_id

        def fix(v: object) -> object:
            v = _dec(v)
            if isinstance(v, str) and v in remap:
                return remap[v]
            return v

        cur.execute("PRAGMA foreign_keys=OFF")
        loaded_tables = 0
        loaded_rows = 0
        for tbl in art.get("tables", []):
            name = tbl["name"]
            snap_cols = tbl["cols"]
            rows = tbl["rows"]
            if not rows:
                continue
            live_cols = [r[1] for r in cur.execute(f"PRAGMA table_info({name})")]
            if not live_cols:
                # table no longer exists in this schema version — skip
                logger.warning("showcase snapshot: table %s absent, skipping", name)
                continue
            live_set = set(live_cols)
            use = [(i, c) for i, c in enumerate(snap_cols) if c in live_set]
            if not use:
                continue
            cols = [c for _, c in use]
            idx = [i for i, _ in use]
            placeholders = ",".join("?" * len(cols))
            collist = ",".join(f'"{c}"' for c in cols)
            sql = f"INSERT OR REPLACE INTO {name} ({collist}) VALUES ({placeholders})"
            batch = [[fix(r[i]) for i in idx] for r in rows]
            try:
                cur.executemany(sql, batch)
            except sqlite3.IntegrityError as exc:
                # A single table failing (e.g. a column added post-snapshot
                # with no server_default) must not abort the whole seed —
                # skip the table, surface a warning, and keep going. The
                # outer ``finally`` still rolls back the partial txn for
                # the bad table because we ``con.rollback()`` here.
                logger.warning(
                    "showcase snapshot: table %s integrity error, skipping (%s)",
                    name,
                    exc,
                )
                con.rollback()
                continue
            loaded_tables += 1
            loaded_rows += len(batch)

        con.commit()
        final = cur.execute(
            f"SELECT count(*) FROM oe_projects_project WHERE id IN ({qp})",
            SHOWCASE_PIDS,
        ).fetchone()[0]
        return {
            "status": "ok",
            "projects": final,
            "tables": loaded_tables,
            "rows": loaded_rows,
        }
    except Exception as exc:  # noqa: BLE001 — boot must never break
        logger.warning("showcase snapshot load failed: %s", exc)
        if con is not None:
            try:
                con.rollback()
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass
        return {"status": "error", "reason": str(exc)[:200]}
    finally:
        if con is not None:
            try:
                con.close()
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass


def main() -> int:
    if len(sys.argv) < 3:
        print(
            "usage: python -m app.scripts.seed_showcase_snapshot "
            "<db_path> <owner_id> [estimator_id] [manager_id] [--force]"
        )
        return 2
    db = sys.argv[1]
    owner = sys.argv[2]
    est = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else ""
    mgr = sys.argv[4] if len(sys.argv) > 4 and not sys.argv[4].startswith("--") else ""
    force = "--force" in sys.argv
    res = seed_showcase_from_snapshot(db, owner, est, mgr, force=force)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("status") in ("ok", "already") else 1


if __name__ == "__main__":
    sys.exit(main())

"""‌⁠‍Export the 7-project localized showcase into a committed snapshot.

Dev-only tool. Run it against a database that already holds the fully
built, audited 7-project showcase (the deterministic-id projects with
their localized BOQs, WBS, budget/EVM, BIM links and every operational
module filled). It walks the project dependency closure and writes a
single gzip-compressed JSON artifact next to this module:

    backend/app/scripts/showcase_snapshot.json.gz

That artifact is what ``seed_showcase_snapshot`` bulk-loads on a fresh
install so a new user immediately sees the whole platform working in
seven languages. The artifact is the *only* thing that needs to be
committed/packaged — no CWICR base or per-language CSVs required at
install time.

Closure rules (every ``oe_*`` table):
  * has ``project_id``            -> rows for the 7 project ids
  * ``oe_projects_project``       -> rows whose ``id`` is one of the 7
  * has ``boq_id``                -> rows under the 7 BOQs
  * has ``model_id``              -> rows under the 7 BIM models
  * has ``schedule_id``           -> rows under those projects' schedules
  * has ``boq_position_id``       -> rows under the 7 BOQs' positions
  * ``oe_costs_item``             -> source='cwicr_loc' + every cost item
                                     the 7 BOQs actually reference
  * otherwise                     -> skipped (global / unrelated)

The per-language ``oe_catalog_resource`` rows (cwicr_local, ~50k) are
intentionally NOT exported: every BOQ position already embeds its
localized resource breakdown in ``metadata.resources`` so the estimate,
budget, EVM and 5D cost-model all render with real numbers. The
Cost-Database browser for those regions stays empty until a normal
catalogue import.

Run: python -m app.scripts.export_showcase_snapshot
"""

from __future__ import annotations

import base64
import gzip
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

# The seven deterministic showcase project ids. Stable across rebuilds
# so the snapshot, the loader and any audit reference them identically.
SHOWCASE_PIDS = [
    "da481707-a571-4367-a7b7-6b5211a912e1",  # EN  Riverside Commercial Tower
    "24c3ddfb-00db-44f0-b0b8-9d7ad4078cf2",  # DE  Wohnquartier Berlin-Mitte
    "6128e9de-cb94-4278-9fbc-d2eeae77b4a6",  # ZH  上海浦东商务综合楼
    "afe169f9-0e4a-4b2f-b2a6-344f3a7a79c1",  # AR  برج الأعمال – دبي
    "8646ba9e-257d-477b-a3e0-db05b9b40578",  # HI  मुंबई आवासीय परिसर
    "311bcdd8-111e-4d41-9e25-c1bdc953d016",  # RU  ЖК «Нева» — СПб
    "0cefc29a-4e20-4287-be24-8ea0c2e4343b",  # BR  Edifício Faria Lima SP
]

SNAPSHOT_PATH = Path(__file__).resolve().parent / "showcase_snapshot.json.gz"


def _enc(v: object) -> object:
    """‌⁠‍JSON-safe encoding of a sqlite cell (bytes -> base64 marker)."""
    if isinstance(v, (bytes, bytearray)):
        return {"__b64__": base64.b64encode(bytes(v)).decode("ascii")}
    return v


def _in(col: str, ids: list[str]) -> tuple[str, list[str]]:
    qm = ",".join("?" * len(ids))
    return f"{col} IN ({qm})", list(ids)


def export(db_path: str, out_path: Path = SNAPSHOT_PATH) -> dict:
    con = sqlite3.connect(db_path, timeout=60)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    pids = SHOWCASE_PIDS
    qp = ",".join("?" * len(pids))

    boq_ids = [r[0] for r in cur.execute(f"SELECT id FROM oe_boq_boq WHERE project_id IN ({qp})", pids)]
    model_ids = [r[0] for r in cur.execute(f"SELECT id FROM oe_bim_model WHERE project_id IN ({qp})", pids)]
    sched_ids = [
        r[0]
        for r in cur.execute(
            f"SELECT id FROM oe_schedule_schedule WHERE project_id IN ({qp})",
            pids,
        )
    ]
    pos_ids: list[str] = []
    ref_cost_ids: set[str] = set()
    if boq_ids:
        qb = ",".join("?" * len(boq_ids))
        for r in cur.execute(
            "SELECT id,cost_code_id,"
            "json_extract(metadata,'$.cost_item_id') mci "
            f"FROM oe_boq_position WHERE boq_id IN ({qb})",
            boq_ids,
        ):
            pos_ids.append(r["id"])
            if r["cost_code_id"]:
                ref_cost_ids.add(r["cost_code_id"])
            if r["mci"]:
                ref_cost_ids.add(r["mci"])

    tables = [
        r[0]
        for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'oe_%' ORDER BY name")
    ]

    payload_tables: list[dict] = []
    skipped: list[str] = []
    total_rows = 0

    for t in tables:
        cols = [r[1] for r in cur.execute(f"PRAGMA table_info({t})")]
        colset = set(cols)
        where: str | None = None
        params: list[str] = []

        if "project_id" in colset:
            where, params = _in("project_id", pids)
        elif t == "oe_projects_project":
            where, params = _in("id", pids)
        elif "boq_id" in colset and boq_ids:
            where, params = _in("boq_id", boq_ids)
        elif "model_id" in colset and model_ids:
            where, params = _in("model_id", model_ids)
        elif "schedule_id" in colset and sched_ids:
            where, params = _in("schedule_id", sched_ids)
        elif "boq_position_id" in colset and pos_ids:
            where, params = _in("boq_position_id", pos_ids)
        elif t == "oe_costs_item":
            ids = sorted(ref_cost_ids)
            if ids:
                qi = ",".join("?" * len(ids))
                where = f"source='cwicr_loc' OR id IN ({qi})"
                params = ids
            else:
                where = "source='cwicr_loc'"
                params = []
        else:
            skipped.append(t)
            continue

        sel = ",".join(f'"{c}"' for c in cols)
        rows = [[_enc(row[c]) for c in cols] for row in cur.execute(f"SELECT {sel} FROM {t} WHERE {where}", params)]
        if not rows:
            # keep table out of the artifact entirely when empty for the 7
            continue
        payload_tables.append({"name": t, "cols": cols, "rows": rows})
        total_rows += len(rows)

    users = {}
    for slug in ("demo", "estimator", "manager"):
        row = cur.execute(
            "SELECT id FROM oe_users_user WHERE email=?",
            (f"{slug}@openestimator.io",),
        ).fetchone()
        if row:
            users[slug] = row[0]

    con.close()

    artifact = {
        "schema": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source_db": str(Path(db_path).name),
        "users": users,
        "pids": pids,
        "boq_ids": boq_ids,
        "model_ids": model_ids,
        "table_count": len(payload_tables),
        "row_count": total_rows,
        "tables": payload_tables,
    }
    raw = json.dumps(artifact, ensure_ascii=False, separators=(",", ":"))
    out_path.write_bytes(gzip.compress(raw.encode("utf-8"), 9))

    summary = {
        "out": str(out_path),
        "bytes_gz": out_path.stat().st_size,
        "tables": len(payload_tables),
        "rows": total_rows,
        "boqs": len(boq_ids),
        "models": len(model_ids),
        "schedules": len(sched_ids),
        "positions": len(pos_ids),
        "skipped_tables": len(skipped),
        "users": users,
    }
    return summary


def main() -> int:
    root = Path(__file__).resolve().parents[3]
    db = sys.argv[1] if len(sys.argv) > 1 else str(root / "backend" / "openestimate.db")
    if not Path(db).exists():
        print(f"!! db not found: {db}")
        return 2
    s = export(db)
    print(json.dumps(s, ensure_ascii=False, indent=2))
    mb = s["bytes_gz"] / 1048576
    print(f"\nSnapshot written: {s['rows']} rows / {s['tables']} tables -> {mb:.2f} MB gz")
    return 0


if __name__ == "__main__":
    sys.exit(main())

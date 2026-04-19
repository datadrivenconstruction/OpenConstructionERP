"""Resume helper for seed_demo_v2.

Use case: seed_demo_v2.py crashed/stuck after CAD conversion finished but
before BOQ build. Re-running from scratch wastes 15 min on reconversion.
This helper looks up the existing 5 demo projects + their ready BIM
models in the DB and runs only Phases 6 (CAD-driven BOQ + group links +
markups), 7 (validation) and 8 (summary).

Run:  python -m app.scripts.seed_demo_v2_resume
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

import httpx

from app.scripts.seed_demo_v2 import (  # noqa: E402
    BASE,
    LOCALES,
    PROJECT_SPECS,
    REPO_ROOT,
    build_cad_driven_boq,
    login_or_register,
    run_validation,
    seed_boq_markups,
)

DB_PATH = Path(__file__).resolve().parents[3] / "backend" / "openestimate.db"


def _lookup_existing(spec: dict) -> tuple[str | None, str | None]:
    """Return (project_id, ready_model_id) for the spec's project, if found."""
    if not DB_PATH.exists():
        return None, None
    con = sqlite3.connect(str(DB_PATH))
    cur = con.cursor()
    target_name = LOCALES[spec["locale"]]["project"]["name"]
    cur.execute(
        "SELECT id FROM oe_projects_project "
        "WHERE name = ? ORDER BY created_at DESC LIMIT 1",
        (target_name,),
    )
    row = cur.fetchone()
    if not row:
        con.close()
        return None, None
    project_id = row[0]
    cur.execute(
        "SELECT id FROM oe_bim_model "
        "WHERE project_id = ? AND status = 'ready' "
        "ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    )
    row = cur.fetchone()
    con.close()
    return project_id, (row[0] if row else None)


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=180.0) as client:
        print("=" * 70)
        print("  OpenEstimate — Demo Seeder v2 RESUME (Phases 6-7-8)")
        print("=" * 70)

        print("\n[1/3] Authenticate...")
        headers = await login_or_register(client)

        print("\n[2/3] Looking up existing projects + ready models in DB...")
        ready: list[tuple[dict, str, str]] = []   # (entry, project_id, model_id)
        for spec in PROJECT_SPECS:
            l10n = LOCALES[spec["locale"]]
            project_id, model_id = _lookup_existing(spec)
            if not project_id:
                print(f"  [{spec['key']}] !! project not found in DB — skip")
                continue
            if not model_id:
                print(
                    f"  [{spec['key']}] project {project_id[:8]} found "
                    f"but no ready BIM model — skip"
                )
                continue
            print(
                f"  [{spec['key']}] project={project_id[:8]} "
                f"model={model_id[:8]} ready"
            )
            entry = {"spec": spec, "l10n": l10n,
                     "project": {"id": project_id}}
            ready.append((entry, project_id, model_id))

        print(f"\n[3/3] Building CAD-driven BOQ + validations for {len(ready)} project(s)...")
        boq_handles: list[tuple[dict, str]] = []
        for entry, project_id, model_id in ready:
            spec = entry["spec"]
            l10n = entry["l10n"]
            print(f"\n  -- [{spec['key'].upper()}] BOQ build")
            try:
                result = await build_cad_driven_boq(
                    client, headers, project_id, spec["currency"],
                    model_id, l10n,
                )
            except Exception as exc:
                import traceback
                print(f"     !! BOQ build crashed: {exc}")
                traceback.print_exc()
                continue
            print(
                f"     sections: {result['sections']:>2}, "
                f"positions: {result['positions']:>2}, "
                f"BIM links: {result['links']:>3}"
            )
            if result["boq_id"]:
                boq_handles.append((entry, result["boq_id"]))
                n_markup = await seed_boq_markups(
                    client, headers, result["boq_id"], l10n,
                )
                print(f"     markups:  {n_markup}")

        print(f"\n  Running validations for {len(boq_handles)} BOQ(s)...")
        for entry, boq_id in boq_handles:
            spec = entry["spec"]
            l10n = entry["l10n"]
            res = await run_validation(
                client, headers, entry["project"]["id"], boq_id,
                l10n["validation_rule_sets"],
            )
            print(f"     [{spec['key']}] validation: {res.get('status', 'n/a')}")

        print("\n" + "=" * 70)
        print("  Resume complete.")
        print("=" * 70)
        for entry, _, _ in ready:
            spec = entry["spec"]
            project = entry["project"]
            print(
                f"  [{spec['key']}] {LOCALES[spec['locale']]['project']['name']}\n"
                f"       /projects/{project['id']}\n"
                f"       /bim?project={project['id']}\n"
                f"       (locale={spec['locale']}, currency={spec['currency']}, "
                f"standard={spec['classification_standard']})"
            )


if __name__ == "__main__":
    asyncio.run(main())

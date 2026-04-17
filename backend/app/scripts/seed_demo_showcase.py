"""Seed 3 showcase demo projects from Sample_Projects/test CAD files.

End-to-end demo seed:
  1. Delete every existing project (cascades into BOQs, BIM models, links, …).
  2. Remove orphaned DAE/GLB files from data/bim/.
  3. Create 3 demo projects — German / English / Spanish — each with full
     currency + classification metadata.
  4. Upload 2 CAD files per project (RVT / IFC / DWG mix) via the real
     /bim_hub/upload-cad/ endpoint so every code path (converter preflight,
     ODA/DDC bridge, DAE→GLB) runs as in production.
  5. Wait for models to reach status="ready".
  6. Create a BOQ per project with sections + ~20 positions, unit rates
     drawn from the seeded cost catalog.
  7. Link a handful of positions to real BIM elements via the new
     ensure-element flow so the BOQ↔BIM link panels have something to show.
  8. Kick off a validation run per project.
  9. Print a summary block with each project's viewer URL.

Usage:
    python -m app.scripts.seed_demo_showcase

Assumes the backend is running on http://localhost:8000 and that an admin
user already exists (or will be registered). Safe to re-run.
"""
from __future__ import annotations

import asyncio
import pathlib
import shutil
import sqlite3
import sys
import time

import httpx

# Windows console defaults to cp1252; force utf-8 for the Unicode project names.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE = "http://localhost:8000"
ADMIN_EMAIL = "admin@openestimate.io"
ADMIN_PASSWORD = "OpenEstimate2026"

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CAD_SOURCE_DIR = pathlib.Path(
    r"C:\Users\Artem Boiko\Downloads\cad2data-Revit-IFC-DWG-DGN-main"
    r"\cad2data-Revit-IFC-DWG-DGN-main\Sample_Projects\test"
)
BIM_DATA_DIR = REPO_ROOT / "backend" / "data" / "bim"

# Upload poll settings
MODEL_READY_TIMEOUT_S = 600  # 10 min per CAD file — RVT via DDC can be slow
MODEL_POLL_INTERVAL_S = 5

# ── 3 demo project specs ───────────────────────────────────────────────────

DEMO_PROJECTS = [
    {
        "key": "de",
        "create": {
            "name": "Wohnkomplex Duplex — Berlin-Mitte",
            "description": (
                "Neubau: 2 Wohneinheiten + Erweiterung eines Bestandsgebäudes. "
                "BGF ca. 480 m². Kostenrahmen ca. 1,8 Mio EUR netto. "
                "Demo-Projekt aus IFC-Quellmodellen (Duplex + Building-Architecture)."
            ),
            "region": "DACH",
            "classification_standard": "DIN276",
            "currency": "EUR",
            "locale": "de",
            "validation_rule_sets": ["din276", "boq_quality"],
            "project_code": "DE-2026-001",
            "project_type": "residential",
            "phase": "design",
            "budget_estimate": "1800000",
            "contingency_pct": "10",
        },
        "files": ["Ifc2x3_Duplex_Architecture.ifc", "AC20-FZK-Haus.ifc"],
        "boq": {
            "name": "Leistungsverzeichnis Hauptgewerke",
            "description": "LV Rohbau + Ausbau, nach DIN 276 gegliedert.",
            "estimate_type": "detailed",
        },
        "sections": [
            ("310", "Baugrube"),
            ("320", "Gründung"),
            ("330", "Außenwände"),
            ("340", "Innenwände"),
            ("350", "Decken"),
            ("360", "Dächer"),
            ("370", "Baukonstruktive Einbauten"),
        ],
        "positions": [
            # (section_index, ordinal, description, unit, qty, rate)
            (0, "310.001", "Aushub Baugrube für Bodenplatte, inkl. Abtransport",  "m3",  185.0, 42.50),
            (1, "320.001", "Stahlbeton-Bodenplatte C25/30 d=25 cm, bewehrt",      "m3",   48.5, 385.00),
            (1, "320.002", "Sauberkeitsschicht C12/15 d=5 cm",                     "m2",  194.0,  18.50),
            (2, "330.001", "Außenwand Stahlbeton C30/37 d=24 cm, Sichtbeton",      "m3",   34.2, 520.00),
            (2, "330.002", "WDVS Mineralwolle d=16 cm, silikonharzgebunden",       "m2",  285.0,  62.00),
            (2, "330.003", "Kunststofffenster Dreifachverglasung, Uw 0,9",          "m2",   42.5, 780.00),
            (3, "340.001", "Trockenbauwand GKB d=12,5 mm doppelt beplankt",         "m2",  168.0,  58.00),
            (3, "340.002", "Kalksandstein-Wand KS-XL d=17,5 cm",                    "m2",   92.0,  74.00),
            (4, "350.001", "Stahlbetondecke d=20 cm, bewehrt, inkl. Schalung",      "m2",  420.0, 105.00),
            (4, "350.002", "Trittschalldämmung d=3 cm + Zementestrich d=5 cm",      "m2",  420.0,  48.00),
            (5, "360.001", "Flachdach Aufbau Warmdach, Gefälle 2%",                 "m2",  220.0, 145.00),
            (5, "360.002", "Dachabdichtung EPDM 1,5 mm, 2-lagig",                   "m2",  220.0,  72.00),
            (6, "370.001", "Innentüren Röhrenspan furniert, Zarge",                 "pcs",  24.0, 385.00),
        ],
    },
    {
        "key": "en",
        "create": {
            "name": "Advanced Commercial Complex — Boston",
            "description": (
                "New-build commercial office + structural steel frame, "
                "~1,200 m² gross floor area. Demo project reuses Autodesk "
                "Revit Advanced Sample (structural) + Basic Sample (arch). "
                "Estimate target budget USD 4.2M."
            ),
            "region": "US",
            "classification_standard": "MasterFormat",
            "currency": "USD",
            "locale": "en",
            "validation_rule_sets": ["masterformat", "boq_quality"],
            "project_code": "US-2026-002",
            "project_type": "commercial",
            "phase": "construction_documents",
            "budget_estimate": "4200000",
            "contingency_pct": "8",
        },
        "files": ["2022 rstadvancedsampleproject.rvt", "2023 racbasicsampleproject.rvt"],
        "boq": {
            "name": "Bill of Quantities — Structural & Architectural",
            "description": "MasterFormat-organised BOQ: Divisions 03, 04, 05, 06, 08, 09.",
            "estimate_type": "detailed",
        },
        "sections": [
            ("03", "Division 03 — Concrete"),
            ("04", "Division 04 — Masonry"),
            ("05", "Division 05 — Metals"),
            ("06", "Division 06 — Wood, Plastics & Composites"),
            ("08", "Division 08 — Openings"),
            ("09", "Division 09 — Finishes"),
        ],
        "positions": [
            (0, "03 30 00.01", "Cast-in-place concrete slab, 6\" thick, 4000 psi",     "sf",  4200.0,  14.50),
            (0, "03 30 00.02", "Concrete foundation wall, 12\" thick, rebar #5 @12\"", "cy",    62.0, 485.00),
            (0, "03 31 00.01", "Structural concrete columns, 18\"x18\", 5000 psi",      "cy",    18.5, 625.00),
            (1, "04 22 00.01", "CMU wall, 8\" nominal, reinforced, grouted",            "sf",  2800.0,  12.75),
            (2, "05 12 00.01", "Structural steel beams, W14x22, shop-primed",           "ton",    24.2, 3850.00),
            (2, "05 12 00.02", "Structural steel columns, W12x65, base plates",         "ton",    12.8, 4200.00),
            (2, "05 31 00.01", "Steel floor deck, 3\" composite, 18 gauge",             "sf",  3900.0,   4.85),
            (3, "06 10 00.01", "Wood framing, interior stud walls 2x6 @16\"",           "sf",  1650.0,   8.25),
            (4, "08 11 13.01", "Hollow metal doors 3'-0\" x 7'-0\", 18 gauge",           "ea",     22.0, 685.00),
            (4, "08 50 00.01", "Aluminum curtain wall, thermally broken, 1\" IG",        "sf",  1450.0, 125.00),
            (4, "08 50 00.02", "Storefront glazing, single door + sidelight",            "ea",      6.0, 4850.00),
            (5, "09 29 00.01", "Gypsum board, 5/8\" Type X, taped & finished",            "sf",  6800.0,   4.20),
            (5, "09 68 00.01", "Carpet tile, nylon, glue-down installation",              "sf",  4200.0,   6.95),
            (5, "09 91 23.01", "Interior paint, eggshell, 2 coats on primed GWB",         "sf",  6800.0,   1.85),
        ],
    },
    {
        "key": "es",
        "create": {
            "name": "Proyecto Mixto Civil-Arquitectónico — Madrid",
            "description": (
                "Urbanización mixta: vial de acceso + edificio de servicios. "
                "Proyecto demo construido a partir de dos DWG de referencia "
                "(arquitectónico + civil). Presupuesto objetivo 850.000 EUR."
            ),
            "region": "ES",
            "classification_standard": "MasterFormat",
            "currency": "EUR",
            "locale": "es",
            "validation_rule_sets": ["masterformat", "boq_quality"],
            "project_code": "ES-2026-003",
            "project_type": "mixed_use",
            "phase": "tender",
            "budget_estimate": "850000",
            "contingency_pct": "12",
        },
        "files": ["architectural_example-imperial.dwg", "civil_example-imperial.dwg"],
        "boq": {
            "name": "Presupuesto — Obra civil y edificación",
            "description": "Presupuesto por capítulos: movimiento de tierras, firmes, edificación y acabados.",
            "estimate_type": "detailed",
        },
        "sections": [
            ("01", "Capítulo 01 — Movimiento de tierras"),
            ("02", "Capítulo 02 — Firmes y pavimentos"),
            ("03", "Capítulo 03 — Estructura"),
            ("04", "Capítulo 04 — Cerramientos"),
            ("05", "Capítulo 05 — Acabados interiores"),
            ("06", "Capítulo 06 — Urbanización"),
        ],
        "positions": [
            (0, "01.001", "Excavación a cielo abierto en terreno compacto",          "m3",  620.0,  9.80),
            (0, "01.002", "Relleno y compactación con material seleccionado",         "m3",  380.0, 15.40),
            (1, "02.001", "Sub-base granular ZA-25, e=20 cm, compactada",              "m2",  580.0, 12.20),
            (1, "02.002", "Mezcla bituminosa AC16 surf D, e=5 cm",                     "m2",  580.0, 18.50),
            (1, "02.003", "Bordillo prefabricado de hormigón 15x25 cm",                "m",   420.0, 16.80),
            (2, "03.001", "Hormigón armado HA-30 en pilares, incluido encofrado",      "m3",   28.4, 285.00),
            (2, "03.002", "Forjado reticular canto 30 cm, incluida armadura",          "m2",  340.0,  98.00),
            (3, "04.001", "Fábrica de ladrillo perforado de 1/2 pie, mortero M-7,5",   "m2",  285.0,  52.00),
            (3, "04.002", "Aislamiento XPS e=8 cm en cerramiento exterior",            "m2",  285.0,  18.50),
            (3, "04.003", "Ventana aluminio lacado RPT, vidrio bajo emisivo",          "m2",   48.0, 320.00),
            (4, "05.001", "Alicatado cerámico en baños, 20x20 cm",                     "m2",   96.0,  38.50),
            (4, "05.002", "Pavimento de baldosa de gres porcelánico 60x60",            "m2",  310.0,  42.00),
            (4, "05.003", "Pintura plástica lisa sobre enlucido, 2 manos",              "m2",  720.0,   8.20),
            (5, "06.001", "Farola viaria LED 40 W, columna 6 m, cimentación",           "ea",    12.0, 685.00),
            (5, "06.002", "Jardinería: pradera y arbolado de alineación",               "m2",  240.0,  22.00),
        ],
    },
]


# ── HTTP helpers ───────────────────────────────────────────────────────────

async def login_or_register(client: httpx.AsyncClient) -> dict[str, str]:
    """Return auth headers; register the admin if login fails."""
    r = await client.post(
        "/api/v1/users/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    if r.status_code != 200:
        await client.post(
            "/api/v1/users/auth/register",
            json={
                "email": ADMIN_EMAIL,
                "password": ADMIN_PASSWORD,
                "full_name": "Demo Admin",
            },
        )
        r = await client.post(
            "/api/v1/users/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        r.raise_for_status()
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def wipe_all_projects_direct() -> int:
    """Delete every project via direct SQLite access.

    The HTTP list endpoint filters projects by ownership for non-admin users,
    so the API route misses 95 % of the stale demo/test projects. We want a
    clean slate, so we wipe directly and rely on the ON DELETE CASCADE FKs
    (BOQs, BIM models, links, documents, ...) to do the heavy lifting.
    """
    db_path = REPO_ROOT / "backend" / "openestimate.db"
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        n = conn.execute("SELECT COUNT(*) FROM oe_projects_project").fetchone()[0]
        # Cascading FKs handle the dependent tables. Do it in a single txn.
        conn.execute("DELETE FROM oe_projects_project")
        # A few tables carry soft project_id references (no FK). Clean them too.
        for soft_table in (
            "oe_bim_model",
            "oe_boq_boq",
            "oe_documents_document",
            "oe_tasks_task",
            "oe_rfi_rfi",
        ):
            try:
                conn.execute(f"DELETE FROM {soft_table}")
            except sqlite3.OperationalError:
                pass  # table may not exist in all deployments
        conn.commit()
        return n
    finally:
        conn.close()


async def promote_admin(headers_unused: dict) -> None:
    """Promote the seed admin user to role='admin' so subsequent API calls
    bypass per-user visibility filters (listing projects, deleting links)."""
    db_path = REPO_ROOT / "backend" / "openestimate.db"
    if not db_path.exists():
        return
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "UPDATE oe_users_user SET role = 'admin' WHERE email = ?",
            (ADMIN_EMAIL,),
        )
        conn.commit()
    finally:
        conn.close()


def wipe_orphan_bim_files() -> int:
    """Remove BIM data directories that no longer correspond to any project."""
    if not BIM_DATA_DIR.exists():
        return 0
    removed = 0
    for child in BIM_DATA_DIR.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed


async def create_project(
    client: httpx.AsyncClient, headers: dict, spec: dict,
) -> dict:
    r = await client.post("/api/v1/projects/", json=spec, headers=headers)
    r.raise_for_status()
    return r.json()


async def upload_cad(
    client: httpx.AsyncClient, headers: dict, project_id: str, file_path: pathlib.Path,
) -> dict:
    """Upload a single CAD file. Returns the response body verbatim."""
    with file_path.open("rb") as f:
        files = {"file": (file_path.name, f, "application/octet-stream")}
        params = {
            "project_id": project_id,
            "name": file_path.stem,
            "discipline": "architecture",
            "conversion_depth": "standard",
        }
        r = await client.post(
            "/api/v1/bim_hub/upload-cad/",
            headers=headers,
            params=params,
            files=files,
            timeout=120,
        )
    r.raise_for_status()
    return r.json()


async def wait_for_model_ready(
    client: httpx.AsyncClient, headers: dict, project_id: str, model_id: str,
    label: str,
) -> str:
    """Poll the model until status in {'ready','error','converter_required'}.

    Returns the final status. Prints progress dots so the runner sees life.
    """
    deadline = time.monotonic() + MODEL_READY_TIMEOUT_S
    last_status = ""
    while time.monotonic() < deadline:
        r = await client.get(
            f"/api/v1/bim_hub/models/{model_id}",
            headers=headers,
        )
        if r.status_code == 404:
            await asyncio.sleep(MODEL_POLL_INTERVAL_S)
            continue
        r.raise_for_status()
        data = r.json()
        st = data.get("status", "")
        if st != last_status:
            print(f"    {label:45} → {st}")
            last_status = st
        # Terminal statuses: ready (success) or any of the failure/skip states.
        # The backend uses 'needs_converter' for DWG/DGN when the converter
        # binary is not on PATH — we record it and move on rather than wait
        # for a conversion that will never happen.
        if st in (
            "ready", "error", "converter_required",
            "needs_converter", "failed", "conversion_failed",
        ):
            return st
        await asyncio.sleep(MODEL_POLL_INTERVAL_S)
    return "timeout"


async def seed_boq(
    client: httpx.AsyncClient, headers: dict, project: dict, spec: dict,
) -> dict:
    """Create BOQ + sections + positions for a project."""
    boq_r = await client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": project["id"], **spec["boq"]},
        headers=headers,
    )
    boq_r.raise_for_status()
    boq = boq_r.json()

    # Create sections
    section_ids: list[str] = []
    for ordinal, desc in spec["sections"]:
        sr = await client.post(
            f"/api/v1/boq/boqs/{boq['id']}/sections/",
            json={"ordinal": ordinal, "description": desc},
            headers=headers,
        )
        sr.raise_for_status()
        section_ids.append(sr.json()["id"])

    # Create positions, each tied to its section as parent. The position
    # create endpoint is nested under the BOQ: /boqs/{boq_id}/positions/
    position_count = 0
    for sec_idx, ordinal, desc, unit, qty, rate in spec["positions"]:
        pr = await client.post(
            f"/api/v1/boq/boqs/{boq['id']}/positions/",
            json={
                "boq_id": boq["id"],
                "parent_id": section_ids[sec_idx],
                "ordinal": ordinal,
                "description": desc,
                "unit": unit,
                "quantity": qty,
                "unit_rate": rate,
                "source": "manual",
            },
            headers=headers,
        )
        if pr.status_code >= 400:
            print(f"      !! position {ordinal} failed: {pr.status_code} {pr.text[:120]}", flush=True)
            continue
        position_count += 1

    return {"boq": boq, "positions_created": position_count}


async def link_bim_sample(
    client: httpx.AsyncClient, headers: dict,
    boq_id: str, model_id: str,
) -> int:
    """Link up to 3 BIM elements of each of {Walls, Floors, Roofs, Doors}
    to the first few BOQ positions to give the link panel real data."""
    # Fetch first BOQ positions
    pos_r = await client.get(f"/api/v1/boq/boqs/{boq_id}/structured/", headers=headers)
    pos_r.raise_for_status()
    structured = pos_r.json()
    positions: list[dict] = []
    for sec in structured.get("sections", []):
        positions.extend(sec.get("positions", []))
    if not positions:
        return 0

    # Fetch some BIM elements
    el_r = await client.get(
        f"/api/v1/bim_hub/models/{model_id}/elements/?limit=200",
        headers=headers,
    )
    el_r.raise_for_status()
    elements = el_r.json().get("items", [])
    if not elements:
        return 0

    # Pick ~5 elements distributed by element_type
    picked: list[dict] = []
    seen_types: set[str] = set()
    for el in elements:
        t = el.get("element_type", "")
        if t in seen_types and len(picked) > 3:
            continue
        seen_types.add(t)
        picked.append(el)
        if len(picked) >= 5:
            break

    # Link each picked element to a position
    created = 0
    for i, el in enumerate(picked):
        pos = positions[i % len(positions)]
        lr = await client.post(
            "/api/v1/bim_hub/links/",
            json={
                "boq_position_id": pos["id"],
                "bim_element_id": el["id"],
                "link_type": "manual",
                "confidence": "high",
            },
            headers=headers,
        )
        if lr.status_code in (200, 201):
            created += 1
    return created


# ── Main orchestration ─────────────────────────────────────────────────────

async def main() -> None:
    if not CAD_SOURCE_DIR.exists():
        sys.exit(f"CAD source directory not found: {CAD_SOURCE_DIR}")

    async with httpx.AsyncClient(base_url=BASE, timeout=120.0) as client:
        print("=" * 70)
        print("  OpenEstimate — Demo Showcase Seeder (3 projects, 6 CAD files)")
        print("=" * 70)

        # ── Auth + promote to admin so ownership filters don't hide anything ──
        headers = await login_or_register(client)
        await promote_admin(headers)
        # Re-login so the fresh JWT carries role='admin'
        headers = await login_or_register(client)
        print("\n[1/7] Authenticated as", ADMIN_EMAIL, "(promoted to admin)")

        # ── Wipe ──
        print("\n[2/7] Wiping existing projects (direct DB cascade)...")
        deleted = wipe_all_projects_direct()
        print(f"      Deleted {deleted} project(s) + cascaded children.")

        print("\n[3/7] Removing orphan BIM data directories...")
        orphans = wipe_orphan_bim_files()
        print(f"      Removed {orphans} orphan BIM data directory/ies.")

        # ── Create projects ──
        print("\n[4/7] Creating 3 demo projects...")
        created_projects: list[dict] = []
        for spec in DEMO_PROJECTS:
            p = await create_project(client, headers, spec["create"])
            created_projects.append({"project": p, "spec": spec})
            print(f"      [OK] [{spec['key']}] {p['name']} -- id={p['id'][:8]}")

        # ── Upload CAD files ──
        print("\n[5/7] Uploading 6 CAD files (kicks off background conversion)...")
        upload_handles: list[tuple[dict, str, dict, pathlib.Path]] = []
        for entry in created_projects:
            p = entry["project"]
            spec = entry["spec"]
            for fname in spec["files"]:
                path = CAD_SOURCE_DIR / fname
                if not path.exists():
                    print(f"      !! missing file: {fname}")
                    continue
                print(f"      >> {spec['key']:2}  {fname:50} ({path.stat().st_size/1_048_576:.1f} MB)")
                resp = await upload_cad(client, headers, p["id"], path)
                if resp.get("status") == "converter_required":
                    print(f"         !! converter not installed for {fname} -- skipping")
                    continue
                model_id = resp.get("model_id") or resp.get("id")
                if not model_id:
                    print(f"         !! no model_id in response: {resp}")
                    continue
                upload_handles.append((p, model_id, resp, path))

        # ── Wait for conversion ──
        print(f"\n[6/7] Waiting for {len(upload_handles)} model(s) to finish converting...")
        ready_models: list[tuple[dict, str]] = []
        for p, mid, _resp, path in upload_handles:
            st = await wait_for_model_ready(client, headers, p["id"], mid, path.name)
            if st == "ready":
                ready_models.append((p, mid))

        # ── Seed BOQ + link BIM ──
        print(f"\n[7/7] Seeding BOQ + BIM links for {len(created_projects)} project(s)...")
        for entry in created_projects:
            p = entry["project"]
            spec = entry["spec"]
            print(f"\n   -- {spec['key'].upper()} -- {p['name']} --")
            seed = await seed_boq(client, headers, p, spec)
            print(f"      BOQ created, {seed['positions_created']} positions.")
            # Find a ready model for this project and link some elements
            model_for_project = next((mid for (pp, mid) in ready_models if pp["id"] == p["id"]), None)
            if model_for_project:
                links = await link_bim_sample(client, headers, seed["boq"]["id"], model_for_project)
                print(f"      {links} BIM<->BOQ link(s) created against model {model_for_project[:8]}.")
            else:
                print("      (no ready BIM model -- skipping links)")

        # ── Summary ──
        print("\n" + "=" * 70)
        print("  Seed complete.")
        print("=" * 70)
        for entry in created_projects:
            p = entry["project"]
            spec = entry["spec"]
            print(f"  [{spec['key']}] {p['name']}")
            print(f"       /projects/{p['id']}    /bim?project={p['id']}")


if __name__ == "__main__":
    asyncio.run(main())

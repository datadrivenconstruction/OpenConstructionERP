"""Continuation script — finish seeding BOQs + BIM links for the 3 demo
projects that the main seeder already created.

Run this after the main seeder created the projects + started uploads.
It picks up the projects by name, waits for any still-processing models,
creates the BOQ + sections + positions, and links a few BIM elements.
"""
from __future__ import annotations

import asyncio
import sys

import httpx

# Reuse the specs from the main seeder — same 3 projects, same BOQ structure.
from app.scripts.seed_demo_showcase import (
    ADMIN_EMAIL, ADMIN_PASSWORD, BASE, DEMO_PROJECTS,
    login_or_register, seed_boq, link_bim_sample,
)

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as client:
        headers = await login_or_register(client)

        # Fetch all projects; match by our demo names.
        r = await client.get("/api/v1/projects/?limit=100", headers=headers)
        r.raise_for_status()
        all_projects = r.json()
        by_name = {p["name"]: p for p in all_projects}

        for spec in DEMO_PROJECTS:
            name = spec["create"]["name"]
            p = by_name.get(name)
            if not p:
                print(f"!! project not found: {name}", flush=True)
                continue
            pid = p["id"]
            print(f"\n== [{spec['key']}] {name} (id={pid[:8]}) ==", flush=True)

            # Skip if BOQ already exists for idempotency.
            bq_r = await client.get(
                "/api/v1/boq/boqs/", params={"project_id": pid}, headers=headers,
            )
            existing_boqs: list[dict] = []
            if bq_r.status_code == 200:
                data = bq_r.json()
                existing_boqs = data if isinstance(data, list) else data.get("items", [])
            if existing_boqs:
                print(f"   BOQ already exists ({len(existing_boqs)}). Skipping.", flush=True)
                continue

            seed = await seed_boq(client, headers, p, spec)
            print(f"   BOQ: {seed['positions_created']} positions created.", flush=True)

            # Find a ready BIM model for this project.
            models_r = await client.get(
                "/api/v1/bim_hub/", params={"project_id": pid}, headers=headers,
            )
            models_r.raise_for_status()
            items = models_r.json()
            items = items if isinstance(items, list) else items.get("items", [])
            ready = [m for m in items if m.get("status") == "ready" and m.get("element_count", 0) > 0]
            if not ready:
                print("   (no ready BIM model with elements — skipping links)", flush=True)
                continue

            # Prefer the model with the most elements
            model = max(ready, key=lambda m: m.get("element_count", 0))
            print(f"   Linking against model {model['name'][:40]} ({model.get('element_count')} elts)", flush=True)
            links = await link_bim_sample(client, headers, seed["boq"]["id"], model["id"])
            print(f"   {links} BIM<->BOQ link(s) created.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

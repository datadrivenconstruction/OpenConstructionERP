# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Seed BOQ sections and markups for demo projects.

Adds section headers to existing BOQ positions and applies default markups.
Usage: python -m app.scripts.seed_sections
"""

import asyncio

import httpx

from app.scripts.seed_credentials import (
    SEED_PASSWORD_ENV,
    login_failed_message,
    resolve_seed_password,
)

BASE = "http://localhost:8000"
ADMIN_EMAIL = "admin@openestimate.io"


async def main() -> None:
    # No password is hardcoded here: this tree is public, so a literal would be
    # a published credential. Unlike the other seed scripts this one only logs
    # in, it never registers, so it has no account of its own whose password it
    # could have just chosen. A generated password therefore cannot work here
    # and SEED_ADMIN_PASSWORD is effectively required.
    password, was_generated = resolve_seed_password()
    if was_generated:
        print(f"{SEED_PASSWORD_ENV} is not set. This script only logs in, so set it to the")
        print(f"password of {ADMIN_EMAIL} and run again.")
        return

    async with httpx.AsyncClient(base_url=BASE, timeout=30.0) as c:
        # Login
        r = await c.post(
            "/api/v1/users/auth/login",
            json={
                "email": ADMIN_EMAIL,
                "password": password,
            },
        )
        if r.status_code != 200:
            print(login_failed_message(r.status_code, ADMIN_EMAIL))
            return
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        # Get German project
        projects = (await c.get("/api/v1/projects/", headers=h)).json()
        de_proj = next((p for p in projects if "Berlin" in p["name"]), None)
        if not de_proj:
            print("German project not found, run seed_international first")
            return

        boqs = (await c.get(f"/api/v1/boq/boqs/?project_id={de_proj['id']}", headers=h)).json()
        if not boqs:
            print("No BOQs found")
            return

        boq = boqs[0]
        boq_id = boq["id"]
        print(f"Project: {de_proj['name']}")
        print(f"BOQ: {boq['name']}")

        # Try to apply default markups
        try:
            r = await c.post(
                f"/api/v1/boq/boqs/{boq_id}/markups/apply-defaults?region=DACH",
                headers=h,
            )
            if r.status_code in (200, 201):
                markups = r.json()
                print(f"\nApplied {len(markups)} default markups (DACH):")
                for m in markups:
                    print(f"  {m.get('name', '?')}: {m.get('percentage', '?')}%")
            else:
                print(f"\nMarkup endpoint not ready yet ({r.status_code})")
                print("  This is expected - the backend agent is still working")
        except Exception as e:
            print(f"\nMarkup endpoint not available: {e}")

        # Get structured BOQ
        try:
            r = await c.get(f"/api/v1/boq/boqs/{boq_id}/structured", headers=h)
            if r.status_code == 200:
                data = r.json()
                print("\nStructured BOQ:")
                print(f"  Sections: {len(data.get('sections', []))}")
                print(f"  Direct cost: {data.get('direct_cost', 0):,.2f}")
                print(f"  Net total: {data.get('net_total', 0):,.2f}")
                print(f"  Grand total: {data.get('grand_total', 0):,.2f}")
            else:
                print(f"\nStructured endpoint not ready yet ({r.status_code})")
        except Exception as e:
            print(f"\nStructured endpoint not available: {e}")

        print("\nDone. Check http://localhost:5175")


if __name__ == "__main__":
    asyncio.run(main())

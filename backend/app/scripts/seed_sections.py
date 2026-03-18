"""Seed BOQ sections and markups for demo projects.

Adds section headers to existing BOQ positions and applies default markups.
Usage: python -m app.scripts.seed_sections
"""

import asyncio

import httpx

BASE = "http://localhost:8000"


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=30.0) as c:
        # Login
        r = await c.post("/api/v1/users/auth/login", json={
            "email": "admin@openestimate.io",
            "password": "OpenEstimate2026",
        })
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
                print("  This is expected — the backend agent is still working")
        except Exception as e:
            print(f"\nMarkup endpoint not available: {e}")

        # Get structured BOQ
        try:
            r = await c.get(f"/api/v1/boq/boqs/{boq_id}/structured", headers=h)
            if r.status_code == 200:
                data = r.json()
                print(f"\nStructured BOQ:")
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

"""Seed demo data: user, project, BOQ with realistic positions, cost items.

Usage: python -m app.scripts.seed_demo
"""

import asyncio
import json

import httpx

BASE = "http://localhost:8000"


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=30.0) as c:
        # 1. Register admin user
        print("Creating admin user...")
        r = await c.post("/api/v1/users/auth/register", json={
            "email": "admin@openestimate.io",
            "password": "OpenEstimate2026",
            "full_name": "Artem Boiko",
        })
        if r.status_code == 409:
            print("  User already exists, logging in...")
        elif r.status_code == 201:
            print(f"  Created: {r.json()['email']} (role: {r.json()['role']})")

        # 2. Login
        r = await c.post("/api/v1/users/auth/login", json={
            "email": "admin@openestimate.io",
            "password": "OpenEstimate2026",
        })
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print(f"  Logged in, token obtained")

        # 3. Create project
        print("\nCreating demo project...")
        r = await c.post("/api/v1/projects/", headers=headers, json={
            "name": "Wohnanlage Berlin-Mitte",
            "description": "Neubau einer Wohnanlage mit 48 Wohneinheiten, 3 Treppenhäuser, Tiefgarage. Baukosten ca. 12 Mio EUR.",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
            "locale": "de",
        })
        project = r.json()
        project_id = project["id"]
        print(f"  Project: {project['name']} (id: {project_id})")

        # 4. Create BOQ
        print("\nCreating BOQ...")
        r = await c.post("/api/v1/boq/boqs/", headers=headers, json={
            "project_id": project_id,
            "name": "LV 01 — Rohbauarbeiten",
            "description": "Leistungsverzeichnis Rohbau: Erdarbeiten, Beton, Mauerwerk, Stahlbau",
        })
        boq = r.json()
        boq_id = boq["id"]
        print(f"  BOQ: {boq['name']} (id: {boq_id})")

        # 5. Add positions — realistic German construction BOQ
        positions = [
            # Erdarbeiten (KG 310)
            {
                "ordinal": "01.01.0010",
                "description": "Baugrube ausheben, Boden der Klasse 3-5, Tiefe bis 4,0 m, seitliche Lagerung",
                "unit": "m3",
                "quantity": 2850.0,
                "unit_rate": 12.50,
                "classification": {"din276": "312"},
            },
            {
                "ordinal": "01.01.0020",
                "description": "Bodenabtransport zur Deponie, einschl. Deponiegebühren",
                "unit": "m3",
                "quantity": 1900.0,
                "unit_rate": 18.00,
                "classification": {"din276": "312"},
            },
            {
                "ordinal": "01.01.0030",
                "description": "Verbau Baugrube, Berliner Verbau, bis 4,0 m Tiefe",
                "unit": "m2",
                "quantity": 680.0,
                "unit_rate": 85.00,
                "classification": {"din276": "312"},
            },
            # Beton- und Stahlbetonarbeiten (KG 330)
            {
                "ordinal": "02.01.0010",
                "description": "Stahlbeton C30/37 für Bodenplatte, d=30cm, einschl. Schalung und Bewehrung",
                "unit": "m3",
                "quantity": 420.0,
                "unit_rate": 285.00,
                "classification": {"din276": "331"},
            },
            {
                "ordinal": "02.01.0020",
                "description": "Stahlbeton C30/37 für Fundamentbalken, b/h=40/60cm",
                "unit": "m3",
                "quantity": 85.0,
                "unit_rate": 320.00,
                "classification": {"din276": "331"},
            },
            {
                "ordinal": "02.02.0010",
                "description": "Stahlbeton C30/37 für Wände Untergeschoss, d=25cm, einschl. Schalung",
                "unit": "m3",
                "quantity": 310.0,
                "unit_rate": 350.00,
                "classification": {"din276": "332"},
            },
            {
                "ordinal": "02.02.0020",
                "description": "Stahlbeton C30/37 für Stützen, Querschnitt 30/30cm bis 40/40cm",
                "unit": "m3",
                "quantity": 45.0,
                "unit_rate": 420.00,
                "classification": {"din276": "332"},
            },
            {
                "ordinal": "02.03.0010",
                "description": "Stahlbeton C30/37 für Geschossdecken, d=22cm, einschl. Schalung und Bewehrung",
                "unit": "m3",
                "quantity": 580.0,
                "unit_rate": 310.00,
                "classification": {"din276": "333"},
            },
            {
                "ordinal": "02.03.0020",
                "description": "Bewehrungsstahl BSt 500 S, liefern, schneiden, biegen und verlegen",
                "unit": "kg",
                "quantity": 98000.0,
                "unit_rate": 1.85,
                "classification": {"din276": "333"},
            },
            {
                "ordinal": "02.04.0010",
                "description": "Treppenlauf Stahlbeton C30/37, fertig geschalt und bewehrt",
                "unit": "pcs",
                "quantity": 18.0,
                "unit_rate": 2800.00,
                "classification": {"din276": "334"},
            },
            # Mauerwerk (KG 340)
            {
                "ordinal": "03.01.0010",
                "description": "Mauerwerk aus Kalksandstein KS 20-2.0, d=24cm, Normalmauermörtel NM IIa",
                "unit": "m2",
                "quantity": 3200.0,
                "unit_rate": 62.00,
                "classification": {"din276": "341"},
            },
            {
                "ordinal": "03.01.0020",
                "description": "Mauerwerk aus Kalksandstein KS 12-1.8, d=17,5cm, für Innenwände",
                "unit": "m2",
                "quantity": 4800.0,
                "unit_rate": 48.00,
                "classification": {"din276": "341"},
            },
            {
                "ordinal": "03.02.0010",
                "description": "Zementputz Innen, 15mm, auf Mauerwerk und Beton",
                "unit": "m2",
                "quantity": 8500.0,
                "unit_rate": 18.50,
                "classification": {"din276": "345"},
            },
            # Stahlbauarbeiten (KG 330)
            {
                "ordinal": "04.01.0010",
                "description": "Stahlkonstruktion Tiefgarage, Stützen und Träger S355, feuerverzinkt",
                "unit": "t",
                "quantity": 32.0,
                "unit_rate": 4200.00,
                "classification": {"din276": "336"},
            },
            # Abdichtung (KG 320)
            {
                "ordinal": "05.01.0010",
                "description": "Bauwerksabdichtung gegen drückendes Wasser, Bitumenschweißbahn 2-lagig",
                "unit": "m2",
                "quantity": 1400.0,
                "unit_rate": 42.00,
                "classification": {"din276": "326"},
            },
            {
                "ordinal": "05.01.0020",
                "description": "Perimeterdämmung XPS 120mm, WLG 035, auf Abdichtung",
                "unit": "m2",
                "quantity": 1400.0,
                "unit_rate": 28.00,
                "classification": {"din276": "326"},
            },
        ]

        print(f"\nAdding {len(positions)} BOQ positions...")
        for pos in positions:
            pos["boq_id"] = boq_id
            r = await c.post(f"/api/v1/boq/boqs/{boq_id}/positions", headers=headers, json=pos)
            if r.status_code in (200, 201):
                data = r.json()
                total = float(data.get("total", 0))
                print(f"  {pos['ordinal']} | {pos['description'][:50]:50s} | {total:>12,.2f} EUR")
            else:
                print(f"  ERROR {r.status_code}: {r.text[:100]}")

        # 6. Get BOQ summary
        print("\n" + "=" * 70)
        r = await c.get(f"/api/v1/boq/boqs/{boq_id}", headers=headers)
        boq_full = r.json()
        grand_total = boq_full.get("grand_total", 0)
        print(f"BOQ: {boq_full['name']}")
        print(f"Positions: {len(boq_full.get('positions', []))}")
        print(f"Grand Total: {grand_total:>12,.2f} EUR")
        print("=" * 70)

        # 7. Seed cost items
        print("\nSeeding cost database items...")
        cost_items = [
            {"code": "C-312-001", "description": "Baugrube ausheben, Boden Kl. 3-5", "unit": "m3", "rate": 12.50, "classification": {"din276": "312"}, "tags": ["erdarbeiten"], "source": "cwicr"},
            {"code": "C-312-002", "description": "Bodenabtransport inkl. Deponie", "unit": "m3", "rate": 18.00, "classification": {"din276": "312"}, "tags": ["erdarbeiten", "transport"], "source": "cwicr"},
            {"code": "C-331-001", "description": "Stahlbeton C30/37, Bodenplatte", "unit": "m3", "rate": 285.00, "classification": {"din276": "331"}, "tags": ["beton", "fundament"], "source": "cwicr"},
            {"code": "C-331-002", "description": "Stahlbeton C30/37, Fundamentbalken", "unit": "m3", "rate": 320.00, "classification": {"din276": "331"}, "tags": ["beton", "fundament"], "source": "cwicr"},
            {"code": "C-332-001", "description": "Stahlbeton Wände UG, d=25cm", "unit": "m3", "rate": 350.00, "classification": {"din276": "332"}, "tags": ["beton", "wand"], "source": "cwicr"},
            {"code": "C-332-002", "description": "Stahlbeton Stützen", "unit": "m3", "rate": 420.00, "classification": {"din276": "332"}, "tags": ["beton", "stütze"], "source": "cwicr"},
            {"code": "C-333-001", "description": "Stahlbeton Geschossdecke, d=22cm", "unit": "m3", "rate": 310.00, "classification": {"din276": "333"}, "tags": ["beton", "decke"], "source": "cwicr"},
            {"code": "C-333-002", "description": "Bewehrungsstahl BSt 500 S", "unit": "kg", "rate": 1.85, "classification": {"din276": "333"}, "tags": ["bewehrung", "stahl"], "source": "cwicr"},
            {"code": "C-334-001", "description": "Treppenlauf Stahlbeton, fertig", "unit": "pcs", "rate": 2800.00, "classification": {"din276": "334"}, "tags": ["treppe"], "source": "cwicr"},
            {"code": "C-341-001", "description": "KS-Mauerwerk 24cm, KS 20-2.0", "unit": "m2", "rate": 62.00, "classification": {"din276": "341"}, "tags": ["mauerwerk", "kalksandstein"], "source": "cwicr"},
            {"code": "C-341-002", "description": "KS-Mauerwerk 17,5cm, KS 12-1.8", "unit": "m2", "rate": 48.00, "classification": {"din276": "341"}, "tags": ["mauerwerk", "innenwand"], "source": "cwicr"},
            {"code": "C-345-001", "description": "Zementputz Innen, 15mm", "unit": "m2", "rate": 18.50, "classification": {"din276": "345"}, "tags": ["putz", "innen"], "source": "cwicr"},
            {"code": "C-336-001", "description": "Stahlkonstruktion S355, feuerverzinkt", "unit": "t", "rate": 4200.00, "classification": {"din276": "336"}, "tags": ["stahl", "stahlbau"], "source": "cwicr"},
            {"code": "C-326-001", "description": "Abdichtung 2-lagig Bitumenschweißbahn", "unit": "m2", "rate": 42.00, "classification": {"din276": "326"}, "tags": ["abdichtung"], "source": "cwicr"},
            {"code": "C-326-002", "description": "Perimeterdämmung XPS 120mm", "unit": "m2", "rate": 28.00, "classification": {"din276": "326"}, "tags": ["dämmung", "perimeter"], "source": "cwicr"},
        ]

        for item in cost_items:
            r = await c.post("/api/v1/costs/", headers=headers, json=item)
            if r.status_code in (200, 201):
                print(f"  {item['code']} — {item['description'][:50]}")
            else:
                print(f"  ERROR {r.status_code}: {r.text[:80]}")

        print(f"\nSeed complete! {len(cost_items)} cost items added.")
        print(f"\nOpen http://localhost:5173 to see the app")


if __name__ == "__main__":
    asyncio.run(main())

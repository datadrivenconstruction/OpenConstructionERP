"""Seed international demo projects with realistic construction data.

Creates 4 demo projects covering different regions and standards:
1. Germany (DACH/DIN 276) — Residential complex
2. UK (NRM) — Office building
3. USA (MasterFormat) — Elementary school
4. International (DIN 276) — Bridge infrastructure

Usage: python -m app.scripts.seed_international
"""

import asyncio

import httpx

BASE = "http://localhost:8000"


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=30.0) as c:
        # Register / login
        await c.post("/api/v1/users/auth/register", json={
            "email": "admin@openestimate.io",
            "password": "OpenEstimate2026",
            "full_name": "Artem Boiko",
        })
        r = await c.post("/api/v1/users/auth/login", json={
            "email": "admin@openestimate.io",
            "password": "OpenEstimate2026",
        })
        token = r.json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}
        print("Authenticated.\n")

        # ═══════════════════════════════════════════════════════════════════
        # PROJECT 1: Germany — Wohnanlage Berlin-Mitte
        # ═══════════════════════════════════════════════════════════════════
        p1 = await create_project(c, h, {
            "name": "Wohnanlage Berlin-Mitte",
            "description": "Neubau einer Wohnanlage mit 48 WE, 3 Treppenhäuser, Tiefgarage mit 60 Stellplätzen. BGF ca. 5.800 m², Baukosten ca. 12,5 Mio EUR netto.",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
            "locale": "de",
        })
        b1 = await create_boq(c, h, p1["id"], "LV 01 — Rohbauarbeiten",
            "Leistungsverzeichnis Rohbau: Erdarbeiten, Beton- und Stahlbetonarbeiten, Mauerwerk, Abdichtung, Stahlbau")

        await add_positions(c, h, b1["id"], [
            ("01.01.0010", "Baugrube ausheben, Boden Kl. 3-5, bis 4,0 m Tiefe, seitliche Lagerung", "m3", 2850, 12.50, {"din276": "312"}),
            ("01.01.0020", "Bodenabtransport zur Deponie, einschl. Deponiegebühren, 15 km", "m3", 1900, 18.00, {"din276": "312"}),
            ("01.01.0030", "Verbau Baugrube, Berliner Verbau, bis 4,0 m Tiefe", "m2", 680, 85.00, {"din276": "312"}),
            ("01.01.0040", "Wasserhaltung während der Bauzeit, offene Grundwasserabsenkung", "pcs", 1, 35000.00, {"din276": "312"}),
            ("02.01.0010", "Stahlbeton C30/37 Bodenplatte, d=30cm, einschl. Schalung und Bewehrung", "m3", 420, 285.00, {"din276": "331"}),
            ("02.01.0020", "Stahlbeton C30/37 Fundamentbalken, b/h=40/60cm", "m3", 85, 320.00, {"din276": "331"}),
            ("02.02.0010", "Stahlbeton C30/37 Wände UG, d=25cm, einschl. Schalung", "m3", 310, 350.00, {"din276": "332"}),
            ("02.02.0020", "Stahlbeton C30/37 Stützen, 30/30 bis 40/40cm", "m3", 45, 420.00, {"din276": "332"}),
            ("02.03.0010", "Stahlbeton C30/37 Geschossdecken, d=22cm, Flachdecke", "m3", 580, 310.00, {"din276": "333"}),
            ("02.03.0020", "Bewehrungsstahl BSt 500 S, liefern und verlegen", "kg", 98000, 1.85, {"din276": "333"}),
            ("02.04.0010", "Treppenläufe Stahlbeton, fertig geschalt und bewehrt", "pcs", 18, 2800.00, {"din276": "334"}),
            ("03.01.0010", "Kalksandstein-Mauerwerk KS 20-2.0, d=24cm, NM IIa", "m2", 3200, 62.00, {"din276": "341"}),
            ("03.01.0020", "Kalksandstein-Mauerwerk KS 12-1.8, d=17,5cm, Innenwände", "m2", 4800, 48.00, {"din276": "341"}),
            ("03.02.0010", "Zementputz innen, 15mm, auf Mauerwerk und Beton", "m2", 8500, 18.50, {"din276": "345"}),
            ("04.01.0010", "Stahlkonstruktion TG, Stützen/Träger S355, feuerverzinkt", "t", 32, 4200.00, {"din276": "336"}),
            ("05.01.0010", "Abdichtung gegen drückendes Wasser, Bitumenschweißbahn 2-lagig", "m2", 1400, 42.00, {"din276": "326"}),
            ("05.01.0020", "Perimeterdämmung XPS 120mm, WLG 035", "m2", 1400, 28.00, {"din276": "326"}),
        ])

        # ═══════════════════════════════════════════════════════════════════
        # PROJECT 2: UK — Commercial Office, Manchester
        # ═══════════════════════════════════════════════════════════════════
        p2 = await create_project(c, h, {
            "name": "Victoria House — Grade A Office",
            "description": "New build 6-storey Grade A office building in Manchester city centre. GIA 4,200 m², BREEAM Excellent target. Steel frame with curtain wall facade.",
            "region": "UK",
            "classification_standard": "nrm",
            "currency": "GBP",
            "locale": "en",
        })
        b2 = await create_boq(c, h, p2["id"], "BOQ — Substructure & Frame",
            "NRM 2 cost plan: substructure, frame, upper floors, roof, stairs")

        await add_positions(c, h, b2["id"], [
            ("1.1.1.1", "Excavation to reduce levels; average 450mm deep; disposal off site", "m3", 1890, 22.50, {"nrm": "1.1.1"}),
            ("1.1.2.1", "Piled foundations; CFA piles 450mm dia; average 12m deep", "m", 2400, 65.00, {"nrm": "1.1.2"}),
            ("1.1.2.2", "Pile caps; reinforced concrete; average 1200x1200x750mm", "pcs", 48, 850.00, {"nrm": "1.1.2"}),
            ("1.1.3.1", "Ground beams; RC 500x350mm; formwork and reinforcement", "m", 320, 185.00, {"nrm": "1.1.3"}),
            ("1.1.4.1", "Ground floor slab; RC 200mm thick; power floated finish", "m2", 700, 95.00, {"nrm": "1.1.4"}),
            ("2.1.1.1", "Steel frame; UKB/UKC columns; including connections and fire protection", "t", 285, 3200.00, {"nrm": "2.1.1"}),
            ("2.1.1.2", "Steel beams; UKB primary and secondary; including connections", "t", 180, 2950.00, {"nrm": "2.1.1"}),
            ("2.2.1.1", "Composite metal deck and concrete slab; 130mm total; mesh reinforced", "m2", 4200, 72.00, {"nrm": "2.2.1"}),
            ("2.2.2.1", "Precast concrete stairs; standard flight; painted steel balustrade", "pcs", 12, 4200.00, {"nrm": "2.2.2"}),
            ("2.3.1.1", "Flat roof; single ply membrane; 200mm insulation; vapour barrier", "m2", 720, 145.00, {"nrm": "2.3.1"}),
            ("2.3.1.2", "Roof edge detail; aluminium coping; drip detail", "m", 180, 85.00, {"nrm": "2.3.1"}),
            ("2.5.1.1", "Curtain wall facade; double glazed; aluminium framing system", "m2", 3600, 485.00, {"nrm": "2.5.1"}),
            ("2.5.2.1", "Entrance doors; revolving; automatic; stainless steel frame", "pcs", 2, 18500.00, {"nrm": "2.5.2"}),
        ])

        # ═══════════════════════════════════════════════════════════════════
        # PROJECT 3: USA — Elementary School, Austin TX
        # ═══════════════════════════════════════════════════════════════════
        p3 = await create_project(c, h, {
            "name": "Cedar Park Elementary School",
            "description": "New 65,000 SF single-story elementary school for 750 students. Includes 30 classrooms, gymnasium, cafeteria, media center, administration wing. LEED Silver.",
            "region": "US",
            "classification_standard": "masterformat",
            "currency": "USD",
            "locale": "en",
        })
        b3 = await create_boq(c, h, p3["id"], "Schedule of Values — General Construction",
            "CSI MasterFormat Divisions 01-14: Site work, concrete, masonry, metals, carpentry, thermal/moisture, doors/windows, finishes")

        await add_positions(c, h, b3["id"], [
            ("31 10 00.01", "Site clearing and grubbing; 8.5 acres", "lsum", 1, 45000.00, {"masterformat": "31 10 00"}),
            ("31 20 00.01", "Earthwork; cut and fill; compaction to 95% Proctor", "m3", 12000, 8.50, {"masterformat": "31 20 00"}),
            ("31 23 00.01", "Storm drainage; 8\" HDPE pipe; catch basins; outfall structure", "m", 450, 125.00, {"masterformat": "31 23 00"}),
            ("03 30 00.01", "Cast-in-place concrete; foundations; 4000 PSI; formed", "m3", 380, 245.00, {"masterformat": "03 30 00"}),
            ("03 30 00.02", "Concrete slab on grade; 5\" thick; 4000 PSI; vapor barrier; WWF", "m2", 6040, 55.00, {"masterformat": "03 30 00"}),
            ("03 30 00.03", "Reinforcing steel; Grade 60; #4 through #8 bars", "kg", 42000, 2.10, {"masterformat": "03 30 00"}),
            ("04 20 00.01", "CMU walls; 8\" lightweight; fully grouted; #5 vertical @ 48\" OC", "m2", 2800, 82.00, {"masterformat": "04 20 00"}),
            ("05 12 00.01", "Structural steel; wide flange beams and columns; W shapes", "t", 145, 4800.00, {"masterformat": "05 12 00"}),
            ("05 31 00.01", "Steel deck; 1.5\" Type B; 20 ga; with shear studs", "m2", 6040, 38.00, {"masterformat": "05 31 00"}),
            ("06 10 00.01", "Rough carpentry; wood framing; trusses; blocking; sheathing", "m2", 1200, 65.00, {"masterformat": "06 10 00"}),
            ("07 21 00.01", "Building insulation; R-30 batt above ceiling; R-19 walls", "m2", 8500, 12.50, {"masterformat": "07 21 00"}),
            ("07 52 00.01", "TPO roofing; 60 mil; fully adhered; 20-year warranty", "m2", 6200, 48.00, {"masterformat": "07 52 00"}),
            ("08 11 00.01", "Hollow metal doors and frames; 16ga; 90-min fire rated", "pcs", 120, 1250.00, {"masterformat": "08 11 00"}),
            ("08 41 00.01", "Aluminum storefront glazing; 2.5\" system; insulated glass", "m2", 850, 320.00, {"masterformat": "08 41 00"}),
            ("09 29 00.01", "Gypsum board; 5/8\" Type X; taped and finished Level 4", "m2", 14000, 28.00, {"masterformat": "09 29 00"}),
            ("09 65 00.01", "VCT flooring; 12x12; commercial grade; corridors and classrooms", "m2", 4200, 35.00, {"masterformat": "09 65 00"}),
        ])

        # ═══════════════════════════════════════════════════════════════════
        # PROJECT 4: International — Highway Bridge, UAE
        # ═══════════════════════════════════════════════════════════════════
        p4 = await create_project(c, h, {
            "name": "Al Reem Island Link Bridge",
            "description": "Post-tensioned concrete bridge connecting Al Reem Island to Abu Dhabi mainland. 6-lane dual carriageway, 480m total length, 3 spans. Design to BS/AASHTO hybrid standards.",
            "region": "INTL",
            "classification_standard": "din276",
            "currency": "USD",
            "locale": "en",
        })
        b4 = await create_boq(c, h, p4["id"], "BOQ — Bridge Structure",
            "Foundations, substructure, superstructure, post-tensioning, barriers, surfacing")

        await add_positions(c, h, b4["id"], [
            ("01.01.0010", "Mobilization and site establishment; temporary works; access roads", "lsum", 1, 2500000.00, {"din276": "200"}),
            ("01.02.0010", "Bored piles; 1500mm dia; average 35m deep; marine conditions", "m", 4200, 850.00, {"din276": "312"}),
            ("01.02.0020", "Pile caps; heavily reinforced; 4m x 4m x 2.5m average", "m3", 960, 420.00, {"din276": "312"}),
            ("02.01.0010", "Abutment walls; RC C40/50; complex formwork; in-situ", "m3", 1200, 380.00, {"din276": "331"}),
            ("02.01.0020", "Bridge piers; RC C50/60; slip-formed; circular 3m diameter", "m3", 2400, 450.00, {"din276": "331"}),
            ("02.02.0010", "Pier caps; RC C50/60; post-tensioned; pre-stressed anchorages", "m3", 480, 650.00, {"din276": "332"}),
            ("03.01.0010", "Bridge deck; post-tensioned box girder; C50/60; segment casting", "m3", 8500, 520.00, {"din276": "333"}),
            ("03.01.0020", "Post-tensioning; 19T15 strand tendons; including anchorages and ducts", "t", 320, 8500.00, {"din276": "333"}),
            ("03.01.0030", "Reinforcing steel; Grade 500; cut, bent and fixed", "t", 4200, 1450.00, {"din276": "333"}),
            ("04.01.0010", "Elastomeric bridge bearings; pot type; 5000kN capacity", "pcs", 24, 45000.00, {"din276": "335"}),
            ("04.01.0020", "Expansion joints; modular; 250mm movement capacity", "m", 48, 3200.00, {"din276": "335"}),
            ("05.01.0010", "New Jersey barriers; precast concrete; F-profile; 1100mm high", "m", 960, 280.00, {"din276": "340"}),
            ("05.01.0020", "Anti-throw screens; stainless steel mesh; 3m high panels", "m", 960, 520.00, {"din276": "340"}),
            ("06.01.0010", "Waterproofing membrane; spray-applied; bridge deck", "m2", 8400, 32.00, {"din276": "326"}),
            ("06.01.0020", "Asphalt surfacing; 2-layer; SMA surface + binder course", "m2", 8400, 45.00, {"din276": "360"}),
            ("07.01.0010", "Bridge lighting; LED; column-mounted; 12m spacing", "pcs", 80, 8500.00, {"din276": "440"}),
        ])

        # ═══════════════════════════════════════════════════════════════════
        # Summary
        # ═══════════════════════════════════════════════════════════════════
        print("\n" + "=" * 70)
        print("DEMO PROJECTS CREATED:")
        print("=" * 70)
        for label, pid in [
            ("DE — Wohnanlage Berlin-Mitte", p1["id"]),
            ("UK — Victoria House Office", p2["id"]),
            ("US — Cedar Park Elementary School", p3["id"]),
            ("INTL — Al Reem Island Bridge", p4["id"]),
        ]:
            boqs = (await c.get(f"/api/v1/boq/boqs/?project_id={pid}", headers=h)).json()
            for boq in boqs:
                full = (await c.get(f"/api/v1/boq/boqs/{boq['id']}", headers=h)).json()
                positions = len(full.get("positions", []))
                total = full.get("grand_total", 0)
                currency = "EUR" if "DE" in label else ("GBP" if "UK" in label else "USD")
                print(f"\n  {label}")
                print(f"    BOQ: {boq['name']}")
                print(f"    Positions: {positions}")
                print(f"    Total: {total:>14,.2f} {currency}")

        print("\n" + "=" * 70)
        print("Open http://localhost:5173 to see all projects")
        print("Login: admin@openestimate.io / OpenEstimate2026")


async def create_project(c: httpx.AsyncClient, h: dict, data: dict) -> dict:
    r = await c.post("/api/v1/projects/", headers=h, json=data)
    p = r.json()
    print(f"Project: {p['name']} ({p['region']}/{p['classification_standard']}/{p['currency']})")
    return p


async def create_boq(c: httpx.AsyncClient, h: dict, project_id: str, name: str, desc: str) -> dict:
    r = await c.post("/api/v1/boq/boqs/", headers=h, json={
        "project_id": project_id, "name": name, "description": desc,
    })
    boq = r.json()
    print(f"  BOQ: {boq['name']}")
    return boq


async def add_positions(
    c: httpx.AsyncClient, h: dict, boq_id: str,
    positions: list[tuple],
) -> None:
    for ordinal, desc, unit, qty, rate, classification in positions:
        r = await c.post(f"/api/v1/boq/boqs/{boq_id}/positions", headers=h, json={
            "boq_id": boq_id,
            "ordinal": ordinal,
            "description": desc,
            "unit": unit,
            "quantity": qty,
            "unit_rate": rate,
            "classification": classification,
        })
        if r.status_code in (200, 201):
            total = float(r.json().get("total", 0))
            print(f"    {ordinal:15s} | {desc[:55]:55s} | {total:>14,.2f}")
        else:
            print(f"    ERROR {r.status_code}: {r.text[:80]}")


if __name__ == "__main__":
    asyncio.run(main())

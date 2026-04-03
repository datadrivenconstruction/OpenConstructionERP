"""Seed 2 demo BOQs with realistic positions that have labor_hours in metadata.

Creates:
  1. "Residential House - 3 Bedroom" — 180 m² house (9 positions, 3 sections)
  2. "Office Renovation - 500 m²" — interior renovation (10 positions, 4 sections)

Each position includes:
  - labor_hours / workers_per_unit for schedule duration calculation
  - Detailed resource breakdowns (labor, material, equipment)
  - Realistic German/European construction rates

After seeding, schedules can be auto-generated via:
  POST /api/v1/schedule/schedules/{schedule_id}/generate-from-boq/{boq_id}

Usage:
    python -m app.scripts.seed_schedule_demo

Idempotent: skips creation if demo BOQs with these names already exist.
"""

import asyncio
import uuid
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select

from app.database import Base, engine, async_session_factory
from app.modules.users.models import User  # noqa: F401
from app.modules.projects.models import Project  # noqa: F401
from app.modules.boq.models import BOQ, Position  # noqa: F401
from app.modules.schedule.models import Schedule  # noqa: F401


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _money(value: float) -> str:
    """Format a float to 2-decimal string (SQLite-compatible storage)."""
    return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _total(qty: float, rate: float) -> str:
    return _money(qty * rate)


# ---------------------------------------------------------------------------
# BOQ 1 — Residential House 3-Bedroom (180 m²)
# ---------------------------------------------------------------------------

_HOUSE_SECTIONS: list[tuple[str, str, list[dict]]] = [
    # (ordinal, section_title, [positions...])
    (
        "01",
        "Earthwork & Foundation",
        [
            {
                "ordinal": "01.001",
                "description": "Site clearing and leveling",
                "unit": "m2",
                "quantity": 250,
                "unit_rate": 8.50,
                "metadata_": {
                    "labor_hours": 0.15,
                    "workers_per_unit": 4,
                    "labor_cost": 3.20,
                    "equipment_cost": 4.80,
                    "resources": [
                        {"name": "General laborer", "type": "labor", "unit": "hrs",
                         "quantity": 0.12, "unit_rate": 22, "total": 2.64},
                        {"name": "Excavator operator", "type": "operator", "unit": "hrs",
                         "quantity": 0.03, "unit_rate": 35, "total": 1.05},
                        {"name": "Mini excavator", "type": "equipment",
                         "unit": "machine hours", "quantity": 0.03, "unit_rate": 65,
                         "total": 1.95},
                    ],
                },
            },
            {
                "ordinal": "01.002",
                "description": "Excavation for foundation",
                "unit": "m3",
                "quantity": 85,
                "unit_rate": 32.00,
                "metadata_": {
                    "labor_hours": 0.8,
                    "workers_per_unit": 3,
                    "labor_cost": 12.80,
                    "equipment_cost": 18.50,
                    "resources": [
                        {"name": "Excavator operator", "type": "operator", "unit": "hrs",
                         "quantity": 0.25, "unit_rate": 35, "total": 8.75},
                        {"name": "General laborer", "type": "labor", "unit": "hrs",
                         "quantity": 0.35, "unit_rate": 22, "total": 7.70},
                        {"name": "Excavator CAT 320", "type": "equipment",
                         "unit": "machine hours", "quantity": 0.25, "unit_rate": 85,
                         "total": 21.25},
                        {"name": "Dump truck 10t", "type": "equipment",
                         "unit": "machine hours", "quantity": 0.15, "unit_rate": 55,
                         "total": 8.25},
                    ],
                },
            },
            {
                "ordinal": "01.003",
                "description": "Foundation concrete C25/30",
                "unit": "m3",
                "quantity": 42,
                "unit_rate": 185.00,
                "metadata_": {
                    "labor_hours": 2.5,
                    "workers_per_unit": 6,
                    "labor_cost": 65.00,
                    "equipment_cost": 35.00,
                    "material_cost": 85.00,
                    "resources": [
                        {"name": "Concrete worker", "type": "labor", "unit": "hrs",
                         "quantity": 1.8, "unit_rate": 28, "total": 50.40},
                        {"name": "Helper", "type": "labor", "unit": "hrs",
                         "quantity": 0.7, "unit_rate": 22, "total": 15.40},
                        {"name": "Concrete C25/30", "type": "material", "unit": "m3",
                         "quantity": 1.05, "unit_rate": 95, "total": 99.75},
                        {"name": "Concrete pump", "type": "equipment",
                         "unit": "machine hours", "quantity": 0.15, "unit_rate": 120,
                         "total": 18.00},
                        {"name": "Vibrator", "type": "equipment",
                         "unit": "machine hours", "quantity": 0.3, "unit_rate": 15,
                         "total": 4.50},
                    ],
                },
            },
        ],
    ),
    (
        "02",
        "Structure",
        [
            {
                "ordinal": "02.001",
                "description": "Reinforcement steel BSt 500",
                "unit": "kg",
                "quantity": 4200,
                "unit_rate": 2.80,
                "metadata_": {
                    "labor_hours": 0.04,
                    "workers_per_unit": 4,
                    "labor_cost": 1.20,
                    "material_cost": 1.15,
                    "resources": [
                        {"name": "Steel fixer", "type": "labor", "unit": "hrs",
                         "quantity": 0.025, "unit_rate": 32, "total": 0.80},
                        {"name": "Helper", "type": "labor", "unit": "hrs",
                         "quantity": 0.015, "unit_rate": 22, "total": 0.33},
                        {"name": "Reinforcement BSt 500", "type": "material", "unit": "kg",
                         "quantity": 1.02, "unit_rate": 1.15, "total": 1.17},
                    ],
                },
            },
            {
                "ordinal": "02.002",
                "description": "Masonry walls 24cm",
                "unit": "m2",
                "quantity": 320,
                "unit_rate": 95.00,
                "metadata_": {
                    "labor_hours": 1.2,
                    "workers_per_unit": 3,
                    "labor_cost": 42.00,
                    "material_cost": 48.00,
                    "resources": [
                        {"name": "Mason", "type": "labor", "unit": "hrs",
                         "quantity": 0.8, "unit_rate": 35, "total": 28.00},
                        {"name": "Helper", "type": "labor", "unit": "hrs",
                         "quantity": 0.4, "unit_rate": 22, "total": 8.80},
                        {"name": "Blocks 24cm", "type": "material", "unit": "pcs",
                         "quantity": 16, "unit_rate": 2.80, "total": 44.80},
                        {"name": "Mortar M5", "type": "material", "unit": "kg",
                         "quantity": 25, "unit_rate": 0.12, "total": 3.00},
                    ],
                },
            },
            {
                "ordinal": "02.003",
                "description": "RC slab C30/37, 20cm",
                "unit": "m2",
                "quantity": 180,
                "unit_rate": 145.00,
                "metadata_": {
                    "labor_hours": 1.8,
                    "workers_per_unit": 5,
                    "labor_cost": 55.00,
                    "equipment_cost": 25.00,
                    "material_cost": 65.00,
                    "resources": [
                        {"name": "Concrete worker", "type": "labor", "unit": "hrs",
                         "quantity": 1.2, "unit_rate": 28, "total": 33.60},
                        {"name": "Steel fixer", "type": "labor", "unit": "hrs",
                         "quantity": 0.3, "unit_rate": 32, "total": 9.60},
                        {"name": "Helper", "type": "labor", "unit": "hrs",
                         "quantity": 0.3, "unit_rate": 22, "total": 6.60},
                        {"name": "Concrete C30/37", "type": "material", "unit": "m3",
                         "quantity": 0.21, "unit_rate": 105, "total": 22.05},
                        {"name": "Formwork panels", "type": "material", "unit": "m2",
                         "quantity": 1.1, "unit_rate": 18, "total": 19.80},
                        {"name": "Tower crane", "type": "equipment",
                         "unit": "machine hours", "quantity": 0.15, "unit_rate": 95,
                         "total": 14.25},
                    ],
                },
            },
        ],
    ),
    (
        "03",
        "Finishing Works",
        [
            {
                "ordinal": "03.001",
                "description": "Interior plaster 15mm",
                "unit": "m2",
                "quantity": 580,
                "unit_rate": 28.00,
                "metadata_": {
                    "labor_hours": 0.35,
                    "workers_per_unit": 3,
                    "labor_cost": 15.40,
                    "equipment_cost": 2.50,
                    "material_cost": 10.10,
                    "resources": [
                        {"name": "Plasterer", "type": "labor", "unit": "hrs",
                         "quantity": 0.25, "unit_rate": 38, "total": 9.50},
                        {"name": "Helper", "type": "labor", "unit": "hrs",
                         "quantity": 0.10, "unit_rate": 22, "total": 2.20},
                        {"name": "Plaster mix", "type": "material", "unit": "kg",
                         "quantity": 18, "unit_rate": 0.35, "total": 6.30},
                        {"name": "Spray machine", "type": "equipment",
                         "unit": "machine hours", "quantity": 0.1, "unit_rate": 25,
                         "total": 2.50},
                    ],
                },
            },
            {
                "ordinal": "03.002",
                "description": "Floor tiling 60x60",
                "unit": "m2",
                "quantity": 155,
                "unit_rate": 65.00,
                "metadata_": {
                    "labor_hours": 0.6,
                    "workers_per_unit": 2,
                    "labor_cost": 25.00,
                    "material_cost": 38.00,
                    "resources": [
                        {"name": "Tiler", "type": "labor", "unit": "hrs",
                         "quantity": 0.45, "unit_rate": 36, "total": 16.20},
                        {"name": "Helper", "type": "labor", "unit": "hrs",
                         "quantity": 0.15, "unit_rate": 22, "total": 3.30},
                        {"name": "Floor tiles 60x60", "type": "material", "unit": "m2",
                         "quantity": 1.08, "unit_rate": 28, "total": 30.24},
                        {"name": "Tile adhesive", "type": "material", "unit": "kg",
                         "quantity": 5, "unit_rate": 1.20, "total": 6.00},
                    ],
                },
            },
            {
                "ordinal": "03.003",
                "description": "Painting (2 coats)",
                "unit": "m2",
                "quantity": 620,
                "unit_rate": 18.00,
                "metadata_": {
                    "labor_hours": 0.2,
                    "workers_per_unit": 3,
                    "labor_cost": 8.00,
                    "material_cost": 8.50,
                    "resources": [
                        {"name": "Painter", "type": "labor", "unit": "hrs",
                         "quantity": 0.15, "unit_rate": 32, "total": 4.80},
                        {"name": "Helper", "type": "labor", "unit": "hrs",
                         "quantity": 0.05, "unit_rate": 22, "total": 1.10},
                        {"name": "Paint (interior)", "type": "material", "unit": "liter",
                         "quantity": 0.25, "unit_rate": 12, "total": 3.00},
                        {"name": "Primer", "type": "material", "unit": "liter",
                         "quantity": 0.1, "unit_rate": 8, "total": 0.80},
                    ],
                },
            },
        ],
    ),
]


# ---------------------------------------------------------------------------
# BOQ 2 — Office Renovation 500 m²
# ---------------------------------------------------------------------------

_OFFICE_SECTIONS: list[tuple[str, str, list[dict]]] = [
    (
        "01",
        "Demolition",
        [
            {
                "ordinal": "01.001",
                "description": "Remove existing partitions",
                "unit": "m2",
                "quantity": 280,
                "unit_rate": 15.00,
                "metadata_": {
                    "labor_hours": 0.3,
                    "workers_per_unit": 4,
                    "labor_cost": 8.00,
                    "equipment_cost": 5.00,
                    "resources": [
                        {"name": "Demolition worker", "type": "labor", "unit": "hrs",
                         "quantity": 0.2, "unit_rate": 28, "total": 5.60},
                        {"name": "Helper", "type": "labor", "unit": "hrs",
                         "quantity": 0.1, "unit_rate": 22, "total": 2.20},
                        {"name": "Jackhammer", "type": "equipment",
                         "unit": "machine hours", "quantity": 0.08, "unit_rate": 35,
                         "total": 2.80},
                    ],
                },
            },
            {
                "ordinal": "01.002",
                "description": "Remove old flooring",
                "unit": "m2",
                "quantity": 500,
                "unit_rate": 12.00,
                "metadata_": {
                    "labor_hours": 0.25,
                    "workers_per_unit": 3,
                    "labor_cost": 7.00,
                    "equipment_cost": 3.50,
                    "resources": [
                        {"name": "Floor worker", "type": "labor", "unit": "hrs",
                         "quantity": 0.18, "unit_rate": 28, "total": 5.04},
                        {"name": "Helper", "type": "labor", "unit": "hrs",
                         "quantity": 0.07, "unit_rate": 22, "total": 1.54},
                    ],
                },
            },
        ],
    ),
    (
        "02",
        "New Partitions & Drywall",
        [
            {
                "ordinal": "02.001",
                "description": "Metal stud framing",
                "unit": "m2",
                "quantity": 350,
                "unit_rate": 32.00,
                "metadata_": {
                    "labor_hours": 0.5,
                    "workers_per_unit": 2,
                    "labor_cost": 18.00,
                    "material_cost": 12.00,
                    "resources": [
                        {"name": "Drywall installer", "type": "labor", "unit": "hrs",
                         "quantity": 0.35, "unit_rate": 34, "total": 11.90},
                        {"name": "Helper", "type": "labor", "unit": "hrs",
                         "quantity": 0.15, "unit_rate": 22, "total": 3.30},
                        {"name": "Metal studs CW75", "type": "material", "unit": "m",
                         "quantity": 3.2, "unit_rate": 2.80, "total": 8.96},
                    ],
                },
            },
            {
                "ordinal": "02.002",
                "description": "Drywall boards (double layer)",
                "unit": "m2",
                "quantity": 700,
                "unit_rate": 28.00,
                "metadata_": {
                    "labor_hours": 0.4,
                    "workers_per_unit": 2,
                    "labor_cost": 14.00,
                    "material_cost": 12.00,
                    "resources": [
                        {"name": "Drywall installer", "type": "labor", "unit": "hrs",
                         "quantity": 0.3, "unit_rate": 34, "total": 10.20},
                        {"name": "Helper", "type": "labor", "unit": "hrs",
                         "quantity": 0.1, "unit_rate": 22, "total": 2.20},
                        {"name": "Gypsum board 12.5mm", "type": "material", "unit": "m2",
                         "quantity": 2.1, "unit_rate": 4.50, "total": 9.45},
                    ],
                },
            },
        ],
    ),
    (
        "03",
        "MEP (Mechanical/Electrical/Plumbing)",
        [
            {
                "ordinal": "03.001",
                "description": "Electrical wiring and outlets",
                "unit": "pcs",
                "quantity": 85,
                "unit_rate": 120.00,
                "metadata_": {
                    "labor_hours": 2.0,
                    "workers_per_unit": 2,
                    "labor_cost": 65.00,
                    "material_cost": 45.00,
                    "resources": [
                        {"name": "Electrician", "type": "labor", "unit": "hrs",
                         "quantity": 1.5, "unit_rate": 38, "total": 57.00},
                        {"name": "Helper", "type": "labor", "unit": "hrs",
                         "quantity": 0.5, "unit_rate": 22, "total": 11.00},
                        {"name": "Cable NYM 3x2.5", "type": "material", "unit": "m",
                         "quantity": 12, "unit_rate": 1.80, "total": 21.60},
                        {"name": "Socket/switch", "type": "material", "unit": "pcs",
                         "quantity": 1, "unit_rate": 18, "total": 18.00},
                    ],
                },
            },
            {
                "ordinal": "03.002",
                "description": "LED lighting installation",
                "unit": "pcs",
                "quantity": 120,
                "unit_rate": 85.00,
                "metadata_": {
                    "labor_hours": 0.8,
                    "workers_per_unit": 2,
                    "labor_cost": 28.00,
                    "material_cost": 52.00,
                    "resources": [
                        {"name": "Electrician", "type": "labor", "unit": "hrs",
                         "quantity": 0.6, "unit_rate": 38, "total": 22.80},
                        {"name": "Helper", "type": "labor", "unit": "hrs",
                         "quantity": 0.2, "unit_rate": 22, "total": 4.40},
                        {"name": "LED panel 60x60", "type": "material", "unit": "pcs",
                         "quantity": 1, "unit_rate": 45, "total": 45.00},
                    ],
                },
            },
        ],
    ),
    (
        "04",
        "Finishing",
        [
            {
                "ordinal": "04.001",
                "description": "Carpet tile flooring",
                "unit": "m2",
                "quantity": 420,
                "unit_rate": 45.00,
                "metadata_": {
                    "labor_hours": 0.2,
                    "workers_per_unit": 3,
                    "labor_cost": 8.00,
                    "material_cost": 35.00,
                    "resources": [
                        {"name": "Floor installer", "type": "labor", "unit": "hrs",
                         "quantity": 0.15, "unit_rate": 32, "total": 4.80},
                        {"name": "Helper", "type": "labor", "unit": "hrs",
                         "quantity": 0.05, "unit_rate": 22, "total": 1.10},
                        {"name": "Carpet tiles", "type": "material", "unit": "m2",
                         "quantity": 1.05, "unit_rate": 28, "total": 29.40},
                    ],
                },
            },
            {
                "ordinal": "04.002",
                "description": "Wall painting (office white)",
                "unit": "m2",
                "quantity": 850,
                "unit_rate": 16.00,
                "metadata_": {
                    "labor_hours": 0.18,
                    "workers_per_unit": 4,
                    "labor_cost": 6.50,
                    "material_cost": 8.00,
                    "resources": [
                        {"name": "Painter", "type": "labor", "unit": "hrs",
                         "quantity": 0.12, "unit_rate": 32, "total": 3.84},
                        {"name": "Helper", "type": "labor", "unit": "hrs",
                         "quantity": 0.06, "unit_rate": 22, "total": 1.32},
                        {"name": "Paint (white matt)", "type": "material", "unit": "liter",
                         "quantity": 0.22, "unit_rate": 14, "total": 3.08},
                    ],
                },
            },
        ],
    ),
]


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def _build_boq_positions(
    boq_id: uuid.UUID,
    sections_data: list[tuple[str, str, list[dict]]],
) -> list[Position]:
    """Build section headers + child positions for a BOQ from structured data."""
    positions: list[Position] = []
    sort = 0

    for sec_ordinal, sec_title, items in sections_data:
        sort += 1
        section = Position(
            id=uuid.uuid4(),
            boq_id=boq_id,
            parent_id=None,
            ordinal=sec_ordinal,
            description=sec_title,
            unit="",
            quantity="0",
            unit_rate="0",
            total="0",
            classification={},
            source="demo",
            confidence=None,
            cad_element_ids=[],
            validation_status="pending",
            metadata_={},
            sort_order=sort,
        )
        positions.append(section)

        for item in items:
            sort += 1
            qty = item["quantity"]
            rate = item["unit_rate"]
            positions.append(
                Position(
                    id=uuid.uuid4(),
                    boq_id=boq_id,
                    parent_id=section.id,
                    ordinal=item["ordinal"],
                    description=item["description"],
                    unit=item["unit"],
                    quantity=_money(qty),
                    unit_rate=_money(rate),
                    total=_total(qty, rate),
                    classification={},
                    source="demo",
                    confidence=None,
                    cad_element_ids=[],
                    validation_status="pending",
                    metadata_=item.get("metadata_", {}),
                    sort_order=sort,
                )
            )

    return positions


# ---------------------------------------------------------------------------
# Main seed function
# ---------------------------------------------------------------------------

async def seed() -> None:
    """Create 2 demo BOQs with labor-hours metadata + schedules for each."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        # Find demo user's first project (created by _seed_demo_account on startup)
        result = await session.execute(select(Project).limit(1))
        project = result.scalar_one_or_none()
        if not project:
            print("No project found. Start the app first to create demo data.")
            return

        project_id = project.id

        # Check idempotency
        existing = (
            await session.execute(
                select(BOQ).where(
                    BOQ.project_id == project_id,
                    BOQ.name.in_([
                        "Residential House - 3 Bedroom",
                        "Office Renovation - 500m²",
                    ]),
                )
            )
        ).scalars().all()

        existing_names = {b.name for b in existing}

        # ── BOQ 1: Residential House ─────────────────────────────────────
        if "Residential House - 3 Bedroom" not in existing_names:
            boq1_id = uuid.uuid4()
            boq1 = BOQ(
                id=boq1_id,
                project_id=project_id,
                name="Residential House - 3 Bedroom",
                description=(
                    "Complete construction estimate for a 180 m² residential house. "
                    "All positions include labor_hours and workers_per_unit for "
                    "resource-based schedule generation."
                ),
                status="draft",
                metadata_={"building_type": "residential", "currency": "EUR", "area_m2": 180},
            )
            session.add(boq1)

            for pos in _build_boq_positions(boq1_id, _HOUSE_SECTIONS):
                session.add(pos)

            # Create a matching schedule (empty — to be generated via API)
            sched1 = Schedule(
                id=uuid.uuid4(),
                project_id=project_id,
                name="Residential House - Construction Schedule",
                description="Auto-generated from BOQ with labor-hours-based durations",
                start_date="2026-05-04",
                status="draft",
                metadata_={"boq_id": str(boq1_id), "source": "seed_schedule_demo"},
            )
            session.add(sched1)

            print(f"Created BOQ 1: 'Residential House - 3 Bedroom' (id={boq1_id})")
            print(f"  Schedule: '{sched1.name}' (id={sched1.id})")
            print(f"  -> Generate: POST /api/v1/schedule/schedules/{sched1.id}"
                  f"/generate-from-boq/{boq1_id}")
        else:
            print("Skipped BOQ 1: 'Residential House - 3 Bedroom' (already exists)")

        # ── BOQ 2: Office Renovation ──────────────────────────────────────
        if "Office Renovation - 500m²" not in existing_names:
            boq2_id = uuid.uuid4()
            boq2 = BOQ(
                id=boq2_id,
                project_id=project_id,
                name="Office Renovation - 500m²",
                description=(
                    "Interior renovation of a 500 m² commercial office space. "
                    "Includes demolition, drywall, MEP, and finishing with full "
                    "resource breakdowns."
                ),
                status="draft",
                metadata_={"building_type": "office", "currency": "EUR", "area_m2": 500},
            )
            session.add(boq2)

            for pos in _build_boq_positions(boq2_id, _OFFICE_SECTIONS):
                session.add(pos)

            # Create a matching schedule (empty — to be generated via API)
            sched2 = Schedule(
                id=uuid.uuid4(),
                project_id=project_id,
                name="Office Renovation - Construction Schedule",
                description="Auto-generated from BOQ with labor-hours-based durations",
                start_date="2026-06-01",
                status="draft",
                metadata_={"boq_id": str(boq2_id), "source": "seed_schedule_demo"},
            )
            session.add(sched2)

            print(f"Created BOQ 2: 'Office Renovation - 500m²' (id={boq2_id})")
            print(f"  Schedule: '{sched2.name}' (id={sched2.id})")
            print(f"  -> Generate: POST /api/v1/schedule/schedules/{sched2.id}"
                  f"/generate-from-boq/{boq2_id}")
        else:
            print("Skipped BOQ 2: 'Office Renovation - 500m²' (already exists)")

        await session.commit()
        print(f"\nProject: {project_id}")
        print("Done. Use the generate-from-boq endpoint to create schedule activities.")


if __name__ == "__main__":
    asyncio.run(seed())

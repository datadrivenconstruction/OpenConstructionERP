"""‌⁠‍Deterministic demo seed for the equipment module.

Generates a representative fleet with telemetry, schedules, work orders,
inspections, rentals, fuel logs, and damage reports. Uses ``random.Random(42)``
so repeated calls on a clean DB are idempotent.
"""

from __future__ import annotations

import logging
import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models import (
    DamageReport,
    Equipment,
    EquipmentRental,
    EquipmentType,
    FuelLog,
    Inspection,
    MaintenanceSchedule,
    MaintenanceWorkOrder,
    PartsLog,
    TelemetryReading,
)

logger = logging.getLogger(__name__)

_SEED = 42

# ── Static type catalog ──────────────────────────────────────────────────

_TYPE_CATALOG: tuple[tuple[str, str, str, int, int, int], ...] = (
    # (code, name, category, service_hrs, service_km, inspect_days)
    ("excavator", "Excavator", "earthmoving", 500, 0, 365),
    ("crane", "Crane", "lifting", 250, 0, 90),
    ("generator", "Generator", "power", 250, 0, 180),
    ("truck", "Truck", "transport", 0, 10000, 365),
    ("loader", "Wheel Loader", "earthmoving", 500, 0, 365),
    ("dozer", "Bulldozer", "earthmoving", 500, 0, 365),
    ("compactor", "Compactor", "compaction", 250, 0, 365),
)

_MANUFACTURERS = ("Caterpillar", "Komatsu", "Volvo", "Liebherr", "JCB", "Hitachi")


async def seed_equipment_demo(session: AsyncSession) -> dict[str, int]:
    """‌⁠‍Create the demo fleet inside ``session``. Returns counts per entity.

    Idempotent: returns zeros for an already-seeded DB (checked via
    presence of equipment codes ``EQ-0001``).
    """
    existing = await session.execute(select(Equipment).where(Equipment.code == "EQ-0001"))
    if existing.scalar_one_or_none() is not None:
        logger.info("Equipment demo already seeded — skipping")
        return {
            "types": 0,
            "equipment": 0,
            "telemetry": 0,
            "schedules": 0,
            "work_orders": 0,
            "inspections": 0,
            "rentals": 0,
            "fuel_logs": 0,
            "parts_logs": 0,
            "damage_reports": 0,
        }

    rng = random.Random(_SEED)
    counts: dict[str, int] = {
        "types": 0,
        "equipment": 0,
        "telemetry": 0,
        "schedules": 0,
        "work_orders": 0,
        "inspections": 0,
        "rentals": 0,
        "fuel_logs": 0,
        "parts_logs": 0,
        "damage_reports": 0,
    }

    # 1. Types
    for code, name, category, svc_h, svc_km, insp_d in _TYPE_CATALOG:
        t = EquipmentType(
            code=code,
            name=name,
            category=category,
            default_service_interval_hours=Decimal(svc_h) if svc_h else None,
            default_service_interval_km=Decimal(svc_km) if svc_km else None,
            default_inspection_interval_days=insp_d,
            description=f"{name} — default service every {svc_h or svc_km} h/km",
        )
        session.add(t)
        counts["types"] += 1
    await session.flush()

    # 2. Equipment (30 units across types)
    plan = (
        ("excavator", 10),
        ("crane", 5),
        ("generator", 8),
        ("truck", 7),
    )
    equipment_units: list[Equipment] = []
    code_idx = 1
    for type_code, qty in plan:
        for _ in range(qty):
            year = rng.randint(2018, 2025)
            e = Equipment(
                code=f"EQ-{code_idx:04d}",
                name=f"{type_code.title()} #{code_idx}",
                type_code=type_code,
                manufacturer=rng.choice(_MANUFACTURERS),
                model=f"M-{rng.randint(100, 999)}",
                serial=f"SN-{rng.randint(100000, 999999)}",
                year=year,
                ownership=rng.choice(("owned", "owned", "owned", "rented", "leased")),
                status=rng.choice(
                    (
                        "active",
                        "active",
                        "active",
                        "active",
                        "under_maintenance",
                        "reserved",
                    )
                ),
                hour_meter=Decimal(rng.randint(0, 5000)),
                odometer_km=Decimal(rng.randint(0, 80000)),
                purchase_date=date(year, rng.randint(1, 12), rng.randint(1, 28)).isoformat(),
                purchase_value=Decimal(rng.randint(40_000, 400_000)),
                depreciation_method="linear",
                useful_life_years=rng.randint(7, 15),
                residual_value=Decimal(rng.randint(2_000, 20_000)),
                currency="EUR",
                location_lat=round(52.5 + rng.uniform(-0.5, 0.5), 6),
                location_lng=round(13.4 + rng.uniform(-0.5, 0.5), 6),
            )
            session.add(e)
            equipment_units.append(e)
            counts["equipment"] += 1
            code_idx += 1
    await session.flush()

    # 3. Telemetry — 90 days, 1 reading/day per unit
    today = date.today()
    for e in equipment_units:
        for day_offset in range(89, -1, -1):
            day = today - timedelta(days=day_offset)
            recorded = datetime.combine(day, datetime.min.time()).replace(tzinfo=UTC)
            r = TelemetryReading(
                equipment_id=e.id,
                recorded_at=recorded,
                fuel_level=Decimal(rng.randint(10, 100)),
                hour_meter=Decimal(int(e.hour_meter) - day_offset * rng.randint(1, 6)),
                odometer_km=Decimal(int(e.odometer_km) - day_offset * rng.randint(5, 60)),
                lat=e.location_lat,
                lng=e.location_lng,
                engine_status=rng.choice(("running", "idle", "off")),
                raw_payload={"src": "seed", "seq": day_offset},
            )
            session.add(r)
            counts["telemetry"] += 1
    await session.flush()

    # 4. Maintenance schedules — 60 (2 per equipment for the first 30)
    for e in equipment_units[:30]:
        for trigger_type, threshold in (("hours", 500), ("date", 365)):
            s = MaintenanceSchedule(
                equipment_id=e.id,
                trigger_type=trigger_type,
                trigger_threshold=Decimal(threshold),
                description=f"Routine {trigger_type} service",
                last_completed_at=(today - timedelta(days=rng.randint(30, 300))).isoformat(),
                last_completed_meter=Decimal(int(e.hour_meter) - rng.randint(100, 1000))
                if trigger_type == "hours"
                else None,
                next_due_meter=(Decimal(int(e.hour_meter) + rng.randint(20, 80)) if trigger_type == "hours" else None),
                next_due_date=(
                    (today + timedelta(days=rng.randint(5, 60))).isoformat() if trigger_type == "date" else None
                ),
                active=True,
            )
            session.add(s)
            counts["schedules"] += 1
    await session.flush()

    # 5. Due work orders — 20
    for e in equipment_units[:20]:
        wo = MaintenanceWorkOrder(
            equipment_id=e.id,
            scheduled_for=(today + timedelta(days=rng.randint(1, 14))).isoformat(),
            status=rng.choice(("scheduled", "scheduled", "in_progress")),
            work_summary=f"Routine service due for {e.code}",
            cost=Decimal(rng.randint(200, 2500)),
            currency="EUR",
        )
        session.add(wo)
        counts["work_orders"] += 1
    await session.flush()

    # 6. Inspections — 30 (mix of expired/valid/expiring)
    insp_types = ("annual", "quarterly", "pre_use")
    for e in equipment_units[:30]:
        offset = rng.randint(-180, 365)
        valid_until = today + timedelta(days=offset)
        insp = Inspection(
            equipment_id=e.id,
            inspection_type=rng.choice(insp_types),
            inspected_at=(valid_until - timedelta(days=365)).isoformat(),
            valid_until=valid_until.isoformat(),
            inspector_name=f"Inspector #{rng.randint(1, 10)}",
            result=rng.choice(("pass", "pass", "pass", "conditional")),
            notes="Routine inspection (seed)",
        )
        session.add(insp)
        counts["inspections"] += 1
    await session.flush()

    # 7. Active rentals — 8 (only created if at least one project exists)
    from app.modules.projects.models import Project

    proj_rows = (await session.execute(select(Project).limit(8))).scalars().all()
    project_ids = [p.id for p in proj_rows]
    if project_ids:
        for i, e in enumerate(equipment_units[:8]):
            project_id = project_ids[i % len(project_ids)]
            r = EquipmentRental(
                equipment_id=e.id,
                project_id=project_id,
                start_date=(today - timedelta(days=rng.randint(1, 30))).isoformat(),
                end_date=None,
                internal_rate_per_day=Decimal(rng.randint(150, 1200)),
                internal_rate_per_hour=Decimal(rng.randint(20, 150)),
                currency="EUR",
                status="active",
            )
            session.add(r)
            counts["rentals"] += 1
        await session.flush()

    # 8. Fuel logs — 200 distributed
    for _ in range(200):
        e = rng.choice(equipment_units)
        log_date = today - timedelta(days=rng.randint(0, 89))
        liters = Decimal(rng.randint(50, 600))
        fl = FuelLog(
            equipment_id=e.id,
            logged_at=log_date.isoformat(),
            fuel_liters=liters,
            hour_meter_at_fill=Decimal(int(e.hour_meter) - rng.randint(0, 200)),
            odometer_km_at_fill=Decimal(int(e.odometer_km) - rng.randint(0, 1000)),
            cost=liters * Decimal("1.85"),
            currency="EUR",
            supplier=rng.choice(("Shell", "BP", "OMV", "Aral", "Local Depot")),
            fuel_type=rng.choice(("diesel", "petrol")),
        )
        session.add(fl)
        counts["fuel_logs"] += 1
    await session.flush()

    # 9. Parts logs — 60
    for _ in range(60):
        e = rng.choice(equipment_units)
        p = PartsLog(
            equipment_id=e.id,
            part_number=f"P-{rng.randint(10000, 99999)}",
            description=rng.choice(
                (
                    "Hydraulic filter",
                    "Engine oil filter",
                    "Air filter",
                    "Belt",
                    "Tire 12.00R20",
                    "Battery 12V",
                )
            ),
            quantity=Decimal(rng.randint(1, 4)),
            unit_cost=Decimal(rng.randint(20, 500)),
            currency="EUR",
            logged_at=(today - timedelta(days=rng.randint(0, 89))).isoformat(),
        )
        session.add(p)
        counts["parts_logs"] += 1
    await session.flush()

    # 10. Damage reports — 12
    for _ in range(12):
        e = rng.choice(equipment_units)
        dr = DamageReport(
            equipment_id=e.id,
            reported_at=(today - timedelta(days=rng.randint(0, 60))).isoformat(),
            reported_by=None,
            severity=rng.choice(("minor", "minor", "major", "critical")),
            description=rng.choice(
                (
                    "Cracked windshield",
                    "Hydraulic leak",
                    "Bent boom",
                    "Damaged tire",
                    "Broken light",
                )
            ),
            photos=[],
            repair_cost_estimate=Decimal(rng.randint(100, 8000)),
            currency="EUR",
            status="reported",
        )
        session.add(dr)
        counts["damage_reports"] += 1
    await session.flush()

    logger.info("Equipment demo seeded: %s", counts)
    return counts

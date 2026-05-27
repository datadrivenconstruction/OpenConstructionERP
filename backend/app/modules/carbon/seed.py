"""‌⁠‍Deterministic seed data for the Carbon & Sustainability module.

Usage:
    >>> from app.modules.carbon.seed import seed_carbon_demo
    >>> await seed_carbon_demo(session, project_ids=[...])

Produces:
    50 EPDRecord rows (concrete 10, steel 5, timber 4, insulation 3,
    glass 4, aluminium 4, brick 4, gypsum 4, plaster 4, finish 8),
    100 MaterialCarbonFactor rows,
    3 CarbonInventory rows per supplied project_id with 80 embodied
    entries each, 50 scope-1/2/3 entries, 6 targets, 4 reports.
    Seed is deterministic (random.Random(42)).
"""

from __future__ import annotations

import random
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.carbon.models import (
    CarbonInventory,
    CarbonTarget,
    EmbodiedCarbonEntry,
    EPDRecord,
    MaterialCarbonFactor,
    Scope1Entry,
    Scope2Entry,
    Scope3Entry,
    SustainabilityReport,
)

_SEED = 42


_MATERIAL_TEMPLATES: list[tuple[str, list[tuple[str, str, Decimal]]]] = [
    (
        "concrete",
        [
            ("C20/25", "kg", Decimal("0.110")),
            ("C25/30", "kg", Decimal("0.118")),
            ("C30/37", "kg", Decimal("0.130")),
            ("C35/45", "kg", Decimal("0.145")),
            ("C40/50", "kg", Decimal("0.160")),
            ("C45/55", "kg", Decimal("0.175")),
            ("C50/60", "kg", Decimal("0.190")),
            ("LC30/33 lightweight", "kg", Decimal("0.150")),
            ("Low-carbon CEM III/B C30", "kg", Decimal("0.080")),
            ("Recycled aggregate C25", "kg", Decimal("0.090")),
        ],
    ),
    (
        "steel",
        [
            ("S235 hot-rolled section", "kg", Decimal("1.350")),
            ("S355 hot-rolled section", "kg", Decimal("1.420")),
            ("Rebar B500B", "kg", Decimal("0.780")),
            ("Stainless steel 304", "kg", Decimal("4.500")),
            ("Galvanised sheet", "kg", Decimal("2.100")),
        ],
    ),
    (
        "timber",
        [
            ("Sawn softwood, kiln-dried", "m3", Decimal("160.0")),
            ("Glulam GL24h", "m3", Decimal("280.0")),
            ("CLT 3-ply 90mm", "m3", Decimal("250.0")),
            ("Plywood 18mm", "m2", Decimal("12.0")),
        ],
    ),
    (
        "insulation",
        [
            ("EPS 100", "m3", Decimal("105.0")),
            ("Mineral wool 100mm", "m2", Decimal("6.4")),
            ("Wood fibre 60mm", "m2", Decimal("3.1")),
        ],
    ),
    (
        "glass",
        [
            ("Double glazing 24mm IGU", "m2", Decimal("28.0")),
            ("Triple glazing low-e", "m2", Decimal("45.0")),
            ("Float glass 6mm", "m2", Decimal("12.0")),
            ("Toughened safety glass 10mm", "m2", Decimal("22.0")),
        ],
    ),
    (
        "aluminium",
        [
            ("Extruded section primary", "kg", Decimal("12.0")),
            ("Extruded section recycled", "kg", Decimal("4.5")),
            ("Sheet 1mm", "kg", Decimal("9.6")),
            ("Composite panel", "m2", Decimal("32.0")),
        ],
    ),
    (
        "brick",
        [
            ("Clay brick fired", "kg", Decimal("0.230")),
            ("Calcium silicate brick", "kg", Decimal("0.110")),
            ("Lightweight brick", "kg", Decimal("0.160")),
            ("Engineering brick", "kg", Decimal("0.300")),
        ],
    ),
    (
        "gypsum",
        [
            ("Gypsum plasterboard 12.5mm", "m2", Decimal("3.6")),
            ("Acoustic plasterboard 15mm", "m2", Decimal("5.5")),
            ("Fire-rated plasterboard", "m2", Decimal("4.4")),
            ("Moisture-resistant plasterboard", "m2", Decimal("4.0")),
        ],
    ),
    (
        "plaster",
        [
            ("Gypsum plaster", "kg", Decimal("0.130")),
            ("Lime plaster", "kg", Decimal("0.180")),
            ("Cement render", "kg", Decimal("0.220")),
            ("Clay plaster", "kg", Decimal("0.110")),
        ],
    ),
    (
        "finish",
        [
            ("Ceramic tile 30x30", "m2", Decimal("11.0")),
            ("Carpet tile", "m2", Decimal("7.5")),
            ("Vinyl flooring", "m2", Decimal("6.0")),
            ("Linoleum 2.5mm", "m2", Decimal("4.5")),
            ("Oak parquet 22mm", "m2", Decimal("9.0")),
            ("Bamboo flooring", "m2", Decimal("3.8")),
            ("Stone tile 20mm", "m2", Decimal("18.0")),
            ("Acrylic paint", "kg", Decimal("2.6")),
        ],
    ),
]


_FUELS = ("diesel", "petrol", "lpg", "natural_gas")
_FUEL_FACTORS = {
    "diesel": Decimal("2.68"),  # kgCO2e per litre
    "petrol": Decimal("2.31"),
    "lpg": Decimal("1.51"),
    "natural_gas": Decimal("2.02"),  # per m3
}


def _build_epd_records(rng: random.Random) -> list[EPDRecord]:
    """‌⁠‍50 EPD records spanning the 10 material classes above."""
    records: list[EPDRecord] = []
    counter = 0
    for material_class, items in _MATERIAL_TEMPLATES:
        for product_name, declared_unit, gwp_a1a3 in items:
            counter += 1
            epd_id = f"EPD-{material_class.upper()}-{counter:03d}"
            manufacturer = rng.choice(
                [
                    "HeidelbergMaterials",
                    "Holcim",
                    "ArcelorMittal",
                    "Rockwool",
                    "Kingspan",
                    "Saint-Gobain",
                    "Lafarge",
                    "BASF",
                    "Owens Corning",
                    "Sika",
                ],
            )
            region = rng.choice(["EU", "DE", "FR", "UK", "US", "CA", "AU", ""])
            validity = date(2026, 12, 31) + timedelta(days=rng.randint(-180, 730))
            records.append(
                EPDRecord(
                    id=uuid.uuid4(),
                    epd_id=epd_id,
                    source=rng.choice(["oekobaudat", "ice", "ec3", "custom"]),
                    material_class=material_class,
                    product_name=product_name,
                    manufacturer=manufacturer,
                    region=region,
                    declared_unit=declared_unit,
                    gwp_a1a3=gwp_a1a3,
                    gwp_a4=Decimal(rng.choice(["0.02", "0.05", "0.08", "0.12"])),
                    gwp_a5=Decimal(rng.choice(["0.01", "0.03", "0.04", "0.06"])),
                    gwp_b_total=Decimal(rng.choice(["0.0", "0.10", "0.20"])),
                    gwp_c_total=Decimal(rng.choice(["0.02", "0.05", "0.08"])),
                    gwp_d_credits=Decimal(rng.choice(["-0.02", "-0.05", "0.00"])),
                    validity_until=validity,
                    document_url=f"https://example.test/epd/{epd_id}.pdf",
                )
            )
    return records


def _build_factors(
    rng: random.Random,
    epds: list[EPDRecord],
) -> list[MaterialCarbonFactor]:
    """‌⁠‍100 material factors, half linked to an EPD, half with override only."""
    factors: list[MaterialCarbonFactor] = []
    for i in range(100):
        epd = epds[i % len(epds)] if i % 2 == 0 else None
        manual = None if epd is not None else Decimal(rng.choice(["0.05", "0.12", "0.22", "0.50", "1.10"]))
        factors.append(
            MaterialCarbonFactor(
                id=uuid.uuid4(),
                cost_item_id=uuid.uuid4(),
                epd_id=epd.id if epd is not None else None,
                manual_override_factor=manual,
                unit_for_factor="kg",
                region=rng.choice(["EU", "DE", "FR", "UK", ""]),
                last_reviewed_at=date(2026, 1, 15) + timedelta(days=rng.randint(0, 90)),
                confidence=rng.choice(["high", "medium", "low"]),
                notes=f"factor #{i + 1}",
            )
        )
    return factors


def _build_inventory_for_project(
    rng: random.Random,
    project_id: uuid.UUID,
    factors: list[MaterialCarbonFactor],
) -> tuple[CarbonInventory, list[EmbodiedCarbonEntry], list[Scope1Entry], list[Scope2Entry], list[Scope3Entry]]:
    """Build one inventory with 80 embodied + 50 ops entries."""
    inv = CarbonInventory(
        id=uuid.uuid4(),
        project_id=project_id,
        name=rng.choice(
            [
                "Baseline 2026",
                "Design-stage estimate",
                "As-built tally",
            ]
        ),
        scope=rng.choice(["cradle_to_gate", "cradle_to_grave", "operational"]),
        as_of_date=date(2026, 1, 1) + timedelta(days=rng.randint(0, 200)),
        status=rng.choice(["draft", "baseline", "current"]),
    )
    embodied: list[EmbodiedCarbonEntry] = []
    for i in range(80):
        factor = rng.choice(factors)
        factor_value = factor.manual_override_factor if factor.manual_override_factor is not None else Decimal("0.130")
        qty = Decimal(rng.choice(["50", "120", "500", "1000", "2500"]))
        embodied.append(
            EmbodiedCarbonEntry(
                id=uuid.uuid4(),
                inventory_id=inv.id,
                element_ref=f"elem-{i:03d}",
                description=f"Material line {i + 1}",
                quantity=qty,
                unit="kg",
                factor_id=factor.id,
                factor_value_used=factor_value,
                carbon_kg=qty * Decimal(str(factor_value)),
                stage=rng.choice(["a1a3", "a4", "a5", "c"]),
            )
        )
    s1: list[Scope1Entry] = []
    s2: list[Scope2Entry] = []
    s3: list[Scope3Entry] = []
    for i in range(50):
        fuel = rng.choice(_FUELS)
        litres = Decimal(rng.choice(["100", "250", "500", "1000"]))
        s1.append(
            Scope1Entry(
                id=uuid.uuid4(),
                inventory_id=inv.id,
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                fuel_type=fuel,
                litres_or_m3=litres,
                emission_factor_kg_co2e_per_unit=_FUEL_FACTORS[fuel],
                total_co2e_kg=litres * _FUEL_FACTORS[fuel],
                source=rng.choice(["fuel_log", "manual", "equipment_telematics"]),
            )
        )
        kwh = Decimal(rng.choice(["1000", "2500", "5000", "10000"]))
        ef2 = Decimal(rng.choice(["0.18", "0.25", "0.40"]))
        s2.append(
            Scope2Entry(
                id=uuid.uuid4(),
                inventory_id=inv.id,
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                energy_type=rng.choice(["grid_electricity", "district_heating"]),
                kwh=kwh,
                emission_factor_kg_co2e_per_kwh=ef2,
                market_or_location=rng.choice(["market", "location"]),
                total_co2e_kg=kwh * ef2,
            )
        )
        act = Decimal(rng.choice(["100", "500", "1000", "2000"]))
        ef3 = Decimal(rng.choice(["0.10", "0.20", "0.50"]))
        s3.append(
            Scope3Entry(
                id=uuid.uuid4(),
                inventory_id=inv.id,
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                category=rng.choice(
                    [
                        "transport_upstream",
                        "transport_downstream",
                        "waste",
                        "business_travel",
                        "other",
                    ]
                ),
                description=f"Activity {i + 1}",
                activity_data=act,
                activity_unit="tkm",
                emission_factor=ef3,
                total_co2e_kg=act * ef3,
            )
        )
    return inv, embodied, s1, s2, s3


def _build_targets(
    rng: random.Random,
    project_id: uuid.UUID,
) -> list[CarbonTarget]:
    out: list[CarbonTarget] = []
    for i in range(6):
        out.append(
            CarbonTarget(
                id=uuid.uuid4(),
                project_id=project_id,
                name=f"Reduction target {i + 1}",
                target_type=rng.choice(
                    [
                        "absolute",
                        "intensity_per_m2",
                        "intensity_per_unit",
                    ]
                ),
                baseline_value=Decimal(rng.choice(["1000", "5000", "10000"])),
                target_value=Decimal(rng.choice(["500", "2500", "5000"])),
                baseline_year=2020,
                target_year=2030,
                scope_set=["1", "2", "embodied"],
                status=rng.choice(["active", "met", "missed"]),
            )
        )
    return out


def _build_reports(
    rng: random.Random,
    project_id: uuid.UUID,
    inventory_id: uuid.UUID,
) -> list[SustainabilityReport]:
    out: list[SustainabilityReport] = []
    for i in range(4):
        out.append(
            SustainabilityReport(
                id=uuid.uuid4(),
                project_id=project_id,
                inventory_id=inventory_id,
                period_start=date(2026, 1, 1),
                period_end=date(2026, 12, 31),
                framework=rng.choice(["ghg_protocol", "gri", "issb", "custom"]),
                totals={"scope1": "1000", "scope2": "2000", "scope3": "500"},
                narrative=f"Sustainability report {i + 1}",
                generated_at=date(2026, 6, 30),
            )
        )
    return out


async def seed_carbon_demo(
    session: AsyncSession,
    project_ids: Iterable[uuid.UUID],
) -> dict[str, int]:
    """Insert deterministic demo data and return per-entity counts."""
    rng = random.Random(_SEED)

    epds = _build_epd_records(rng)
    session.add_all(epds)
    await session.flush()

    factors = _build_factors(rng, epds)
    session.add_all(factors)
    await session.flush()

    inv_count = 0
    embodied_count = 0
    s1_count = 0
    s2_count = 0
    s3_count = 0
    target_count = 0
    report_count = 0

    for project_id in project_ids:
        # 3 inventories per project.
        first_inventory_id: uuid.UUID | None = None
        for _ in range(3):
            inv, embodied, s1, s2, s3 = _build_inventory_for_project(
                rng,
                project_id,
                factors,
            )
            session.add(inv)
            await session.flush()
            first_inventory_id = first_inventory_id or inv.id
            session.add_all(embodied + s1 + s2 + s3)
            await session.flush()
            inv_count += 1
            embodied_count += len(embodied)
            s1_count += len(s1)
            s2_count += len(s2)
            s3_count += len(s3)

        targets = _build_targets(rng, project_id)
        session.add_all(targets)
        target_count += len(targets)

        if first_inventory_id is not None:
            reports = _build_reports(rng, project_id, first_inventory_id)
            session.add_all(reports)
            report_count += len(reports)

        await session.flush()

    return {
        "epd_records": len(epds),
        "material_factors": len(factors),
        "inventories": inv_count,
        "embodied_entries": embodied_count,
        "scope1_entries": s1_count,
        "scope2_entries": s2_count,
        "scope3_entries": s3_count,
        "targets": target_count,
        "reports": report_count,
    }

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Deterministic seed data for the Carbon & Sustainability module.

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

from sqlalchemy import select
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
    """50 EPD records spanning the 10 material classes above."""
    records: list[EPDRecord] = []
    counter = 0
    for material_class, items in _MATERIAL_TEMPLATES:
        for product_name, declared_unit, gwp_a1a3 in items:
            counter += 1
            epd_id = f"EPD-{material_class.upper()}-{counter:03d}"
            manufacturer = rng.choice(
                [
                    "Brandstein Materials",
                    "Marnholt Cement",
                    "Ferrolane Steel",
                    "Petrafibre Insulation",
                    "Aldbourne Panels",
                    "Verrachaux Glass",
                    "Cavannes Cement",
                    "Rennstadt Chemie",
                    "Brenfield Composites",
                    "Auvernik Chemie",
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
    """100 material factors, half linked to an EPD, half with override only."""
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

    # The EPD library and its factors are shared by every project, and
    # ``epd_id`` is unique. Enrichment runs this seed whenever no inventory
    # exists, which is true again after a pack switch has deleted the previous
    # pack's projects, so a second run reuses the library it wrote the first
    # time instead of inserting it again and failing on the index. Both lists
    # are still built, in the same order, so the generator reaches the project
    # rows below at the same point and they stay deterministic.
    epds = _build_epd_records(rng)
    wanted = [e.epd_id for e in epds]
    stored = {
        e.epd_id: e
        for e in (await session.execute(select(EPDRecord).where(EPDRecord.epd_id.in_(wanted)))).scalars().all()
    }
    reuse = len(stored) == len(wanted)
    if reuse:
        epds = [stored[epd_id] for epd_id in wanted]
    else:
        session.add_all(epds)
        await session.flush()

    factors = _build_factors(rng, epds)
    if reuse:
        notes = [f.notes for f in factors]
        stored_factors = {
            f.notes: f
            for f in (
                await session.execute(select(MaterialCarbonFactor).where(MaterialCarbonFactor.notes.in_(notes)))
            ).scalars()
        }
        reuse = len(stored_factors) == len(notes)
        if reuse:
            factors = [stored_factors[n] for n in notes]
    if not reuse:
        session.add_all(factors)
        await session.flush()

    inv_count = 0
    embodied_count = 0
    s1_count = 0
    s2_count = 0
    s3_count = 0
    target_count = 0
    report_count = 0

    project_ids = list(project_ids)
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

    lifecycle_counts = await seed_lifecycle_demo(session, project_ids)

    return {
        **lifecycle_counts,
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


DEMO_EPD_IDS = ("DEMO-EPD-C30-CEM-I", "DEMO-EPD-C30-CEM-III")
DEMO_COMPANY = "Demo Construction Group"


async def seed_lifecycle_demo(session: AsyncSession, project_ids: list[uuid.UUID]) -> dict[str, int]:
    """Two EPDs with factors, a budget overrun, one cheaper-in-CO2 alternative and one E1 report.

    Idempotent: keyed on the demo EPD ids and the demo company name.
    """
    from app.modules.carbon.lifecycle_service import BUDGET_TARGET_TYPE, CarbonLifecycleService
    from app.modules.carbon.models import CarbonCompanyActivity

    if not project_ids:
        return {"lifecycle_epds": 0}
    stored = (await session.execute(select(EPDRecord).where(EPDRecord.epd_id.in_(DEMO_EPD_IDS)))).scalars().all()
    if stored:
        return {"lifecycle_epds": 0}

    catalog_item_id = None
    try:
        from app.modules.supplier_catalogs.models import CatalogItem

        catalog_item_id = (await session.execute(select(CatalogItem.id).limit(1))).scalar()
    except Exception:  # supplier catalogues not installed
        catalog_item_id = None

    cem1 = EPDRecord(
        epd_id=DEMO_EPD_IDS[0],
        source="custom",
        material_class="concrete",
        product_name="Ready-mix concrete C30/37, CEM I",
        manufacturer="Demo Ready-Mix",
        region="EU",
        declared_unit="m3",
        gwp_a1a3=Decimal("310"),
        gwp_a4=Decimal("6.5"),
        gwp_c_total=Decimal("12"),
        gwp_d_credits=Decimal("-8"),
        validity_until=date(2030, 6, 30),
        epd_format="ilcd_xml",
        supplier_catalog_item_id=catalog_item_id,
    )
    cem3 = EPDRecord(
        epd_id=DEMO_EPD_IDS[1],
        source="custom",
        material_class="concrete",
        product_name="Ready-mix concrete C30/37, CEM III/A slag cement",
        manufacturer="Demo Ready-Mix",
        region="EU",
        declared_unit="m3",
        gwp_a1a3=Decimal("205"),
        gwp_a4=Decimal("6.5"),
        gwp_c_total=Decimal("12"),
        gwp_d_credits=Decimal("-8"),
        validity_until=date(2031, 3, 31),
        epd_format="csv",
    )
    session.add_all([cem1, cem3])
    await session.flush()
    f1, f3 = (
        MaterialCarbonFactor(
            epd_id=e.id,
            unit_for_factor="m3",
            region="EU",
            confidence="high",
            factor_set="Demo EPD set",
            factor_set_year=2025,
            notes=f"lifecycle demo {e.epd_id}",
        )
        for e in (cem1, cem3)
    )
    session.add_all([f1, f3])
    await session.flush()

    first = project_ids[0]
    inv = (
        (
            await session.execute(
                select(CarbonInventory).where(CarbonInventory.project_id == first).order_by(CarbonInventory.created_at)
            )
        )
        .scalars()
        .first()
    )
    if inv is None:
        inv = CarbonInventory(project_id=first, name="Baseline inventory", as_of_date=date(2026, 6, 30))
        session.add(inv)
        await session.flush()
    qty = Decimal("120")
    entry = EmbodiedCarbonEntry(
        inventory_id=inv.id,
        description="Foundation slab concrete C30/37 (CEM I)",
        quantity=qty,
        unit="m3",
        factor_id=f1.id,
        factor_value_used=Decimal("310"),
        carbon_kg=qty * Decimal("310"),
        stage="a1a3",
        source="manual",
        data_quality="calculated",
    )
    entry.metadata_ = {
        "demo_alternative": {
            "factor_id": str(f3.id),
            "current_unit_rate": "145.00",
            "alternative_unit_rate": "152.00",
        }
    }
    session.add(entry)
    await session.flush()

    svc = CarbonLifecycleService(session)
    actuals = []
    for pid_inv in (
        await session.execute(select(CarbonInventory.id).where(CarbonInventory.project_id == first))
    ).scalars():
        totals = await svc.base.compute_inventory_totals_fresh(pid_inv)
        actuals.append(sum(Decimal(str(totals.get(k, 0))) for k in ("embodied_a1a5", "embodied_b", "embodied_c")))
    budget_kg = (min(actuals) * Decimal("0.8")).quantize(Decimal("1")) if actuals else Decimal("1")
    session.add(
        CarbonTarget(
            project_id=first,
            name="Project carbon budget",
            target_type=BUDGET_TARGET_TYPE,
            baseline_value=budget_kg,
            target_value=budget_kg,
            baseline_year=2026,
            target_year=2026,
            scope_set=["a1a3", "a4", "a5", "b", "c"],
        )
    )
    session.add_all(
        [
            CarbonCompanyActivity(
                reporting_year=2026,
                scope=2,
                category="office",
                description="Head office electricity",
                activity_amount=Decimal("185000"),
                activity_unit="kWh",
                emission_factor=Decimal("0.38"),
                factor_source="National grid average",
                co2e_kg=Decimal("70300"),
                energy_kwh=Decimal("185000"),
                renewable_share_pct=Decimal("35"),
                market_based_co2e_kg=Decimal("45695"),
                data_quality="measured",
            ),
            CarbonCompanyActivity(
                reporting_year=2026,
                scope=1,
                category="fleet_fuel",
                description="Company cars diesel",
                activity_amount=Decimal("42000"),
                activity_unit="L",
                emission_factor=Decimal("2.66"),
                factor_source="Generic combustion defaults (2023)",
                co2e_kg=Decimal("111720"),
                energy_kwh=Decimal("420000"),
                data_quality="measured",
                source_module="equipment",
            ),
        ]
    )
    await session.flush()
    await svc.generate_company_report(
        year=2026,
        template="esrs_e1",
        net_revenue=Decimal("84000000"),
        currency="EUR",
        company_name=DEMO_COMPANY,
        project_ids=set(project_ids),
        user_id=None,
        admin=True,
    )
    return {"lifecycle_epds": 2, "lifecycle_reports": 1}

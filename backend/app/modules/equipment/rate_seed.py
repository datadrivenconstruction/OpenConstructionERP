# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Synthetic demo rate catalogues: five invented machines per showcase currency.

Every value here is made up for the demo and flagged ``is_synthetic``. No national list or
rate book is reproduced. The first EUR machine and the first USD machine are the two worked
examples of the specification (average value and average annual investment conventions).
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.equipment.models import Equipment, EquipmentRental
from app.modules.equipment.rate_models import EquipmentRateCatalogue, EquipmentRateItem

logger = logging.getLogger(__name__)

D = Decimal
DEMO_VALID_FROM = "2026-01-01"

# code, name, category, size, P, Rv, n, v, i, r, h
_EUR: tuple[tuple[Any, ...], ...] = (
    ("D-EX20", "Demo excavator 20 t", "Earthwork", "20 t", "180000", "18000", "6", "10", "0.06", "0.60", "170"),
    ("D-LD", "Demo wheel loader", "Earthwork", "12 t", "150000", "15000", "6", "10", "0.06", "0.55", "170"),
    ("D-TC", "Demo tower crane", "Lifting", "8 t", "320000", "40000", "10", "11", "0.06", "0.70", "180"),
    ("D-DU6", "Demo dumper 6 t", "Transport", "6 t", "42000", "4000", "6", "10", "0.06", "0.50", "160"),
    ("D-CP", "Demo compactor", "Compaction", "9 t", "60000", "6000", "8", "9", "0.06", "0.45", "150"),
)
_USD: tuple[tuple[Any, ...], ...] = (
    ("D-WL", "Demo wheel loader", "Earthwork", "3 m3", "250000", "50000", "5", "12", "0.08", "0.50", "150"),
    ("D-EX20", "Demo excavator 20 t", "Earthwork", "20 t", "190000", "20000", "6", "10", "0.08", "0.60", "170"),
    ("D-TC", "Demo tower crane", "Lifting", "8 t", "340000", "45000", "10", "11", "0.08", "0.70", "180"),
    ("D-DU6", "Demo dumper 6 t", "Transport", "6 t", "45000", "4500", "6", "10", "0.08", "0.50", "160"),
    ("D-CP", "Demo compactor", "Compaction", "9 t", "64000", "6400", "8", "9", "0.08", "0.45", "150"),
)

DEMO_SETS: dict[str, tuple[str, tuple[tuple[Any, ...], ...]]] = {
    "EUR": ("average_value", _EUR),
    "USD": ("average_annual_investment", _USD),
}


async def load_demo_catalogue(session: AsyncSession, currency: str) -> EquipmentRateCatalogue:
    """Create the five-machine demo catalogue for ``currency`` (EUR or USD); idempotent."""
    cur = currency.upper()
    if cur not in DEMO_SETS:
        raise ValueError(f"no demo catalogue for {currency!r}")
    convention, rows = DEMO_SETS[cur]
    name = f"Demo fleet rates ({cur})"
    existing = (
        await session.execute(
            select(EquipmentRateCatalogue).where(
                EquipmentRateCatalogue.name == name, EquipmentRateCatalogue.is_synthetic.is_(True)
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    catalogue = EquipmentRateCatalogue(
        family_id=uuid.uuid4(),
        name=name,
        source_label="Synthetic demo values",
        licence_note="Invented numbers for the demo. Replace with your own table before pricing real work.",
        currency=cur,
        valid_from=DEMO_VALID_FROM,
        interest_convention=convention,
        is_synthetic=True,
        working_days_per_month=D("20"),
        standby_factor=D("0.5"),
        breakdown_factor=D("0"),
        tolerance_pct=D("10"),
    )
    session.add(catalogue)
    await session.flush()
    for code, item_name, category, size, p, rv, n, v, i, r, h in rows:
        session.add(
            EquipmentRateItem(
                catalogue_id=catalogue.id,
                code=code,
                name=item_name,
                category=category,
                size_key=size,
                value=D(p),
                residual=D(rv),
                life_years=D(n),
                months_per_year=D(v),
                interest=D(i),
                repair=D(r),
                hours_per_month=D(h),
            )
        )
    await session.flush()
    return catalogue


async def seed_rate_catalogue_demo(session: AsyncSession, project_ids: list[uuid.UUID] | None = None) -> dict[str, int]:
    """Showcase data: both demo catalogues, asset ``EX-03`` linked to the EUR excavator.

    ``EX-03`` carries a returned rental at the catalogue hourly rate so the rate shows up in
    the rental list; the charge preview reproduces the 4,044.60 EUR month from its hours.
    """
    eur = await load_demo_catalogue(session, "EUR")
    await load_demo_catalogue(session, "USD")
    item = (
        await session.execute(
            select(EquipmentRateItem).where(
                EquipmentRateItem.catalogue_id == eur.id, EquipmentRateItem.code == "D-EX20"
            )
        )
    ).scalar_one()
    created = 0
    asset = (await session.execute(select(Equipment).where(Equipment.code == "EX-03"))).scalar_one_or_none()
    if asset is None:
        asset = Equipment(
            code="EX-03",
            name="Excavator 20 t",
            type_code="excavator",
            ownership="owned",
            status="active",
            currency="EUR",
            purchase_value=item.value,
            residual_value=item.residual,
            useful_life_years=int(item.life_years),
            rate_item_id=item.id,
            cost_code="300.20",
        )
        session.add(asset)
        await session.flush()
        created = 1
    elif asset.rate_item_id is None:
        asset.rate_item_id = item.id
    if project_ids and created:
        rental = EquipmentRental(
            equipment_id=asset.id,
            project_id=project_ids[0],
            start_date="2026-10-01",
            end_date="2026-10-31",
            internal_rate_per_day=D("0"),
            internal_rate_per_hour=D("29.96"),
            currency="EUR",
            status="returned",
            metadata_={"rate_source": {"item_id": str(item.id), "catalogue": eur.name, "overridden": False}},
        )
        session.add(rental)
        await session.flush()
    return {"catalogues": 2, "machines": 10, "assets": created}

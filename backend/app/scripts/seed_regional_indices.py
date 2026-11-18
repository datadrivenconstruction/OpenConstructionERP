# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Seed regional cost indices (v3.12.0 - Stream B).

Inserts ~50 sample rows into ``oe_regional_indices`` - 8 cities × 6
trade categories. Factors are 1.0-baselined on Berlin, with values
calibrated against open published city cost indices (a UK cost index,
Eurostat construction price index for EU). US metro rows are derived from
BLS wage data, see ``_US_LABOR_WAGES``. They are
representative averages - production deployments should overwrite the
``OE_v3.12_seed_2026Q2`` rows with audited indices.

Idempotent: a row already in the DB (by the table's UNIQUE
constraint) is skipped so the script can run on top of an existing
catalogue without duplicating snapshots.

Usage::

    cd backend && python -m app.scripts.seed_regional_indices
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from decimal import Decimal

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


# Seed snapshot ID. Hard-coded so re-imports of this script are
# idempotent against the UNIQUE(region, category, subcategory,
# effective_date) constraint.
_SEED_SOURCE = "OE_v3.12_seed_2026Q2"
_SEED_DATE = date(2026, 4, 1)


# Factor matrix (regions × categories). Berlin = 1.00 baseline.
#
# Categories: concrete · steel · labor · mep · finishes · sitework
# Calibration anchors:
#   * Munich is ~12 % above Berlin on average (German cost index 2026Q1).
#   * London is ~18 % above Berlin (UK cost index, general).
#   * Manchester is ~95 % of London (UK cost index, regional).
#   * US rows are not in this matrix: they are derived below from public
#     BLS wage data and baselined on the US national average, because the
#     catalogue they adjust is the national USD one.
#   * Paris is ~8 % above Berlin (FFB 2026).
#   * Madrid is ~85 % of Berlin (Eurostat 2026).
_FACTORS: dict[str, dict[str, float]] = {
    "DE_BERLIN": {
        "concrete": 1.00,
        "steel": 1.00,
        "labor": 1.00,
        "mep": 1.00,
        "finishes": 1.00,
        "sitework": 1.00,
    },
    "DE_MUNICH": {
        "concrete": 1.10,
        "steel": 1.08,
        "labor": 1.15,
        "mep": 1.12,
        "finishes": 1.14,
        "sitework": 1.09,
    },
    "UK_LONDON": {
        "concrete": 1.20,
        "steel": 1.18,
        "labor": 1.25,
        "mep": 1.16,
        "finishes": 1.22,
        "sitework": 1.10,
    },
    "UK_MANCHESTER": {
        "concrete": 1.05,
        "steel": 1.08,
        "labor": 1.02,
        "mep": 1.06,
        "finishes": 1.04,
        "sitework": 0.98,
    },
    "FR_PARIS": {
        "concrete": 1.06,
        "steel": 1.05,
        "labor": 1.12,
        "mep": 1.08,
        "finishes": 1.10,
        "sitework": 1.04,
    },
    "ES_MADRID": {
        "concrete": 0.85,
        "steel": 0.88,
        "labor": 0.78,
        "mep": 0.86,
        "finishes": 0.84,
        "sitework": 0.82,
    },
}


# US metro factors, derived from public data and baselined on the US national
# average (US_NATIONAL = 1.00), the price level of the national USD catalogue.
#
# Source: U.S. Bureau of Labor Statistics, Occupational Employment and Wage
# Statistics (OEWS), May 2025, annual mean wage of SOC 47-0000 "Construction
# and Extraction Occupations", per metropolitan statistical area. Public domain
# (17 U.S.C. § 105). Series ids follow ``OEUM<area>000000470000004``; the
# national series is ``OEUN000000000000047000004``.
#
# Method: the labour factor of a metro is its wage over the national wage.
# Materials and plant are priced nationally, so a category's factor moves
# only by its labour share: factor = 1 + share x (labour factor - 1). The
# shares are the stated assumptions of the method, not measurements; an
# installation that knows its own mix overwrites the rows.
_US_SEED_SOURCE = "BLS_OEWS_2025_05_SOC47"
# A later date than the matrix above, so the derived rows read as the latest.
_US_SEED_DATE = date(2026, 5, 1)
_US_NATIONAL_WAGE = 65360
_US_LABOR_WAGES: dict[str, tuple[str, int]] = {
    "US_NYC": ("35620", 82140),
    "US_LA": ("31080", 77100),
    "US_SF": ("41860", 90820),
    "US_SACRAMENTO": ("40900", 75820),
    "US_HOUSTON": ("26420", 57020),
    "US_DALLAS": ("19100", 56210),
    "US_MIAMI": ("33100", 58140),
    "US_ORLANDO": ("36740", 54850),
    "US_DENVER": ("19740", 68640),
    "US_CHICAGO": ("16980", 85000),
    "US_ATLANTA": ("12060", 58770),
}
#: Labour share of installed cost per category (assumption of the method).
_US_LABOR_SHARE: dict[str, Decimal] = {
    "concrete": Decimal("0.40"),
    "steel": Decimal("0.35"),
    "labor": Decimal("1.00"),
    "mep": Decimal("0.45"),
    "finishes": Decimal("0.50"),
    "sitework": Decimal("0.35"),
}


def us_metro_factors() -> dict[str, dict[str, Decimal]]:
    """The US metro factor matrix derived from the BLS wages above."""
    out: dict[str, dict[str, Decimal]] = {"US_NATIONAL": dict.fromkeys(_US_LABOR_SHARE, Decimal("1.00"))}
    for region, (_area, wage) in _US_LABOR_WAGES.items():
        labour = Decimal(wage) / Decimal(_US_NATIONAL_WAGE)
        out[region] = {
            category: (Decimal(1) + share * (labour - Decimal(1))).quantize(Decimal("0.01"))
            for category, share in _US_LABOR_SHARE.items()
        }
    return out


def _rows() -> list[dict[str, object]]:
    """Materialise the factor matrix as flat dicts for bulk insert."""
    out: list[dict[str, object]] = []
    for region, by_category in _FACTORS.items():
        for category, factor in by_category.items():
            out.append(
                {
                    "region_code": region,
                    "category": category,
                    "subcategory": None,
                    "factor": Decimal(str(factor)),
                    "source": _SEED_SOURCE,
                    "effective_date": _SEED_DATE,
                }
            )
    for region, by_category in us_metro_factors().items():
        for category, factor in by_category.items():
            out.append(
                {
                    "region_code": region,
                    "category": category,
                    "subcategory": None,
                    "factor": factor,
                    "source": _US_SEED_SOURCE,
                    "effective_date": _US_SEED_DATE,
                }
            )
    return out


async def main() -> int:
    """Run the seed. Returns the count of NEW rows inserted (skipped rows excluded)."""
    from sqlalchemy import and_, delete, func, select

    from app.database import Base, async_session_factory, engine
    from app.modules.costs.models import RegionalIndex

    # Make sure the schema exists in SQLite dev mode.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    print("=" * 70)
    print(f"  REGIONAL INDICES SEED - {_SEED_SOURCE} ({_SEED_DATE.isoformat()})")
    print("=" * 70)

    rows = _rows()
    inserted = 0
    skipped = 0

    async with async_session_factory() as session:
        # Earlier seeds shipped US rows calibrated on a commercial index; the
        # BLS-derived rows replace them.
        await session.execute(
            delete(RegionalIndex).where(
                RegionalIndex.source == _SEED_SOURCE,
                RegionalIndex.region_code.like(r"US\_%", escape="\\"),
            )
        )
        for row in rows:
            # Composite-key existence check (subcategory is NULL here
            # so we use IS NULL explicitly - SQLAlchemy expands ``==
            # None`` correctly but the explicit form is more readable).
            existing_stmt = select(func.count(RegionalIndex.id)).where(
                and_(
                    RegionalIndex.region_code == row["region_code"],
                    RegionalIndex.category == row["category"],
                    RegionalIndex.subcategory.is_(None),
                    RegionalIndex.effective_date == row["effective_date"],
                )
            )
            already = int((await session.execute(existing_stmt)).scalar_one() or 0)
            if already:
                skipped += 1
                continue

            session.add(RegionalIndex(**row))
            inserted += 1

        await session.commit()

    print(f"\n  inserted: {inserted}    skipped (already present): {skipped}")
    print(f"  total rows in factor matrix: {len(rows)}")
    print("=" * 70)
    return inserted


if __name__ == "__main__":
    asyncio.run(main())

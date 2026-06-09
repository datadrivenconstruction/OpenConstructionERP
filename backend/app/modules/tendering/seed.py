"""Demo seed data for the tendering module.

Creates a small, realistic set of tender packages and bids for non-flagship
demo projects. By design the flagship project has NO tender packages, so the
flagship id is skipped for package creation while other projects receive a
handful of packages across different trades and statuses.

Loaded on demand via ``await seed_tendering(session, project_ids)``. Safe to
call repeatedly: if a marker package already exists for the first seeded
project, the function returns immediately without inserting duplicates.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tendering.models import TenderBid, TenderPackage

logger = logging.getLogger(__name__)

FLAGSHIP_PROJECT_ID = uuid.UUID("f1a95000-0001-4a00-8b00-000000000001")

# (suffix, trade name, status, deadline ISO string, base budget)
_PACKAGE_SPECS: list[tuple[str, str, str, str, str]] = [
    ("ELEC", "Electrical works", "open", "2026-07-15", "120000"),
    ("HVAC", "HVAC supply and install", "closed", "2026-05-30", "240000"),
    ("FACD", "Facade cladding", "draft", "2026-08-10", "510000"),
]

# (company, contact email, price multiplier vs budget, status)
_BID_SPECS: list[tuple[str, str, str, str]] = [
    ("Alpha Construction Ltd", "tenders@alpha.example", "0.94", "submitted"),
    ("Beta Builders GmbH", "bids@beta.example", "1.02", "submitted"),
    ("Gamma Contractors Inc", "estimating@gamma.example", "1.11", "submitted"),
    ("Delta Engineering Co", "office@delta.example", "1.23", "submitted"),
]


async def _seed_one_project(
    session: AsyncSession,
    project_id: uuid.UUID,
    project_index: int,
) -> dict[str, int]:
    """Seed tender packages and bids for a single project.

    Args:
        session: Open async DB session.
        project_id: Project to attach packages to.
        project_index: Stable index used to build deterministic package names.

    Returns:
        Per-entity row counts inserted for this project.
    """
    counts = {"packages": 0, "bids": 0}

    for pkg_idx, (suffix, trade, status, deadline, budget) in enumerate(_PACKAGE_SPECS):
        name = f"TP-P{project_index:02d}-{suffix} {trade}"
        package = TenderPackage(
            project_id=project_id,
            boq_id=None,
            name=name,
            description=(
                f"Tender package for {trade.lower()} on demo project "
                f"{project_index + 1}. Includes scope, drawings, and "
                f"instructions to bidders."
            ),
            status=status,
            deadline=deadline,
            metadata_={"seed": True, "demo": True, "trade": suffix},
        )
        session.add(package)
        await session.flush()
        counts["packages"] += 1

        # Each package gets 2-4 bids from different vendors with a price spread.
        # The flagship-style pattern is avoided here; draft packages get fewer
        # bids, closed/open packages get the full set.
        if status == "draft":
            bid_specs = _BID_SPECS[:2]
        elif status == "open":
            bid_specs = _BID_SPECS[:3]
        else:
            bid_specs = _BID_SPECS

        budget_dec = Decimal(budget)
        for bid_idx, (company, email, multiplier, bid_status) in enumerate(bid_specs):
            total = (budget_dec * Decimal(multiplier)).quantize(Decimal("0.01"))
            unit_price = (total / Decimal("100")).quantize(Decimal("0.01"))
            bid = TenderBid(
                package_id=package.id,
                company_name=company,
                contact_email=email,
                total_amount=str(total),
                currency="EUR",
                submitted_at=(
                    f"2026-0{5 + (pkg_idx % 3)}-1{bid_idx} 10:00:00+00:00" if bid_status == "submitted" else None
                ),
                status=bid_status,
                notes=f"Bid from {company} for {trade.lower()}.",
                line_items=[
                    {
                        "code": "01",
                        "description": f"{trade} - main scope",
                        "unit": "lsum",
                        "quantity": "1",
                        "unit_price": str(total),
                        "total_price": str(total),
                    },
                    {
                        "code": "02",
                        "description": f"{trade} - provisional sum",
                        "unit": "lsum",
                        "quantity": "1",
                        "unit_price": str(unit_price),
                        "total_price": str(unit_price),
                    },
                ],
                metadata_={"seed": True, "rank": bid_idx + 1},
            )
            session.add(bid)
            counts["bids"] += 1
        await session.flush()

    return counts


async def seed_tendering(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
) -> dict[str, int]:
    """Seed deterministic demo tender packages and bids.

    The flagship project intentionally receives no tender packages, matching
    the demo narrative where other projects are out to tender. Seeding is
    limited to the first three non-flagship projects to stay light, and is
    idempotent: it short-circuits when a marker package already exists for the
    first project that would be seeded.

    Args:
        session: Open async DB session.
        project_ids: Candidate projects to seed against.

    Returns:
        Aggregated per-entity row counts.
    """
    totals = {"packages": 0, "bids": 0}

    # The flagship has no tender packages by design, so seed the other
    # projects only. Keep at most the first 3 non-flagship projects light.
    target_ids = [pid for pid in project_ids if pid != FLAGSHIP_PROJECT_ID][:3]
    if not target_ids:
        logger.info("tendering seed: no non-flagship projects to seed, skipping")
        return totals

    # Idempotency guard: if a package already exists for the first target
    # project, assume the seed has already run and return empty.
    marker_name = f"TP-P00-{_PACKAGE_SPECS[0][0]} {_PACKAGE_SPECS[0][1]}"
    existing = await session.execute(
        select(TenderPackage).where(
            TenderPackage.project_id == target_ids[0],
            TenderPackage.name == marker_name,
        )
    )
    if existing.scalar_one_or_none() is not None:
        logger.info("tendering seed: marker package already present, skipping")
        return {}

    for idx, pid in enumerate(target_ids):
        counts = await _seed_one_project(session, pid, idx)
        for key, value in counts.items():
            totals[key] += value

    await session.flush()
    logger.info("tendering seed complete: %s", totals)
    return totals

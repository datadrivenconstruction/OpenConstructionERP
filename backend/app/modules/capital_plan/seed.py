# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Capital plan demo seed: one five-year plan, eight items, two scenarios.

The baseline runs over the funding envelope in exactly one year, so the gap row is red
the first time the page opens; the second scenario delays the road programme by a year
and clears it. The plan hangs under the root portfolio node when one exists. The seeder
does nothing once any plan exists, so a re-run never doubles it.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.capital_plan.models import (
    CapitalPlan,
    CapitalPlanEnvelope,
    CapitalPlanItem,
    CapitalPlanScenario,
)
from app.modules.portfolio.models import PortfolioNode

logger = logging.getLogger(__name__)

# (title, priority, start offset, duration, cost, score)
_ITEMS: tuple[tuple[str, int, int, int, str, int | None], ...] = (
    ("Water main renewal", 1, 0, 2, "8000000", 90),
    ("School extension", 2, 0, 2, "6000000", 75),
    ("Road resurfacing programme", 3, 1, 3, "9000000", 60),
    ("Fire station", 2, 1, 1, "5000000", 80),
    ("Library refurbishment", 4, 2, 2, "4000000", 40),
    ("Bridge repair", 1, 2, 2, "7500000", 85),
    ("Park and playground", 5, 3, 1, "2400000", 30),
    ("Depot relocation", 3, 3, 2, "6000000", 55),
)
# (year offset, amount, label)
_ENVELOPES: tuple[tuple[int, str, str], ...] = (
    (0, "10000000", "Bond"),
    (1, "14000000", "Bond"),
    (2, "12000000", "Bond"),
    (3, "15000000", "Bond"),
    (4, "10000000", "Bond"),
)


async def seed_capital_plan_demo(session: AsyncSession) -> dict[str, int]:
    """Create the demo plan once; returns insert counts."""
    totals = {"plans": 0, "scenarios": 0, "items": 0}
    if (await session.execute(select(CapitalPlan.id).limit(1))).scalars().first() is not None:
        return totals
    year = datetime.now(UTC).year
    try:
        async with session.begin_nested():
            root = (
                (
                    await session.execute(
                        select(PortfolioNode)
                        .where(PortfolioNode.parent_id.is_(None))
                        .order_by(PortfolioNode.created_at)
                    )
                )
                .scalars()
                .first()
            )
            plan = CapitalPlan(
                node_id=root.id if root else None,
                name="Five-year capital plan",
                currency="EUR",
                start_year=year,
                horizon_years=5,
                metadata_={"demo": True},
            )
            session.add(plan)
            await session.flush()
            for offset, amount, label in _ENVELOPES:
                session.add(
                    CapitalPlanEnvelope(plan_id=plan.id, year=year + offset, amount=Decimal(amount), label=label)
                )
            scenarios = []
            for name, baseline in (("Baseline", True), ("Delay roads 1y", False)):
                scenario = CapitalPlanScenario(plan_id=plan.id, name=name, is_baseline=baseline)
                session.add(scenario)
                scenarios.append(scenario)
            await session.flush()
            for scenario in scenarios:
                for title, priority, offset, duration, cost, score in _ITEMS:
                    delay = 1 if scenario.name != "Baseline" and title.startswith("Road") else 0
                    session.add(
                        CapitalPlanItem(
                            scenario_id=scenario.id,
                            title=title,
                            priority=priority,
                            start_year=year + offset + delay,
                            duration_years=duration,
                            total_cost=Decimal(cost),
                            phasing_json=[],
                            status="proposed",
                            score=score,
                        )
                    )
                    totals["items"] += 1
            totals["plans"] = 1
            totals["scenarios"] = len(scenarios)
    except Exception:
        logger.warning("Capital plan demo seed skipped (non-fatal)", exc_info=True)
        return {"plans": 0, "scenarios": 0, "items": 0}
    return totals

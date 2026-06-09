"""Demo seed data for the Management of Change (MoC) module.

``seed_moc(session, project_ids)`` creates a small, deterministic set of
MoC entries spread across the lifecycle states (proposed, reviewed,
accepted, declined, implemented) and attaches one to three impact rows
(cost, schedule, quality, safety) to each entry.

The seed is idempotent: it short-circuits when a MoC entry with the
expected marker code already exists for the first project id, so it is
safe to call more than once.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.moc.models import MoCEntry, MoCImpact

logger = logging.getLogger(__name__)

# Flagship demo project. Always seeded when present in project_ids.
_FLAGSHIP_ID = uuid.UUID("f1a95000-0001-4a00-8b00-000000000001")

# (suffix, status, change_category, risk_level, title, schedule_delta_days, cost_impact)
_ENTRY_SPECS: list[tuple[str, str, str, str, str, int, str]] = [
    (
        "001",
        "proposed",
        "design",
        "medium",
        "Relocate main electrical riser to core B",
        5,
        "18500.00",
    ),
    (
        "002",
        "reviewed",
        "engineering",
        "high",
        "Upgrade slab rebar to comply with revised load study",
        12,
        "64200.00",
    ),
    (
        "003",
        "accepted",
        "contract",
        "medium",
        "Substitute facade panel supplier after lead-time slip",
        -3,
        "9800.00",
    ),
    (
        "004",
        "declined",
        "safety",
        "critical",
        "Add temporary edge protection on level 7 perimeter",
        0,
        "4200.00",
    ),
    (
        "005",
        "implemented",
        "engineering",
        "low",
        "Re-route chilled water loop around plant room column",
        2,
        "12750.00",
    ),
]

# Impact rows keyed by entry suffix.
# (impact_area, severity, description, cost_impact, schedule_delta_days, mitigation)
_IMPACT_SPECS: dict[str, list[tuple[str, str, str, str, int, str]]] = {
    "001": [
        (
            "cost",
            "medium",
            "Additional conduit, cabling and labour for the new riser path.",
            "18500.00",
            0,
            "Bulk order conduit with the existing electrical package.",
        ),
        (
            "schedule",
            "low",
            "Five extra days for first-fix coordination.",
            "0.00",
            5,
            "Run the rework in parallel with dry-lining on lower floors.",
        ),
    ],
    "002": [
        (
            "cost",
            "high",
            "Extra reinforcement steel and revised formwork.",
            "64200.00",
            0,
            "Negotiate a fixed steel price before order placement.",
        ),
        (
            "schedule",
            "high",
            "Twelve days lost to redesign and inspection sign-off.",
            "0.00",
            12,
            "Accelerate adjacent trades to recover the float.",
        ),
        (
            "quality",
            "medium",
            "Tighter rebar spacing raises pour and vibration risk.",
            "0.00",
            0,
            "Add an extra concrete inspection hold point.",
        ),
    ],
    "003": [
        (
            "cost",
            "medium",
            "Price delta between the original and replacement panel supplier.",
            "9800.00",
            0,
            "Recover the delta through the variation account.",
        ),
        (
            "schedule",
            "low",
            "Three days saved by avoiding the original supplier backlog.",
            "0.00",
            -3,
            "Lock the new delivery slot in writing.",
        ),
    ],
    "004": [
        (
            "safety",
            "critical",
            "Open perimeter on level 7 during structural works.",
            "4200.00",
            0,
            "Install proprietary edge protection before access is granted.",
        ),
    ],
    "005": [
        (
            "cost",
            "low",
            "Minor extra pipe runs and fittings for the loop diversion.",
            "12750.00",
            0,
            "Use offcuts already held in stores.",
        ),
        (
            "schedule",
            "low",
            "Two days for re-routing and pressure testing.",
            "0.00",
            2,
            "Test out of hours to avoid blocking the plant room.",
        ),
        (
            "quality",
            "low",
            "Extra joints increase the leak-test surface.",
            "0.00",
            0,
            "Add an additional pressure-test cycle.",
        ),
    ],
}


def _select_project_ids(project_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """Pick at most the first three project ids, always including the flagship."""
    selected: list[uuid.UUID] = list(project_ids[:3])
    if _FLAGSHIP_ID in project_ids and _FLAGSHIP_ID not in selected:
        selected.append(_FLAGSHIP_ID)
    return selected


async def _seed_one_project(
    session: AsyncSession,
    project_id: uuid.UUID,
    project_index: int,
) -> dict[str, int]:
    """Seed MoC entries and impacts for a single project.

    Returns counts for aggregation. Skips any entry whose code already
    exists for this project so re-runs do not create duplicates.
    """
    counts = {"entries": 0, "impacts": 0}

    for suffix, status, category, risk, title, schedule_delta, cost_impact in _ENTRY_SPECS:
        code = f"MOC-P{project_index:02d}-{suffix}"

        existing = await session.execute(
            select(MoCEntry).where(
                MoCEntry.project_id == project_id,
                MoCEntry.code == code,
            )
        )
        if existing.scalar_one_or_none() is not None:
            continue

        reviewed = status in {"reviewed", "accepted", "declined", "implemented"}
        decided = status in {"accepted", "declined", "implemented"}
        implemented = status == "implemented"

        entry = MoCEntry(
            project_id=project_id,
            code=code,
            title=title,
            description=f"Demo management-of-change proposal: {title}.",
            change_category=category,
            risk_level=risk,
            proposed_by="demo-engineer",
            proposed_at="2026-05-01T09:00:00+00:00",
            reviewed_by="demo-reviewer" if reviewed else None,
            reviewed_at="2026-05-05T14:30:00+00:00" if reviewed else None,
            review_notes="Risk review completed against the project baseline." if reviewed else "",
            decided_by="demo-sponsor" if decided else None,
            decided_at="2026-05-08T11:00:00+00:00" if decided else None,
            decision_notes=("Approved by the sponsor." if status != "declined" else "") if decided else "",
            implemented_by="demo-site-team" if implemented else None,
            implemented_at="2026-05-20T16:00:00+00:00" if implemented else None,
            cost_impact=Decimal(cost_impact),
            schedule_delta_days=schedule_delta,
            currency="EUR",
            status=status,
            metadata_={"seed": True, "demo": True},
        )
        session.add(entry)
        await session.flush()
        counts["entries"] += 1

        for area, severity, description, impact_cost, impact_days, mitigation in _IMPACT_SPECS[suffix]:
            impact = MoCImpact(
                moc_entry_id=entry.id,
                impact_area=area,
                description=description,
                severity=severity,
                cost_impact=Decimal(impact_cost),
                schedule_delta_days=impact_days,
                currency="EUR",
                mitigation=mitigation,
            )
            session.add(impact)
            counts["impacts"] += 1
        await session.flush()

    return counts


async def seed_moc(
    session: AsyncSession,
    project_ids: list[uuid.UUID],
) -> dict[str, int]:
    """Seed deterministic demo MoC entries and impacts.

    Args:
        session: Open async DB session.
        project_ids: Candidate project ids. At most the first three are
            seeded, always including the flagship project if present.

    Returns:
        Aggregated row counts per entity inserted. Returns an empty dict
        when the marker entry already exists for the first project id.
    """
    if not project_ids:
        logger.info("moc seed skipped: no project ids provided")
        return {}

    # Idempotency marker: the first entry for the first project id.
    marker_code = "MOC-P00-001"
    marker = await session.execute(
        select(MoCEntry).where(
            MoCEntry.project_id == project_ids[0],
            MoCEntry.code == marker_code,
        )
    )
    if marker.scalar_one_or_none() is not None:
        logger.info("moc seed skipped: marker entry already present")
        return {}

    totals = {"entries": 0, "impacts": 0}
    for index, project_id in enumerate(_select_project_ids(project_ids)):
        counts = await _seed_one_project(session, project_id, index)
        for key, value in counts.items():
            totals[key] += value

    await session.flush()
    logger.info("moc seed complete: %s", totals)
    return totals

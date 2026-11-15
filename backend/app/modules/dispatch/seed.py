# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo dispatch board: a yard, a workshop, one column per demo project and three crews.

The board opened on "No columns yet". The dispatch board is company-wide rather
than per project, so this seeds it once: the two standing places crews come from,
a column for each of the first demo projects, and today's cards with each crew
placed on a project. Nothing is written when the board already has a column.

Only demo projects are handed in by the caller.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dispatch.models import DispatchCrew, DispatchLocation, DispatchPlacement

logger = logging.getLogger(__name__)

#: English texts of the seeded board, in one place so they can be localised later.
TEXTS: dict[str, object] = {
    "yard": "Main yard",
    "shop": "Workshop",
    "crews": (
        ("Formwork crew A", "Formwork"),
        ("Concrete crew", "Concrete"),
        ("Finishing crew", "Finishing"),
    ),
    "note": "Planned start of the pour sequence.",
}

#: At most this many project columns, so the board stays readable.
_MAX_PROJECT_COLUMNS = 4


async def seed_dispatch_demo(session: AsyncSession, project_ids: Iterable[uuid.UUID]) -> dict[str, int]:
    """Write the demo board. The caller commits."""
    from app.modules.projects.models import Project

    totals = {"locations": 0, "crews": 0, "placements": 0}
    ids = list(project_ids)
    if not ids:
        return totals
    if (await session.execute(select(DispatchLocation.id).limit(1))).first() is not None:
        return totals
    projects = (
        (await session.execute(select(Project).where(Project.id.in_(ids)).order_by(Project.name))).scalars().all()
    )[:_MAX_PROJECT_COLUMNS]
    if not projects:
        return totals

    columns: list[DispatchLocation] = []
    for order, (kind, name, pid) in enumerate(
        [("yard", str(TEXTS["yard"]), None), ("shop", str(TEXTS["shop"]), None)]
        + [("project", p.name, p.id) for p in projects]
    ):
        column = DispatchLocation(name=name, kind=kind, project_id=pid, sort_order=order, is_active=True)
        session.add(column)
        columns.append(column)
    await session.flush()
    totals["locations"] = len(columns)

    today = datetime.now(UTC).date()
    project_columns = [c for c in columns if c.kind == "project"]
    for index, (name, trade) in enumerate(TEXTS["crews"]):  # type: ignore[misc]
        crew = DispatchCrew(name=name, trade=trade, member_ids=[], min_size=0, is_active=True)
        session.add(crew)
        await session.flush()
        totals["crews"] += 1
        session.add(
            DispatchPlacement(
                day=today,
                card_kind="crew",
                card_ref=str(crew.id),
                location_id=project_columns[index % len(project_columns)].id,
                start_time="07:00",
                notes=str(TEXTS["note"]),
                source="seed",
            )
        )
        totals["placements"] += 1
    await session.flush()
    return totals

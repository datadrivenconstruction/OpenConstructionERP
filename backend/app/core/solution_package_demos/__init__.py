# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo seeds of solution packages that the classic demo templates do not cover.

The scenario itself is data (``*.json`` next to this file); the code only
writes it through the neutral modules. The supply-chain demo follows the
rebar cages of bored piles through the prefab stage machine, so every unit
carries the audit trail a real one would.
"""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

_DATA = Path(__file__).resolve().parent


def load_rebar_cage_scenario() -> dict[str, Any]:
    """The rebar cage scenario as data."""
    return json.loads((_DATA / "rebar_cage_supply_chain.json").read_text(encoding="utf-8"))


async def seed_rebar_cage_demo(session: AsyncSession, *, owner_id: str) -> dict[str, Any]:
    """Create the rebar cage demo project once; a second call returns the existing one."""
    from app.modules.prefab.models import PrefabUnit, ProductionEvent
    from app.modules.projects.models import Project

    scenario = load_rebar_cage_scenario()
    demo_id = scenario["demo_id"]
    for project in (await session.execute(select(Project))).scalars():
        meta = project.metadata_ or {}
        if meta.get("demo_id") == demo_id and str(project.owner_id) == str(owner_id):
            return {"project_id": str(project.id), "project_name": project.name, "already_installed": True}

    spec = scenario["project"]
    project = Project(
        name=spec["name"],
        description=spec["description"],
        region=spec["region"],
        classification_standard=spec["classification_standard"],
        currency=spec["currency"],
        owner_id=uuid.UUID(str(owner_id)),
        metadata_={"is_demo": True, "demo_id": demo_id, "solution_package": "supply_chain"},
    )
    session.add(project)
    await session.flush()

    stages: list[str] = scenario["stages"]
    today = date.today()
    for spec_unit in scenario["units"]:
        unit = PrefabUnit(
            project_id=project.id,
            ref=spec_unit["ref"],
            unit_type=scenario["unit_type"],
            status=spec_unit["status"],
            target_install_date=today + timedelta(days=spec_unit["target_install_offset_days"]),
            drawing_ref=spec_unit["drawing_ref"],
            element_ref=spec_unit["element_ref"],
            delivery_note_ref=spec_unit.get("delivery_note_ref"),
            notes=spec_unit["notes"],
            qr_token=secrets.token_urlsafe(18),
            created_by=str(owner_id),
        )
        session.add(unit)
        await session.flush()
        reached = stages[: stages.index(spec_unit["status"]) + 1]
        previous: str | None = None
        for stage in reached:
            note = "Unit registered" if previous is None else None
            if stage == "delivered" and spec_unit.get("delivery_note_ref"):
                note = f"Received on delivery note {spec_unit['delivery_note_ref']}"
            if stage == "installed":
                note = f"Installed into pile {spec_unit['element_ref']}"
            session.add(
                ProductionEvent(unit_id=unit.id, stage=stage, from_stage=previous, note=note, created_by=str(owner_id))
            )
            previous = stage
    await session.flush()
    return {
        "project_id": str(project.id),
        "project_name": project.name,
        "units": len(scenario["units"]),
        "already_installed": False,
    }

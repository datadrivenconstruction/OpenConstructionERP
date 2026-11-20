# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plan editor part of the Riverside Yard demo: the project's feature code library."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.survey_core.plan_schemas import CodeEntryIn, CodeLibraryIn
from app.modules.survey_core.plan_service import PlanService

CODES = Path(__file__).resolve().parent / "demo" / "riverside" / "codes_riverside.json"
PLAN_DEMOS = frozenset({"survey-riverside-yard"})


async def seed_plan_demo(session: AsyncSession, project_id: uuid.UUID, user_id: str) -> dict[str, Any]:
    """Give the demo project its own code library, so the plan draws kerbs, fence, trees and manholes."""
    items = json.loads(CODES.read_text(encoding="utf-8"))["items"]
    body = CodeLibraryIn(items=[CodeEntryIn(**i) for i in items])
    out = await PlanService(session).put_codes(project_id, body, user_id, ["*"])
    return {"survey_plan_codes": len(out.items)}


__all__ = ["PLAN_DEMOS", "seed_plan_demo"]

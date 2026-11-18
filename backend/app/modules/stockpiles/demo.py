# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Riverside Yard stockpile demo: Stockpile A with its base surface and book stock.

The survey itself stays for the learner: add ``stockpile_A_2026-10-12.csv``,
set the density, and read the variance against the 8,400 t on the books.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

DATA = Path(__file__).resolve().parent.parent / "survey_core" / "demo" / "riverside"
BOOK_TONNES = 8400.0


async def seed_stockpile_demo(session: AsyncSession, project_id: uuid.UUID, user_id: str) -> dict[str, Any]:
    """Create Stockpile A in ``project_id``; the project CRS must already be set."""
    from app.modules.stockpiles.schemas import StockpileCreate
    from app.modules.stockpiles.service import StockpileService

    pile = await StockpileService(session).create_stockpile(
        project_id,
        StockpileCreate(
            name="Stockpile A",
            material="Aggregate 0/32",
            location_note="Riverside Yard, east of the platform",
            base_text=(DATA / "stockpile_A_base.csv").read_text(encoding="utf-8"),
            base_filename="stockpile_A_base.csv",
            book_tonnes=BOOK_TONNES,
        ),
        user_id,
    )
    return {"survey_stockpiles": 1, "survey_stockpile_book_t": pile.book_tonnes}

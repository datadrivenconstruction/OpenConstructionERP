# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ quotes: three synthetic supplier quotes on the first demo tender package.

They go through the same rules parser a real upload does, so the review screen
shows real confidences and anchors. One quote excludes scaffolding, one leaves an
item out (a scope gap the levelling plugs), and one carries a price escalation
clause. Supplier names are invented and generic.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.quote_capture.models import CapturedQuote

logger = logging.getLogger(__name__)

_SUPPLIERS = (
    ("Alder Facade Works", Decimal("0.96"), "exclusion"),
    ("Birchway Building Services", Decimal("1.02"), "gap"),
    ("Cedarline Contracting", Decimal("1.07"), "escalation"),
)
MAX_LINES = 8


def _fmt(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):,.2f}"


def quote_text(
    supplier: str, positions: list, factor: Decimal, flavour: str, currency: str, today: date
) -> tuple[str, int]:
    """Plain-text quote for the given positions; returns the text and the number of priced lines."""
    rows: list[str] = []
    total = Decimal("0")
    picked = positions[:MAX_LINES]
    for idx, pos in enumerate(picked, start=1):
        if flavour == "gap" and idx == 2 and len(picked) > 2:
            continue
        qty = Decimal(str(pos.quantity or 0)).quantize(Decimal("0.01"))
        rate = (Decimal(str(pos.unit_rate or 0)) * factor).quantize(Decimal("0.01"))
        line_total = (qty * rate).quantize(Decimal("0.01"))
        total += line_total
        desc = " ".join((pos.description or "Item").split())[:70]
        rows.append(f"{idx}  {desc}  {_fmt(qty)}  {pos.unit}  {_fmt(rate)}  {_fmt(line_total)}")
    issued = today - timedelta(days=3)
    lines = [
        f"Supplier: {supplier}",
        f"Quote date: {issued.isoformat()}",
        "This quotation is valid for 30 days.",
        "Pos  Description  Qty  Unit  Rate  Total",
        *rows,
    ]
    if flavour == "exclusion":
        lines.append("Excluding scaffolding and edge protection, to be provided by the main contractor.")
    if flavour == "escalation":
        lines.append("Prices are subject to a price adjustment clause for material cost changes after 60 days.")
    lines += [
        "Payment terms: 30 days from invoice",
        "Delivery: 3 weeks after order",
        f"Total net {_fmt(total)} {currency}",
    ]
    return "\n".join(lines), len(rows)


async def seed_demo_quotes(
    session: AsyncSession, *, project_id: uuid.UUID, created_by: str | None = None, today: date | None = None
) -> int:
    """Seed three quotes on the project's first tender package; idempotent per project."""
    from app.modules.projects.models import Project
    from app.modules.quote_capture.service import QuoteCaptureService
    from app.modules.tendering.models import TenderPackage

    if (await session.execute(select(CapturedQuote.id).where(CapturedQuote.project_id == project_id))).first():
        return 0
    package = (
        (
            await session.execute(
                select(TenderPackage).where(TenderPackage.project_id == project_id).order_by(TenderPackage.created_at)
            )
        )
        .scalars()
        .first()
    )
    if package is None:
        return 0
    svc = QuoteCaptureService(session)
    positions = await svc.scope_positions(package)
    if len(positions) < 3:
        return 0
    project = await session.get(Project, project_id)
    currency = ((getattr(project, "currency", "") or "EUR").upper())[:3]
    today = today or date.today()
    count = 0
    for supplier, factor, flavour in _SUPPLIERS:
        text, _n = quote_text(supplier, positions, factor, flavour, currency, today)
        await svc.create_from_text(
            project_id=project_id,
            package_id=package.id,
            text=text,
            filename=f"{supplier.lower().replace(' ', '-')}-quote.txt",
            user_id=created_by,
            locale="en",
            llm=False,
            engine_label="demo",
        )
        count += 1
    return count

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo captured quotes: three supplier quotes read from email text.

The capture page opened on "No quotes captured yet". This writes three quotes a
buyer would have received for a fit-out package, as the text of the supplier's
email, and runs the same rules pass the capture uses to read them, so the
lines, header fields and notes on screen are what the extractor produces and not
hand-typed JSON. Supplier names come from the project's own template through
``demo_firms_for_project``; a project whose template names no firms gets none.

Idempotent per project. Only demo projects are handed in by the caller.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.quote_capture.documents import read_text
from app.modules.quote_capture.models import CapturedQuote
from app.modules.quote_capture.parsing import parse_quote

logger = logging.getLogger(__name__)

#: English texts of the seeded emails, in one place so they can be localised later.
TEXTS: dict[str, object] = {
    "filename": "quote-{n}.txt",
    "validity": "This quotation is valid for 30 days.",
    "payment": "Payment terms: 30 days from invoice",
    "exclusions": "Excluding scaffolding and out-of-hours working.",
    "total": "Total excl. VAT {currency} {total}",
    "lines": (
        ("Metal stud partition 100 mm", "m2", "250", "38.50"),
        ("Plasterboard ceiling", "m2", "120", "41.25"),
        ("Access panels 600x600", "ea", "8", "95.00"),
    ),
}

#: Price level and review state of each quote.
_PLAN = (("1.00", "in_review"), ("1.06", "draft"), ("1.11", "draft"))


def _money(value: Decimal) -> str:
    return f"{value:,.2f}"


def _email(supplier: str, day: str, factor: Decimal, currency: str) -> str:
    rows = []
    total = Decimal("0")
    for number, (desc, unit, qty, rate) in enumerate(TEXTS["lines"], start=1):  # type: ignore[arg-type]
        unit_rate = (Decimal(rate) * factor).quantize(Decimal("0.01"))
        amount = (Decimal(qty) * unit_rate).quantize(Decimal("0.01"))
        total += amount
        rows.append(f"{number}  {desc}   {qty} {unit}   {_money(unit_rate)}   {_money(amount)}")
    return "\n".join(
        [
            supplier,
            f"Quote date: {day}",
            str(TEXTS["validity"]),
            *rows,
            str(TEXTS["exclusions"]),
            str(TEXTS["payment"]),
            str(TEXTS["total"]).format(currency=currency, total=_money(total)),
        ]
    )


async def seed_quote_capture_demo(session: AsyncSession, project_ids: Iterable[uuid.UUID]) -> dict[str, int]:
    """Write the demo quotes for the given demo projects. The caller commits."""
    from app.core.demo_projects import demo_firms_for_project
    from app.modules.projects.models import Project

    ids = list(project_ids)
    totals = {"projects": 0, "quotes": 0}
    if not ids:
        return totals
    seeded = set(
        (await session.execute(select(CapturedQuote.project_id).where(CapturedQuote.project_id.in_(ids)))).scalars()
    )
    today = datetime.now(UTC).date()
    for project in (
        await session.execute(select(Project).where(Project.id.in_([p for p in ids if p not in seeded])))
    ).scalars():
        firms = await demo_firms_for_project(session, project.id)
        if not firms:
            continue
        currency = (project.currency or "EUR")[:10]
        for index, (supplier, _email_addr) in enumerate(firms[: len(_PLAN)]):
            factor, state = _PLAN[index]
            day = (today - timedelta(days=6 - index)).isoformat()
            document = read_text(_email(supplier, day, Decimal(factor), currency), kind="email")
            result = parse_quote(document.lines, "en", today=today)
            header = result["header"]
            total = header.get("quote_total", {}).get("value") if isinstance(header.get("quote_total"), dict) else None
            session.add(
                CapturedQuote(
                    id=uuid.uuid4(),
                    project_id=project.id,
                    supplier_name=supplier[:255],
                    status=state,
                    source_kind="email",
                    original_filename=str(TEXTS["filename"]).format(n=index + 1),
                    mime_type="text/plain",
                    extraction_engine="rules",
                    locale="en",
                    currency=currency,
                    quote_total=str(total or "0"),
                    page_count=len(document.pages),
                    header=header,
                    lines=result["lines"],
                    notes=result["notes"],
                    document={
                        "engine": document.engine,
                        "pages": document.pages,
                        "lines": [{"text": ln.text, "anchor": ln.anchor} for ln in document.lines],
                    },
                    document_text=document.text,
                    created_by=str(project.owner_id) if project.owner_id else None,
                )
            )
            totals["quotes"] += 1
        totals["projects"] += 1
    await session.flush()
    return totals

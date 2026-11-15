# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Demo RFQs: one package out for bids with three quotes, one still in draft.

The register opened on "No RFQs yet" on every demo project. This writes the two
packages a buyer has on the go at any time, so the comparison table, the scope
coverage and the award step all have something to show. Bidders are the
project's own subcontractor and supplier contacts; a project with fewer than
two of them gets the packages and no quotes, never an invented firm.

Idempotent per project (a project that already has an RFQ is left alone), and
only demo projects are handed in by the caller.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rfq_bidding.models import RFQ, RFQBid, RFQBidLine, RFQLine

logger = logging.getLogger(__name__)

#: English texts of the seeded packages, in one place so they can be localised later.
TEXTS: dict[str, dict] = {
    "issued": {
        "title": "Structural steel and metalwork package",
        "description": "Supply and installation of structural steel, stairs and balustrades.",
        "scope": "Fabrication drawings, supply, erection and corrosion protection. Excludes foundations.",
        "lines": (
            ("Structural steel frame, supply and erect", "t", "42", "3150"),
            ("Steel staircase with balustrade", "pcs", "6", "8400"),
            ("Intumescent paint, 60 minutes", "m2", "950", "24"),
        ),
    },
    "draft": {
        "title": "Facade glazing and curtain wall",
        "description": "Unitised curtain wall and glazed entrance screens.",
        "scope": "Design, supply and installation including sealing and cleaning.",
        "lines": (
            ("Unitised curtain wall", "m2", "1200", "620"),
            ("Glazed entrance screen", "pcs", "4", "14500"),
        ),
    },
}

#: Price level of each bidder against the base rates; the lowest bid is not always the best fit.
_BID_FACTORS = (Decimal("1.00"), Decimal("1.07"), Decimal("1.13"))
_BID_SCORES = (("7.5", "8.5"), ("9.0", "7.0"), ("8.0", "8.0"))


def _bidders(contacts: list, pid: uuid.UUID) -> list[str]:
    out: list[str] = []
    for contact in contacts:
        meta = contact.metadata_ if isinstance(contact.metadata_, dict) else {}
        if meta.get("project_id") == str(pid):
            out.append(str(contact.id))
    return out[: len(_BID_FACTORS)]


async def seed_rfq_demo(session: AsyncSession, project_ids: Iterable[uuid.UUID]) -> dict[str, int]:
    """Write the demo RFQs for the given demo projects. The caller commits."""
    from app.modules.contacts.models import Contact
    from app.modules.projects.models import Project

    ids = list(project_ids)
    totals = {"projects": 0, "rfqs": 0, "bids": 0}
    if not ids:
        return totals
    seeded = set((await session.execute(select(RFQ.project_id).where(RFQ.project_id.in_(ids)))).scalars().all())
    projects = (
        await session.execute(select(Project).where(Project.id.in_([p for p in ids if p not in seeded])))
    ).scalars()
    contacts = (
        (await session.execute(select(Contact).where(Contact.contact_type.in_(("subcontractor", "supplier")))))
        .scalars()
        .all()
    )
    now = datetime.now(UTC)
    for project in projects:
        ccy = (project.currency or "EUR")[:10]
        bidders = _bidders(contacts, project.id)
        for number, (key, status) in enumerate((("issued", "issued"), ("draft", "draft")), start=1):
            text = TEXTS[key]
            rfq = RFQ(
                project_id=project.id,
                rfq_number=f"RFQ-{number:03d}",
                title=text["title"],
                description=text["description"],
                scope_of_work=text["scope"],
                submission_deadline=(now + timedelta(days=10 if status == "issued" else 21)).date().isoformat(),
                currency_code=ccy,
                status=status,
                issued_to_contacts=bidders if status == "issued" else [],
                created_by=project.owner_id,
                metadata_={"demo_seed": "rfq"},
            )
            session.add(rfq)
            await session.flush()
            lines = []
            for line_no, (desc, unit, qty, rate) in enumerate(text["lines"], start=1):
                line = RFQLine(rfq_id=rfq.id, line_no=line_no, description=desc, unit=unit, quantity=Decimal(qty))
                session.add(line)
                lines.append((line, Decimal(qty), Decimal(rate)))
            await session.flush()
            totals["rfqs"] += 1
            if status != "issued":
                continue
            for index, contact_id in enumerate(bidders):
                factor = _BID_FACTORS[index]
                bid_total = Decimal("0")
                bid = RFQBid(
                    rfq_id=rfq.id,
                    bidder_contact_id=contact_id,
                    bid_amount="0",
                    currency_code=ccy,
                    submitted_at=(now - timedelta(days=3 - index)).isoformat(timespec="seconds"),
                    validity_days=60,
                    technical_score=_BID_SCORES[index][0],
                    commercial_score=_BID_SCORES[index][1],
                    status="received",
                    metadata_={"demo_seed": "rfq"},
                )
                session.add(bid)
                await session.flush()
                for line, qty, rate in lines:
                    unit_rate = (rate * factor).quantize(Decimal("0.01"))
                    amount = (qty * unit_rate).quantize(Decimal("0.01"))
                    bid_total += amount
                    session.add(
                        RFQBidLine(
                            bid_id=bid.id,
                            rfq_line_id=line.id,
                            description=line.description,
                            unit=line.unit,
                            quantity=qty,
                            unit_rate=unit_rate,
                            amount=amount,
                        )
                    )
                bid.bid_amount = str(bid_total)
                totals["bids"] += 1
        totals["projects"] += 1
    await session.flush()
    return totals

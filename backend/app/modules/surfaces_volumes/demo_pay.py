# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Riverside Yard, from survey to payment: the subcontract, its open certificate and the haul.

Seeds an earthworks subcontract whose schedule of works line bills BOQ 1.02
Bulk excavation, an open (draft) payment certificate for October, ten verified
haul tickets from the cut of V-001 and the haulier's invoice for them. The
invoice bills two loads more on one ticket than the ticket shows, the one
deliberate mismatch of the lesson. Numbers live in
``survey_core/demo/riverside/expected.json`` under ``payment``.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

EXPECTED = Path(__file__).resolve().parent.parent / "survey_core" / "demo" / "riverside" / "expected.json"
#: A tiny transparent PNG standing in for the receiver's signature on the demo tickets.
DEMO_SIGNATURE = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


def _spec() -> dict[str, Any]:
    return json.loads(EXPECTED.read_text(encoding="utf-8"))["payment"]


async def _position(session: AsyncSession, project_id: uuid.UUID, description: str) -> Any:
    from app.modules.boq.models import BOQ, Position  # noqa: PLC0415

    stmt = (
        select(Position)
        .join(BOQ, BOQ.id == Position.boq_id)
        .where(BOQ.project_id == project_id, Position.description == description)
    )
    return (await session.execute(stmt)).scalars().first()


async def _free_code(session: AsyncSession, base: str) -> str:
    """Contract codes are unique across projects, so a second install of the demo gets a suffix."""
    from app.modules.contracts.models import Contract  # noqa: PLC0415

    taken = set((await session.execute(select(Contract.code).where(Contract.code.like(f"{base}%")))).scalars().all())
    code, n = base, 1
    while code in taken:
        n += 1
        code = f"{base}-{n}"
    return code


async def seed_pay_demo(
    session: AsyncSession, project_id: uuid.UUID, user_id: str, volume_id: uuid.UUID
) -> dict[str, Any]:
    """Load the payment part of the course; returns counts for the install summary."""
    spec = _spec()
    contract = await _seed_contract(session, project_id, user_id, spec["contract"])
    tickets = await _seed_haul(session, project_id, user_id, volume_id, spec["haul"])
    return {"survey_contracts": 1 if contract else 0, "survey_haul_tickets": tickets}


async def _seed_contract(session: AsyncSession, project_id: uuid.UUID, user_id: str, c: dict[str, Any]) -> Any:
    from app.modules.contracts.schemas import ContractCreate, ContractLineCreate, ProgressClaimCreate  # noqa: PLC0415
    from app.modules.contracts.service import ContractsService  # noqa: PLC0415

    line = c["line"]
    position = await _position(session, project_id, line["description"])
    if position is None:
        return None
    service = ContractsService(session)
    contract = await service.create_contract(
        ContractCreate(
            code=await _free_code(session, c["code"]),
            title=c["title"],
            contract_type="unit_price",
            counterparty_type="subcontractor",
            project_id=project_id,
            start_date=c["start_date"],
            end_date=c["end_date"],
            total_value=Decimal(str(line["quantity"])) * Decimal(str(line["unit_rate"])),
            currency=c["currency"],
            retention_percent=Decimal(str(c["retention_pct"])),
            metadata={"demo": "survey-riverside-yard"},
        ),
        user_id=user_id,
    )
    await service.create_line(
        ContractLineCreate(
            contract_id=contract.id,
            code=line["code"],
            description=line["description"],
            unit=line["unit"],
            quantity=Decimal(str(line["quantity"])),
            unit_rate=Decimal(str(line["unit_rate"])),
            metadata={"boq_position_id": str(position.id)},
        )
    )
    # Signed: the schedule of works is frozen and certificates bill it.
    contract.status = "active"
    await session.flush()
    cert = c["certificate"]
    await service.create_progress_claim(
        ProgressClaimCreate(
            contract_id=contract.id,
            claim_number=cert["number"],
            period_start=cert["period_start"],
            period_end=cert["period_end"],
            claim_date=cert["period_end"],
            currency=c["currency"],
        )
    )
    return contract


async def _seed_haul(
    session: AsyncSession, project_id: uuid.UUID, user_id: str, volume_id: uuid.UUID, h: dict[str, Any]
) -> int:
    from app.modules.haul_tickets.models import HaulMaterial, HaulRate  # noqa: PLC0415
    from app.modules.haul_tickets.schemas import InvoiceIn, InvoiceLineIn, TicketCreate  # noqa: PLC0415
    from app.modules.haul_tickets.service import HaulTicketService  # noqa: PLC0415

    m, rate = h["material"], Decimal(str(h["rate_per_load"]))
    session.add(
        HaulMaterial(
            project_id=project_id,
            code=m["code"],
            name=m["name"],
            unit="t",
            haul_type="earthworks",
            density_t_m3=Decimal(str(m["density_t_m3"])),
        )
    )
    session.add(
        HaulRate(
            project_id=project_id,
            haulier_name=h["haulier"],
            material_code=m["code"],
            rate_basis="load",
            rate=rate,
            currency=h["currency"],
        )
    )
    await session.flush()
    service = HaulTicketService(session)
    disposal = await _position(session, project_id, h["offsite_position"])
    fill = await _position(session, project_id, h["internal_position"])
    for t in h["tickets"]:
        internal = t.get("internal", False)
        weighed = t.get("net_t") is not None
        row, _created = await service.create(
            TicketCreate(
                project_id=project_id,
                ticket_number=t["number"],
                haul_type="earthworks",
                direction="internal" if internal else "outbound",
                ticket_date=date.fromisoformat(t["date"]),
                origin=h["origin"],
                origin_kind="site",
                destination=h["internal_destination"] if internal else h["offsite_destination"],
                destination_kind="site" if internal else "dump",
                material_code=m["code"],
                material_name=m["name"],
                unit="t" if weighed else "load",
                net_t=Decimal(str(t["net_t"])) if weighed else None,
                loads=t["loads"],
                haulier_name=h["haulier"],
                plate=t["plate"],
                vehicle_capacity=None if weighed else Decimal(str(h["truck_capacity_m3"])),
                rate_basis="load",
                rate=rate,
                currency=h["currency"],
                boq_position_id=(fill if internal else disposal).id if (fill and disposal) else None,
                survey_volume_id=volume_id,
                receiver_name=h["receiver"],
                signature=DEMO_SIGNATURE,
            ),
            user_id,
        )
        row.status = "verified"
    await session.flush()
    inv = h["invoice"]
    bill = {x["number"]: x for x in h["tickets"]}
    lines = []
    for number, t in bill.items():
        loads = inv["billed_loads"].get(number, t["loads"])
        lines.append(
            InvoiceLineIn(ticket_number=number, quantity=Decimal(loads), rate=rate, amount=rate * Decimal(loads))
        )
    await service.create_invoice(
        InvoiceIn(
            project_id=project_id,
            haulier_name=h["haulier"],
            invoice_number=inv["number"],
            invoice_date=date.fromisoformat(inv["date"]),
            period_from=date.fromisoformat(inv["period_from"]),
            period_to=date.fromisoformat(inv["period_to"]),
            currency=h["currency"],
            lines=lines,
        ),
        user_id,
    )
    return len(h["tickets"])

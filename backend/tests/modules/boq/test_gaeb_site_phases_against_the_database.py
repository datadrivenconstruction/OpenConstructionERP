# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""GAEB X31 apply and X89 claim export, against real rows.

The pure modules are tested on their own; these tests hold the route
functions to what they promise once rows are involved:

* applying confirmed X31 quantities writes a measurement sheet and leaves the
  bill quantity alone unless asked; applying the same file twice writes
  nothing the second time;
* a position id from another bill, or a section row, is refused per item
  and the rest still applies; a stranger gets the same 404 as a missing bill;
  a locked bill refuses the whole apply;
* the X89 of the second claim on a contract bills that claim's period only,
  its item total equals the claim's gross, its VAT is the bill's tax markup,
  and the parties come from the e-invoice settings and the counterparty
  contact. Without a seller address the export refuses with the gaps named.

Every read-back is a fresh SELECT.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.modules.boq.gaeb_exchange_router import (
    X31ApplyItem,
    X31ApplyRequest,
    apply_boq_gaeb_x31,
    export_boq_gaeb_x31,
    export_claim_gaeb_x89,
    preview_claim_gaeb_x89,
)
from app.modules.boq.gaeb_x31 import parse_x31
from app.modules.boq.models import BOQ, BOQMarkup, Position
from app.modules.boq.schemas import PositionCreate
from app.modules.boq.service import BOQService
from app.modules.contacts.models import Contact
from app.modules.contracts.models import Contract, ContractLine, ProgressClaim, ProgressClaimLine
from app.modules.finance.einvoice_settings_models import DEFAULT_SCOPE, EInvoiceSettings
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

NS89 = "{http://www.gaeb.de/GAEB_DA_XML/DA89/3.3}"


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def _user(session) -> User:
    user = User(email=f"gaeb-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x", full_name="Estimator", role="editor")
    session.add(user)
    await session.flush()
    return user


async def _bill(session, owner: User) -> tuple[BOQ, dict[str, Position]]:
    project = Project(name=f"Kita {uuid.uuid4().hex[:6]}", owner_id=owner.id, currency="EUR", country_code="DE")
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name="LV Rohbau", status="draft", metadata_={})
    session.add(boq)
    await session.flush()
    svc = BOQService(session)
    for ordinal, unit, qty, rate in (
        ("01", "section", 0, 0),
        ("01.0010", "m3", 120, 185.5),
        ("01.0020", "t", 10, 1340),
    ):
        await svc.add_position(
            PositionCreate(
                boq_id=boq.id, ordinal=ordinal, description=f"Pos {ordinal}", unit=unit, quantity=qty, unit_rate=rate
            )
        )
    await session.flush()
    rows = (await session.execute(select(Position).where(Position.boq_id == boq.id))).scalars().all()
    return boq, {p.ordinal: p for p in rows}


async def _fresh(session, position_id: uuid.UUID) -> tuple[str, dict]:
    row = (await session.execute(select(Position.quantity, Position.metadata_).where(Position.id == position_id))).one()
    return str(row[0]), dict(row[1] or {})


async def _body(response) -> bytes:
    chunks = [chunk async for chunk in response.body_iterator]
    return b"".join(c if isinstance(c, bytes) else c.encode("utf-8") for c in chunks)


# ── X31 apply ────────────────────────────────────────────────────────────


async def test_apply_writes_a_sheet_keeps_the_bill_quantity_and_is_idempotent(session) -> None:
    owner = await _user(session)
    boq, pos = await _bill(session, owner)
    _other_boq, other = await _bill(session, owner)
    target = pos["01.0010"]
    body = X31ApplyRequest(
        file_name="aufmass.x31",
        items=[
            X31ApplyItem(position_id=target.id, quantity="125.5", oz="01.0010", rows=["row a"]),
            X31ApplyItem(position_id=other["01.0020"].id, quantity="3", oz="01.0020"),
            X31ApplyItem(position_id=pos["01"].id, quantity="1", oz="01"),
        ],
    )
    first = await apply_boq_gaeb_x31(boq.id, str(owner.id), {"role": "editor"}, session, body)
    assert first["applied"] == [str(target.id)]
    assert {e["error"] for e in first["errors"]} == {"position_not_in_boq", "position_is_section"}

    qty, meta = await _fresh(session, target.id)
    assert Decimal(qty) == Decimal("120")
    assert meta["measurement"]["source"] == "gaeb_x31"
    assert meta["measurement"]["lines"][0]["formula"] == "125.500"
    # The other bill's position was not touched.
    _q, other_meta = await _fresh(session, other["01.0020"].id)
    assert "measurement" not in other_meta

    second = await apply_boq_gaeb_x31(boq.id, str(owner.id), {"role": "editor"}, session, body)
    assert second["applied"] == []
    assert second["unchanged"] == [str(target.id)]

    # Asked explicitly, the bill quantity follows.
    body.set_boq_quantity = True
    third = await apply_boq_gaeb_x31(boq.id, str(owner.id), {"role": "editor"}, session, body)
    assert third["applied"] == [str(target.id)]
    qty, _meta = await _fresh(session, target.id)
    assert Decimal(qty) == Decimal("125.5")


async def test_export_reads_back_what_apply_wrote(session) -> None:
    owner = await _user(session)
    boq, pos = await _bill(session, owner)
    with pytest.raises(HTTPException) as nothing:
        await export_boq_gaeb_x31(boq.id, str(owner.id), {"role": "editor"}, session, basis="measured")
    assert nothing.value.status_code == 422

    await apply_boq_gaeb_x31(
        boq.id,
        str(owner.id),
        {"role": "editor"},
        session,
        X31ApplyRequest(items=[X31ApplyItem(position_id=pos["01.0020"].id, quantity="7.25")]),
    )
    response = await export_boq_gaeb_x31(boq.id, str(owner.id), {"role": "editor"}, session, basis="measured")
    assert response.headers["X-GAEB-Written"] == "1"
    parsed = parse_x31(await _body(response))
    assert [(i.oz, i.quantity) for i in parsed.items] == [("01.0020", Decimal("7.250"))]


async def test_a_stranger_and_a_locked_bill_are_refused(session) -> None:
    owner = await _user(session)
    stranger = await _user(session)
    boq, pos = await _bill(session, owner)
    body = X31ApplyRequest(items=[X31ApplyItem(position_id=pos["01.0010"].id, quantity="1")])

    with pytest.raises(HTTPException) as denied:
        await apply_boq_gaeb_x31(boq.id, str(stranger.id), {"role": "editor"}, session, body)
    assert denied.value.status_code == 404

    locked = await session.get(BOQ, boq.id)
    locked.is_locked = True
    await session.flush()
    with pytest.raises(HTTPException) as refused:
        await apply_boq_gaeb_x31(boq.id, str(owner.id), {"role": "editor"}, session, body)
    assert refused.value.status_code == 409
    _qty, meta = await _fresh(session, pos["01.0010"].id)
    assert "measurement" not in meta


# ── X89 from a progress claim ───────────────────────────────────────────


async def _contract_with_two_claims(session, owner: User, *, with_seller: bool = True):
    boq, pos = await _bill(session, owner)
    session.add(
        BOQMarkup(boq_id=boq.id, name="MwSt", category="tax", percentage="19", markup_type="percentage", is_active=True)
    )
    client = Contact(
        contact_type="client",
        company_name="Stadt Musterstadt",
        country_code="DE",
        address={"line1": "Rathausplatz 1", "postcode": "12345", "city": "Musterstadt"},
    )
    session.add(client)
    if with_seller:
        existing = (
            await session.execute(select(EInvoiceSettings).where(EInvoiceSettings.scope == DEFAULT_SCOPE))
        ).scalar_one_or_none()
        settings = existing or EInvoiceSettings(scope=DEFAULT_SCOPE)
        settings.seller_name = "Rohbau Nord GmbH"
        settings.seller_line1 = "Hafenweg 4"
        settings.seller_postcode = "20457"
        settings.seller_city = "Hamburg"
        settings.seller_country_code = "DE"
        settings.seller_vat_id = "DE123456789"
        session.add(settings)
    await session.flush()
    project_id = (await session.execute(select(BOQ.project_id).where(BOQ.id == boq.id))).scalar_one()
    contract = Contract(
        code=f"V-{uuid.uuid4().hex[:6]}",
        title="Rohbau",
        project_id=project_id,
        contract_type="unit_price",
        counterparty_type="client",
        counterparty_id=client.id,
        currency="EUR",
        total_value=Decimal("35680"),
        retention_percent=Decimal("5"),
        status="active",
    )
    session.add(contract)
    await session.flush()
    concrete = ContractLine(
        contract_id=contract.id,
        code="1",
        description="Concrete",
        unit="m3",
        quantity=Decimal("120"),
        unit_rate=Decimal("185.5"),
        total_value=Decimal("22260"),
        order_index=1,
        metadata_={"boq_position_id": str(pos["01.0010"].id)},
    )
    rebar = ContractLine(
        contract_id=contract.id,
        code="2",
        description="Rebar",
        unit="t",
        quantity=Decimal("10"),
        unit_rate=Decimal("1340"),
        total_value=Decimal("13400"),
        order_index=2,
        metadata_={"boq_position_id": str(pos["01.0020"].id)},
    )
    session.add_all([concrete, rebar])
    await session.flush()

    claims = []
    for number, (period_from, period_to), lines, prior in (
        ("AR-1", (date(2026, 8, 1), date(2026, 8, 31)), [(concrete, "40", "7420.00"), (rebar, "3", "4020.00")], {}),
        (
            "AR-2",
            (date(2026, 9, 1), date(2026, 9, 30)),
            [(concrete, "40", "7420.00"), (rebar, "2", "2680.00")],
            {concrete.id: Decimal("7420.00"), rebar.id: Decimal("4020.00")},
        ),
    ):
        gross = sum((Decimal(v) for _l, _q, v in lines), Decimal("0"))
        claim = ProgressClaim(
            contract_id=contract.id,
            claim_number=number,
            period_from=period_from,
            period_to=period_to,
            application_date=period_to,
            currency="EUR",
            gross_amount=gross,
            retention_amount=(gross * Decimal("0.05")).quantize(Decimal("0.01")),
            net_due=gross,
            status="submitted",
        )
        session.add(claim)
        await session.flush()
        for line, qty, value in lines:
            before = prior.get(line.id, Decimal("0"))
            session.add(
                ProgressClaimLine(
                    progress_claim_id=claim.id,
                    contract_line_id=line.id,
                    period_completed_qty=Decimal(qty),
                    period_completed_value=Decimal(value),
                    period_completed_pct=Decimal("0"),
                    prior_completed_value=before,
                    cumulative_completed_value=before + Decimal(value),
                )
            )
        await session.flush()
        claims.append(claim)
    return claims


async def test_the_second_claim_invoices_its_own_period_with_the_bills_vat(session) -> None:
    owner = await _user(session)
    _first, second = await _contract_with_two_claims(session, owner)

    preview = await preview_claim_gaeb_x89(second.id, str(owner.id), session, vat_rate=None, invoice_type="deduction")
    assert preview["missing"] == []
    assert preview["vat_source"] == "boq_tax_markup"
    assert preview["figures"]["net"] == "10100.00"
    assert preview["figures"]["vat_amount"] == "1919.00"
    assert preview["figures"]["gross"] == "12019.00"
    assert preview["recipient"]["name"] == "Stadt Musterstadt"
    assert preview["creator"]["vat_id"] == "DE123456789"

    response = await export_claim_gaeb_x89(second.id, str(owner.id), session, vat_rate=None, invoice_type="deduction")
    root = ET.fromstring(await _body(response))
    amounts = [Decimal(i.findtext(f"{NS89}IT") or "0") for i in root.iter(f"{NS89}Item")]
    # The claim's gross, not the running total of 21540.00 across both claims.
    assert sum(amounts, Decimal("0")) == second.gross_amount == Decimal("10100.00")
    totals = root.find(f"{NS89}Invoice/{NS89}BoQ/{NS89}BoQInfo/{NS89}Totals")
    assert totals is not None
    assert Decimal(totals.findtext(f"{NS89}TotalGross") or "0") == Decimal("12019.00")
    assert [i.findtext(f"{NS89}BillQty") for i in root.iter(f"{NS89}Item")] == ["40.000", "2.000"]
    assert root.findtext(f"{NS89}Invoice/{NS89}InvoiceHeader/{NS89}InvoiceNo") == "AR-2"
    assert root.findtext(f"{NS89}Invoice/{NS89}InvoiceHeader/{NS89}SequentialNo") == "2"


async def test_an_explicit_rate_wins_and_a_missing_seller_is_named(session) -> None:
    owner = await _user(session)
    _first, second = await _contract_with_two_claims(session, owner, with_seller=False)
    settings = (
        await session.execute(select(EInvoiceSettings).where(EInvoiceSettings.scope == DEFAULT_SCOPE))
    ).scalar_one_or_none()
    if settings is not None:
        settings.seller_line1 = ""
        await session.flush()

    preview = await preview_claim_gaeb_x89(
        second.id, str(owner.id), session, vat_rate=Decimal("7"), invoice_type="deduction"
    )
    assert preview["vat_source"] == "request"
    assert preview["figures"]["vat_amount"] == "707.00"
    assert "creator.street" in preview["missing"]

    with pytest.raises(HTTPException) as refused:
        await export_claim_gaeb_x89(second.id, str(owner.id), session, vat_rate=None, invoice_type="deduction")
    assert refused.value.status_code == 422
    assert "creator.street" in refused.value.detail["missing"]


async def test_a_stranger_cannot_read_the_claim(session) -> None:
    owner = await _user(session)
    stranger = await _user(session)
    _first, second = await _contract_with_two_claims(session, owner)
    with pytest.raises(HTTPException) as denied:
        await preview_claim_gaeb_x89(second.id, str(stranger.id), session, vat_rate=None, invoice_type="deduction")
    assert denied.value.status_code in (403, 404)

"""PG: a customer offer is sent, frozen, revised and awarded to a client contract on a real database.

The SQLite suite prices offers from fixtures. This lane stores a project, a priced bill and a
customer, and drives the service through its three state changes: send freezes the figures,
revise opens a lettered draft that supersedes nothing until it is sent, and accept awards the
chosen optional items to a client contract whose milestones add up to the accepted total.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.modules.boq.models import BOQ, Position
from app.modules.contacts.models import Contact
from app.modules.offers.schemas import AcceptRequest, InstalmentIn, OfferCreate, OfferUpdate
from app.modules.offers.service import OfferService
from app.modules.projects.models import Project
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _bill(session):
    tag = uuid.uuid4().hex[:8]
    owner = User(email=f"offer-{tag}@example.test", hashed_password="x", full_name="Offer Owner")
    session.add(owner)
    await session.flush()
    project = Project(name=f"Offer {tag}", owner_id=owner.id, currency="EUR", country_code="DE", locale="de")
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name=f"Bill {tag}")
    session.add(boq)
    await session.flush()
    rows = [
        ("1.1", "Excavation", "m3", "100", "12.50"),
        ("1.2", "Concrete", "m3", "40", "180.00"),
    ]
    for ordinal, description, unit, qty, rate in rows:
        total = str(Decimal(qty) * Decimal(rate))
        session.add(
            Position(
                boq_id=boq.id,
                ordinal=ordinal,
                description=description,
                unit=unit,
                quantity=qty,
                unit_rate=rate,
                total=total,
                sort_order=int(ordinal.split(".")[1]),
            )
        )
    terrace = Position(
        boq_id=boq.id,
        ordinal="1.3",
        description="Terrace",
        unit="m2",
        quantity="10",
        unit_rate="300.00",
        total="3000.00",
        sort_order=3,
        metadata_={"offer_role": "optional"},
    )
    session.add(terrace)
    customer = Contact(
        contact_type="client",
        company_name="Muster GmbH",
        primary_email="kunde@example.test",
        country_code="DE",
        address={"street": "Hauptstr. 1", "postal_code": "10115", "city": "Berlin", "country": "DE"},
    )
    session.add(customer)
    await session.flush()
    return owner, project, boq, customer


async def _ready_offer(session):
    owner, project, boq, customer = await _bill(session)
    service = OfferService(session)
    offer = await service.create(
        OfferCreate(project_id=project.id, boq_id=boq.id, contact_id=customer.id), str(owner.id)
    )
    return service, owner, project, boq, offer


async def test_send_freezes_the_figures_and_a_revision_opens_a_draft(pg_session) -> None:
    service, owner, _project, _boq, offer = await _ready_offer(pg_session)
    assert offer.status == "draft"
    assert offer.revision == "A"
    assert Decimal(offer.totals["net"]) == Decimal("8450.00")

    sent = await service.send(offer.id)
    assert sent.status == "sent"
    assert sent.sent_at is not None

    with pytest.raises(HTTPException) as frozen:
        await service.update(offer.id, OfferUpdate(reference="changed"))
    assert frozen.value.status_code in (409, 422)

    draft = await service.revise(offer.id, str(owner.id))
    assert draft.revision == "B"
    assert draft.status == "draft"
    assert draft.group_id == offer.group_id
    assert draft.number == offer.number

    with pytest.raises(HTTPException) as twice:
        await service.revise(offer.id, str(owner.id))
    assert twice.value.status_code == 409

    resent = await service.send(draft.id)
    assert resent.status == "sent"
    assert (await service.get(offer.id)).status == "superseded"


async def test_accept_awards_the_taken_options_to_a_contract_whose_milestones_add_up(pg_session) -> None:
    service, owner, _project, _boq, offer = await _ready_offer(pg_session)
    plan = [
        InstalmentIn(code="1", name="Deposit", kind="deposit", percent="30", due={"type": "signing"}),
        InstalmentIn(code="2", name="Progress", kind="progress", percent="40", due={"type": "acceptance"}),
        InstalmentIn(code="3", name="Final", kind="final", percent="30", due={"type": "acceptance"}),
    ]
    await service.update(offer.id, OfferUpdate(instalments=plan))
    await service.send(offer.id)

    accepted, contract_id, milestones = await service.accept(
        offer.id, AcceptRequest(optional_ordinals=["1.3"], create_contract=True), str(owner.id)
    )

    assert accepted.status == "accepted"
    assert accepted.accepted_options == ["1.3"]
    assert contract_id is not None
    assert accepted.contract_id == contract_id
    assert milestones == 3
    taken = Decimal(accepted.metadata_["accepted_totals"]["net"])
    assert taken == Decimal("8450.00") + Decimal("3000.00")

    from sqlalchemy import select

    from app.modules.contracts.models import Contract, ContractMilestone

    contract = await pg_session.get(Contract, contract_id)
    assert contract is not None
    rows = (
        (await pg_session.execute(select(ContractMilestone.value).where(ContractMilestone.contract_id == contract_id)))
        .scalars()
        .all()
    )
    assert sum(Decimal(str(v)) for v in rows) == contract.total_value


async def test_accept_without_a_contract_still_records_the_decision(pg_session) -> None:
    service, owner, _project, _boq, offer = await _ready_offer(pg_session)
    await service.send(offer.id)

    accepted, contract_id, milestones = await service.accept(
        offer.id, AcceptRequest(create_contract=False), str(owner.id)
    )

    assert accepted.status == "accepted"
    assert contract_id is None
    assert milestones == 0


async def test_a_draft_cannot_be_accepted(pg_session) -> None:
    service, owner, _project, _boq, offer = await _ready_offer(pg_session)

    with pytest.raises(HTTPException) as err:
        await service.accept(offer.id, AcceptRequest(), str(owner.id))

    assert err.value.status_code == 409

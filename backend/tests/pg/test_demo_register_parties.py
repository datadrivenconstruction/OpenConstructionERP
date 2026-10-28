# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Four registers name a party in prose; each must also point at one.

Purchase orders, contracts, inspections and the punch list each have a column
for the contact they are about, and every one of them was left null. On screen
that is a vendor column of blanks, a contract register whose counterparty is
text, and a punch list reading Unassigned on all ten rows.

The ids are minted by the seeding writer as it goes, so a link can only be read
back from a database; the unit tests beside the generator can check that a seed
row names a role, not that the role became an id. That is what this file is for.

Both demos, because the writer picks the contact list and each register's rows
through separate fallbacks: office-frankfurt takes contacts from the generator,
retail-market-heilbronn has a hand-curated contact list, and a curated list can
hold a different set of roles than the generated one the registers assume.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.demo_projects import DEMO_TEMPLATES, _seed_module_data
from app.modules.contacts.models import Contact
from app.modules.contracts.models import Contract
from app.modules.inspections.models import QualityInspection
from app.modules.procurement.models import PurchaseOrder
from app.modules.projects.models import Project
from app.modules.punchlist.models import PunchItem
from app.modules.users.models import User

_DEMOS = ["office-frankfurt", "retail-market-heilbronn"]


async def _seeded_project(session, demo_id: str) -> uuid.UUID:
    owner = User(
        email=f"parties-{uuid.uuid4().hex[:8]}@example.test",
        hashed_password="x",
        full_name="Register Parties Owner",
    )
    session.add(owner)
    await session.flush()

    project = Project(name=f"Registers for {demo_id}", owner_id=owner.id)
    session.add(project)
    await session.flush()

    await _seed_module_data(session, project.id, owner.id, demo_id, DEMO_TEMPLATES[demo_id])
    await session.flush()
    return project.id


async def _contact_roles(session, project_id: uuid.UUID) -> dict[str, str]:
    """Role of each contact this project seeded, keyed by id as stored."""
    rows = (await session.execute(select(Contact.id, Contact.contact_type, Contact.metadata_))).all()
    return {str(cid): ctype for cid, ctype, meta in rows if (meta or {}).get("project_id") == str(project_id)}


@pytest.mark.parametrize("demo_id", _DEMOS)
async def test_a_purchase_order_points_at_the_firm_it_is_with(pg_session, demo_id: str) -> None:
    project_id = await _seeded_project(pg_session, demo_id)
    roles = await _contact_roles(pg_session, project_id)
    orders = (
        (await pg_session.execute(select(PurchaseOrder).where(PurchaseOrder.project_id == project_id))).scalars().all()
    )
    assert orders, f"{demo_id} seeded no purchase orders, so this would pass on nothing"

    linked = [po for po in orders if po.vendor_contact_id]
    assert linked, f"{demo_id}: every purchase order has an empty vendor column"
    for po in linked:
        assert po.vendor_contact_id in roles, f"{po.po_number} points at a contact this project did not seed"


@pytest.mark.parametrize("demo_id", _DEMOS)
async def test_every_contract_points_at_its_counterparty(pg_session, demo_id: str) -> None:
    """This register can be checked in full: every contract has a party to name."""
    project_id = await _seeded_project(pg_session, demo_id)
    roles = await _contact_roles(pg_session, project_id)
    contracts = (await pg_session.execute(select(Contract).where(Contract.project_id == project_id))).scalars().all()
    assert contracts, f"{demo_id} seeded no contracts, so this would pass on nothing"

    for contract in contracts:
        assert contract.counterparty_id is not None, f"{contract.code} names a counterparty it does not link to"
        assert str(contract.counterparty_id) in roles, f"{contract.code} points at a contact this project did not seed"

    # The subcontracts are one per firm and must not collapse onto one contact,
    # which is what a lookup without a position would have done while their
    # titles went on naming three different companies.
    subs = [c for c in contracts if c.counterparty_type == "subcontractor"]
    if len(subs) > 1:
        assert len({str(c.counterparty_id) for c in subs}) == len(subs), (
            f"{demo_id}: {len(subs)} subcontracts share fewer counterparties than they have titles"
        )


@pytest.mark.parametrize("demo_id", _DEMOS)
async def test_an_inspection_records_who_carried_it_out(pg_session, demo_id: str) -> None:
    project_id = await _seeded_project(pg_session, demo_id)
    roles = await _contact_roles(pg_session, project_id)
    inspections = (
        (await pg_session.execute(select(QualityInspection).where(QualityInspection.project_id == project_id)))
        .scalars()
        .all()
    )
    assert inspections, f"{demo_id} seeded no inspections, so this would pass on nothing"

    linked = [i for i in inspections if i.inspector_id]
    assert linked, f"{demo_id}: no inspection records an inspector"
    for inspection in linked:
        assert str(inspection.inspector_id) in roles, (
            f"{inspection.inspection_number} points at a contact this project did not seed"
        )


@pytest.mark.parametrize("demo_id", _DEMOS)
async def test_the_punch_list_is_not_unassigned_throughout(pg_session, demo_id: str) -> None:
    """Ten rows reading Unassigned is the whole defect, so this checks all of them."""
    project_id = await _seeded_project(pg_session, demo_id)
    roles = await _contact_roles(pg_session, project_id)
    items = (await pg_session.execute(select(PunchItem).where(PunchItem.project_id == project_id))).scalars().all()
    assert items, f"{demo_id} seeded no punch items, so this would pass on nothing"

    for item in items:
        assert item.assigned_to, f"{item.title!r} is unassigned"
        assert item.assigned_to in roles, f"{item.title!r} is assigned to a contact this project did not seed"

    # An item nobody has closed cannot have been verified by anybody.
    for item in items:
        if item.status not in ("closed", "verified"):
            assert not item.verified_by, f"{item.title!r} is open and already carries a verifier"

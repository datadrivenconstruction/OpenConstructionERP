# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: the contract an award drafts names a real firm, and every award drafts one.

Three gaps between the award and the contract it turns into, each written as a
failing control before the fix:

* The bid_management award set ``Contract.counterparty_id`` to the bidder row,
  a snapshot no contracts or finance reader resolves, so the counterparty
  never had a name and finance copied the bidder id into the invoice contact.
  A bidder now carries the directory entry it was invited from, and the award
  maps that onto the contract. A bidder typed in by hand maps to no
  counterparty at all, with its free-text company on the contract party.
* The award deduplicated on the code ``CONTRACT-{package code}``, so a contract
  someone had typed with that code swallowed the award without a word.
* ``tendering.package.awarded`` drafted a purchase order and no contract.

Scope lines added from the bill keep their position, and the award carries it
onto the contract line, where the contracts progress bridge reads it.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.modules.bid_management import events as bm_events
from app.modules.bid_management.models import Bidder, BidPackage, BidPackageLineItem
from app.modules.bid_management.schemas import BidderCreate, BidPackageLinesFromBOQ
from app.modules.bid_management.service import BidManagementService
from app.modules.boq.models import BOQ, Position
from app.modules.contacts.models import Contact
from app.modules.contracts.models import Contract, ContractLine, ContractParty
from app.modules.contracts.service import ContractsService
from app.modules.notifications import _wave5_cross_module_subscribers as w5
from app.modules.procurement.models import PurchaseOrder
from app.modules.projects.models import Project
from app.modules.subcontractors.models import Subcontractor
from app.modules.tendering.models import TenderBid, TenderPackage
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


class _NonCommittingSession:
    """The real session with ``commit`` demoted to ``flush``.

    The subscribers open their own session and commit, which is right in
    production and fatal to a test that keeps its rows inside a transaction it
    means to roll back.
    """

    def __init__(self, inner) -> None:
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    async def commit(self) -> None:
        await self._inner.flush()

    async def close(self) -> None:
        return None

    async def __aenter__(self) -> _NonCommittingSession:
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False


async def _project(session) -> Project:
    owner = User(email=f"award-{uuid.uuid4().hex[:8]}@example.test", hashed_password="x", full_name="Owner")
    session.add(owner)
    await session.flush()
    project = Project(name="Award links", owner_id=owner.id)
    session.add(project)
    await session.flush()
    return project


async def _bid_package(session, project, **kw) -> BidPackage:
    package = BidPackage(
        project_id=project.id, code=f"BP-{uuid.uuid4().hex[:8]}", title="Concrete", currency="EUR", **kw
    )
    session.add(package)
    await session.flush()
    return package


async def _directory_sub(session, *, with_contact: bool = True) -> tuple[Subcontractor, Contact | None]:
    contact = None
    if with_contact:
        contact = Contact(contact_type="subcontractor", company_name="Rheinbeton GmbH")
        session.add(contact)
        await session.flush()
    sub = Subcontractor(legal_name="Rheinbeton GmbH", contact_id=contact.id if contact else None)
    session.add(sub)
    await session.flush()
    return sub, contact


async def _award_bid_package(session, monkeypatch, package, bidder) -> None:
    monkeypatch.setattr(w5, "async_session_factory", lambda: _NonCommittingSession(session))
    await w5._on_bid_package_awarded(
        w5.Event(
            name="bid_management.package.awarded",
            data={
                "package_id": str(package.id),
                "project_id": str(package.project_id),
                "awarded_bidder_id": str(bidder.id),
                "awarded_amount": "95000.00",
                "currency": "EUR",
            },
            source_module="bid_management",
        )
    )


async def _award_contracts(session, project) -> list[Contract]:
    rows = await session.execute(select(Contract).where(Contract.project_id == project.id))
    return list(rows.scalars().all())


# ── X4: the counterparty ────────────────────────────────────────────────


async def test_a_directory_bidder_becomes_a_counterparty_contracts_can_name(pg_session, monkeypatch) -> None:
    project = await _project(pg_session)
    package = await _bid_package(pg_session, project)
    sub, contact = await _directory_sub(pg_session)
    bidder = await BidManagementService(pg_session).create_bidder(
        BidderCreate(package_id=package.id, company_name="Rheinbeton", subcontractor_id=sub.id)
    )
    # The contact is derived from the subcontractor, not typed twice.
    assert bidder.contact_id == contact.id

    await _award_bid_package(pg_session, monkeypatch, package, bidder)

    [contract] = await _award_contracts(pg_session, project)
    assert contract.counterparty_id == sub.id, (
        f"counterparty is {contract.counterparty_id}, the bidder row is {bidder.id}"
    )
    assert await ContractsService(pg_session).resolve_counterparty_name(contract) == "Rheinbeton GmbH"
    assert contract.metadata_["counterparty_contact_id"] == str(contact.id)
    [party] = (
        (await pg_session.execute(select(ContractParty).where(ContractParty.contract_id == contract.id)))
        .scalars()
        .all()
    )
    assert (party.party_type, party.party_id, party.is_primary) == ("subcontractor", sub.id, True)


async def test_a_contact_only_bidder_names_the_contact(pg_session, monkeypatch) -> None:
    project = await _project(pg_session)
    package = await _bid_package(pg_session, project)
    contact = Contact(contact_type="subcontractor", company_name="Kranbau AG")
    pg_session.add(contact)
    await pg_session.flush()
    bidder = await BidManagementService(pg_session).create_bidder(
        BidderCreate(package_id=package.id, company_name="Kranbau", contact_id=contact.id)
    )

    await _award_bid_package(pg_session, monkeypatch, package, bidder)

    [contract] = await _award_contracts(pg_session, project)
    assert contract.counterparty_id == contact.id
    assert await ContractsService(pg_session).resolve_counterparty_name(contract) == "Kranbau AG"


async def test_a_hand_typed_bidder_never_puts_its_own_id_on_the_contract(pg_session, monkeypatch) -> None:
    project = await _project(pg_session)
    package = await _bid_package(pg_session, project)
    bidder = Bidder(package_id=package.id, company_name="ACME Bau GmbH", status="active")
    pg_session.add(bidder)
    await pg_session.flush()

    await _award_bid_package(pg_session, monkeypatch, package, bidder)

    [contract] = await _award_contracts(pg_session, project)
    assert contract.counterparty_id is None, f"the bidder row {bidder.id} leaked onto the contract"
    [party] = (
        (await pg_session.execute(select(ContractParty).where(ContractParty.contract_id == contract.id)))
        .scalars()
        .all()
    )
    assert (party.party_type, party.party_id, party.display_name) == ("external", None, "ACME Bau GmbH")


async def test_a_bidder_link_to_nothing_is_refused(pg_session) -> None:
    project = await _project(pg_session)
    package = await _bid_package(pg_session, project)
    with pytest.raises(HTTPException) as exc:
        await BidManagementService(pg_session).create_bidder(
            BidderCreate(package_id=package.id, company_name="Ghost", subcontractor_id=uuid.uuid4())
        )
    assert exc.value.status_code == 400


async def test_a_hand_made_contract_with_the_award_code_does_not_swallow_the_award(
    pg_session, monkeypatch, caplog
) -> None:
    project = await _project(pg_session)
    package = await _bid_package(pg_session, project)
    manual = Contract(
        code=f"CONTRACT-{package.code}", title="Typed by hand", project_id=project.id, status="draft", terms={}
    )
    pg_session.add(manual)
    bidder = Bidder(package_id=package.id, company_name="ACME Bau GmbH", status="active")
    pg_session.add(bidder)
    await pg_session.flush()

    with caplog.at_level(logging.WARNING):
        await _award_bid_package(pg_session, monkeypatch, package, bidder)

    contracts = await _award_contracts(pg_session, project)
    drafted = [c for c in contracts if (c.metadata_ or {}).get("bid_package_id") == str(package.id)]
    assert len(contracts) == 2 and len(drafted) == 1, f"award drafted {len(drafted)} contract(s)"
    assert drafted[0].code == f"CONTRACT-{package.code}-2"
    assert any("already used" in r.getMessage() for r in caplog.records)


async def test_refiring_the_award_drafts_one_contract(pg_session, monkeypatch) -> None:
    project = await _project(pg_session)
    package = await _bid_package(pg_session, project)
    bidder = Bidder(package_id=package.id, company_name="ACME Bau GmbH", status="active")
    pg_session.add(bidder)
    await pg_session.flush()

    await _award_bid_package(pg_session, monkeypatch, package, bidder)
    await _award_bid_package(pg_session, monkeypatch, package, bidder)

    assert len(await _award_contracts(pg_session, project)) == 1


# ── X6: scope lines from the bill ───────────────────────────────────────


async def _boq(session, project, positions: list[tuple[str, str, str, str]]) -> list[Position]:
    boq = BOQ(project_id=project.id, name="Bill")
    session.add(boq)
    await session.flush()
    made = []
    for ordinal, description, unit, qty in positions:
        pos = Position(boq_id=boq.id, ordinal=ordinal, description=description, unit=unit, quantity=qty)
        session.add(pos)
        made.append(pos)
    await session.flush()
    return made


async def test_scope_lines_from_the_bill_reach_the_contract_line(pg_session, monkeypatch) -> None:
    project = await _project(pg_session)
    package = await _bid_package(pg_session, project)
    section, wall, slab = await _boq(
        pg_session,
        project,
        [("01", "Concrete", "", "0"), ("01.001", "Wall C30/37", "m3", "12.5"), ("01.002", "Slab", "m2", "80")],
    )
    svc = BidManagementService(pg_session)

    added = await svc.add_lines_from_boq(
        package.id, BidPackageLinesFromBOQ(position_ids=[section.id, wall.id, slab.id])
    )
    assert [(li.code, li.boq_position_id, Decimal(str(li.quantity))) for li in added] == [
        ("01.001", wall.id, Decimal("12.5")),
        ("01.002", slab.id, Decimal("80")),
    ], "the section header is skipped, the priced positions are copied with their link"
    # Adding the same selection again adds nothing.
    assert await svc.add_lines_from_boq(package.id, BidPackageLinesFromBOQ(position_ids=[wall.id])) == []

    bidder = Bidder(package_id=package.id, company_name="ACME Bau GmbH", status="active")
    pg_session.add(bidder)
    await pg_session.flush()
    await _award_bid_package(pg_session, monkeypatch, package, bidder)

    [contract] = await _award_contracts(pg_session, project)
    lines = (
        (await pg_session.execute(select(ContractLine).where(ContractLine.contract_id == contract.id))).scalars().all()
    )
    assert sorted((ln.metadata_ or {}).get("boq_position_id") for ln in lines) == sorted([str(wall.id), str(slab.id)])


async def test_a_position_from_another_project_is_refused(pg_session) -> None:
    project = await _project(pg_session)
    other = await _project(pg_session)
    package = await _bid_package(pg_session, project)
    [foreign] = await _boq(pg_session, other, [("09.001", "Elsewhere", "m", "1")])

    with pytest.raises(HTTPException) as exc:
        await BidManagementService(pg_session).add_lines_from_boq(
            package.id, BidPackageLinesFromBOQ(position_ids=[foreign.id])
        )
    assert exc.value.status_code == 400
    count = await pg_session.execute(
        select(func.count()).select_from(BidPackageLineItem).where(BidPackageLineItem.package_id == package.id)
    )
    assert count.scalar_one() == 0


# ── X5: a tender award drafts a contract ────────────────────────────────


async def _tender_award(session, project, *, sub: Subcontractor | None = None, status: str = "awarded"):
    wall, slab = await _boq(session, project, [("02.001", "Wall", "m3", "10"), ("02.002", "Slab", "m2", "5")])
    [foreign] = await _boq(session, await _project(session), [("99", "Foreign", "m", "1")])
    recipients = []
    if sub is not None:
        recipients.append({"email": "Bids@Rheinbeton.test", "subcontractor_id": str(sub.id)})
    package = TenderPackage(
        project_id=project.id,
        boq_id=wall.boq_id,
        name="Shell works",
        status=status,
        metadata_={"recipients": recipients},
    )
    session.add(package)
    await session.flush()
    bid = TenderBid(
        package_id=package.id,
        company_name="Rheinbeton",
        contact_email="bids@rheinbeton.test",
        total_amount="1500",
        currency="EUR",
        status="accepted",
        line_items=[
            {"position_id": str(wall.id), "description": "Wall", "unit": "m3", "quantity": 10, "unit_rate": "100"},
            {"position_id": str(slab.id), "description": "Slab", "unit": "m2", "quantity": 5, "unit_rate": "60"},
            {"position_id": str(foreign.id), "description": "Stray", "unit": "m", "quantity": 1, "unit_rate": "200"},
        ],
    )
    session.add(bid)
    await session.flush()
    return package, bid, wall, slab


async def _fire_tender(session, monkeypatch, package, bid) -> None:
    monkeypatch.setattr(bm_events, "async_session_factory", lambda: _NonCommittingSession(session))
    await bm_events._draft_contract_from_tender_award(
        bm_events.Event(
            name="tendering.package.awarded",
            data={"package_id": str(package.id), "bid_id": str(bid.id)},
            source_module="oe_tendering",
        )
    )


_LOADER_PROBE = """
import asyncio
from fastapi import FastAPI
from app.core.events import event_bus
from app.core.module_loader import ModuleLoader

loader = ModuleLoader()
loader.discover()
asyncio.run(loader._load_module("oe_bid_management", FastAPI()))
names = [f"{h.__module__}.{h.__name__}" for h in event_bus._handlers.get("tendering.package.awarded", [])]
print("HANDLERS=" + ",".join(names))
"""


async def test_the_module_loader_subscribes_the_tender_award_handler() -> None:
    """Calling the handler directly proves nothing if the bus never calls it.

    This file imports ``bm_events`` itself, which registers the handler, so an
    in-process check would pass whether or not the loader ever imports
    ``events.py``. A clean interpreter that only runs the loader's own load of
    the module is the honest question. The loader suppresses
    ``ModuleNotFoundError`` from ``events.py``, so a broken import there would
    otherwise drop the contract draft silently.
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(backend), env.get("PYTHONPATH", "")) if p)
    env.setdefault("DATABASE_URL", "postgresql+asyncpg://probe:probe@127.0.0.1:59999/probe")
    env.setdefault("DATABASE_SYNC_URL", "postgresql+psycopg://probe:probe@127.0.0.1:59999/probe")
    done = subprocess.run(
        [sys.executable, "-c", _LOADER_PROBE],
        cwd=backend,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    line = next((ln for ln in done.stdout.splitlines() if ln.startswith("HANDLERS=")), None)
    assert line is not None, f"the probe did not run: rc={done.returncode}\n{done.stderr[-3000:]}"
    assert "app.modules.bid_management.events._on_tender_awarded" in line.split("=", 1)[1].split(","), line


async def test_a_tender_award_drafts_a_contract_with_its_bill_links(pg_session, monkeypatch) -> None:
    project = await _project(pg_session)
    sub, _contact = await _directory_sub(pg_session)
    package, bid, wall, slab = await _tender_award(pg_session, project, sub=sub)

    await _fire_tender(pg_session, monkeypatch, package, bid)
    await _fire_tender(pg_session, monkeypatch, package, bid)

    contracts = await _award_contracts(pg_session, project)
    assert len(contracts) == 1, f"{len(contracts)} contracts for one tender award"
    [contract] = contracts
    assert contract.metadata_["tender_package_id"] == str(package.id)
    assert contract.counterparty_id == sub.id
    assert contract.total_value == Decimal("1500")
    lines = (
        (
            await pg_session.execute(
                select(ContractLine).where(ContractLine.contract_id == contract.id).order_by(ContractLine.order_index)
            )
        )
        .scalars()
        .all()
    )
    assert [(ln.metadata_ or {}).get("boq_position_id") for ln in lines] == [str(wall.id), str(slab.id), None]
    assert all(ln.cost_line_id is None for ln in lines), "the purchase order carries the cost line, not the contract"
    # The contract handler raises no purchase order of its own.
    po_count = await pg_session.execute(
        select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.project_id == project.id)
    )
    assert po_count.scalar_one() == 0


async def test_an_event_for_a_package_that_is_not_awarded_drafts_nothing(pg_session, monkeypatch) -> None:
    """The status guard: a replayed or stray event is not an award."""
    project = await _project(pg_session)
    package, bid, _wall, _slab = await _tender_award(pg_session, project, status="evaluating")

    await _fire_tender(pg_session, monkeypatch, package, bid)

    assert await _award_contracts(pg_session, project) == []


def _capture_publishes(monkeypatch) -> list[str]:
    from app.core.events import event_bus

    names: list[str] = []
    monkeypatch.setattr(event_bus, "publish_detached", lambda name, *_a, **_kw: names.append(name))
    return names


async def test_a_committed_tender_award_publishes(pg_session, monkeypatch) -> None:
    """Control for the rollback test below: the same award, committed, does publish."""
    from app.modules.tendering.service import TenderingService

    project = await _project(pg_session)
    package, bid, _wall, _slab = await _tender_award(pg_session, project, status="evaluating")
    bid.status = "submitted"
    await pg_session.flush()
    names = _capture_publishes(monkeypatch)

    await TenderingService(pg_session).apply_winner(package.id, bid.id)
    assert "tendering.package.awarded" not in names, "published before the commit"
    await pg_session.commit()

    assert "tendering.package.awarded" in names


async def test_a_rolled_back_tender_award_publishes_nothing(pg_engine, monkeypatch) -> None:
    """No event, so neither the purchase order nor the contract subscriber ever runs."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.modules.tendering.service import TenderingService

    async with async_sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)() as session:
        project = await _project(session)
        package, bid, _wall, _slab = await _tender_award(session, project, status="evaluating")
        bid.status = "submitted"
        await session.flush()
        names = _capture_publishes(monkeypatch)

        await TenderingService(session).apply_winner(package.id, bid.id)
        await session.rollback()

    assert "tendering.package.awarded" not in names, names


# ── Boot repair: contracts drafted before the bidder links existed ──────


async def _legacy_award_contract(session, project, bidder: Bidder) -> Contract:
    """The shape the award subscriber wrote before 18.1: the bidder row as counterparty."""
    contract = Contract(
        code=f"CONTRACT-OLD-{uuid.uuid4().hex[:6]}",
        title="Old award",
        counterparty_type="subcontractor",
        counterparty_id=bidder.id,
        project_id=project.id,
        status="draft",
        terms={},
    )
    contract.metadata_ = {
        "source": "bid_management.package.awarded",
        "bid_package_id": str(bidder.package_id),
        "awarded_bidder_id": str(bidder.id),
        "awarded_bidder_name": bidder.company_name,
    }
    session.add(contract)
    await session.flush()
    return contract


async def _parties(session, contract) -> list[tuple[str, uuid.UUID | None, str]]:
    rows = await session.execute(select(ContractParty).where(ContractParty.contract_id == contract.id))
    return [(p.party_type, p.party_id, p.display_name) for p in rows.scalars().all()]


async def test_the_boot_repair_repoints_old_award_contracts_once(pg_session) -> None:
    from app.modules.bid_management.award_contract import repair_bidder_counterparties

    project = await _project(pg_session)
    package = await _bid_package(pg_session, project)
    sub, contact = await _directory_sub(pg_session)
    linked = Bidder(package_id=package.id, company_name="Rheinbeton", subcontractor_id=sub.id, contact_id=contact.id)
    typed = Bidder(package_id=package.id, company_name="ACME Bau GmbH")
    pg_session.add_all([linked, typed])
    await pg_session.flush()
    linked_contract = await _legacy_award_contract(pg_session, project, linked)
    typed_contract = await _legacy_award_contract(pg_session, project, typed)
    # A counterparty someone set by hand since is not the defect and stays.
    hand_set = await _legacy_award_contract(pg_session, project, typed)
    hand_set.counterparty_id = sub.id
    await pg_session.flush()

    assert await repair_bidder_counterparties(pg_session) == 2

    assert linked_contract.counterparty_id == sub.id
    assert linked_contract.metadata_["counterparty_contact_id"] == str(contact.id)
    assert await _parties(pg_session, linked_contract) == [("subcontractor", sub.id, "Rheinbeton")]
    assert typed_contract.counterparty_id is None
    assert await _parties(pg_session, typed_contract) == [("external", None, "ACME Bau GmbH")]
    assert hand_set.counterparty_id == sub.id and await _parties(pg_session, hand_set) == []

    # A second boot changes nothing.
    assert await repair_bidder_counterparties(pg_session) == 0
    assert len(await _parties(pg_session, linked_contract)) == 1
    assert len(await _parties(pg_session, typed_contract)) == 1


async def test_the_boot_repair_is_registered() -> None:
    from app.core.data_repairs import discover_data_repairs

    assert "bid_award_contract_counterparty" in {r.repair_id for r in discover_data_repairs()}


@pytest.mark.parametrize("tender_first", [True, False])
async def test_both_award_paths_for_one_award_draft_one_contract(pg_session, monkeypatch, tender_first) -> None:
    project = await _project(pg_session)
    package, bid, _wall, _slab = await _tender_award(pg_session, project)
    bid_package = await _bid_package(pg_session, project, tender_id=package.id)
    bidder = Bidder(package_id=bid_package.id, company_name="Rheinbeton", status="active")
    pg_session.add(bidder)
    await pg_session.flush()

    if tender_first:
        await _fire_tender(pg_session, monkeypatch, package, bid)
        await _award_bid_package(pg_session, monkeypatch, bid_package, bidder)
    else:
        await _award_bid_package(pg_session, monkeypatch, bid_package, bidder)
        await _fire_tender(pg_session, monkeypatch, package, bid)

    assert len(await _award_contracts(pg_session, project)) == 1

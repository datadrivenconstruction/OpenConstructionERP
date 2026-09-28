# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A punch item can belong to one contract, and retention reads that.

Before this, a punch item carried a project and nothing else, so on a project
with several contracts each contract's retention release withheld for every
open item on the project. The attribution is optional: an item attributed to
no contract is the project's, and it stays in every contract's withholding
exactly as before. Only an item attributed to another contract drops out, so
the figure can shrink as items are attributed and never grow. Splitting the
project's items across contracts by value was rejected on purpose - it would
invent an allocation and print it on a certificate.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.modules.contracts.models import Contract, ContractLine, ProgressClaim
from app.modules.contracts.schemas import AutoGenerateClaimRequest
from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.projects.models import Project
from app.modules.punchlist.models import PunchItem
from app.modules.punchlist.schemas import PunchItemCreate, PunchItemUpdate
from app.modules.punchlist.service import PunchListService
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio

OWNER_ID = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    register_contracts_validation_rules()
    async with transactional_session() as s:
        s.add(User(id=OWNER_ID, email=f"punch-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x"))
        await s.flush()
        yield s


async def _project(session) -> Project:
    project = Project(id=uuid.uuid4(), name="Punch", owner_id=OWNER_ID, currency="USD", country_code="US")
    session.add(project)
    await session.flush()
    return project


async def _contract(session, project: Project, title: str) -> Contract:
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{uuid.uuid4().hex[:8]}",
        title=title,
        project_id=project.id,
        contract_type="lump_sum",
        currency="USD",
        total_value=Decimal("100000"),
        retention_percent=Decimal("10"),
        status="active",
    )
    session.add(contract)
    await session.flush()
    line = ContractLine(
        id=uuid.uuid4(),
        contract_id=contract.id,
        code="A",
        description="Line A",
        quantity=Decimal("1"),
        unit_rate=Decimal("100000"),
        total_value=Decimal("100000"),
        order_index=0,
    )
    session.add(line)
    await session.flush()
    contract.line = line  # type: ignore[attr-defined]
    return contract


@pytest_asyncio.fixture
async def world(session):
    project = await _project(session)
    main = await _contract(session, project, "Main works")
    fitout = await _contract(session, project, "Fit-out")
    return SimpleNamespace(project=project, main=main, fitout=fitout)


def _create(project: Project, title: str, **fields) -> PunchItemCreate:
    return PunchItemCreate(project_id=project.id, title=title, rework_cost="1000", rework_cost_currency="USD", **fields)


async def test_an_item_can_be_attributed_to_a_contract_on_its_project(session, world) -> None:
    svc = PunchListService(session)
    item = await svc.create_item(_create(world.project, "Door closer", contract_id=world.main.id))
    assert item.contract_id == str(world.main.id)

    # Moved to the other contract, then taken off again.
    item = await svc.update_item(item.id, PunchItemUpdate(contract_id=world.fitout.id))
    assert item.contract_id == str(world.fitout.id)
    item = await svc.update_item(item.id, PunchItemUpdate(contract_id=None))
    assert item.contract_id is None


async def test_an_item_left_unattributed_stays_unattributed(session, world) -> None:
    item = await PunchListService(session).create_item(_create(world.project, "Scuffed wall"))
    assert item.contract_id is None


async def test_a_contract_on_another_project_is_refused(session, world) -> None:
    elsewhere = await _contract(session, await _project(session), "Elsewhere")
    svc = PunchListService(session)
    with pytest.raises(HTTPException) as refused:
        await svc.create_item(_create(world.project, "Door closer", contract_id=elsewhere.id))
    assert refused.value.status_code == 422
    assert refused.value.detail["error"] == "contract_not_on_project"

    item = await svc.create_item(_create(world.project, "Door closer"))
    with pytest.raises(HTTPException) as refused:
        await svc.update_item(item.id, PunchItemUpdate(contract_id=elsewhere.id))
    assert refused.value.detail["error"] == "contract_not_on_project"
    with pytest.raises(HTTPException):
        await svc.update_item(item.id, PunchItemUpdate(contract_id=uuid.uuid4()))


async def test_the_list_filters_by_contract_and_by_what_is_still_open(session, world) -> None:
    svc = PunchListService(session)
    main_open = await svc.create_item(_create(world.project, "Main open", contract_id=world.main.id))
    main_closed = await svc.create_item(_create(world.project, "Main closed", contract_id=world.main.id))
    await svc.repo.update_fields(main_closed.id, status="closed")
    fitout = await svc.create_item(_create(world.project, "Fit-out", contract_id=world.fitout.id))
    loose = await svc.create_item(_create(world.project, "Loose"))

    def ids(rows) -> set:
        return {row.id for row in rows}

    rows, total = await svc.list_items(world.project.id, contract_filter=str(world.main.id))
    assert (ids(rows), total) == ({main_open.id, main_closed.id}, 2)
    rows, total = await svc.list_items(world.project.id, contract_filter=str(world.main.id), open_only=True)
    assert (ids(rows), total) == ({main_open.id}, 1)
    rows, _ = await svc.list_items(world.project.id, contract_filter="none")
    assert ids(rows) == {loose.id}
    rows, _ = await svc.list_items(world.project.id)
    assert ids(rows) == {main_open.id, main_closed.id, fitout.id, loose.id}


async def _held(session, svc: ContractsService, contract: Contract) -> None:
    claim = ProgressClaim(
        id=uuid.uuid4(),
        contract_id=contract.id,
        claim_number="PC-1",
        period_start="2026-01-01",
        period_end="2026-01-28",
        period_from=date(2026, 1, 1),
        period_to=date(2026, 1, 28),
        currency="USD",
        status="draft",
    )
    session.add(claim)
    await session.flush()
    await svc.auto_generate_claim_lines(
        claim.id, AutoGenerateClaimRequest(completion={str(contract.line.id): Decimal("50")})
    )
    await svc.claim_repo.update_fields(claim.id, status="approved")


def _preview_request() -> SimpleNamespace:
    return SimpleNamespace(event="substantial_completion", amount=None, open_items_value=None)


async def test_with_nothing_attributed_the_withholding_is_what_it_always_was(session, world) -> None:
    svc = ContractsService(session)
    await _held(session, svc, world.main)
    for title in ("Door closer", "Paint touch-up"):
        session.add(
            PunchItem(
                project_id=world.project.id, title=title, status="open", rework_cost="1000", rework_cost_currency="USD"
            )
        )
    await session.flush()

    preview = await svc.preview_retention_release(world.main.id, _preview_request())
    assert (preview["open_items_count"], preview["open_items_elsewhere"]) == (2, 0)
    assert preview["withheld_for_open_items"] == Decimal("3000.00")


async def test_an_item_attributed_to_another_contract_is_not_withheld_here(session, world) -> None:
    svc = ContractsService(session)
    await _held(session, svc, world.main)
    punch = PunchListService(session)
    await punch.create_item(_create(world.project, "Main's own", contract_id=world.main.id))
    await punch.create_item(_create(world.project, "The project's"))
    await punch.create_item(_create(world.project, "Fit-out's", contract_id=world.fitout.id))

    preview = await svc.preview_retention_release(world.main.id, _preview_request())
    # Its own item and the unattributed one; the fit-out item is counted apart.
    assert (preview["open_items_count"], preview["open_items_elsewhere"]) == (2, 1)
    assert preview["withheld_for_open_items"] == Decimal("3000.00")


async def test_an_attribution_to_a_deleted_contract_counts_as_none(session, world) -> None:
    svc = ContractsService(session)
    await _held(session, svc, world.main)
    await PunchListService(session).create_item(_create(world.project, "Orphan", contract_id=world.fitout.id))
    await session.delete(world.fitout)
    await session.flush()

    preview = await svc.preview_retention_release(world.main.id, _preview_request())
    assert (preview["open_items_count"], preview["open_items_elsewhere"]) == (1, 0)

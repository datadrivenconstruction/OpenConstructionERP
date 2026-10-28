# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Promoting a request over HTTP must commit the figures it was approved on.

The service carries a request's own figures into the order for anything the
caller left unnamed, but the route used to name every field itself, so the
carry-forward never fired on the only path a user can reach. The variations
page sends a currency and nothing else, which meant every order promoted
through the interface was created valued at zero, and the change order
mirroring it was priced off the same nothing.

These tests drive the route handler rather than the service, because that is
where the defect lived and where nothing was asserting anything: no test in
the tree touched ``convert-to-vo`` at all. The handler is called directly with
its dependencies supplied, so what is exercised is the body it accepts and the
payload it builds. The permission dependency in front of it does not run this
way and is not covered here.

The invariant worth keeping is that the amount the high-value gate is applied
to and the amount the order ends up carrying are the same amount. It is
asserted from both sides below: a caller who may not approve that figure is
refused, and a caller who may sees exactly that figure committed.

PostgreSQL, py3.12 - needs the app plus a database.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.changeorders.models import ChangeOrder
from app.modules.contracts.models import Contract
from app.modules.projects.models import Project
from app.modules.users.models import User
from app.modules.variations.models import VariationOrder
from app.modules.variations.router import _ConvertVOBody, convert_vr_to_vo
from app.modules.variations.schemas import VariationRequestCreate
from app.modules.variations.service import VariationsService
from tests._pg import transactional_session

#: What the request is approved on. Above HIGH_VALUE_APPROVAL_THRESHOLD
#: (100_000) so the same figure can be read from the authorisation gate as
#: well as from the order, which is the point of the pairing below.
ESTIMATE = Decimal("250000.75")
ESTIMATE_DAYS = 21
TITLE = "Piling redesign after ground survey"

#: A caller who may promote a request but may not approve this size of change.
#: ``variations.approve_high_value`` is admin-only.
MANAGER = {"role": "manager", "permissions": ["variations.convert_to_vo"]}
ADMIN = {"role": "admin", "permissions": []}


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _owner_and_project(session: AsyncSession) -> tuple[str, uuid.UUID]:
    """An admin user owning a project, so project access is never the thing under test.

    The id comes back as a string because that is what ``CurrentUserId``
    resolves to, and the order records it in a text column.
    """
    user = User(
        email=f"cvr-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="CVR",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(
        name=f"CVR {uuid.uuid4().hex[:6]}",
        owner_id=user.id,
        currency="EUR",
        contract_value="5000000",
        planned_start_date="2026-01-01",
        planned_end_date="2026-12-31",
    )
    session.add(proj)
    await session.flush()
    return str(user.id), proj.id


async def _approved_request(session: AsyncSession, project_id: uuid.UUID) -> uuid.UUID:
    service = VariationsService(session)
    vr = await service.create_request(
        VariationRequestCreate(
            project_id=project_id,
            title=TITLE,
            estimated_cost_impact=ESTIMATE,
            estimated_schedule_days=ESTIMATE_DAYS,
            currency="EUR",
        )
    )
    await service.transition_variation_request(vr.id, "submitted")
    await service.transition_variation_request(vr.id, "approved")
    await session.flush()
    return vr.id


async def _convert(
    session: AsyncSession,
    vr_id: uuid.UUID,
    user_id: str,
    *,
    body: _ConvertVOBody | None = None,
    payload: dict | None = None,
):
    """Call the route handler the way FastAPI would, with the dependencies filled in."""
    return await convert_vr_to_vo(
        vr_id,
        session=session,
        user_id=user_id,
        user_payload=payload if payload is not None else ADMIN,
        body=body if body is not None else _ConvertVOBody(),
        service=VariationsService(session),
    )


@pytest.mark.asyncio
async def test_a_conversion_that_names_no_figures_commits_the_request(session: AsyncSession) -> None:
    """An empty body is the interface's own body, and it must not zero the order."""
    user_id, project_id = await _owner_and_project(session)
    vr_id = await _approved_request(session, project_id)

    order = await _convert(session, vr_id, user_id)

    assert order.final_cost_impact == ESTIMATE
    assert order.final_schedule_days == ESTIMATE_DAYS
    assert order.title == TITLE
    assert order.currency == "EUR"
    assert order.variation_request_id == vr_id


@pytest.mark.asyncio
async def test_a_currency_only_conversion_is_still_worth_the_request(session: AsyncSession) -> None:
    """What the variations page sends, verbatim: a currency and nothing else."""
    user_id, project_id = await _owner_and_project(session)
    vr_id = await _approved_request(session, project_id)

    order = await _convert(session, vr_id, user_id, body=_ConvertVOBody(currency="EUR"))

    assert order.final_cost_impact == ESTIMATE
    assert order.final_schedule_days == ESTIMATE_DAYS


@pytest.mark.asyncio
async def test_the_mirrored_change_order_is_priced_the_same(session: AsyncSession) -> None:
    """The mirror is what the change-order side of the business reads.

    It is created from the order, so an order valued at zero produced a mirror
    valued at zero, and both records of the change agreed on the wrong number.
    """
    user_id, project_id = await _owner_and_project(session)
    vr_id = await _approved_request(session, project_id)

    order = await _convert(session, vr_id, user_id)
    await session.flush()

    mirror = await session.get(ChangeOrder, order.reference_change_order_id)
    assert mirror is not None, "the promotion must mirror the order into a change order"
    assert Decimal(str(mirror.cost_impact)) == ESTIMATE
    assert mirror.metadata_["variation_order_id"] == str(order.id)


@pytest.mark.asyncio
async def test_a_figure_the_caller_names_still_wins(session: AsyncSession) -> None:
    """Carrying the request forward is a fallback, not an override.

    A promotion is where a request's estimate becomes an agreed figure, so a
    caller who negotiated a different one has to be able to say so.
    """
    user_id, project_id = await _owner_and_project(session)
    vr_id = await _approved_request(session, project_id)
    agreed = Decimal("199000.00")

    order = await _convert(
        session,
        vr_id,
        user_id,
        body=_ConvertVOBody(title="Piling redesign, agreed", final_cost_impact=agreed, final_schedule_days=14),
    )

    assert order.final_cost_impact == agreed
    assert order.final_schedule_days == 14
    assert order.title == "Piling redesign, agreed"


@pytest.mark.asyncio
async def test_nil_is_an_answer_and_not_a_blank(session: AsyncSession) -> None:
    """Agreed at no cost, or adding no time, has to stick.

    This is why the two figures are the fields the route treats as nullable
    rather than falling back on a falsy value the way the title and the
    currency do. Reading a nil as "said nothing" would turn a variation
    negotiated down to nothing into the request's estimate, which is a figure
    nobody agreed to and the opposite of the defect this route already had.
    """
    user_id, project_id = await _owner_and_project(session)
    vr_id = await _approved_request(session, project_id)

    days_only = await _convert(session, vr_id, user_id, body=_ConvertVOBody(final_schedule_days=0))
    assert days_only.final_schedule_days == 0
    assert days_only.final_cost_impact == ESTIMATE

    vr2 = await _approved_request(session, project_id)
    cost_free = await _convert(session, vr2, user_id, body=_ConvertVOBody(final_cost_impact=Decimal("0")))
    assert cost_free.final_cost_impact == Decimal("0")
    assert cost_free.final_schedule_days == ESTIMATE_DAYS


@pytest.mark.asyncio
async def test_the_figure_the_gate_reads_is_the_figure_the_order_carries(session: AsyncSession) -> None:
    """The two halves of one invariant, asserted against the same amount.

    The gate refusing a manager proves it was applied to the request's
    estimate; the admin's order carrying that estimate proves the same number
    is what gets committed. Before the fix the two halves were about different
    numbers: the gate turned callers away over an amount the order was never
    going to carry, and the order that did get created was worth nothing.
    """
    user_id, project_id = await _owner_and_project(session)
    vr_id = await _approved_request(session, project_id)

    with pytest.raises(HTTPException) as refused:
        await _convert(session, vr_id, user_id, payload=MANAGER)
    assert refused.value.status_code == 403

    order = await _convert(session, vr_id, user_id, payload=ADMIN)
    assert order.final_cost_impact == ESTIMATE


@pytest.mark.asyncio
async def test_a_conversion_can_name_the_contract_it_amends(session: AsyncSession) -> None:
    """Completion moves the contract sum, and this is where the contract is chosen.

    A request has no contract of its own, so nothing can be carried forward
    here. What the route can do is let the person promoting it say which
    contract the money lands on, which nothing in the interface could do
    before.
    """
    user_id, project_id = await _owner_and_project(session)
    vr_id = await _approved_request(session, project_id)
    contract = Contract(
        code=f"CT-{uuid.uuid4().hex[:8]}",
        title="Main works",
        project_id=project_id,
        status="active",
        currency="EUR",
        total_value=Decimal("5000000"),
    )
    session.add(contract)
    await session.flush()

    order = await _convert(
        session,
        vr_id,
        user_id,
        body=_ConvertVOBody(affected_contract_id=contract.id),
    )
    await session.flush()

    assert order.affected_contract_id == contract.id
    stored = await session.get(VariationOrder, order.id)
    assert stored is not None
    assert stored.affected_contract_id == contract.id

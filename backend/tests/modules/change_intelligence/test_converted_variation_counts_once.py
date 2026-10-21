# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A converted variation is one change, and must be counted as one.

Promoting a variation request creates two rows for one agreed change: the
variation order, and the change order that mirrors it
(``VariationsService.convert_vr_to_vo``). Both families feed the earned-value
gather and the run-rate curve, so before the mirror was recognised every
conversion added its money twice - to the cumulative curve, to the intake rate
and, once the mirror was approved, to the committed impact.

The pair is created here by the real promotion rather than by hand-built rows,
because the link the dedup reads is stamped by that call and a fixture that
stamped it itself would prove nothing about the code that ships.

Suppression is conditional on the variation order counting, so the two cases
that a blanket "drop every mirror" rule gets wrong are asserted too: a mirror
whose variation order was voided is the only surviving record of the change and
must carry it, and a change order nobody promoted is not a mirror at all.

PostgreSQL, py3.12 - needs the app plus a database, so it cannot run on the
pure-engine runner.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.change_intelligence.change_run_rate import (
    BUCKET_APPROVED,
    BUCKET_PENDING,
)
from app.modules.change_intelligence.service import (
    build_change_run_rate,
    gather_approved_changes,
)
from app.modules.changeorders.models import ChangeOrder
from app.modules.changeorders.schemas import ChangeOrderCreate
from app.modules.changeorders.service import ChangeOrderService
from app.modules.projects.models import Project
from app.modules.users.models import User
from app.modules.variations.models import VariationOrder
from app.modules.variations.schemas import VariationOrderCreate, VariationRequestCreate
from app.modules.variations.service import VariationsService
from tests._pg import transactional_session

#: What the request is approved on, and therefore what the order and its mirror
#: both carry. Every assertion below is against this one amount, so a curve
#: that counted the pair twice would read as double it.
AMOUNT = Decimal("40000")
NOW = datetime(2026, 6, 30, tzinfo=UTC)


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"cv-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="CV",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(
        name=f"CV {uuid.uuid4().hex[:6]}",
        owner_id=user.id,
        currency="EUR",
        contract_value="1000000",
        planned_start_date="2026-01-01",
        planned_end_date="2026-12-31",
    )
    session.add(proj)
    await session.flush()
    return proj.id


async def _promote(session: AsyncSession, project_id: uuid.UUID) -> tuple[VariationOrder, ChangeOrder]:
    """Run a request through approval into an order plus its mirrored change order."""
    service = VariationsService(session)
    vr = await service.create_request(
        VariationRequestCreate(
            project_id=project_id,
            title="Additional drainage",
            estimated_cost_impact=AMOUNT,
            currency="EUR",
        )
    )
    await service.transition_variation_request(vr.id, "submitted")
    await service.transition_variation_request(vr.id, "approved")
    vo = await service.convert_vr_to_vo(
        vr.id,
        VariationOrderCreate(project_id=project_id, currency="EUR"),
    )
    await session.flush()
    mirror = await session.get(ChangeOrder, vo.reference_change_order_id)
    assert mirror is not None, "the promotion must mirror the order into a change order"
    assert mirror.metadata_["variation_order_id"] == str(vo.id)
    return vo, mirror


async def _approve(session: AsyncSession, order: ChangeOrder) -> None:
    service = ChangeOrderService(session)
    await service.submit_order(order.id, user_id=str(uuid.uuid4()))
    await service.approve_order(order.id, user_id=str(uuid.uuid4()))
    await session.flush()


@pytest.mark.asyncio
async def test_a_converted_variation_reaches_the_run_rate_curve_once(session: AsyncSession) -> None:
    """One promotion, one change on the curve, and it is the order that carries it.

    The buckets are asserted, not just the total: the order is in force and the
    mirror is still a draft, so dropping the wrong half of the pair would leave
    the same cumulative value sitting in the wrong bucket.
    """
    pid = await _project(session)
    vo, mirror = await _promote(session, pid)

    run_rate = await build_change_run_rate(session, pid, now=NOW)

    assert run_rate.change_count == 1
    assert run_rate.approved_value == AMOUNT
    assert run_rate.pending_value == Decimal("0")
    assert run_rate.total_change_value == AMOUNT
    assert vo.status == "issued"
    assert mirror.status == "draft"


@pytest.mark.asyncio
async def test_an_approved_mirror_does_not_commit_the_money_a_second_time(session: AsyncSession) -> None:
    """The committed-impact gather counts the pair once.

    The mirror is created as a draft, which the gather ignores, so the double
    count only surfaces once somebody approves it - and approving it is the
    point of mirroring it.
    """
    pid = await _project(session)
    vo, mirror = await _promote(session, pid)
    await _approve(session, mirror)

    changes = await gather_approved_changes(session, pid)

    assert [c.ref_id for c in changes] == [str(vo.id)]
    assert sum((c.cost_impact for c in changes), Decimal("0")) == AMOUNT


@pytest.mark.asyncio
async def test_the_mirror_of_a_voided_order_is_the_change_and_still_counts(session: AsyncSession) -> None:
    """A dead variation order carries nothing, so its mirror carries everything.

    This is the case a blanket "a mirror never counts" rule loses: the change
    would then be recorded by neither half and simply disappear.
    """
    pid = await _project(session)
    vo, mirror = await _promote(session, pid)
    await VariationsService(session).transition_variation_order(vo.id, "voided", reason="test void")
    await session.flush()

    run_rate = await build_change_run_rate(session, pid, now=NOW)
    assert run_rate.change_count == 1
    assert run_rate.pending_value == AMOUNT
    assert run_rate.approved_value == Decimal("0")

    await _approve(session, mirror)
    changes = await gather_approved_changes(session, pid)
    assert [c.ref_id for c in changes] == [str(mirror.id)]
    assert sum((c.cost_impact for c in changes), Decimal("0")) == AMOUNT


@pytest.mark.asyncio
async def test_a_change_order_nobody_promoted_still_counts(session: AsyncSession) -> None:
    """Not every change order beside a variation order is its mirror.

    A change order raised on its own carries no variation link and its own
    money, so it belongs on the curve alongside the variation. The demo data
    also anchors a variation order to such a change order through
    ``reference_change_order_id``, which is why the dedup reads the link from
    the change order instead.
    """
    own = Decimal("7500")
    pid = await _project(session)
    vo, mirror = await _promote(session, pid)
    independent = await ChangeOrderService(session).create_order(
        ChangeOrderCreate(
            project_id=pid,
            title="Rock excavation",
            currency="EUR",
            cost_impact=str(own),
        )
    )
    await session.flush()
    await _approve(session, independent)

    run_rate = await build_change_run_rate(session, pid, now=NOW)
    assert run_rate.change_count == 2
    assert run_rate.approved_value == AMOUNT + own
    assert run_rate.pending_value == Decimal("0")

    changes = await gather_approved_changes(session, pid)
    assert {c.ref_id for c in changes} == {str(vo.id), str(independent.id)}
    assert sum((c.cost_impact for c in changes), Decimal("0")) == AMOUNT + own
    assert mirror.metadata_["origin"] == "variations.convert_vr_to_vo"


def test_the_two_buckets_are_the_ones_the_pair_lands_in() -> None:
    """Names the property the first test rests on, so a rename cannot hide it."""
    from app.modules.change_intelligence.change_run_rate import (
        KIND_CHANGE_ORDER,
        KIND_VARIATION_ORDER,
        classify_change_bucket,
    )

    assert classify_change_bucket(KIND_VARIATION_ORDER, "issued") == BUCKET_APPROVED
    assert classify_change_bucket(KIND_CHANGE_ORDER, "draft") == BUCKET_PENDING

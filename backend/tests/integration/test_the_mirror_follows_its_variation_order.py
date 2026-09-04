# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A mirrored change order has no price of its own - issue #435.

Promoting an approved variation request creates a variation order and mirrors
it into ``oe_changeorders``. The mirror is not a second commercial decision, so
editing its amount is refused with a 409 that tells the user to change the
amount on the variation order because the mirror follows. Two things were
wrong with that sentence.

The mirror did not follow. ``VariationsService.update_order`` writes the
variation order and stops, so an order corrected after promotion left its
mirror holding the superseded figure. Both halves post to a contract under one
identity, so whichever is approved first moves the money and the other stands
down as already posted: link a mirror to a contract by hand, correct the order,
approve the mirror, and the superseded amount is what reaches the contract
while the corrected one stands down.

And the amount was not held. The 409 covers a PATCH, but every line item write
runs ``_recalculate_cost_impact``, which sets ``cost_impact`` to the sum of the
lines - so a mirror that refuses ``{"cost_impact": "9999"}`` arrived at 9999
through one line item for 9999. A guard covering one of two doors reads as
closed, which is worse than no guard at all.

Both claims are asserted against money that actually moved rather than against
the stored column alone: the project budget the approval writes back, and the
``changeorder.approved`` payload the contracts subscriber posts from.

Real PostgreSQL, because every claim is about what is stored and read back
across two modules.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Import the sibling ORM modules so their tables exist in Base.metadata.
import app.modules.boq.models  # noqa: F401
import app.modules.changeorders.models  # noqa: F401
import app.modules.contracts.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.variations.models  # noqa: F401
from app.core.audit_log import ActivityLog
from app.core.events import event_bus
from app.modules.changeorders.models import ChangeOrder, ChangeOrderItem
from app.modules.changeorders.schemas import ChangeOrderCreate, ChangeOrderItemCreate, ChangeOrderItemUpdate
from app.modules.changeorders.service import ChangeOrderService
from app.modules.projects.models import Project
from app.modules.variations.models import VariationOrder
from app.modules.variations.schemas import VariationOrderCreate, VariationOrderUpdate
from app.modules.variations.service import VariationsService
from tests._pg import transactional_session

#: Two people, because approving a change order somebody else submitted is the
#: only way through ``_assert_not_self_approval``.
SUBMITTER = "44444444-4444-4444-4444-444444444444"
APPROVER = "55555555-5555-5555-5555-555555555555"

BUDGET = Decimal("2000000")
#: What the change was agreed at, and what it was corrected to afterwards.
#: Deliberately unlike each other and unlike the request's headline, so an
#: assertion cannot pass against the wrong one of the three by coincidence.
AGREED = Decimal("7200")
CORRECTED = Decimal("6800")
HEADLINE = Decimal("12000")


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Isolated PostgreSQL session, FK triggers off, rolled back on teardown."""
    async with transactional_session(disable_fks=True) as sess:
        yield sess


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Every event the services publish, in order, as they publish it."""
    seen: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        event_bus,
        "publish_detached",
        lambda name, data=None, source_module=None: seen.append((name, dict(data or {}))),
    )
    return seen


def _last(published: list[tuple[str, dict[str, Any]]], name: str) -> dict[str, Any]:
    for published_name, data in reversed(published):
        if published_name == name:
            return data
    raise AssertionError(f"no {name!r} was published; saw {[n for n, _ in published]}")


async def _make_project(session: AsyncSession) -> Project:
    project = Project(name="Harbour Terminal", owner_id=uuid.uuid4(), currency="EUR", budget_estimate=str(BUDGET))
    session.add(project)
    await session.flush()
    return project


async def _promote(session: AsyncSession, project: Project) -> tuple[VariationOrder, ChangeOrder]:
    """Run a request through approval at ``AGREED`` and return the pair it produced."""
    service = VariationsService(session)
    request = await service.create_request(
        _request_payload(project),
    )
    await service.transition_variation_request(request.id, "submitted", user_id=SUBMITTER)
    await service.transition_variation_request(
        request.id,
        "approved",
        user_id=APPROVER,
        agreed_cost_impact=AGREED,
    )
    order = await service.convert_vr_to_vo(
        request.id,
        VariationOrderCreate(project_id=project.id, currency="EUR"),
        user_id=APPROVER,
    )
    assert order.reference_change_order_id is not None
    mirror = await session.get(ChangeOrder, order.reference_change_order_id)
    assert mirror is not None, "the promotion must mirror the order into a change order"
    return order, mirror


def _request_payload(project: Project):  # noqa: ANN202 - the schema is imported where it is used
    from app.modules.variations.schemas import VariationRequestCreate

    return VariationRequestCreate(
        project_id=project.id,
        title="Deeper pile caps at grid F",
        estimated_cost_impact=HEADLINE,
        estimated_schedule_days=5,
        currency="EUR",
    )


async def _correct_the_order(session: AsyncSession, order: VariationOrder, amount: Decimal) -> None:
    """Re-agree the variation order at a different figure, as a QS would."""
    await VariationsService(session).update_order(
        order.id,
        VariationOrderUpdate(final_cost_impact=amount),
        user_id=APPROVER,
    )


async def _audit_metadata(session: AsyncSession, order: ChangeOrder, to_status: str) -> dict[str, Any]:
    """The audit row a transition left behind, or a failure if it left none.

    ``_safe_audit`` swallows every failure so an audit write can never roll
    back the money, which also means a test that only reads the column would
    pass with no audit row at all.
    """
    rows = (
        (
            await session.execute(
                select(ActivityLog)
                .where(ActivityLog.entity_type == "change_order")
                .where(ActivityLog.entity_id == str(order.id))
                .where(ActivityLog.to_status == to_status)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, f"expected one {to_status} audit row, found {len(rows)}"
    return dict(rows[0].metadata_ or {})


async def _approve(session: AsyncSession, order: ChangeOrder) -> ChangeOrder:
    service = ChangeOrderService(session)
    await service.submit_order(order.id, user_id=SUBMITTER)
    return await service.approve_order(order.id, user_id=APPROVER)


class TestTheMirrorFollowsTheVariationOrder:
    """One commercial decision, one number, however late the decision changes."""

    @pytest.mark.asyncio
    async def test_a_corrected_order_moves_the_amount_its_mirror_approves(
        self, session: AsyncSession, published: list[tuple[str, dict[str, Any]]]
    ) -> None:
        project = await _make_project(session)
        order, mirror = await _promote(session, project)
        assert Decimal(str(mirror.cost_impact)) == AGREED, "the mirror starts as a copy of the order"

        await _correct_the_order(session, order, CORRECTED)
        approved = await _approve(session, mirror)

        assert Decimal(str(approved.cost_impact)) == CORRECTED
        # And the figure that leaves the module, which is the one the contracts
        # subscriber posts and the one the budget writeback used.
        assert Decimal(_last(published, "changeorder.approved")["cost_impact"]) == CORRECTED
        refreshed = await session.get(Project, project.id)
        assert refreshed is not None
        assert Decimal(str(refreshed.budget_estimate)) == BUDGET + CORRECTED

    @pytest.mark.asyncio
    async def test_the_approver_is_shown_the_corrected_amount_at_submission(self, session: AsyncSession) -> None:
        # Approval is not the only moment that matters. A mirror submitted at
        # the superseded figure puts that figure in front of the person who has
        # to decide, so the correction is taken on the way in as well.
        project = await _make_project(session)
        order, mirror = await _promote(session, project)
        await _correct_the_order(session, order, CORRECTED)

        submitted = await ChangeOrderService(session).submit_order(mirror.id, user_id=SUBMITTER)

        assert submitted.status == "submitted"
        assert Decimal(str(submitted.cost_impact)) == CORRECTED

        # And the substitution is on the record at this moment too, not only at
        # approval: the audit row is the only place the submission-time swap is
        # written down, so a passing column check without it would be reading a
        # number nobody could account for afterwards.
        recorded = (await _audit_metadata(session, mirror, "submitted"))["mirror_amount_resynced"]
        assert Decimal(recorded["from"]) == AGREED
        assert Decimal(recorded["to"]) == CORRECTED
        assert recorded["variation_order_id"] == str(order.id)

    @pytest.mark.asyncio
    async def test_the_substitution_is_recorded_rather_than_made_quietly(
        self, session: AsyncSession, published: list[tuple[str, dict[str, Any]]]
    ) -> None:
        # Corrected between submission and approval, which is the case that
        # shows approval reads the order rather than trusting what submission
        # left behind. A correction can run upward as easily as downward, and
        # then the approval posts more than the approver was shown. Silently
        # substituting a number is what this whole issue is about, so the
        # substitution names both figures and the order it came from.
        project = await _make_project(session)
        order, mirror = await _promote(session, project)
        service = ChangeOrderService(session)
        await service.submit_order(mirror.id, user_id=SUBMITTER)
        await _correct_the_order(session, order, AGREED + Decimal("500"))

        approved = await service.approve_order(mirror.id, user_id=APPROVER)
        assert Decimal(str(approved.cost_impact)) == AGREED + Decimal("500")

        resynced = _last(published, "changeorder.approved")["mirror_amount_resynced"]
        assert resynced is not None
        assert Decimal(resynced["from"]) == AGREED
        assert Decimal(resynced["to"]) == AGREED + Decimal("500")
        assert resynced["variation_order_id"] == str(order.id)

    @pytest.mark.asyncio
    async def test_an_uncorrected_mirror_reports_no_substitution(
        self, session: AsyncSession, published: list[tuple[str, dict[str, Any]]]
    ) -> None:
        # The control for the record above: a resync stamp on every approval
        # would say nothing, and a reader would learn to skip it.
        project = await _make_project(session)
        _, mirror = await _promote(session, project)

        await _approve(session, mirror)

        approved_event = _last(published, "changeorder.approved")
        assert approved_event["mirror_amount_resynced"] is None
        assert Decimal(approved_event["cost_impact"]) == AGREED
        assert "mirror_amount_resynced" not in await _audit_metadata(session, mirror, "submitted")

    @pytest.mark.asyncio
    async def test_a_standalone_order_keeps_the_amount_it_was_given(
        self, session: AsyncSession, published: list[tuple[str, dict[str, Any]]]
    ) -> None:
        # The control that matters most: nothing above may reach a change order
        # somebody raised by hand, which has no variation behind it and whose
        # own cost impact is the only decision there is.
        project = await _make_project(session)
        service = ChangeOrderService(session)
        standalone = await service.create_order(
            ChangeOrderCreate(
                project_id=project.id,
                title="Temporary site lighting",
                reason_category="design_change",
                currency="EUR",
                cost_impact="4000",
            )
        )

        approved = await _approve(session, standalone)

        assert Decimal(str(approved.cost_impact)) == Decimal("4000")
        assert _last(published, "changeorder.approved")["mirror_amount_resynced"] is None

    @pytest.mark.asyncio
    async def test_a_deleted_variation_order_leaves_the_copy_standing(self, session: AsyncSession) -> None:
        # Refusing here would strand a change order whose amount nobody can
        # correct any more, so the copy is the figure of last resort.
        project = await _make_project(session)
        order, mirror = await _promote(session, project)
        await VariationsService(session).delete_order(order.id)

        approved = await _approve(session, mirror)

        assert Decimal(str(approved.cost_impact)) == AGREED


class TestTheMirrorCannotBePricedByItsLines:
    """The second door onto the same number."""

    @pytest.mark.asyncio
    async def test_adding_a_line_to_a_mirror_is_refused(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        order, mirror = await _promote(session, project)

        with pytest.raises(HTTPException) as excinfo:
            await ChangeOrderService(session).add_item(
                mirror.id,
                ChangeOrderItemCreate(
                    description="Extra piling, priced here instead",
                    change_type="added",
                    original_quantity=0,
                    new_quantity=1,
                    original_rate=0,
                    new_rate=9999,
                    unit="item",
                ),
            )

        assert excinfo.value.status_code == 409
        # It names where the price does live, because a refusal that only says
        # no leaves the user looking for a permission they do not lack.
        assert str(order.id) in str(excinfo.value.detail)
        refreshed = await session.get(ChangeOrder, mirror.id)
        assert refreshed is not None
        assert Decimal(str(refreshed.cost_impact)) == AGREED

    @pytest.mark.asyncio
    async def test_changing_a_line_on_a_mirror_is_refused(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        _, mirror = await _promote(session, project)
        line = await _line_on(session, mirror)

        with pytest.raises(HTTPException) as excinfo:
            await ChangeOrderService(session).update_item(
                mirror.id,
                line.id,
                ChangeOrderItemUpdate(new_rate=9999),
            )

        assert excinfo.value.status_code == 409

    @pytest.mark.asyncio
    async def test_deleting_a_line_on_a_mirror_is_refused(self, session: AsyncSession) -> None:
        # Deletion prices the record just as surely as addition does: the
        # remaining lines are re-summed onto the amount.
        project = await _make_project(session)
        _, mirror = await _promote(session, project)
        line = await _line_on(session, mirror)

        with pytest.raises(HTTPException) as excinfo:
            await ChangeOrderService(session).delete_item(mirror.id, line.id)

        assert excinfo.value.status_code == 409

    @pytest.mark.asyncio
    async def test_a_standalone_order_is_still_priced_by_its_lines(self, session: AsyncSession) -> None:
        # The control. Line items are how an ordinary change order arrives at
        # its amount, and holding the mirror must not take that away.
        project = await _make_project(session)
        service = ChangeOrderService(session)
        standalone = await service.create_order(
            ChangeOrderCreate(
                project_id=project.id,
                title="Extra site lighting",
                reason_category="design_change",
                currency="EUR",
                cost_impact="0",
            )
        )

        await service.add_item(
            standalone.id,
            ChangeOrderItemCreate(
                description="Floodlight mast",
                change_type="added",
                original_quantity=0,
                new_quantity=2,
                original_rate=0,
                new_rate=1500,
                unit="item",
            ),
        )

        refreshed = await session.get(ChangeOrder, standalone.id)
        assert refreshed is not None
        assert Decimal(str(refreshed.cost_impact)) == Decimal("3000")


async def _line_on(session: AsyncSession, order: ChangeOrder) -> ChangeOrderItem:
    """Put a line on an order directly, so the update and delete doors can be tried.

    Written through the ORM rather than through ``add_item``, which is one of
    the doors under test and now refuses.
    """
    line = ChangeOrderItem(
        change_order_id=order.id,
        description="Piling, as promoted",
        change_type="added",
        original_quantity="0",
        new_quantity="1",
        original_rate="0",
        new_rate=str(AGREED),
        cost_delta=str(AGREED),
        unit="item",
        sort_order=0,
    )
    session.add(line)
    await session.flush()
    return line

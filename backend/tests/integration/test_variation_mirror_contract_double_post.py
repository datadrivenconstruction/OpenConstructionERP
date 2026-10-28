# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠One commercial change must move a contract's value exactly once.

Promoting a variation request mirrors the resulting variation order into
``oe_changeorders`` as a draft change order
(``VariationsService.convert_vr_to_vo``). Two independent wave-5
subscribers can then add money to the same contract: one on variation
order completion, one on change order approval. They originally
deduplicated only against their own metadata bucket, so nothing stopped
the mirrored pair from posting the same amount twice.

Both now post under a shared source key naming the commercial change
rather than the row (``_contract_source_key``), so the pair posts once in
either arrival order. That ordering independence is the point of the
shape and is asserted directly, because a guard keyed on whether the
money has already landed can only ever close one of the two orders.

Reachability is the whole point of this file, so it is asserted rather
than assumed:

* the mirror as created carries no ``metadata.contract_id``, so the
  change order subscriber returns before it opens a session - the plain
  promote / complete / approve flow posts once;
* the mirror is a *draft*, and ``ChangeOrderUpdate`` accepts ``metadata``
  which ``update_order`` merges, so linking it to the very contract the
  variation order already names is one PATCH away - and that is the pair
  that used to post twice.

The events are recorded from the real publishers and handed to the real
handlers, so the payloads under test are the ones the services actually
emit. Driving the handlers directly keeps the assertions free of the
detached-publish race; ``test_subscribers_are_registered`` asserts the
wiring that production relies on to call them.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.modules.notifications._wave5_cross_module_subscribers as w5
from app.core.events import Event, event_bus
from app.modules.changeorders.models import ChangeOrder
from app.modules.changeorders.schemas import ChangeOrderCreate, ChangeOrderUpdate
from app.modules.changeorders.service import ChangeOrderService
from app.modules.contracts.models import Contract
from app.modules.projects.models import Project
from app.modules.users.models import User
from app.modules.variations.models import VariationOrder, VariationRequest
from app.modules.variations.schemas import (
    VariationOrderCreate,
    VariationOrderUpdate,
    VariationRequestCreate,
)
from app.modules.variations.service import VariationsService
from tests._pg import isolated_engine

BASE_VALUE = Decimal("100000")
VO_AMOUNT = Decimal("25000")
#: What a request is approved on when the promotion names no figures of its
#: own. Deliberately unlike ``VO_AMOUNT`` so a carried-over value cannot be
#: mistaken for a payload value, and non-zero so the assertions below cannot
#: pass against an order that was created empty.
REQUEST_AMOUNT = Decimal("18750.40")
REQUEST_DAYS = 12

VO_COMPLETED_EVENT = "variations.contract_sum.updated"
CO_APPROVED_EVENT = "changeorder.approved"


class _Harness:
    """A throwaway database plus the events the services published into it."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self.factory = factory
        self.published: list[tuple[str, dict[str, Any]]] = []
        self.project_id: uuid.UUID
        self.contract_id: uuid.UUID

    def last_event(self, name: str) -> dict[str, Any]:
        for published_name, data in reversed(self.published):
            if published_name == name:
                return data
        raise AssertionError(f"no {name!r} was published; saw {[n for n, _ in self.published]}")

    async def contract_state(self) -> tuple[Decimal, dict[str, Any]]:
        """Re-read the contract in a fresh session (the handlers commit their own)."""
        async with self.factory() as session:
            contract = await session.get(Contract, self.contract_id)
            assert contract is not None
            return Decimal(str(contract.total_value)), dict(contract.metadata_ or {})

    async def deliver(self, name: str) -> None:
        """Hand the last published *name* payload to every wave-5 handler
        registered under *name*.

        ``dict(w5._SUBSCRIPTIONS)[name]`` silently drops duplicate keys, so a
        second handler on the same event name (e.g. two ``changeorder.approved``
        entries) was never called.  Iterate all matching pairs instead, which is
        what the production dispatcher does.
        """
        handlers = [h for n, h in w5._SUBSCRIPTIONS if n == name]
        if not handlers:
            raise AssertionError(f"no handler registered for {name!r}")
        evt = Event(name=name, data=self.last_event(name))
        for handler in handlers:
            await handler(evt)  # type: ignore[operator]


@pytest_asyncio.fixture
async def harness(monkeypatch: pytest.MonkeyPatch):
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        # The wave-5 handlers open their own isolated session by design; point
        # it at the same throwaway database so they read and write the rows the
        # test just committed.
        monkeypatch.setattr(w5, "async_session_factory", factory)

        h = _Harness(factory)
        monkeypatch.setattr(
            event_bus,
            "publish_detached",
            lambda name, data=None, source_module=None: h.published.append((name, dict(data or {}))),
        )

        async with factory() as session:
            user = User(
                email=f"vm-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password="x",
                full_name="Variation mirror",
                role="admin",
            )
            session.add(user)
            await session.flush()
            project = Project(name=f"VM {uuid.uuid4().hex[:6]}", owner_id=user.id, currency="EUR")
            session.add(project)
            await session.flush()
            contract = Contract(
                code=f"CT-{uuid.uuid4().hex[:8]}",
                title="Main works",
                project_id=project.id,
                status="active",
                currency="EUR",
                total_value=BASE_VALUE,
            )
            session.add(contract)
            await session.commit()
            h.project_id = project.id
            h.contract_id = contract.id
            yield h


async def _promote(
    session: AsyncSession,
    harness: _Harness,
    *,
    amount: Decimal = VO_AMOUNT,
    link_contract: bool = True,
    currency: str = "EUR",
) -> tuple[VariationOrder, ChangeOrder]:
    """Run a variation request through approval into a VO plus its mirrored CO."""
    service = VariationsService(session)
    vr = await service.create_request(
        VariationRequestCreate(
            project_id=harness.project_id,
            title="Additional piling",
            estimated_cost_impact=amount,
            currency=currency,
        )
    )
    await service.transition_variation_request(vr.id, "submitted")
    await service.transition_variation_request(vr.id, "approved")
    vo = await service.convert_vr_to_vo(
        vr.id,
        VariationOrderCreate(
            project_id=harness.project_id,
            title="Additional piling",
            final_cost_impact=amount,
            currency=currency,
            affected_contract_id=harness.contract_id if link_contract else None,
        ),
    )
    await session.commit()
    mirror = await session.get(ChangeOrder, vo.reference_change_order_id)
    assert mirror is not None, "the promotion must mirror the VO into a change order"
    return vo, mirror


async def _complete(session: AsyncSession, harness: _Harness, vo: VariationOrder) -> None:
    """Drive the VO to completed and let the variation subscriber post its money."""
    service = VariationsService(session)
    await service.transition_variation_order(vo.id, "in_progress")
    await service.transition_variation_order(vo.id, "completed")
    await session.commit()
    await harness.deliver(VO_COMPLETED_EVENT)


async def _approve(session: AsyncSession, harness: _Harness, order: ChangeOrder) -> None:
    """Drive a CO through submit + approve and let the CO subscriber run."""
    service = ChangeOrderService(session)
    await service.submit_order(order.id, user_id=str(uuid.uuid4()))
    await service.approve_order(order.id, user_id=str(uuid.uuid4()))
    await session.commit()
    await harness.deliver(CO_APPROVED_EVENT)


async def _link_to_contract(session: AsyncSession, harness: _Harness, order: ChangeOrder) -> None:
    """Stamp ``metadata.contract_id`` on a draft CO, as the create/edit form does."""
    service = ChangeOrderService(session)
    await service.update_order(
        order.id,
        ChangeOrderUpdate(metadata={"contract_id": str(harness.contract_id)}),
    )
    await session.commit()


@pytest.mark.asyncio
async def test_mirror_carries_the_variation_link_and_no_contract_link(harness: _Harness) -> None:
    """The mirror knows which VO it came from, and names no contract.

    Both halves matter: the variation link is what the dedup keys on, and
    the absent contract link is why the plain flow never double-posts.
    """
    async with harness.factory() as session:
        vo, mirror = await _promote(session, harness)

    assert mirror.metadata_["origin"] == "variations.convert_vr_to_vo"
    assert mirror.metadata_["variation_order_id"] == str(vo.id)
    assert "contract_id" not in mirror.metadata_
    assert mirror.status == "draft"
    assert Decimal(str(mirror.cost_impact)) == VO_AMOUNT


@pytest.mark.asyncio
async def test_plain_promotion_posts_the_money_once(harness: _Harness) -> None:
    """Promote, complete, approve the mirror: the contract moves by one VO."""
    async with harness.factory() as session:
        vo, mirror = await _promote(session, harness)
        await _complete(session, harness, vo)
        await _approve(session, harness, mirror)

    total, md = await harness.contract_state()
    assert harness.last_event(CO_APPROVED_EVENT)["contract_id"] is None
    assert total == BASE_VALUE + VO_AMOUNT
    assert md["variation_ids"] == [str(vo.id)]
    assert Decimal(md["variation_total"]) == VO_AMOUNT
    # The change order path never ran - it has no contract to post against.
    assert "change_order_ids" not in md
    assert "change_order_total" not in md


@pytest.mark.asyncio
async def test_linked_mirror_posts_the_money_once(harness: _Harness) -> None:
    """The regression gate: linking the mirror to the same contract is not a second change.

    A PATCH stamping ``metadata.contract_id`` on the draft mirror is all it
    takes to put both subscribers on the same contract. The variation order
    has already posted its amount, so approving its mirror must not post it
    again.
    """
    async with harness.factory() as session:
        vo, mirror = await _promote(session, harness)
        await _link_to_contract(session, harness, mirror)
        await _complete(session, harness, vo)
        await _approve(session, harness, mirror)

    total, md = await harness.contract_state()
    assert harness.last_event(CO_APPROVED_EVENT)["contract_id"] == str(harness.contract_id)
    assert total == BASE_VALUE + VO_AMOUNT
    assert md["variation_ids"] == [str(vo.id)]
    assert Decimal(md["variation_total"]) == VO_AMOUNT
    # Skipped, not applied: the money is already on the contract via the VO.
    assert "change_order_total" not in md
    skipped = md["skipped_variation_mirror"]
    assert len(skipped) == 1
    assert skipped[0]["change_order_id"] == str(mirror.id)
    assert skipped[0]["variation_order_id"] == str(vo.id)
    assert skipped[0]["skipped"] == "change_order"
    # Money as Decimal, never as a string: the CO renders its impact to 2 dp.
    assert Decimal(skipped[0]["cost_impact"]) == VO_AMOUNT
    # The rollup counts change_order_ids, so a skipped post must stay out of it.
    assert "change_order_ids" not in md
    # One commercial change, posted under one source identity.
    assert md["posted_sources"] == [f"variation_order:{vo.id}"]


@pytest.mark.asyncio
async def test_linked_mirror_posts_the_money_once_when_the_mirror_is_approved_first(
    harness: _Harness,
) -> None:
    """The reverse ordering, which a money-already-applied guard cannot close.

    Approving the mirror before the variation order completes used to post
    twice: at approval time the VO had put nothing on the contract yet, so a
    guard asking "is the money already there" had to answer no. Keying on the
    source instead makes the question answerable before either half has
    posted, so the ordering stops mattering.
    """
    async with harness.factory() as session:
        vo, mirror = await _promote(session, harness)
        await _link_to_contract(session, harness, mirror)
        await _approve(session, harness, mirror)
        await _complete(session, harness, vo)

    total, md = await harness.contract_state()
    assert total == BASE_VALUE + VO_AMOUNT
    # This time the change order carried the money, so it is the VO that stands down.
    assert md["change_order_ids"] == [str(mirror.id)]
    assert Decimal(md["change_order_total"]) == VO_AMOUNT
    assert "variation_total" not in md
    skipped = md["skipped_variation_mirror"]
    assert len(skipped) == 1
    assert skipped[0]["variation_order_id"] == str(vo.id)
    assert skipped[0]["skipped"] == "variation_order"
    # The mirror posted under the variation order's identity, not its own,
    # which is exactly what lets the VO recognise the change as already posted.
    assert md["posted_sources"] == [f"variation_order:{vo.id}"]


@pytest.mark.asyncio
async def test_both_orderings_agree_on_the_total(harness: _Harness) -> None:
    """The property the fix is really about: the total does not depend on arrival order.

    Asserted as an equality between two measured runs rather than against a
    constant, so it keeps holding if the fixture amounts ever change.
    """
    async with harness.factory() as session:
        vo, mirror = await _promote(session, harness)
        await _link_to_contract(session, harness, mirror)
        await _complete(session, harness, vo)
        await _approve(session, harness, mirror)
    forward_total, _ = await harness.contract_state()

    # A second contract in the same database, driven in the opposite order.
    async with harness.factory() as session:
        contract = Contract(
            code=f"CT-{uuid.uuid4().hex[:8]}",
            title="Main works (reverse)",
            project_id=harness.project_id,
            status="active",
            currency="EUR",
            total_value=BASE_VALUE,
        )
        session.add(contract)
        await session.commit()
        harness.contract_id = contract.id

        vo2, mirror2 = await _promote(session, harness)
        await _link_to_contract(session, harness, mirror2)
        await _approve(session, harness, mirror2)
        await _complete(session, harness, vo2)
    reverse_total, _ = await harness.contract_state()

    assert forward_total == reverse_total == BASE_VALUE + VO_AMOUNT


@pytest.mark.asyncio
async def test_independent_change_order_still_posts(harness: _Harness) -> None:
    """A CO a user raised on the same contract is not a mirror and must post."""
    amount = Decimal("4200.50")
    async with harness.factory() as session:
        vo, mirror = await _promote(session, harness)
        await _complete(session, harness, vo)

        service = ChangeOrderService(session)
        independent = await service.create_order(
            ChangeOrderCreate(
                project_id=harness.project_id,
                title="Rock excavation",
                currency="EUR",
                cost_impact=str(amount),
                metadata={"contract_id": str(harness.contract_id)},
            )
        )
        await session.commit()
        await _approve(session, harness, independent)

    total, md = await harness.contract_state()
    assert total == BASE_VALUE + VO_AMOUNT + amount
    assert md["change_order_ids"] == [str(independent.id)]
    assert Decimal(md["change_order_total"]) == amount
    assert "skipped_variation_mirror" not in md
    assert mirror.status == "draft"


@pytest.mark.asyncio
async def test_mirror_of_an_unlinked_variation_order_still_posts(harness: _Harness) -> None:
    """A mirror is only silenced when its VO posted the money.

    When the VO names no contract the variation path never posts, so the
    mirrored CO is the only route to the contract and must take it.
    """
    async with harness.factory() as session:
        vo, mirror = await _promote(session, harness, link_contract=False)
        await _link_to_contract(session, harness, mirror)
        await _approve(session, harness, mirror)

    total, md = await harness.contract_state()
    assert total == BASE_VALUE + VO_AMOUNT
    assert md["change_order_ids"] == [str(mirror.id)]
    assert Decimal(md["change_order_total"]) == VO_AMOUNT
    assert "variation_ids" not in md
    assert vo.affected_contract_id is None


@pytest.mark.asyncio
async def test_a_variation_still_posts_after_an_unrelated_change_order(harness: _Harness) -> None:
    """The variation half of the guard must not fire on another source's key.

    ``test_independent_change_order_still_posts`` runs this same pair the other
    way round, so on its own it only ever reads the variation-side check
    against an empty bucket. Here the bucket already holds a change order's key
    by the time the variation order arrives, which is what shows the two key
    spaces are namespaced rather than merely failing to collide by luck.
    """
    amount = Decimal("3300.25")
    async with harness.factory() as session:
        vo, mirror = await _promote(session, harness)

        service = ChangeOrderService(session)
        independent = await service.create_order(
            ChangeOrderCreate(
                project_id=harness.project_id,
                title="Temporary works",
                currency="EUR",
                cost_impact=str(amount),
                metadata={"contract_id": str(harness.contract_id)},
            )
        )
        await session.commit()
        await _approve(session, harness, independent)
        await _complete(session, harness, vo)

    total, md = await harness.contract_state()
    assert total == BASE_VALUE + amount + VO_AMOUNT
    assert md["posted_sources"] == [f"change_order:{independent.id}", f"variation_order:{vo.id}"]
    assert md["variation_ids"] == [str(vo.id)]
    assert Decimal(md["variation_total"]) == VO_AMOUNT
    assert "skipped_variation_mirror" not in md
    assert mirror.status == "draft"


@pytest.mark.asyncio
async def test_a_currency_mismatched_variation_does_not_silence_its_mirror(harness: _Harness) -> None:
    """Recording a variation order is not the same as posting its money.

    The variation handler appends to ``variation_ids`` before the currency
    guard runs, so a variation order in a foreign currency sits on that list
    having moved nothing. ``ChangeOrderUpdate`` accepts ``currency`` as well as
    ``metadata``, so the one PATCH that links the mirror can also put it in the
    contract's own currency - which leaves the mirror as the only half able to
    post. A guard that read ``variation_ids`` as proof of payment would silence
    it and the amount would reach the contract by neither route.
    """
    async with harness.factory() as session:
        vo, mirror = await _promote(session, harness, currency="GBP")
        service = ChangeOrderService(session)
        await service.update_order(
            mirror.id,
            ChangeOrderUpdate(metadata={"contract_id": str(harness.contract_id)}, currency="EUR"),
        )
        await session.commit()
        await _complete(session, harness, vo)

        held_total, held_md = await harness.contract_state()
        assert held_total == BASE_VALUE, "a foreign-currency variation must not move total_value"
        assert held_md["variation_ids"] == [str(vo.id)], "and yet it is recorded"
        assert held_md["skipped_currency_mismatch"][0]["variation_id"] == str(vo.id)
        assert held_md.get(w5._POSTED_SOURCES_KEY, []) == []

        await _approve(session, harness, mirror)

    total, md = await harness.contract_state()
    assert total == BASE_VALUE + VO_AMOUNT
    assert md["change_order_ids"] == [str(mirror.id)]
    assert Decimal(md["change_order_total"]) == VO_AMOUNT
    assert md[w5._POSTED_SOURCES_KEY] == [f"variation_order:{vo.id}"]
    assert "skipped_variation_mirror" not in md


async def _promote_naming_only_a_currency(
    session: AsyncSession,
    harness: _Harness,
    *,
    currency: str = "EUR",
) -> tuple[VariationOrder, ChangeOrder]:
    """Promote the way the variations page does: the payload names a currency, nothing else.

    Every other field of ``VariationOrderCreate`` carries a schema default, so
    this is the payload that used to produce an order with no title, no value
    and no contract - the one shape a user can actually reach from the UI.
    """
    service = VariationsService(session)
    vr = await service.create_request(
        VariationRequestCreate(
            project_id=harness.project_id,
            title="Deeper pile caps",
            estimated_cost_impact=REQUEST_AMOUNT,
            estimated_schedule_days=REQUEST_DAYS,
            currency=currency,
        )
    )
    await service.transition_variation_request(vr.id, "submitted")
    await service.transition_variation_request(vr.id, "approved")
    vo = await service.convert_vr_to_vo(
        vr.id,
        VariationOrderCreate(project_id=harness.project_id, currency=currency),
    )
    await session.commit()
    mirror = await session.get(ChangeOrder, vo.reference_change_order_id)
    assert mirror is not None, "the promotion must mirror the VO into a change order"
    return vo, mirror


@pytest.mark.asyncio
async def test_promotion_carries_the_requests_figures_when_the_caller_names_none(
    harness: _Harness,
) -> None:
    """An order promoted from a request inherits what the request was approved on.

    Asserted against the request's own figures rather than against constants
    the payload also carries, so the test cannot pass on an order that merely
    happens to hold the right numbers by way of the payload.
    """
    async with harness.factory() as session:
        vo, mirror = await _promote_naming_only_a_currency(session, harness)
        vr = await session.get(VariationRequest, vo.variation_request_id)

    assert vr is not None
    assert vo.title == vr.title != ""
    assert Decimal(str(vo.final_cost_impact)) == Decimal(str(vr.estimated_cost_impact)) == REQUEST_AMOUNT
    assert vo.final_schedule_days == vr.estimated_schedule_days == REQUEST_DAYS
    assert vo.currency == "EUR"
    # The mirror is priced off the order, so an empty order used to mirror as
    # an empty change order too.
    assert Decimal(str(mirror.cost_impact)) == REQUEST_AMOUNT
    assert mirror.title == vr.title
    assert mirror.schedule_impact_days == REQUEST_DAYS


@pytest.mark.asyncio
async def test_an_explicitly_named_figure_still_wins_over_the_request(harness: _Harness) -> None:
    """Carry-over fills the silence, it does not overrule the caller.

    A promotion that agrees a different title or a different value - including
    a deliberate zero, which is indistinguishable from an unset field by value
    alone - must get exactly what it asked for.
    """
    async with harness.factory() as session:
        service = VariationsService(session)
        vr = await service.create_request(
            VariationRequestCreate(
                project_id=harness.project_id,
                title="Deeper pile caps",
                estimated_cost_impact=REQUEST_AMOUNT,
                estimated_schedule_days=REQUEST_DAYS,
                currency="EUR",
            )
        )
        await service.transition_variation_request(vr.id, "submitted")
        await service.transition_variation_request(vr.id, "approved")
        vo = await service.convert_vr_to_vo(
            vr.id,
            VariationOrderCreate(
                project_id=harness.project_id,
                title="Agreed at nil cost",
                final_cost_impact=Decimal("0"),
                final_schedule_days=0,
                currency="EUR",
            ),
        )
        await session.commit()

    assert vo.title == "Agreed at nil cost"
    assert Decimal(str(vo.final_cost_impact)) == Decimal("0")
    assert vo.final_schedule_days == 0


@pytest.mark.asyncio
async def test_a_promoted_order_linked_after_the_fact_posts_the_money_once(
    harness: _Harness,
) -> None:
    """The chain a user can actually reach, end to end, and it posts once.

    Nothing in the UI names a contract while promoting, and until
    ``VariationOrderUpdate`` carried ``affected_contract_id`` nothing could
    name one afterwards either, so an order created this way never reached a
    contract at all. Linking it is now a PATCH; both halves of the mirrored
    pair are then live against the same contract, and the shared source key is
    what keeps the amount from landing twice.

    The amount is the request's estimate, so an order promoted empty would
    move the contract by zero and fail here rather than pass quietly.
    """
    async with harness.factory() as session:
        vo, mirror = await _promote_naming_only_a_currency(session, harness)

        service = VariationsService(session)
        vo = await service.update_order(
            vo.id,
            VariationOrderUpdate(affected_contract_id=harness.contract_id),
        )
        await session.commit()
        assert vo.affected_contract_id == harness.contract_id

        await _link_to_contract(session, harness, mirror)
        await _complete(session, harness, vo)
        after_variation, _ = await harness.contract_state()
        await _approve(session, harness, mirror)

    total, md = await harness.contract_state()
    assert after_variation == BASE_VALUE + REQUEST_AMOUNT
    assert total == after_variation, "approving the mirror is not a second commercial change"
    assert md["variation_ids"] == [str(vo.id)]
    assert Decimal(md["variation_total"]) == REQUEST_AMOUNT
    assert md[w5._POSTED_SOURCES_KEY] == [f"variation_order:{vo.id}"]
    assert md["skipped_variation_mirror"][0]["skipped"] == "change_order"
    assert "change_order_total" not in md


def test_subscribers_are_registered() -> None:
    """Both money paths are wired, which is what makes the pair reachable."""
    assert (VO_COMPLETED_EVENT, w5._on_variation_completed) in w5._SUBSCRIPTIONS
    assert (CO_APPROVED_EVENT, w5._on_changeorder_approved_contract) in w5._SUBSCRIPTIONS

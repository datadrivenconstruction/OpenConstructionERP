# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The commercial approval boundary of a variation - issue #435.

A variation request carries a headline estimate and may own a priced bill, and
the two are allowed to differ while the change is being priced. Nothing
recorded the boundary between them: which pricing state was put in front of
the approver, and what commercial amount that approver actually agreed to.

That gap is not visible in the way a missing field usually is. There is always
a number to hand - the headline - and it is a plausible figure of the right
order of magnitude, so a variation agreed at a negotiated 7,200 and one that
silently inherited a stale 12,000 produce records that look the same and flow
downstream identically. The point of these tests is that they no longer can.

Five claims:

* Submitting freezes WHICH pricing state was submitted, and freezing means
  frozen: the bill goes on being revised afterwards, which is the normal way a
  variation gets negotiated, and a total read later answers a different
  question from the one the record has to answer.
* Submitting also keeps the bill as it stood, as a snapshot in the bill's own
  version history, so the frozen total still has lines behind it once the
  bill has moved on. A total is what gets agreed against; only the lines can
  defend it.
* Approving records what was agreed AND why it is that number. "The agreed
  value happens to equal the bill total" and "nobody ever really decided" must
  not be the same record.
* An amount that departs from the submitted pricing state has to say why. A
  difference is legitimate; a silent one is the defect.
* The agreed value flows into the Variation Order without being re-entered,
  and a request approved before any of this existed still promotes on the only
  figure it has.

Real PostgreSQL rather than a stubbed session, because every claim is about
what is stored and read back, and a stub would only restate the service's own
branching.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

# Import the sibling ORM modules so their tables exist in Base.metadata.
import app.modules.boq.models  # noqa: F401
import app.modules.changeorders.models  # noqa: F401
import app.modules.contracts.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.variations.models  # noqa: F401
from app.modules.boq.models import BOQ, BOQSnapshot, Position
from app.modules.boq.service import BOQService
from app.modules.changeorders.models import ChangeOrder
from app.modules.changeorders.schemas import ChangeOrderUpdate
from app.modules.changeorders.service import ChangeOrderService
from app.modules.projects.models import Project
from app.modules.variations.models import VariationRequest
from app.modules.variations.schemas import VariationBOQCreate, VariationBOQSourcePosition, VariationOrderCreate
from app.modules.variations.service import (
    AGREED_BASIS_HEADLINE,
    AGREED_BASIS_NEGOTIATED,
    AGREED_BASIS_PRICED_BOQ,
    VariationsService,
)
from tests._pg import transactional_session

ACTOR = "33333333-3333-3333-3333-333333333333"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Isolated PostgreSQL session, FK triggers off, rolled back on teardown."""
    async with transactional_session(disable_fks=True) as sess:
        yield sess


async def _make_project(session: AsyncSession) -> Project:
    project = Project(name="Riverside Depot", owner_id=uuid.uuid4(), currency="EUR", budget_estimate="2000000")
    session.add(project)
    await session.flush()
    return project


async def _make_source_position(session: AsyncSession, project: Project) -> Position:
    boq = BOQ(project_id=project.id, name="Tender estimate")
    session.add(boq)
    await session.flush()
    position = Position(
        boq_id=boq.id,
        ordinal="0010",
        description="Reinforced concrete wall C30/37",
        unit="m3",
        quantity="100",
        unit_rate="250",
        total="25000",
        classification={"din276": "331"},
        source="manual",
        cad_element_ids=[],
    )
    session.add(position)
    await session.flush()
    return position


async def _make_request(session: AsyncSession, project: Project, *, headline: str = "12000") -> VariationRequest:
    request = VariationRequest(
        project_id=project.id,
        code=f"VR-{uuid.uuid4().hex[:6]}",
        title="Additional retaining wall at grid F",
        estimated_cost_impact=Decimal(headline),
        estimated_schedule_days=5,
        currency="EUR",
    )
    session.add(request)
    await session.flush()
    return request


async def _price_the_variation(
    session: AsyncSession,
    service: VariationsService,
    request: VariationRequest,
    source: Position,
    *,
    quantity: str,
) -> None:
    """Give the request a bill of its own at 250 per unit."""
    await service.create_request_boq(
        request.id,
        VariationBOQCreate(
            source_positions=[VariationBOQSourcePosition(position_id=source.id, quantity=Decimal(quantity))]
        ),
    )


class TestSubmittingFreezesThePricingState:
    @pytest.mark.asyncio
    async def test_the_bill_and_its_total_are_recorded_at_submission(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        source = await _make_source_position(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)
        await _price_the_variation(session, service, request, source, quantity="30")

        submitted = await service.transition_variation_request(request.id, "submitted", user_id=ACTOR)

        assert submitted.submitted_boq_id is not None
        assert submitted.submitted_boq_total == Decimal("7500.00")

    @pytest.mark.asyncio
    async def test_a_request_with_no_bill_of_its_own_records_neither(self, session: AsyncSession) -> None:
        # Priced by the headline alone, which is a legitimate way to run a
        # small variation. Both columns stay NULL to say so, rather than
        # copying the headline in and making it look like a priced state.
        project = await _make_project(session)
        request = await _make_request(session, project)
        service = VariationsService(session)

        submitted = await service.transition_variation_request(request.id, "submitted", user_id=ACTOR)

        assert submitted.submitted_boq_id is None
        assert submitted.submitted_boq_total is None

    @pytest.mark.asyncio
    async def test_revising_the_bill_afterwards_does_not_move_the_frozen_total(self, session: AsyncSession) -> None:
        # The claim the whole column exists for. Negotiation happens after
        # submission, so a total recomputed at approval time would answer
        # "what does the bill say now" when the record has to answer "what
        # was the approver looking at".
        project = await _make_project(session)
        source = await _make_source_position(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)
        await _price_the_variation(session, service, request, source, quantity="30")
        await service.transition_variation_request(request.id, "submitted", user_id=ACTOR)

        boq, _reason = await service.resolve_request_boq(request.id)
        assert boq is not None
        line = (await service.get_request_boq_view(request.id))["traces"][0]
        position = await session.get(Position, line.position_id)
        assert position is not None
        position.quantity = "20"
        position.total = "5000"
        await session.flush()

        approved = await service.transition_variation_request(request.id, "approved", user_id=ACTOR)
        assert approved.submitted_boq_total == Decimal("7500.00")


class TestSubmittingKeepsTheBillAsItStood:
    """The lines behind the frozen total, kept where the bill keeps its history.

    ``submitted_boq_total`` says what figure the approver was given. Once the
    bill has been revised, nothing else said which lines made that figure up,
    so a price could be agreed against the record but not defended from it.
    Submission now writes a snapshot into the bill's own version history, the
    same copy the editor's history panel lists, and the request names it.
    """

    @pytest.mark.asyncio
    async def test_submission_writes_a_snapshot_of_the_bill_and_names_it(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        source = await _make_source_position(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)
        await _price_the_variation(session, service, request, source, quantity="30")

        submitted = await service.transition_variation_request(request.id, "submitted", user_id=ACTOR)

        assert submitted.submitted_boq_snapshot_id is not None
        snapshot = await session.get(BOQSnapshot, submitted.submitted_boq_snapshot_id)
        assert snapshot is not None
        assert snapshot.boq_id == submitted.submitted_boq_id
        # Named after the request, so a reader of the bill's history can tell
        # it from a copy somebody took by hand, and stamped with who submitted.
        assert request.code in snapshot.name
        assert snapshot.created_by == uuid.UUID(ACTOR)
        lines = snapshot.snapshot_data["positions"]
        assert [(Decimal(line["quantity"]), Decimal(line["unit_rate"])) for line in lines] == [
            (Decimal("30"), Decimal("250")),
        ]
        # The lines add up to the total frozen beside them: one pricing state,
        # recorded twice, in two forms that agree.
        assert sum(Decimal(line["total"]) for line in lines) == submitted.submitted_boq_total

    @pytest.mark.asyncio
    async def test_revising_the_bill_afterwards_leaves_the_snapshot_as_it_was(self, session: AsyncSession) -> None:
        # The claim the snapshot exists for, and the same revision the frozen
        # total is tested against above: 30 m3 submitted, re-measured to 20
        # during negotiation. The live bill says 20; the record of what was
        # submitted still says 30.
        project = await _make_project(session)
        source = await _make_source_position(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)
        await _price_the_variation(session, service, request, source, quantity="30")
        submitted = await service.transition_variation_request(request.id, "submitted", user_id=ACTOR)
        snapshot_id = submitted.submitted_boq_snapshot_id
        assert snapshot_id is not None

        line = (await service.get_request_boq_view(request.id))["traces"][0]
        position = await session.get(Position, line.position_id)
        assert position is not None
        position.quantity = "20"
        position.total = "5000"
        await session.flush()

        # The live bill moved, which is the control: a snapshot that agreed
        # with the bill here would be a view of it, not a copy.
        assert (await service.get_request_boq_view(request.id))["grand_total"] == Decimal("5000.00")
        kept = await session.get(BOQSnapshot, snapshot_id)
        assert kept is not None
        await session.refresh(kept)
        assert [Decimal(line["quantity"]) for line in kept.snapshot_data["positions"]] == [Decimal("30")]
        # And it sits in the bill's own history, where the editor lists it,
        # rather than in a store of this module's own.
        boq, _reason = await service.resolve_request_boq(request.id)
        assert boq is not None
        history = await BOQService(session).list_snapshots(boq.id)
        assert [snap.id for snap in history] == [snapshot_id]

    @pytest.mark.asyncio
    async def test_a_request_with_no_bill_has_nothing_to_keep(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        request = await _make_request(session, project)
        service = VariationsService(session)

        submitted = await service.transition_variation_request(request.id, "submitted", user_id=ACTOR)

        assert submitted.status == "submitted"
        assert submitted.submitted_boq_snapshot_id is None

    @pytest.mark.asyncio
    async def test_an_actor_that_is_not_an_id_is_recorded_as_nobody_rather_than_refused(
        self, session: AsyncSession
    ) -> None:
        # Actors reach the service as strings and a script may name itself.
        # The snapshot's author column takes a user id; a name is not one, and
        # the submission must not fail over who pressed the button when the
        # activity log already has that.
        project = await _make_project(session)
        source = await _make_source_position(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)
        await _price_the_variation(session, service, request, source, quantity="30")

        submitted = await service.transition_variation_request(request.id, "submitted", user_id="nightly-import")

        assert submitted.submitted_boq_snapshot_id is not None
        snapshot = await session.get(BOQSnapshot, submitted.submitted_boq_snapshot_id)
        assert snapshot is not None
        assert snapshot.created_by is None


class TestApprovingRecordsWhatWasAgreedAndWhy:
    @pytest.mark.asyncio
    async def test_with_a_bill_and_no_named_amount_the_bill_total_is_the_agreement(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        source = await _make_source_position(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)
        await _price_the_variation(session, service, request, source, quantity="30")
        await service.transition_variation_request(request.id, "submitted", user_id=ACTOR)

        approved = await service.transition_variation_request(request.id, "approved", user_id=ACTOR)

        assert approved.agreed_cost_impact == Decimal("7500.00")
        assert approved.agreed_basis == AGREED_BASIS_PRICED_BOQ
        # And emphatically not the headline it was raised with, which is the
        # implicit inheritance this replaces.
        assert approved.estimated_cost_impact == Decimal("12000")

    @pytest.mark.asyncio
    async def test_with_no_bill_the_headline_is_the_agreement_and_says_so(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        request = await _make_request(session, project)
        service = VariationsService(session)
        await service.transition_variation_request(request.id, "submitted", user_id=ACTOR)

        approved = await service.transition_variation_request(request.id, "approved", user_id=ACTOR)

        assert approved.agreed_cost_impact == Decimal("12000")
        # The number is the same one it would have inherited before. The
        # difference is that the record now says that is what happened.
        assert approved.agreed_basis == AGREED_BASIS_HEADLINE

    @pytest.mark.asyncio
    async def test_a_negotiated_amount_needs_a_reason_when_it_departs(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        source = await _make_source_position(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)
        await _price_the_variation(session, service, request, source, quantity="30")
        await service.transition_variation_request(request.id, "submitted", user_id=ACTOR)

        with pytest.raises(HTTPException) as excinfo:
            await service.transition_variation_request(
                request.id,
                "approved",
                user_id=ACTOR,
                agreed_cost_impact=Decimal("7200"),
            )
        assert excinfo.value.status_code == 422

        # The status is untouched, so the approver can send the same decision
        # again with the reason rather than finding the request half-moved.
        still = await service.get_request(request.id)
        assert still.status == "submitted"

    @pytest.mark.asyncio
    async def test_a_negotiated_amount_with_a_reason_is_recorded_as_negotiated(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        source = await _make_source_position(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)
        await _price_the_variation(session, service, request, source, quantity="30")
        await service.transition_variation_request(request.id, "submitted", user_id=ACTOR)

        approved = await service.transition_variation_request(
            request.id,
            "approved",
            user_id=ACTOR,
            agreed_cost_impact=Decimal("7200"),
            agreed_variance_note="Settled at 7,200 in the 14 August commercial meeting.",
        )

        assert approved.agreed_cost_impact == Decimal("7200.00")
        assert approved.agreed_basis == AGREED_BASIS_NEGOTIATED
        assert "7,200" in approved.agreed_variance_note
        # The pricing state it departed from is still there to depart from,
        # which is what makes the difference auditable rather than merely
        # recorded.
        assert approved.submitted_boq_total == Decimal("7500.00")

    @pytest.mark.asyncio
    async def test_naming_the_bill_total_itself_needs_no_reason(self, session: AsyncSession) -> None:
        # The control for the refusal above: the gate is about a DIFFERENCE,
        # not about the act of naming an amount.
        project = await _make_project(session)
        source = await _make_source_position(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)
        await _price_the_variation(session, service, request, source, quantity="30")
        await service.transition_variation_request(request.id, "submitted", user_id=ACTOR)

        approved = await service.transition_variation_request(
            request.id,
            "approved",
            user_id=ACTOR,
            agreed_cost_impact=Decimal("7500"),
        )
        assert approved.agreed_basis == AGREED_BASIS_NEGOTIATED


class TestTheAgreedValueFlowsWithoutBeingReEntered:
    @pytest.mark.asyncio
    async def test_promotion_carries_the_agreed_amount_into_the_order(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        source = await _make_source_position(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)
        await _price_the_variation(session, service, request, source, quantity="30")
        await service.transition_variation_request(request.id, "submitted", user_id=ACTOR)
        await service.transition_variation_request(
            request.id,
            "approved",
            user_id=ACTOR,
            agreed_cost_impact=Decimal("7200"),
            agreed_variance_note="Settled at 7,200 in the 14 August commercial meeting.",
        )

        order = await service.convert_vr_to_vo(
            request.id,
            VariationOrderCreate(project_id=project.id, currency="EUR"),
            user_id=ACTOR,
        )

        # Not 12,000 and not 7,500: the amount somebody actually agreed to.
        assert order.final_cost_impact == Decimal("7200.00")

    @pytest.mark.asyncio
    async def test_a_request_approved_before_any_of_this_still_promotes(self, session: AsyncSession) -> None:
        # Backwards compatibility, and it has to be tested from the state a
        # migrated row is actually in: approved, with no agreement recorded,
        # because the column did not exist when the decision was taken. The
        # headline is the only figure such a row has ever had.
        project = await _make_project(session)
        request = await _make_request(session, project)
        request.status = "approved"
        request.agreed_cost_impact = None
        request.agreed_basis = ""
        await session.flush()
        service = VariationsService(session)

        order = await service.convert_vr_to_vo(
            request.id,
            VariationOrderCreate(project_id=project.id, currency="EUR"),
            user_id=ACTOR,
        )

        assert order.final_cost_impact == Decimal("12000.00")

    @pytest.mark.asyncio
    async def test_an_order_issued_at_its_own_figure_still_wins(self, session: AsyncSession) -> None:
        # The agreed value is a default, not an override. An Engineer issuing
        # the order at a different figure is a decision of its own and the
        # promotion must not quietly replace it.
        project = await _make_project(session)
        request = await _make_request(session, project)
        service = VariationsService(session)
        await service.transition_variation_request(request.id, "submitted", user_id=ACTOR)
        await service.transition_variation_request(request.id, "approved", user_id=ACTOR)

        order = await service.convert_vr_to_vo(
            request.id,
            VariationOrderCreate(
                project_id=project.id,
                currency="EUR",
                final_cost_impact=Decimal("9000"),
            ),
            user_id=ACTOR,
        )

        assert order.final_cost_impact == Decimal("9000.00")


class TestTheMirroredChangeOrderIsNotASecondPrice:
    """One commercial decision, one number, all the way down."""

    @pytest.mark.asyncio
    async def test_the_mirrored_order_cannot_be_repriced_on_its_own(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        request = await _make_request(session, project)
        service = VariationsService(session)
        await service.transition_variation_request(request.id, "submitted", user_id=ACTOR)
        await service.transition_variation_request(
            request.id,
            "approved",
            user_id=ACTOR,
            agreed_cost_impact=Decimal("7200"),
        )
        order = await service.convert_vr_to_vo(
            request.id,
            VariationOrderCreate(project_id=project.id, currency="EUR"),
            user_id=ACTOR,
        )
        assert order.reference_change_order_id is not None
        mirrored = await session.get(ChangeOrder, order.reference_change_order_id)
        assert mirrored is not None

        with pytest.raises(HTTPException) as excinfo:
            await ChangeOrderService(session).update_order(
                mirrored.id,
                ChangeOrderUpdate(cost_impact="9999"),
                user_id=ACTOR,
            )
        assert excinfo.value.status_code == 409
        # It says where the number does live, because a refusal that only
        # says no leaves the user looking for a permission they do not lack.
        assert str(order.id) in str(excinfo.value.detail)

    @pytest.mark.asyncio
    async def test_everything_that_is_its_own_business_stays_editable(self, session: AsyncSession) -> None:
        # The control. A guard that held the whole record would make the
        # mirrored order read-only, which is not what the chain claims to own.
        project = await _make_project(session)
        request = await _make_request(session, project)
        service = VariationsService(session)
        await service.transition_variation_request(request.id, "submitted", user_id=ACTOR)
        await service.transition_variation_request(request.id, "approved", user_id=ACTOR)
        order = await service.convert_vr_to_vo(
            request.id,
            VariationOrderCreate(project_id=project.id, currency="EUR"),
            user_id=ACTOR,
        )
        mirrored = await session.get(ChangeOrder, order.reference_change_order_id)
        assert mirrored is not None

        updated = await ChangeOrderService(session).update_order(
            mirrored.id,
            ChangeOrderUpdate(title="Retaining wall at grid F, as agreed"),
            user_id=ACTOR,
        )
        assert updated.title == "Retaining wall at grid F, as agreed"

    @pytest.mark.asyncio
    async def test_the_currency_stays_editable_and_that_is_deliberate(self, session: AsyncSession) -> None:
        # Named because it looks like an omission. A variation raised in a
        # currency the contract does not use reaches the contract only through
        # the mirror, and the PATCH that links the mirror is the same one that
        # puts it in the contract currency. Holding it here would leave the
        # amount arriving by neither route; test_variation_mirror_contract_
        # double_post covers that path from the other end.
        project = await _make_project(session)
        request = await _make_request(session, project)
        service = VariationsService(session)
        await service.transition_variation_request(request.id, "submitted", user_id=ACTOR)
        await service.transition_variation_request(request.id, "approved", user_id=ACTOR)
        order = await service.convert_vr_to_vo(
            request.id,
            VariationOrderCreate(project_id=project.id, currency="GBP"),
            user_id=ACTOR,
        )
        mirrored = await session.get(ChangeOrder, order.reference_change_order_id)
        assert mirrored is not None

        updated = await ChangeOrderService(session).update_order(
            mirrored.id,
            ChangeOrderUpdate(currency="EUR"),
            user_id=ACTOR,
        )
        assert updated.currency == "EUR"

    @pytest.mark.asyncio
    async def test_a_standalone_change_order_is_priced_where_it_always_was(self, session: AsyncSession) -> None:
        # No variation behind it, so there is no other price to contradict and
        # its own cost impact is the only decision there is.
        from app.modules.changeorders.schemas import ChangeOrderCreate

        project = await _make_project(session)
        co_service = ChangeOrderService(session)
        standalone = await co_service.create_order(
            ChangeOrderCreate(
                project_id=project.id,
                title="Extra site lighting",
                reason_category="design_change",
                currency="EUR",
                cost_impact="4000",
            )
        )

        updated = await co_service.update_order(
            standalone.id,
            ChangeOrderUpdate(cost_impact="4500"),
            user_id=ACTOR,
        )
        assert Decimal(str(updated.cost_impact)) == Decimal("4500")

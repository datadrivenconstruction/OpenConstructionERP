# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""DB-backed tests for a variation request's own bill of quantities.

A variation request could only ever carry two headline numbers, an estimated
cost and a number of days. Issue #435 lets it own a dedicated bill instead,
holding only the scope that variation changes, priced by the ordinary BOQ
machinery and traceable back to the contract lines and estimate positions it
derives from.

Two claims are worth more than the feature itself, and both are tested here.

The first is that nothing changed for anybody who does not use it. A request
with no bill answers exactly what it answered before, and the column that
carries the link is NULL on every row that existed before it, so the three
places that now exclude variation bills exclude nothing that is there today.

The second is the regression this could have shipped. ``_resolve_writeback_boq``
in the change-orders module refuses to guess between two unlocked bills on one
project, and said so in a docstring that already named this feature as the
thing about to produce them. Without the exclusion, opening one variation bill
would turn every subsequent change-order approval on that project into a 409.

These run against real PostgreSQL rather than a stubbed session because every
claim is about what a *query* returns; a stub would only restate the service's
own branching back at it.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

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
from app.core.boq_target import resolve_project_boq
from app.modules.boq.models import BOQ, Position
from app.modules.boq.repository import BOQRepository
from app.modules.boq.service import BOQService
from app.modules.changeorders.models import ChangeOrder, ChangeOrderItem
from app.modules.changeorders.service import ChangeOrderService
from app.modules.contracts.models import Contract, ContractLine
from app.modules.projects.models import Project
from app.modules.variations.models import VariationBOQTrace, VariationRequest
from app.modules.variations.schemas import (
    VariationBOQCreate,
    VariationBOQSourceContractLine,
    VariationBOQSourcePosition,
)
from app.modules.variations.service import VariationsService
from tests._pg import transactional_session

ACTOR = "33333333-3333-3333-3333-333333333333"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Isolated PostgreSQL session, FK triggers off, rolled back on teardown."""
    async with transactional_session(disable_fks=True) as sess:
        yield sess


# ── Seed helpers ────────────────────────────────────────────────────────────


async def _make_project(session: AsyncSession, name: str = "Riverside Depot") -> Project:
    project = Project(
        name=name,
        owner_id=uuid.uuid4(),
        currency="EUR",
        budget_estimate="2000000",
    )
    session.add(project)
    await session.flush()
    return project


async def _make_boq(session: AsyncSession, project: Project, name: str = "Tender estimate") -> BOQ:
    boq = BOQ(project_id=project.id, name=name)
    session.add(boq)
    await session.flush()
    return boq


async def _make_position(
    session: AsyncSession,
    boq: BOQ,
    *,
    ordinal: str = "0010",
    description: str = "Reinforced concrete wall C30/37",
    unit: str = "m3",
    quantity: str = "100",
    unit_rate: str = "250",
) -> Position:
    position = Position(
        boq_id=boq.id,
        ordinal=ordinal,
        description=description,
        unit=unit,
        quantity=quantity,
        unit_rate=unit_rate,
        total=str(Decimal(quantity) * Decimal(unit_rate)),
        classification={"din276": "331"},
        source="manual",
        cad_element_ids=[],
    )
    session.add(position)
    await session.flush()
    return position


async def _make_request(session: AsyncSession, project: Project, *, code: str = "VR-0001") -> VariationRequest:
    request = VariationRequest(
        project_id=project.id,
        code=code,
        title="Additional retaining wall at grid F",
        estimated_cost_impact=Decimal("12000"),
        estimated_schedule_days=5,
        currency="EUR",
    )
    session.add(request)
    await session.flush()
    return request


async def _make_contract_line(
    session: AsyncSession,
    project: Project,
    *,
    quantity: str = "40",
    unit_rate: str = "300",
) -> tuple[Contract, ContractLine]:
    contract = Contract(
        code="C-001",
        title="Main works",
        project_id=project.id,
        currency="EUR",
        total_value=Decimal("1500000"),
    )
    session.add(contract)
    await session.flush()
    line = ContractLine(
        contract_id=contract.id,
        code="SOV-020",
        description="Retaining walls",
        unit="m3",
        quantity=Decimal(quantity),
        unit_rate=Decimal(unit_rate),
        total_value=Decimal(quantity) * Decimal(unit_rate),
    )
    session.add(line)
    await session.flush()
    return contract, line


# ── A request with no bill is untouched ─────────────────────────────────────


class TestRequestWithoutABill:
    """The state every request was in before this feature, and most still are."""

    @pytest.mark.asyncio
    async def test_the_view_says_it_has_no_bill_and_keeps_the_headline(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        request = await _make_request(session, project)

        view = await VariationsService(session).get_request_boq_view(request.id)

        assert view["has_boq"] is False
        assert view["estimated_cost_impact"] == Decimal("12000")
        # No bill means no priced total, which is not the same statement as
        # "priced at nothing" - so the money keys are absent, not zero.
        assert "grand_total" not in view

    @pytest.mark.asyncio
    async def test_the_resolver_says_no_bill_rather_than_guessing_at_a_project_one(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        # A perfectly good project bill exists. It is not this request's.
        await _make_boq(session, project)
        request = await _make_request(session, project)

        boq, reason = await VariationsService(session).resolve_request_boq(request.id)

        assert boq is None
        assert reason == "no_active_boq"

    @pytest.mark.asyncio
    async def test_adopting_a_total_that_does_not_exist_is_refused(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        request = await _make_request(session, project)

        with pytest.raises(HTTPException) as excinfo:
            await VariationsService(session).adopt_request_boq_total(request.id)

        assert excinfo.value.status_code == 404
        assert excinfo.value.detail["error"] == "no_variation_boq"


# ── A request with a bill prices from it ────────────────────────────────────


class TestRequestWithABill:
    @pytest.mark.asyncio
    async def test_the_bill_is_priced_from_its_own_lines(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        source_boq = await _make_boq(session, project)
        source = await _make_position(session, source_boq, quantity="100", unit_rate="250")
        request = await _make_request(session, project)
        service = VariationsService(session)

        await service.create_request_boq(
            request.id,
            VariationBOQCreate(
                source_positions=[
                    # The variation re-measures 30 of the 100 contracted m3.
                    VariationBOQSourcePosition(position_id=source.id, quantity=Decimal("30")),
                ]
            ),
        )
        view = await service.get_request_boq_view(request.id)

        assert view["has_boq"] is True
        assert view["position_count"] == 1
        assert view["grand_total"] == Decimal("7500.00")
        # The headline forecast is left exactly where the author put it. The
        # bill disagreeing with it is the finding, not a reason to overwrite.
        assert view["estimated_cost_impact"] == Decimal("12000")
        assert view["estimate_matches_boq"] is False

    @pytest.mark.asyncio
    async def test_a_line_seeded_from_a_contract_line_carries_its_rate(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        _contract, line = await _make_contract_line(session, project, quantity="40", unit_rate="300")
        request = await _make_request(session, project)
        service = VariationsService(session)

        await service.create_request_boq(
            request.id,
            VariationBOQCreate(
                source_contract_lines=[
                    VariationBOQSourceContractLine(contract_line_id=line.id, quantity=Decimal("10")),
                ]
            ),
        )
        view = await service.get_request_boq_view(request.id)

        assert view["grand_total"] == Decimal("3000.00")

    @pytest.mark.asyncio
    async def test_adopting_makes_the_priced_total_the_headline(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        source_boq = await _make_boq(session, project)
        source = await _make_position(session, source_boq, quantity="100", unit_rate="250")
        request = await _make_request(session, project)
        service = VariationsService(session)
        await service.create_request_boq(
            request.id,
            VariationBOQCreate(
                source_positions=[VariationBOQSourcePosition(position_id=source.id, quantity=Decimal("30"))]
            ),
        )

        updated = await service.adopt_request_boq_total(request.id, user_id=ACTOR)

        assert Decimal(str(updated.estimated_cost_impact)) == Decimal("7500.00")
        view = await service.get_request_boq_view(request.id)
        assert view["estimate_matches_boq"] is True

    @pytest.mark.asyncio
    async def test_a_decided_request_will_not_have_its_figure_replaced(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        source_boq = await _make_boq(session, project)
        source = await _make_position(session, source_boq)
        request = await _make_request(session, project)
        service = VariationsService(session)
        await service.create_request_boq(
            request.id,
            VariationBOQCreate(source_positions=[VariationBOQSourcePosition(position_id=source.id)]),
        )
        request.status = "approved"
        await session.flush()

        with pytest.raises(HTTPException) as excinfo:
            await service.adopt_request_boq_total(request.id)

        assert excinfo.value.status_code == 409
        assert excinfo.value.detail["error"] == "variation_request_decided"

    @pytest.mark.asyncio
    async def test_a_second_bill_is_refused_because_a_revision_is_what_was_meant(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        request = await _make_request(session, project)
        service = VariationsService(session)
        await service.create_request_boq(request.id, VariationBOQCreate())

        with pytest.raises(HTTPException) as excinfo:
            await service.create_request_boq(request.id, VariationBOQCreate())

        assert excinfo.value.status_code == 409
        assert excinfo.value.detail["error"] == "variation_boq_exists"


# ── Traceability ────────────────────────────────────────────────────────────


class TestTraceability:
    @pytest.mark.asyncio
    async def test_every_seeded_line_resolves_back_to_what_it_came_from(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        source_boq = await _make_boq(session, project)
        source = await _make_position(session, source_boq)
        contract, line = await _make_contract_line(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)

        boq = await service.create_request_boq(
            request.id,
            VariationBOQCreate(
                source_positions=[VariationBOQSourcePosition(position_id=source.id, note="re-measured")],
                source_contract_lines=[VariationBOQSourceContractLine(contract_line_id=line.id)],
            ),
        )

        traces = (
            (await session.execute(select(VariationBOQTrace).where(VariationBOQTrace.boq_id == boq.id))).scalars().all()
        )
        assert len(traces) == 2
        by_origin = {trace.origin: trace for trace in traces}
        assert by_origin["boq_position"].source_position_id == source.id
        assert by_origin["boq_position"].source_boq_id == source_boq.id
        assert by_origin["boq_position"].note == "re-measured"
        assert by_origin["contract_line"].contract_line_id == line.id
        assert by_origin["contract_line"].contract_id == contract.id

        # Each trace names a line that really is in the variation's bill.
        position_ids = {
            row.id
            for row in ((await session.execute(select(Position).where(Position.boq_id == boq.id))).scalars().all())
        }
        assert {trace.position_id for trace in traces} == position_ids

    @pytest.mark.asyncio
    async def test_the_view_reports_the_trace_and_flags_an_untraced_line(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        source_boq = await _make_boq(session, project)
        source = await _make_position(session, source_boq)
        request = await _make_request(session, project)
        service = VariationsService(session)
        boq = await service.create_request_boq(
            request.id,
            VariationBOQCreate(source_positions=[VariationBOQSourcePosition(position_id=source.id)]),
        )
        # A line added by hand in the BOQ editor afterwards - the ordinary way
        # a variation grows scope nobody estimated or contracted before.
        session.add(
            Position(
                boq_id=boq.id,
                ordinal="0020",
                description="Temporary propping",
                unit="pcs",
                quantity="4",
                unit_rate="500",
                total="2000",
                classification={},
                source="manual",
                cad_element_ids=[],
                sort_order=2,
            )
        )
        await session.flush()

        view = await service.get_request_boq_view(request.id)

        assert len(view["traces"]) == 1
        flagged = [check for check in view["checks"] if check["rule_id"] == "variations.boq_lines_are_traced"]
        assert len(flagged) == 1
        assert flagged[0]["passed"] is False

    @pytest.mark.asyncio
    async def test_scope_from_another_project_is_refused_rather_than_skipped(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        other = await _make_project(session, name="Someone else's job")
        other_boq = await _make_boq(session, other)
        foreign = await _make_position(session, other_boq)
        request = await _make_request(session, project)

        with pytest.raises(HTTPException) as excinfo:
            await VariationsService(session).create_request_boq(
                request.id,
                VariationBOQCreate(source_positions=[VariationBOQSourcePosition(position_id=foreign.id)]),
            )

        assert excinfo.value.status_code == 400
        assert excinfo.value.detail["error"] == "source_position_not_in_project"


# ── What the screen actually sends ──────────────────────────────────────────


class TestTheBodyTheScreenSends:
    """The two bodies the variations page posts, before and after Issue #435.

    Everything above tests the endpoint. These test the call, because the call
    is where the defect was: the page opened every variation bill with an empty
    body, so the only writer of the trace table was unreachable from the
    product and `variations.boq_lines_are_traced` reported that correctly on
    every line a surveyor then typed.
    """

    @staticmethod
    async def _add_line(
        session: AsyncSession,
        contract: Contract,
        *,
        code: str,
        description: str,
        unit: str = "m3",
        quantity: str = "10",
        unit_rate: str = "300",
    ) -> ContractLine:
        """A further schedule-of-values line on an existing contract."""
        line = ContractLine(
            contract_id=contract.id,
            code=code,
            description=description,
            unit=unit,
            quantity=Decimal(quantity),
            unit_rate=Decimal(unit_rate),
            total_value=Decimal(quantity) * Decimal(unit_rate),
        )
        session.add(line)
        await session.flush()
        return line

    @pytest.mark.asyncio
    async def test_the_empty_body_leaves_every_line_untraced(self, session: AsyncSession) -> None:
        """The body the page used to send, priced the way a surveyor prices it.

        An empty bill is not itself the finding: the finding arrives when the
        scope is typed into it, because there was no moment at which any of it
        could acquire provenance.
        """
        project = await _make_project(session)
        request = await _make_request(session, project)
        service = VariationsService(session)

        boq = await service.create_request_boq(request.id, VariationBOQCreate())
        for index, description in enumerate(("Retaining wall extension", "Additional drainage"), start=1):
            session.add(
                Position(
                    boq_id=boq.id,
                    ordinal=f"{index * 10:04d}",
                    description=description,
                    unit="m3",
                    quantity="10",
                    unit_rate="300",
                    total="3000",
                    classification={},
                    source="manual",
                    cad_element_ids=[],
                    sort_order=index,
                )
            )
        await session.flush()

        view = await service.get_request_boq_view(request.id)

        assert view["traces"] == []
        # The denominator, printed next to the verdict on purpose: the rule
        # below is failing over two priced lines rather than passing over none.
        assert view["position_count"] == 2
        flagged = [check for check in view["checks"] if check["rule_id"] == "variations.boq_lines_are_traced"]
        assert len(flagged) == 2
        assert all(check["passed"] is False for check in flagged)

    @pytest.mark.asyncio
    async def test_naming_the_contract_lines_traces_every_line_of_the_bill(self, session: AsyncSession) -> None:
        """The body the page sends now, over the same priced scope."""
        project = await _make_project(session)
        contract, first = await _make_contract_line(session, project)
        second = await self._add_line(
            session,
            contract,
            code="SOV-030",
            description="Additional drainage",
        )
        request = await _make_request(session, project)
        service = VariationsService(session)

        boq = await service.create_request_boq(
            request.id,
            VariationBOQCreate(
                source_contract_lines=[
                    VariationBOQSourceContractLine(contract_line_id=first.id, quantity=Decimal("10")),
                    VariationBOQSourceContractLine(contract_line_id=second.id),
                ]
            ),
        )

        view = await service.get_request_boq_view(request.id)

        assert boq.id == view["boq_id"]
        assert len(view["traces"]) == 2
        assert {trace.contract_line_id for trace in view["traces"]} == {first.id, second.id}
        assert {trace.contract_id for trace in view["traces"]} == {contract.id}
        # Same population as the test above, so the two verdicts are comparable.
        assert view["position_count"] == 2
        flagged = [check for check in view["checks"] if check["rule_id"] == "variations.boq_lines_are_traced"]
        assert flagged == []

    @pytest.mark.asyncio
    async def test_a_line_with_no_unit_is_not_a_line_the_rule_ever_judges(self, session: AsyncSession) -> None:
        """Why the count has to be read next to the verdict.

        The rule skips a line carrying no unit, because a row with no unit is a
        heading rather than money, and the bill view counts priced lines the
        same way. So a bill whose lines all lack units reports no findings while
        tracing nothing at all, and "no findings" and "everything traced" are
        the same output. A schedule-of-values line whose unit is NULL seeds
        exactly such a row, which is why the picker warns about one.
        """
        project = await _make_project(session)
        request = await _make_request(session, project)
        service = VariationsService(session)

        boq = await service.create_request_boq(request.id, VariationBOQCreate())
        session.add(
            Position(
                boq_id=boq.id,
                ordinal="0010",
                description="Provisional sum, to be measured",
                unit="",
                quantity="1",
                unit_rate="5000",
                total="5000",
                classification={},
                source="manual",
                cad_element_ids=[],
                sort_order=1,
            )
        )
        await session.flush()

        view = await service.get_request_boq_view(request.id)

        assert view["traces"] == []
        assert view["position_count"] == 0
        assert [check for check in view["checks"] if check["rule_id"] == "variations.boq_lines_are_traced"] == []


# ── The variation bill stays out of the project's own reckoning ─────────────


class TestVariationBillIsNotAProjectBill:
    """A deliberate decision, not an accident: see the decision record.

    A variation's priced scope is not part of the project estimate until the
    variation is agreed, and the register an estimator opens to see "the
    project's bills" is not the place to discover money that nobody has agreed
    to yet. It is reached from the request that owns it, and by id like any
    other bill.
    """

    @pytest.mark.asyncio
    async def test_it_is_absent_from_the_projects_bill_register(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        project_bill = await _make_boq(session, project, name="Tender estimate")
        request = await _make_request(session, project)
        variation_bill = await VariationsService(session).create_request_boq(request.id, VariationBOQCreate())

        rows, total = await BOQRepository(session).list_for_project(project.id)

        assert [row.id for row in rows] == [project_bill.id]
        assert total == 1
        # And it really is a bill on this project - the exclusion is a filter,
        # not a different project_id.
        assert variation_bill.project_id == project.id

    @pytest.mark.asyncio
    async def test_the_shared_resolver_does_not_offer_it_as_a_candidate(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        project_bill = await _make_boq(session, project)
        request = await _make_request(session, project)
        await VariationsService(session).create_request_boq(request.id, VariationBOQCreate())

        resolved, reason = await resolve_project_boq(session, project.id)

        assert reason is None
        assert resolved is not None
        assert resolved.id == project_bill.id

    @pytest.mark.asyncio
    async def test_a_change_order_still_knows_where_to_write(self, session: AsyncSession) -> None:
        """The regression this feature could have shipped.

        ``_resolve_writeback_boq`` refuses to guess between two unlocked bills.
        Before the exclusion, one variation bill was enough to make every
        change-order approval on the project ambiguous.
        """
        project = await _make_project(session)
        project_bill = await _make_boq(session, project)
        request = await _make_request(session, project)
        await VariationsService(session).create_request_boq(request.id, VariationBOQCreate())

        order = ChangeOrder(
            project_id=project.id,
            code="CO-001",
            title="Extra propping",
            status="submitted",
            cost_impact=Decimal("2000"),
            currency="EUR",
        )
        session.add(order)
        await session.flush()
        session.add(
            ChangeOrderItem(
                change_order_id=order.id,
                description="Propping",
                change_type="added",
                new_quantity=Decimal("1"),
                unit="lsum",
                new_rate=Decimal("2000"),
                cost_delta=Decimal("2000"),
            )
        )
        await session.flush()

        resolved, reason = await ChangeOrderService(session)._resolve_writeback_boq(project.id, None)

        assert reason is None
        assert resolved is not None
        assert resolved.id == project_bill.id


# ── Revisions ───────────────────────────────────────────────────────────────


class TestRevisions:
    @pytest.mark.asyncio
    async def test_a_revision_of_a_variation_bill_is_still_the_requests_bill(self, session: AsyncSession) -> None:
        """Without carrying the link, a revision would launder the bill.

        ``duplicate_boq`` is what ``POST /boqs/{id}/create-revision/`` calls.
        A copy that dropped the link would become a bill of the project at
        large - listed in the project register, and a candidate for the
        change-order writeback again.
        """
        project = await _make_project(session)
        request = await _make_request(session, project)
        service = VariationsService(session)
        original = await service.create_request_boq(request.id, VariationBOQCreate())

        boq_service = BOQService(session)
        revision = await boq_service.duplicate_boq(original.id)
        revision_id = revision.id
        await boq_service.boq_repo.update_fields(revision_id, parent_estimate_id=original.id)

        refreshed = await boq_service.get_boq(revision_id)
        assert refreshed.variation_request_id == request.id

        # The chain head is the current bill, and it is the revision.
        current, reason = await service.resolve_request_boq(request.id)
        assert reason is None
        assert current is not None
        assert current.id == revision_id

        # Still invisible to the project register, both of them.
        rows, total = await BOQRepository(session).list_for_project(project.id)
        assert rows == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_a_forked_revision_chain_is_a_question_not_a_guess(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        request = await _make_request(session, project)
        service = VariationsService(session)
        original = await service.create_request_boq(request.id, VariationBOQCreate())
        boq_service = BOQService(session)
        for _ in range(2):
            copy = await boq_service.duplicate_boq(original.id)
            await boq_service.boq_repo.update_fields(copy.id, parent_estimate_id=original.id)

        current, reason = await service.resolve_request_boq(request.id)

        assert current is None
        assert reason == "ambiguous_boq"

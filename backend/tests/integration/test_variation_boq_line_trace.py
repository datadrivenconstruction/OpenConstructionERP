# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tracing a line that was added to a variation bill after the bill was opened.

Opening a variation request's bill can seed it from named contract
schedule-of-values lines and estimating positions, and each seeded line gets a
provenance row. That was the only moment at which a line could ever acquire
one. The bill is deliberately an ordinary bill - the whole point of Issue #435
is that the BOQ module works on it unchanged - so it grows through the BOQ
editor, and every line typed in there stayed untraced with no route able to
change that.

``variations.boq_lines_are_traced`` reported exactly that, on every such line,
for as long as the line existed. A warning nobody can act on is worse than no
warning, so the claim these tests exist to pin is the pair: the rule fails over
a hand-added line, and passes over the same line once its provenance is
recorded, with the priced population unchanged between the two readings.

The population is asserted next to every verdict on purpose. The rule skips a
line whose unit is empty, so "no findings" and "nothing to find" are the same
output, and a test that only counted findings could go green over a bill it
never judged.

These run against real PostgreSQL because every claim is about what a query
returns - which trace row exists, and what the bill view reads back.
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
import app.modules.contracts.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.users.models  # noqa: F401
import app.modules.variations.models  # noqa: F401
from app.modules.boq.models import BOQ, Position
from app.modules.contracts.models import Contract, ContractLine
from app.modules.projects.models import Project
from app.modules.users.models import User
from app.modules.variations.models import VariationBOQTrace, VariationRequest
from app.modules.variations.router import (
    clear_variation_boq_line_trace,
    set_variation_boq_line_trace,
)
from app.modules.variations.schemas import VariationBOQCreate, VariationBOQLineTraceUpdate
from app.modules.variations.service import VariationsService
from tests._pg import transactional_session

RULE = "variations.boq_lines_are_traced"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Isolated PostgreSQL session, FK triggers off, rolled back on teardown."""
    async with transactional_session(disable_fks=True) as sess:
        yield sess


# ── Seed helpers ────────────────────────────────────────────────────────────


async def _make_project(session: AsyncSession, name: str = "Riverside Depot", owner_id=None) -> Project:
    project = Project(
        name=name,
        owner_id=owner_id or uuid.uuid4(),
        currency="EUR",
        budget_estimate="2000000",
    )
    session.add(project)
    await session.flush()
    return project


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
    code: str = "SOV-020",
    contract_code: str = "C-001",
) -> tuple[Contract, ContractLine]:
    contract = Contract(
        code=contract_code,
        title="Main works",
        project_id=project.id,
        currency="EUR",
        total_value=Decimal("1500000"),
    )
    session.add(contract)
    await session.flush()
    line = ContractLine(
        contract_id=contract.id,
        code=code,
        description="Retaining walls",
        unit="m3",
        quantity=Decimal("40"),
        unit_rate=Decimal("300"),
        total_value=Decimal("12000"),
    )
    session.add(line)
    await session.flush()
    return contract, line


async def _add_line_by_hand(
    session: AsyncSession,
    boq_id: uuid.UUID,
    *,
    ordinal: str = "0010",
    description: str = "Temporary propping",
    unit: str = "m3",
) -> Position:
    """A line typed into the bill in the BOQ editor, the way scope actually grows.

    A real unit, because the rule declines to judge a line without one and a
    unitless line would make every verdict below vacuously quiet.
    """
    position = Position(
        boq_id=boq_id,
        ordinal=ordinal,
        description=description,
        unit=unit,
        quantity="4",
        unit_rate="500",
        total="2000",
        classification={},
        source="manual",
        cad_element_ids=[],
        sort_order=int(ordinal),
    )
    session.add(position)
    await session.flush()
    return position


def _findings(view: dict) -> list[dict]:
    """The rule's findings on this bill. Empty means every priced line traced."""
    return [check for check in view["checks"] if check["rule_id"] == RULE]


async def _trace_rows(session: AsyncSession, boq_id: uuid.UUID) -> list[VariationBOQTrace]:
    stmt = select(VariationBOQTrace).where(VariationBOQTrace.boq_id == boq_id)
    return list((await session.execute(stmt)).scalars().all())


# ── The claim the change exists to make ─────────────────────────────────────


class TestTheRuleBecomesSatisfiable:
    """Both directions over one bill, with the priced population held constant."""

    @pytest.mark.asyncio
    async def test_a_hand_added_line_fails_the_rule_and_passes_once_traced(self, session: AsyncSession) -> None:
        """The whole point of the change, asserted before and after on the same data.

        Nothing about the bill changes between the two readings except the
        trace row, so the difference in verdict cannot be coming from anywhere
        else. ``position_count`` is asserted at both readings for the same
        reason: it is the denominator the verdict is about.
        """
        project = await _make_project(session)
        contract, line = await _make_contract_line(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)

        boq = await service.create_request_boq(request.id, VariationBOQCreate())
        position = await _add_line_by_hand(session, boq.id)

        before = await service.get_request_boq_view(request.id)
        assert before["position_count"] == 1
        assert len(_findings(before)) == 1
        assert _findings(before)[0]["passed"] is False

        await service.set_boq_line_trace(
            request.id,
            position.id,
            VariationBOQLineTraceUpdate(contract_line_id=line.id, note="Re-measured after the ground survey"),
        )

        after = await service.get_request_boq_view(request.id)
        assert after["position_count"] == 1
        assert _findings(after) == []

    @pytest.mark.asyncio
    async def test_the_trace_reads_back_with_the_contract_it_belongs_to(self, session: AsyncSession) -> None:
        """The row records the contract as well as the line, as the seeded path does.

        The contract is not in the payload. It is resolved from the line, so a
        caller cannot file a schedule-of-values line under the wrong contract.
        """
        project = await _make_project(session)
        contract, line = await _make_contract_line(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)

        boq = await service.create_request_boq(request.id, VariationBOQCreate())
        position = await _add_line_by_hand(session, boq.id)

        trace = await service.set_boq_line_trace(
            request.id, position.id, VariationBOQLineTraceUpdate(contract_line_id=line.id)
        )

        assert trace.origin == "contract_line"
        assert trace.contract_line_id == line.id
        assert trace.contract_id == contract.id
        assert trace.variation_request_id == request.id
        assert trace.boq_id == boq.id

        view = await service.get_request_boq_view(request.id)
        assert [row.position_id for row in view["traces"]] == [position.id]

    @pytest.mark.asyncio
    async def test_an_estimating_position_traces_the_line_just_as_well(self, session: AsyncSession) -> None:
        """Provenance for the money, where the scope was estimated but never contracted.

        The rule accepts either reference, so this has to satisfy it too, or
        new scope priced off the estimate would stay permanently flagged.
        """
        project = await _make_project(session)
        estimate = BOQ(project_id=project.id, name="Tender estimate")
        session.add(estimate)
        await session.flush()
        source = await _add_line_by_hand(session, estimate.id, description="Reinforced concrete wall C30/37")
        request = await _make_request(session, project)
        service = VariationsService(session)

        boq = await service.create_request_boq(request.id, VariationBOQCreate())
        position = await _add_line_by_hand(session, boq.id)

        trace = await service.set_boq_line_trace(
            request.id, position.id, VariationBOQLineTraceUpdate(source_position_id=source.id)
        )

        assert trace.origin == "boq_position"
        assert trace.source_position_id == source.id
        assert trace.source_boq_id == estimate.id
        assert trace.contract_line_id is None

        view = await service.get_request_boq_view(request.id)
        assert view["position_count"] == 1
        assert _findings(view) == []


# ── Clearing ────────────────────────────────────────────────────────────────


class TestClearingTheTrace:
    """Withdrawing an answer is not the same as never having given one."""

    @pytest.mark.asyncio
    async def test_clearing_keeps_the_row_and_makes_the_rule_fail_again(self, session: AsyncSession) -> None:
        """The row survives as ``manual``, and the line is untraced again.

        Both halves matter. The row surviving is what the model asks for, so
        that a line somebody has declared derives from nothing is
        distinguishable from a line nobody has looked at. The rule failing
        again is what makes the clear real rather than cosmetic.
        """
        project = await _make_project(session)
        _contract, line = await _make_contract_line(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)

        boq = await service.create_request_boq(request.id, VariationBOQCreate())
        position = await _add_line_by_hand(session, boq.id)
        await service.set_boq_line_trace(
            request.id, position.id, VariationBOQLineTraceUpdate(contract_line_id=line.id, note="keep me until cleared")
        )
        assert _findings(await service.get_request_boq_view(request.id)) == []

        cleared = await service.clear_boq_line_trace(request.id, position.id)

        assert cleared.origin == "manual"
        assert cleared.contract_line_id is None
        assert cleared.contract_id is None
        assert cleared.source_position_id is None
        assert cleared.note == ""
        assert len(await _trace_rows(session, boq.id)) == 1

        view = await service.get_request_boq_view(request.id)
        assert view["position_count"] == 1
        assert len(_findings(view)) == 1
        assert _findings(view)[0]["passed"] is False

    @pytest.mark.asyncio
    async def test_tracing_twice_replaces_the_answer_rather_than_adding_one(self, session: AsyncSession) -> None:
        """One line, one provenance row - and no field left behind from the first answer.

        A partial update would leave the first answer's ``contract_id``
        underneath the second answer's source position, and the line would
        read as traced to a contract nobody named.
        """
        project = await _make_project(session)
        _contract, line = await _make_contract_line(session, project)
        estimate = BOQ(project_id=project.id, name="Tender estimate")
        session.add(estimate)
        await session.flush()
        source = await _add_line_by_hand(session, estimate.id, description="Reinforced concrete wall C30/37")
        request = await _make_request(session, project)
        service = VariationsService(session)

        boq = await service.create_request_boq(request.id, VariationBOQCreate())
        position = await _add_line_by_hand(session, boq.id)

        await service.set_boq_line_trace(request.id, position.id, VariationBOQLineTraceUpdate(contract_line_id=line.id))
        second = await service.set_boq_line_trace(
            request.id, position.id, VariationBOQLineTraceUpdate(source_position_id=source.id)
        )

        assert len(await _trace_rows(session, boq.id)) == 1
        assert second.origin == "boq_position"
        assert second.source_position_id == source.id
        assert second.contract_line_id is None
        assert second.contract_id is None


# ── References that would dangle are refused, not stored ────────────────────


class TestReferencesThatWouldPointOutOfTheProject:
    """A stored dangling reference is worse than a refusal the caller can read."""

    @pytest.mark.asyncio
    async def test_a_contract_line_of_another_project_is_refused(self, session: AsyncSession) -> None:
        """The refusal is the same one the seeding path raises, by the same loader.

        A variation request names a project, not a contract, so the project is
        the only scope this record can be checked against. Within it, any
        contract's schedule of values is fair game; outside it, nothing is.
        """
        project = await _make_project(session)
        other = await _make_project(session, name="Someone else's job")
        _contract, foreign = await _make_contract_line(session, other, contract_code="C-999")
        request = await _make_request(session, project)
        service = VariationsService(session)

        boq = await service.create_request_boq(request.id, VariationBOQCreate())
        position = await _add_line_by_hand(session, boq.id)

        with pytest.raises(HTTPException) as excinfo:
            await service.set_boq_line_trace(
                request.id, position.id, VariationBOQLineTraceUpdate(contract_line_id=foreign.id)
            )

        assert excinfo.value.status_code == 400
        assert excinfo.value.detail["error"] == "contract_line_not_in_project"
        # Refused rather than half-written: nothing was recorded about the line.
        assert await _trace_rows(session, boq.id) == []

    @pytest.mark.asyncio
    async def test_a_line_belonging_to_another_requests_bill_is_not_traceable_here(self, session: AsyncSession) -> None:
        """Project access says the caller may touch this request. It says nothing about a bare position id.

        Both requests here are on projects the caller could legitimately reach,
        which is what makes this a separate guard rather than a restatement of
        the project check: without it, the trace table would hold a row about a
        line the request that owns the row has never contained.
        """
        project = await _make_project(session)
        _contract, line = await _make_contract_line(session, project)
        mine = await _make_request(session, project, code="VR-0001")
        theirs = await _make_request(session, project, code="VR-0002")
        service = VariationsService(session)

        my_boq = await service.create_request_boq(mine.id, VariationBOQCreate())
        their_boq = await service.create_request_boq(theirs.id, VariationBOQCreate())
        their_line = await _add_line_by_hand(session, their_boq.id)

        with pytest.raises(HTTPException) as excinfo:
            await service.set_boq_line_trace(
                mine.id, their_line.id, VariationBOQLineTraceUpdate(contract_line_id=line.id)
            )

        assert excinfo.value.status_code == 404
        assert excinfo.value.detail["error"] == "line_not_in_variation_boq"
        assert await _trace_rows(session, my_boq.id) == []
        assert await _trace_rows(session, their_boq.id) == []

    @pytest.mark.asyncio
    async def test_another_variations_priced_scope_is_not_estimating_provenance(self, session: AsyncSession) -> None:
        """The source of a line may be the estimate, never another variation's bill.

        Both bills are on the caller's own project, so the project filter
        cannot be what refuses this. A variation bill holds priced scope
        nobody has agreed to, and citing it as where the money came from
        defends one unagreed figure with another. The loader excludes it by
        the same ``variation_request_id IS NULL`` filter the three other
        places that mean "the project's own bills" already apply, which is
        also why a line cannot cite itself.
        """
        project = await _make_project(session)
        mine = await _make_request(session, project, code="VR-0001")
        theirs = await _make_request(session, project, code="VR-0002")
        service = VariationsService(session)

        my_boq = await service.create_request_boq(mine.id, VariationBOQCreate())
        their_boq = await service.create_request_boq(theirs.id, VariationBOQCreate())
        position = await _add_line_by_hand(session, my_boq.id)
        their_line = await _add_line_by_hand(session, their_boq.id, description="Priced by somebody else")

        for source_id, why in ((their_line.id, "another request's bill"), (position.id, "the line itself")):
            with pytest.raises(HTTPException) as excinfo:
                await service.set_boq_line_trace(
                    mine.id, position.id, VariationBOQLineTraceUpdate(source_position_id=source_id)
                )
            assert excinfo.value.status_code == 400, why
            assert excinfo.value.detail["error"] == "source_position_not_in_project", why

        assert await _trace_rows(session, my_boq.id) == []

    @pytest.mark.asyncio
    async def test_the_estimating_bill_is_still_a_source(self, session: AsyncSession) -> None:
        """The control for the exclusion above, on the same project.

        Narrowing what counts as a source is only correct if it still admits
        the thing it exists to admit, and a filter that refused everything
        would make the test above pass while breaking the feature.
        """
        project = await _make_project(session)
        estimate = BOQ(project_id=project.id, name="Tender estimate")
        session.add(estimate)
        await session.flush()
        source = await _add_line_by_hand(session, estimate.id, description="Reinforced concrete wall C30/37")
        request = await _make_request(session, project)
        service = VariationsService(session)

        boq = await service.create_request_boq(request.id, VariationBOQCreate())
        position = await _add_line_by_hand(session, boq.id)

        trace = await service.set_boq_line_trace(
            request.id, position.id, VariationBOQLineTraceUpdate(source_position_id=source.id)
        )

        assert trace.source_position_id == source.id
        assert trace.source_boq_id == estimate.id


# ── The route in front of the service ───────────────────────────────────────


class TestTheRouteGuardsTheProject:
    """The mutator carries the same project check its read sibling carries.

    Asserted by driving the handler rather than by reading it, because the
    defect this guards against is a route that simply forgot to call it, and
    reading a route that forgot proves nothing.
    """

    @staticmethod
    async def _user(session: AsyncSession, role: str = "editor") -> User:
        user = User(
            email=f"trace-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="x",
            full_name="Quantity surveyor",
            role=role,
        )
        session.add(user)
        await session.flush()
        return user

    @pytest.mark.asyncio
    async def test_a_caller_with_no_access_to_the_project_is_refused(self, session: AsyncSession) -> None:
        """404, and nothing written - the module's policy for both missing and forbidden."""
        outsider = await self._user(session)
        project = await _make_project(session)  # owned by somebody else entirely
        _contract, line = await _make_contract_line(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)

        boq = await service.create_request_boq(request.id, VariationBOQCreate())
        position = await _add_line_by_hand(session, boq.id)

        with pytest.raises(HTTPException) as excinfo:
            await set_variation_boq_line_trace(
                request.id,
                position.id,
                session=session,
                user_id=str(outsider.id),
                body=VariationBOQLineTraceUpdate(contract_line_id=line.id),
                service=service,
            )

        assert excinfo.value.status_code == 404
        assert await _trace_rows(session, boq.id) == []

    @pytest.mark.asyncio
    async def test_the_projects_own_editor_traces_the_line_through_the_route(self, session: AsyncSession) -> None:
        """The control the refusal above needs, over the same route and payload.

        Without it, a route broken in any other way would produce the same 404
        and the test above would pass for the wrong reason.
        """
        owner = await self._user(session)
        project = await _make_project(session, owner_id=owner.id)
        _contract, line = await _make_contract_line(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)

        boq = await service.create_request_boq(request.id, VariationBOQCreate())
        position = await _add_line_by_hand(session, boq.id)

        response = await set_variation_boq_line_trace(
            request.id,
            position.id,
            session=session,
            user_id=str(owner.id),
            body=VariationBOQLineTraceUpdate(contract_line_id=line.id),
            service=service,
        )

        assert response.contract_line_id == line.id
        assert response.origin == "contract_line"
        assert _findings(await service.get_request_boq_view(request.id)) == []

    @pytest.mark.asyncio
    async def test_the_clear_route_carries_the_same_guard(self, session: AsyncSession) -> None:
        """The read sibling has the check; so must both mutators, not just one."""
        outsider = await self._user(session)
        project = await _make_project(session)
        _contract, line = await _make_contract_line(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)

        boq = await service.create_request_boq(request.id, VariationBOQCreate())
        position = await _add_line_by_hand(session, boq.id)
        await service.set_boq_line_trace(request.id, position.id, VariationBOQLineTraceUpdate(contract_line_id=line.id))

        with pytest.raises(HTTPException) as excinfo:
            await clear_variation_boq_line_trace(
                request.id,
                position.id,
                session=session,
                user_id=str(outsider.id),
                service=service,
            )

        assert excinfo.value.status_code == 404
        # The refusal did not quietly clear it on the way out.
        rows = await _trace_rows(session, boq.id)
        assert [row.contract_line_id for row in rows] == [line.id]

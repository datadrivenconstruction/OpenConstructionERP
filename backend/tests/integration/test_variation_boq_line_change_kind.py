# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What a variation line does to its source, recorded, summed and judged.

Issue #435. A trace row said where a line of a variation's bill came from - the
schedule-of-values line it affects, the estimating position it was priced
from - and nothing about what the variation does to that source. A bill of
three lines citing three contract lines could be three additions, three
omissions or three re-measures, and the record could not tell them apart,
which is the distinction that makes an omission price correctly.

``change_kind`` is that statement. These tests pin the four places it has to
hold together, on a real database, because every claim is about what is
written and what is read back:

* it is stored as stated on both writers, the seeding path and the trace PUT,
  and reset with the references when a trace is cleared;
* the bill view splits the direct cost by kind and the three subtotals sum to
  the bill's own ``direct_cost``, so the net change reads as a sum a person
  can check;
* a line with no trace row counts as ``added`` in that sum and is judged as
  ``added`` by the rule, so the money and the verdict agree on every line;
* ``variations.change_kind_matches_numbers`` reports a kind that contradicts
  the numbers on the read path, and stops reporting it once the estimator
  has corrected one or the other - nothing is inferred or corrected for them.

The population is asserted next to every verdict, for the reason the sibling
trace tests give: the rule skips a heading, so "no findings" and "nothing to
find" are the same output unless the count of priced lines is in the test.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
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
from app.modules.variations.router import set_variation_boq_line_trace
from app.modules.variations.schemas import (
    VariationBOQCreate,
    VariationBOQLineTraceUpdate,
    VariationBOQResponse,
    VariationBOQSourceContractLine,
    VariationBOQSourcePosition,
)
from app.modules.variations.service import VariationsService
from tests._pg import transactional_session

RULE = "variations.change_kind_matches_numbers"
TRACED_RULE = "variations.boq_lines_are_traced"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Isolated PostgreSQL session, FK triggers off, rolled back on teardown."""
    async with transactional_session(disable_fks=True) as sess:
        yield sess


# ── Seed helpers ────────────────────────────────────────────────────────────


async def _make_project(session: AsyncSession, owner_id=None) -> Project:
    project = Project(
        name="Riverside Depot",
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
        title="Retaining wall at grid F re-measured, propping added",
        estimated_cost_impact=Decimal("0"),
        estimated_schedule_days=0,
        currency="EUR",
    )
    session.add(request)
    await session.flush()
    return request


async def _make_contract_lines(session: AsyncSession, project: Project) -> tuple[Contract, ContractLine, ContractLine]:
    """A contract with two schedule-of-values lines: walls at 40 m3, drainage at 100 m."""
    contract = Contract(
        code="C-001",
        title="Main works",
        project_id=project.id,
        currency="EUR",
        total_value=Decimal("1500000"),
    )
    session.add(contract)
    await session.flush()
    walls = ContractLine(
        contract_id=contract.id,
        code="SOV-020",
        description="Retaining walls",
        unit="m3",
        quantity=Decimal("40"),
        unit_rate=Decimal("300"),
        total_value=Decimal("12000"),
    )
    drainage = ContractLine(
        contract_id=contract.id,
        code="SOV-030",
        description="Land drainage",
        unit="m",
        quantity=Decimal("100"),
        unit_rate=Decimal("50"),
        total_value=Decimal("5000"),
    )
    session.add_all([walls, drainage])
    await session.flush()
    return contract, walls, drainage


async def _make_estimate_position(session: AsyncSession, project: Project) -> Position:
    estimate = BOQ(project_id=project.id, name="Tender estimate")
    session.add(estimate)
    await session.flush()
    return await _add_line_by_hand(session, estimate.id, description="Temporary propping", quantity="4", rate="500")


async def _add_line_by_hand(
    session: AsyncSession,
    boq_id: uuid.UUID,
    *,
    ordinal: str = "0090",
    description: str = "Temporary propping",
    unit: str = "m3",
    quantity: str = "4",
    rate: str = "500",
) -> Position:
    """A line typed into the bill in the BOQ editor, the way scope actually grows."""
    position = Position(
        boq_id=boq_id,
        ordinal=ordinal,
        description=description,
        unit=unit,
        quantity=quantity,
        unit_rate=rate,
        total=format(Decimal(quantity) * Decimal(rate), "f"),
        classification={},
        source="manual",
        cad_element_ids=[],
        sort_order=int(ordinal),
    )
    session.add(position)
    await session.flush()
    return position


def _findings(view: dict, rule_id: str = RULE) -> list[dict]:
    return [check for check in view["checks"] if check["rule_id"] == rule_id]


async def _trace_rows(session: AsyncSession, boq_id: uuid.UUID) -> list[VariationBOQTrace]:
    stmt = select(VariationBOQTrace).where(VariationBOQTrace.boq_id == boq_id)
    return list((await session.execute(stmt)).scalars().all())


async def _positions(session: AsyncSession, boq_id: uuid.UUID) -> dict[str, Position]:
    stmt = select(Position).where(Position.boq_id == boq_id)
    return {row.ordinal: row for row in (await session.execute(stmt)).scalars().all()}


# ── Stored as stated, on both writers ───────────────────────────────────────


class TestTheKindIsRecordedNotInferred:
    @pytest.mark.asyncio
    async def test_seeding_records_the_kind_named_for_each_source(self, session: AsyncSession) -> None:
        """Three sources, three kinds, read back on the rows the seeding wrote.

        The walls are omitted, carried as a negative quantity; the drainage is
        re-measured up; the propping is new scope priced off the estimate.
        """
        project = await _make_project(session)
        _contract, walls, drainage = await _make_contract_lines(session, project)
        propping = await _make_estimate_position(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)

        boq = await service.create_request_boq(
            request.id,
            VariationBOQCreate(
                source_positions=[VariationBOQSourcePosition(position_id=propping.id, change_kind="added")],
                source_contract_lines=[
                    VariationBOQSourceContractLine(
                        contract_line_id=walls.id, quantity=Decimal("-40"), change_kind="removed"
                    ),
                    VariationBOQSourceContractLine(
                        contract_line_id=drainage.id, quantity=Decimal("20"), change_kind="modified"
                    ),
                ],
            ),
        )

        by_line = {row.contract_line_id: row for row in await _trace_rows(session, boq.id)}
        assert by_line[walls.id].change_kind == "removed"
        assert by_line[drainage.id].change_kind == "modified"
        assert by_line[None].change_kind == "added"
        assert by_line[None].source_position_id == propping.id

    @pytest.mark.asyncio
    async def test_a_source_named_without_a_kind_is_added_even_when_it_is_a_contract_line(
        self, session: AsyncSession
    ) -> None:
        """Extra quantity of a contracted item is the commonest variation and it is an addition.

        The kind is a statement, so a seeding that made none is recorded as
        the default rather than as a guess from the fact that a contract line
        was named.
        """
        project = await _make_project(session)
        _contract, walls, _drainage = await _make_contract_lines(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)

        boq = await service.create_request_boq(
            request.id,
            VariationBOQCreate(source_contract_lines=[VariationBOQSourceContractLine(contract_line_id=walls.id)]),
        )

        rows = await _trace_rows(session, boq.id)
        assert [row.change_kind for row in rows] == ["added"]
        assert rows[0].contract_line_id == walls.id

    @pytest.mark.asyncio
    async def test_the_trace_put_records_the_kind_and_a_second_put_replaces_it(self, session: AsyncSession) -> None:
        """One row per line, and no half of the last answer left behind.

        A line re-traced from an omission to an addition that kept
        ``removed`` would read as omitting scope it adds.
        """
        project = await _make_project(session)
        _contract, walls, _drainage = await _make_contract_lines(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)

        boq = await service.create_request_boq(request.id, VariationBOQCreate())
        position = await _add_line_by_hand(session, boq.id, quantity="-40", rate="300")

        first = await service.set_boq_line_trace(
            request.id,
            position.id,
            VariationBOQLineTraceUpdate(contract_line_id=walls.id, change_kind="removed"),
        )
        assert first.change_kind == "removed"
        assert first.contract_line_id == walls.id

        second = await service.set_boq_line_trace(
            request.id,
            position.id,
            VariationBOQLineTraceUpdate(contract_line_id=walls.id, change_kind="modified", note="Re-measured down"),
        )
        assert second.change_kind == "modified"
        assert len(await _trace_rows(session, boq.id)) == 1
        assert (await _trace_rows(session, boq.id))[0].change_kind == "modified"

    @pytest.mark.asyncio
    async def test_clearing_a_trace_takes_the_kind_back_to_added_with_the_references(
        self, session: AsyncSession
    ) -> None:
        """A line that derives from nothing cannot be omitting or modifying anything."""
        project = await _make_project(session)
        _contract, walls, _drainage = await _make_contract_lines(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)

        boq = await service.create_request_boq(request.id, VariationBOQCreate())
        position = await _add_line_by_hand(session, boq.id, quantity="-40", rate="300")
        await service.set_boq_line_trace(
            request.id, position.id, VariationBOQLineTraceUpdate(contract_line_id=walls.id, change_kind="removed")
        )

        cleared = await service.clear_boq_line_trace(request.id, position.id)

        assert cleared.change_kind == "added"
        assert cleared.contract_line_id is None
        assert cleared.origin == "manual"


# ── The bill view: subtotals by kind that sum to the direct cost ────────────


class TestTheViewSplitsTheMoneyByKind:
    @pytest.mark.asyncio
    async def test_the_three_subtotals_sum_to_the_direct_cost_and_the_net_reads_as_their_sum(
        self, session: AsyncSession
    ) -> None:
        """Omission -12000, re-measure +1000, addition +2000: net -9000, and the bill agrees.

        The subtotals are valued line by line the way the bill values them,
        so this is one figure split three ways rather than a second figure
        that happens to match on a single-currency bill.
        """
        project = await _make_project(session)
        _contract, walls, drainage = await _make_contract_lines(session, project)
        propping = await _make_estimate_position(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)

        await service.create_request_boq(
            request.id,
            VariationBOQCreate(
                source_positions=[VariationBOQSourcePosition(position_id=propping.id, change_kind="added")],
                source_contract_lines=[
                    VariationBOQSourceContractLine(
                        contract_line_id=walls.id, quantity=Decimal("-40"), change_kind="removed"
                    ),
                    VariationBOQSourceContractLine(
                        contract_line_id=drainage.id, quantity=Decimal("20"), change_kind="modified"
                    ),
                ],
            ),
        )

        view = await service.get_request_boq_view(request.id)
        summary = view["change_summary"]

        assert view["position_count"] == 3
        assert summary["added"] == {"line_count": 1, "total": Decimal("2000")}
        assert summary["removed"] == {"line_count": 1, "total": Decimal("-12000")}
        assert summary["modified"] == {"line_count": 1, "total": Decimal("1000")}
        assert summary["net_total"] == Decimal("-9000")
        assert (
            summary["net_total"]
            == summary["added"]["total"] + summary["removed"]["total"] + summary["modified"]["total"]
        )
        assert summary["net_total"] == view["direct_cost"]
        # A correctly stated bill raises no finding from the kind rule, and
        # the count above says the rule had three lines to judge.
        assert _findings(view) == []

    @pytest.mark.asyncio
    async def test_a_line_with_no_trace_row_is_counted_as_added(self, session: AsyncSession) -> None:
        """The money and the rule read an untraced line the same way.

        Untraced is still reported by the sibling rule, which is the correct
        and separate statement that nobody has said where the line came from.
        """
        project = await _make_project(session)
        request = await _make_request(session, project)
        service = VariationsService(session)

        boq = await service.create_request_boq(request.id, VariationBOQCreate())
        await _add_line_by_hand(session, boq.id, quantity="4", rate="500")

        view = await service.get_request_boq_view(request.id)

        assert view["position_count"] == 1
        assert await _trace_rows(session, boq.id) == []
        assert view["change_summary"]["added"] == {"line_count": 1, "total": Decimal("2000")}
        assert view["change_summary"]["removed"]["line_count"] == 0
        assert view["change_summary"]["modified"]["line_count"] == 0
        assert _findings(view) == []
        assert len(_findings(view, TRACED_RULE)) == 1

    @pytest.mark.asyncio
    async def test_the_response_schema_carries_the_split_as_money_strings(self, session: AsyncSession) -> None:
        """What leaves the route: decimals as strings, the same way every other money field does."""
        project = await _make_project(session)
        _contract, walls, _drainage = await _make_contract_lines(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)

        await service.create_request_boq(
            request.id,
            VariationBOQCreate(
                source_contract_lines=[
                    VariationBOQSourceContractLine(
                        contract_line_id=walls.id, quantity=Decimal("-40"), change_kind="removed"
                    )
                ]
            ),
        )

        body = VariationBOQResponse.model_validate(await service.get_request_boq_view(request.id)).model_dump(
            mode="json"
        )

        # Cent-rounded decimal strings, the shape every other money field of
        # this module leaves in, so the split reads exactly like direct_cost.
        assert body["change_summary"]["removed"] == {"line_count": 1, "total": "-12000.00"}
        assert body["change_summary"]["added"] == {"line_count": 0, "total": "0.00"}
        assert body["change_summary"]["net_total"] == "-12000.00"
        assert body["change_summary"]["net_total"] == body["direct_cost"]
        assert [trace["change_kind"] for trace in body["traces"]] == ["removed"]

    @pytest.mark.asyncio
    async def test_a_request_with_no_bill_has_no_split(self, session: AsyncSession) -> None:
        project = await _make_project(session)
        request = await _make_request(session, project)

        body = VariationBOQResponse.model_validate(
            await VariationsService(session).get_request_boq_view(request.id)
        ).model_dump(mode="json")

        assert body["has_boq"] is False
        assert body["change_summary"] is None


# ── The rule on the read path: reported, then satisfied by a correction ─────


class TestTheRuleJudgesTheStatedKind:
    @pytest.mark.asyncio
    async def test_a_removed_line_with_a_positive_quantity_is_reported_until_the_quantity_is_corrected(
        self, session: AsyncSession
    ) -> None:
        """Both readings on the same line; only the quantity changes between them."""
        project = await _make_project(session)
        _contract, walls, _drainage = await _make_contract_lines(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)

        boq = await service.create_request_boq(request.id, VariationBOQCreate())
        position = await _add_line_by_hand(session, boq.id, quantity="40", rate="300")
        await service.set_boq_line_trace(
            request.id, position.id, VariationBOQLineTraceUpdate(contract_line_id=walls.id, change_kind="removed")
        )

        before = await service.get_request_boq_view(request.id)
        assert before["position_count"] == 1
        assert len(_findings(before)) == 1
        assert _findings(before)[0]["passed"] is False
        assert "40" in _findings(before)[0]["message"]
        # The subtotal follows the statement, not the sign: the estimator
        # said removed, so the money sits under removed until they say otherwise.
        assert before["change_summary"]["removed"] == {"line_count": 1, "total": Decimal("12000")}

        position.quantity = "-40"
        position.total = "-12000"
        await session.flush()

        after = await service.get_request_boq_view(request.id)
        assert after["position_count"] == 1
        assert _findings(after) == []
        assert after["change_summary"]["removed"] == {"line_count": 1, "total": Decimal("-12000")}

    @pytest.mark.asyncio
    async def test_a_modified_line_with_no_contract_line_is_reported_until_one_is_named(
        self, session: AsyncSession
    ) -> None:
        """The other finding the brief names, and the correction that clears it."""
        project = await _make_project(session)
        _contract, walls, _drainage = await _make_contract_lines(session, project)
        propping = await _make_estimate_position(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)

        boq = await service.create_request_boq(request.id, VariationBOQCreate())
        position = await _add_line_by_hand(session, boq.id, quantity="10", rate="300")
        await service.set_boq_line_trace(
            request.id,
            position.id,
            VariationBOQLineTraceUpdate(source_position_id=propping.id, change_kind="modified"),
        )

        before = await service.get_request_boq_view(request.id)
        assert before["position_count"] == 1
        assert len(_findings(before)) == 1
        # Traced to the estimate, so the sibling rule is satisfied: the
        # finding here is about the kind alone.
        assert _findings(before, TRACED_RULE) == []

        await service.set_boq_line_trace(
            request.id, position.id, VariationBOQLineTraceUpdate(contract_line_id=walls.id, change_kind="modified")
        )

        after = await service.get_request_boq_view(request.id)
        assert after["position_count"] == 1
        assert _findings(after) == []

    @pytest.mark.asyncio
    async def test_the_kind_is_stored_even_when_it_contradicts_the_numbers(self, session: AsyncSession) -> None:
        """The estimator is told, not refused: an unfinished statement and a wrong one are not the same 4xx."""
        project = await _make_project(session)
        _contract, walls, _drainage = await _make_contract_lines(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)

        boq = await service.create_request_boq(request.id, VariationBOQCreate())
        position = await _add_line_by_hand(session, boq.id, quantity="40", rate="300")

        trace = await service.set_boq_line_trace(
            request.id, position.id, VariationBOQLineTraceUpdate(contract_line_id=walls.id, change_kind="removed")
        )

        assert trace.change_kind == "removed"
        assert [row.change_kind for row in await _trace_rows(session, boq.id)] == ["removed"]


# ── The route carries the kind through ──────────────────────────────────────


class TestTheRoute:
    @pytest.mark.asyncio
    async def test_the_response_names_the_kind_that_was_sent(self, session: AsyncSession) -> None:
        """Driven through the handler, so a route that dropped the field would fail here."""
        owner = User(
            email=f"kind-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="x",
            full_name="Quantity surveyor",
            role="editor",
        )
        session.add(owner)
        await session.flush()
        project = await _make_project(session, owner_id=owner.id)
        _contract, walls, _drainage = await _make_contract_lines(session, project)
        request = await _make_request(session, project)
        service = VariationsService(session)

        boq = await service.create_request_boq(request.id, VariationBOQCreate())
        position = await _add_line_by_hand(session, boq.id, quantity="-40", rate="300")

        response = await set_variation_boq_line_trace(
            request.id,
            position.id,
            session=session,
            user_id=str(owner.id),
            body=VariationBOQLineTraceUpdate(contract_line_id=walls.id, change_kind="removed"),
            service=service,
        )

        assert response.change_kind == "removed"
        assert response.contract_line_id == walls.id
        positions = await _positions(session, boq.id)
        assert positions["0090"].id == position.id

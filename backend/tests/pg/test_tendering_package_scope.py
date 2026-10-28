# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG: a package over part of a bill is levelled and compared against that part.

Both comparison screens load the package's BOQ, and a package covering a
quarter of a bill points at the whole thing. Until the package's own scope was
read, the other three quarters landed on the reference side of the matrix,
where every bidder counted as having omitted them: each out-of-scope line was
imputed at the bidder's own mean rate, so a bid levelled to roughly four times
what it quoted and the budget comparison measured it against four times its own
budget. Both numbers are what the screens exist to show.

This has to run against a real cluster. The arithmetic is pure, but the failure
lives in the join between a stored package's metadata and a stored BOQ's
positions, and a unit test over the filter alone cannot see whether either
screen calls it - which is exactly how the gap shipped.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.boq.models import BOQ, Position
from app.modules.projects.models import Project
from app.modules.tendering.models import TenderBid, TenderPackage
from app.modules.tendering.service import TenderingService
from app.modules.users.models import User

# Eight lines of equal value, so a scope of the first four is worth exactly half
# the bill and any leakage from the other half is unmistakable.
LINE_QUANTITY = "100"
LINE_RATE = "1000.00"
LINE_TOTAL = "100000.00"
BILL_LINES = 8
SCOPE_LINES = 4
# What the two bidders quote for their four lines, a little either side of the
# 400,000 those lines are budgeted at.
BID_TOTALS = ("380000.00", "425000.00")


async def _bill_of_eight(session) -> tuple[Project, BOQ, list[Position]]:
    """A stored project carrying one BOQ of eight equally priced lines."""
    owner = User(email=f"scope-{uuid.uuid4().hex[:8]}@example.test", hashed_password="x", full_name="Scope")
    session.add(owner)
    await session.flush()

    project = Project(name="Retail park", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()

    boq = BOQ(project_id=project.id, name="Bill of quantities")
    session.add(boq)
    await session.flush()

    positions = [
        Position(
            boq_id=boq.id,
            ordinal=f"01.{index + 1:03d}",
            description=f"Trade line {index + 1}",
            unit="m2",
            quantity=LINE_QUANTITY,
            unit_rate=LINE_RATE,
            total=LINE_TOTAL,
        )
        for index in range(BILL_LINES)
    ]
    session.add_all(positions)
    await session.flush()
    return project, boq, positions


async def _package_with_two_bids(session, project, boq, positions, *, declare_scope: bool) -> TenderPackage:
    """A package over the first four lines, quoted line by line by two bidders.

    ``declare_scope`` is the whole point of the test: the same stored rows,
    with and without the package saying which lines it covers.
    """
    scope = positions[:SCOPE_LINES]
    metadata: dict = {"package_index": 1, "total_packages": 2}
    if declare_scope:
        metadata["scope_position_ids"] = [str(p.id) for p in scope]

    package = TenderPackage(
        project_id=project.id,
        boq_id=boq.id,
        name="Lot 1 - shell",
        description="First lot of the bill",
        status="evaluating",
        metadata_=metadata,
    )
    session.add(package)
    await session.flush()

    for index, total in enumerate(BID_TOTALS):
        rate = Decimal(total) / Decimal(SCOPE_LINES) / Decimal(LINE_QUANTITY)
        session.add(
            TenderBid(
                package_id=package.id,
                company_name=f"Bidder {index + 1}",
                contact_email=f"bid{index + 1}@example.test",
                total_amount=total,
                currency="EUR",
                status="submitted",
                line_items=[
                    {
                        "position_id": str(position.id),
                        "description": position.description,
                        "unit": position.unit,
                        "quantity": float(Decimal(LINE_QUANTITY)),
                        "unit_rate": str(rate),
                        "total": float(rate * Decimal(LINE_QUANTITY)),
                    }
                    for position in scope
                ],
                metadata_={},
            )
        )
    await session.flush()
    return package


@pytest.mark.asyncio
async def test_leveling_reads_the_scope_the_package_declares(pg_session) -> None:
    """Four lines quoted against four lines asked for: nothing to impute."""
    project, boq, positions = await _bill_of_eight(pg_session)
    package = await _package_with_two_bids(pg_session, project, boq, positions, declare_scope=True)

    result = await TenderingService(pg_session).level_bids(package.id)

    assert result.reference_line_count == SCOPE_LINES, "the matrix must not carry lines nobody was asked to price"
    assert len(result.bid_summaries) == 2
    for summary in result.bid_summaries:
        assert summary.imputed_lines == 0, "a bidder who quoted the whole scope omitted nothing"
        assert summary.matched_lines == SCOPE_LINES
        assert summary.scaled_lines == 0
        assert summary.leveled_amount == summary.raw_amount, "leveling a complete quote must not move its total"


@pytest.mark.asyncio
async def test_without_a_declared_scope_the_whole_bill_is_still_the_reference(pg_session) -> None:
    """The control. Same rows, no scope: this is the shape that was shipping.

    It also pins the behaviour every package created before scopes existed
    depends on, so the narrowing cannot quietly start applying to them.
    """
    project, boq, positions = await _bill_of_eight(pg_session)
    package = await _package_with_two_bids(pg_session, project, boq, positions, declare_scope=False)

    result = await TenderingService(pg_session).level_bids(package.id)

    assert result.reference_line_count == BILL_LINES
    for summary in result.bid_summaries:
        assert summary.imputed_lines == BILL_LINES - SCOPE_LINES
        assert summary.leveled_amount > summary.raw_amount, "the un-narrowed matrix is what inflated the bid"


@pytest.mark.asyncio
async def test_the_budget_compared_against_is_the_scope_budget(pg_session) -> None:
    """A bid a little under its lot must not read as far under the whole bill."""
    project, boq, positions = await _bill_of_eight(pg_session)
    package = await _package_with_two_bids(pg_session, project, boq, positions, declare_scope=True)

    result = await TenderingService(pg_session).compare_bids(package.id)

    scope_budget = Decimal(LINE_TOTAL) * SCOPE_LINES
    assert Decimal(str(result.budget_total)) == scope_budget
    assert len(result.rows) == SCOPE_LINES


@pytest.mark.asyncio
async def test_a_scope_naming_lines_of_another_bill_is_ignored(pg_session) -> None:
    """Stale metadata widens back to the bill rather than emptying the screen."""
    project, boq, positions = await _bill_of_eight(pg_session)
    package = await _package_with_two_bids(pg_session, project, boq, positions, declare_scope=True)
    package.metadata_ = {**package.metadata_, "scope_position_ids": [str(uuid.uuid4())]}
    await pg_session.flush()

    result = await TenderingService(pg_session).level_bids(package.id)

    assert result.reference_line_count == BILL_LINES

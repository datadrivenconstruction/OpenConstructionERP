# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Generating a claim writes every line's retention in one statement.

Working a claim's retention out used to write column I back one UPDATE per
claim line, so generating a claim on a 500 line schedule of values sent 502
UPDATE statements where it now sends 3 (517 statements in all where it now
sends 21), and that round trip per line was most of the time generation
took. The figures are all known before the first write,
so they now go out as one statement however long the schedule is.

A statement that bypasses the ORM leaves the instances already in the session
holding what they held before, and in an async session a stale attribute is
not reloaded on access. The certificate reads column I straight off those
instances and falls back to allocating it when it finds none, so a write that
reached only the database would print a different column I with no error.
The second test reads the lines back in the same session, without a refresh,
for that reason.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select

from app.modules.contracts.models import Contract, ContractLine, ProgressClaimLine
from app.modules.contracts.schemas import AutoGenerateClaimRequest
from app.modules.contracts.service import ContractsService
from app.modules.projects.models import Project
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio

LINE_VALUE = Decimal("1000")


async def _schedule(session, count: int) -> tuple[Contract, list[ContractLine]]:
    suffix = uuid.uuid4().hex[:8]
    owner = User(id=uuid.uuid4(), email=f"bulk-{suffix}@site.example", hashed_password="x")
    session.add(owner)
    await session.flush()
    project = Project(
        id=uuid.uuid4(),
        name="Long schedule",
        owner_id=owner.id,
        currency="USD",
        country_code="US",
        metadata_={},
    )
    session.add(project)
    await session.flush()
    contract = Contract(
        id=uuid.uuid4(),
        code=f"C-{suffix}",
        title="Main works",
        project_id=project.id,
        contract_type="lump_sum",
        currency="USD",
        total_value=LINE_VALUE * count,
        original_contract_value=LINE_VALUE * count,
        retention_percent=Decimal("10"),
        status="active",
    )
    session.add(contract)
    await session.flush()
    lines = [
        ContractLine(
            id=uuid.uuid4(),
            contract_id=contract.id,
            code=f"L{index:04d}",
            description=f"Schedule line {index}",
            quantity=Decimal("1"),
            unit_rate=LINE_VALUE,
            total_value=LINE_VALUE,
            order_index=index,
        )
        for index in range(count)
    ]
    session.add_all(lines)
    await session.flush()
    return contract, lines


async def _generated(svc: ContractsService, contract: Contract, lines: list[ContractLine]):
    claim = await svc.create_progress_claim(
        SimpleNamespace(
            contract_id=contract.id,
            claim_number="PC-1",
            period_start="2026-03-01",
            period_end="2026-03-31",
            claim_date="2026-03-31",
            currency="USD",
            metadata={},
        )
    )
    return await svc.auto_generate_claim_lines(
        claim.id,
        AutoGenerateClaimRequest(completion={str(line.id): Decimal("50") for line in lines}),
    )


@contextmanager
def _claim_line_updates(session):
    """Count the UPDATE statements sent for claim lines while the block runs."""
    seen: list[str] = []
    connection = session.bind.sync_connection

    def _record(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        if statement.lstrip().upper().startswith("UPDATE OE_CONTRACTS_PROGRESS_CLAIM_LINE "):
            seen.append(statement)

    event.listen(connection, "before_cursor_execute", _record)
    try:
        yield seen
    finally:
        event.remove(connection, "before_cursor_execute", _record)


@pytest.mark.parametrize("count", [50, 500])
async def test_the_line_retention_goes_out_in_one_statement(pg_session, count: int) -> None:
    svc = ContractsService(pg_session)
    contract, lines = await _schedule(pg_session, count)

    with _claim_line_updates(pg_session) as updates:
        claim = await _generated(svc, contract, lines)

    assert len(updates) == 1
    assert Decimal(str(claim.retention_amount)) == Decimal("50") * count


async def test_the_lines_in_the_session_carry_what_was_written(pg_session) -> None:
    svc = ContractsService(pg_session)
    contract, lines = await _schedule(pg_session, 5)
    claim = await _generated(svc, contract, lines)

    # The same instances the generator wrote through, not reloaded.
    in_session = await svc.claim_line_repo.list_for_claim(claim.id)
    assert len(in_session) == 5
    assert {row.retention_to_date for row in in_session} == {Decimal("50.00")}
    assert {row.retention_stored_to_date for row in in_session} == {Decimal("0.00")}
    assert {row.retention_rate for row in in_session} == {Decimal("10.0000")}

    stored = (
        await pg_session.execute(
            select(ProgressClaimLine.retention_to_date).where(ProgressClaimLine.progress_claim_id == claim.id)
        )
    ).scalars()
    assert {Decimal(str(value)) for value in stored} == {Decimal("50.00")}


async def test_each_line_gets_its_own_figures_when_they_all_differ(pg_session) -> None:
    """One statement for many rows must not hand one row's figures to another.

    Every line above holds the same value, so a write that paired the wrong
    parameters with the wrong row would still read 50.00 everywhere. Here no
    two lines retain the same amount, and each is checked by its own id, in
    the session and in the database, against what the engine works out for it.
    """
    svc = ContractsService(pg_session)
    contract, lines = await _schedule(pg_session, 4)
    values = [Decimal("1000"), Decimal("2500"), Decimal("7300"), Decimal("40")]
    percents = [Decimal("30"), Decimal("20"), Decimal("10"), Decimal("25")]
    for line, value in zip(lines, values, strict=True):
        line.unit_rate = value
        line.total_value = value
    contract.total_value = contract.original_contract_value = sum(values, Decimal("0"))
    await pg_session.flush()
    claim = await svc.create_progress_claim(
        SimpleNamespace(
            contract_id=contract.id,
            claim_number="PC-1",
            period_start="2026-03-01",
            period_end="2026-03-31",
            claim_date="2026-03-31",
            currency="USD",
            metadata={},
        )
    )
    with _claim_line_updates(pg_session) as updates:
        claim = await svc.auto_generate_claim_lines(
            claim.id,
            AutoGenerateClaimRequest(completion={str(line.id): pct for line, pct in zip(lines, percents, strict=True)}),
        )
    assert len(updates) == 1

    # 10% of 300, 500, 730 and 10.
    expected = {line.id: Decimal(want) for line, want in zip(lines, ["30.00", "50.00", "73.00", "1.00"], strict=True)}
    rows = await svc.claim_line_repo.list_for_claim(claim.id)
    assert {row.contract_line_id: row.retention_to_date for row in rows} == expected
    stored = (
        await pg_session.execute(
            select(ProgressClaimLine.contract_line_id, ProgressClaimLine.retention_to_date).where(
                ProgressClaimLine.progress_claim_id == claim.id
            )
        )
    ).all()
    assert {line_id: Decimal(str(value)) for line_id, value in stored} == expected
    # The same figures the engine gives line by line.
    figures = await svc.claim_retention_figures(claim)
    assert figures is not None
    assert {line_id: share.retention_to_date for line_id, share in figures.lines.items()} == expected
    assert Decimal(str(claim.retention_amount)) == Decimal("154.00")

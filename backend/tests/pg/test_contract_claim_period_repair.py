# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A claim billed before the period date columns existed gets its dates.

The product never runs ``alembic upgrade``. An existing install boots with its
claims already in the table, the boot heal adds ``period_from``, ``period_to``
and ``application_date`` empty, and only the ``contracts_claim_period_dates``
repair fills them. Every date question the billing work asks - which claims
came before this one, which sub pay apps fall in this month - reads those
columns, so a repair that does nothing leaves every legacy claim unordered
while every signal says the upgrade went fine.

The first test walks that path for real: the columns are dropped from a
populated table, the heal puts them back, and the repair has to fill them. The
second holds the repair to what it may and may not write, twice over, because a
second boot runs it again.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import text

from app.modules.contracts.repairs import _run_claim_period_dates

pytestmark = pytest.mark.asyncio

_CLAIM = "oe_contracts_progress_claim"
_CLAIM_LINE = "oe_contracts_progress_claim_line"
_LINE = "oe_contracts_contract_line"

#: What v42 adds to the three existing tables, and whether each may hold NULL.
#: The nullable ones are nullable because a zero would be a false statement
#: about a legacy row; see the revision's docstring.
_ADDED: dict[str, dict[str, str]] = {
    _CLAIM: {
        "period_from": "YES",
        "period_to": "YES",
        "application_date": "YES",
        "completed_stored_to_date": "YES",
        "retention_held_to_date": "YES",
    },
    _CLAIM_LINE: {
        "prior_completed_value": "YES",
        "materials_stored_value": "NO",
        "retention_to_date": "YES",
        "retention_stored_to_date": "YES",
        "retention_rate": "YES",
    },
    _LINE: {"origin": "NO", "source_key": "YES", "original_value": "YES"},
}


def _parents(suffix: str) -> tuple:
    from app.modules.contracts.models import Contract, ContractLine
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(
        id=uuid.uuid4(),
        email=f"claim-periods-{suffix}@site.example",
        hashed_password="x",
        full_name="Project Accountant",
    )
    project = Project(id=uuid.uuid4(), name="Claim period probe", owner_id=owner.id, currency="USD")
    contract = Contract(
        id=uuid.uuid4(), project_id=project.id, code=f"CT-{suffix}", title="Prime contract", currency="USD"
    )
    line = ContractLine(id=uuid.uuid4(), contract_id=contract.id, description="Site concrete", total_value="1000")
    return owner, project, contract, line


def _claim(contract_id: uuid.UUID, number: str, **fields: object):
    from app.modules.contracts.models import ProgressClaim

    return ProgressClaim(id=uuid.uuid4(), contract_id=contract_id, claim_number=number, currency="USD", **fields)


async def _live_columns(conn, table: str) -> dict[str, str]:
    rows = await conn.execute(
        text("SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name = :t"),
        {"t": table},
    )
    return {name: nullable for name, nullable in rows.all()}


async def _dates(session, claim_id: uuid.UUID) -> tuple:
    row = await session.execute(
        text(f"SELECT period_from, period_to, application_date FROM {_CLAIM} WHERE id = :id"),  # noqa: S608
        {"id": str(claim_id)},
    )
    return tuple(row.one())


async def test_the_heal_then_the_repair_bring_a_populated_install_up_to_date(pg_engine) -> None:
    """Columns back with the right nullability, legacy rows filled, money untouched."""
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.core.postgres_migrator import postgres_auto_migrate
    from app.database import Base
    from app.modules.contracts.models import ProgressClaimLine

    suffix = uuid.uuid4().hex[:8]
    owner, project, contract, line = _parents(suffix)
    claim = _claim(
        contract.id,
        "PC-001",
        period_start="2026-03-01",
        period_end="2026-03-31",
        claim_date="2026-04-02",
        gross_amount="400",
    )
    claim_line = ProgressClaimLine(
        id=uuid.uuid4(), progress_claim_id=claim.id, contract_line_id=line.id, period_completed_value="400"
    )
    claim_id, claim_line_id, line_id = claim.id, claim_line.id, line.id
    async with AsyncSession(pg_engine) as session:
        # One at a time: the metadata holds foreign-key cycles, so the unit of
        # work cannot always sort a batch of these by dependency.
        for row in (owner, project, contract, line, claim, claim_line):
            session.add(row)
            await session.flush()
        await session.commit()

    async with pg_engine.begin() as conn:
        for table, columns in _ADDED.items():
            for column in columns:
                await conn.execute(text(f'ALTER TABLE "{table}" DROP COLUMN IF EXISTS "{column}" CASCADE'))

    async with pg_engine.connect() as conn:
        for table, columns in _ADDED.items():
            assert not set(columns) & set(await _live_columns(conn, table)), f"{table} still has the new columns"

    await postgres_auto_migrate(pg_engine, Base)

    async with pg_engine.connect() as conn:
        for table, columns in _ADDED.items():
            live = await _live_columns(conn, table)
            for column, nullable in columns.items():
                assert column in live, f"the heal did not add {table}.{column} back"
                assert live[column] == nullable, f"{table}.{column} came back with is_nullable={live[column]}"
        index = (
            await conn.execute(
                text("SELECT 1 FROM pg_indexes WHERE tablename = :t AND indexname = :i"),
                {"t": _CLAIM, "i": "ix_oe_contracts_progress_claim_period_to"},
            )
        ).scalar_one_or_none()
        assert index == 1, "the period_to index did not come back under its model name"
        stored = (
            await conn.execute(
                text(
                    f"SELECT materials_stored_value, prior_completed_value, period_completed_value FROM {_CLAIM_LINE} WHERE id = :id"
                ),  # noqa: S608
                {"id": str(claim_line_id)},
            )
        ).one()
        origin = (
            await conn.execute(text(f"SELECT origin FROM {_LINE} WHERE id = :id"), {"id": str(line_id)})  # noqa: S608
        ).scalar_one()

    # Stored materials were never recorded before, so zero is the truth. The
    # prior value was never stored either, and NULL is what tells the G703
    # builder to derive it rather than read a false zero.
    assert stored.materials_stored_value == 0
    assert stored.prior_completed_value is None
    assert stored.period_completed_value == 400
    assert origin == "original"

    async with AsyncSession(pg_engine) as session:
        assert await _dates(session, claim_id) == (None, None, None), "the heal filled dates it cannot know"
        await _run_claim_period_dates(session)
        await session.commit()
        assert await _dates(session, claim_id) == (date(2026, 3, 1), date(2026, 3, 31), date(2026, 4, 2))


async def test_the_repair_fills_only_what_it_can_read_and_changes_nothing_the_second_time(pg_session) -> None:
    suffix = uuid.uuid4().hex[:8]
    owner, project, contract, line = _parents(suffix)
    claims = {
        "iso": _claim(contract.id, "PC-1", period_start="2026-01-01", period_end="2026-01-31", claim_date="2026-02-03"),
        # A bare month covers the whole month.
        "month": _claim(contract.id, "PC-2", period_start="2026-02", period_end="2026-02"),
        # Day-month or month-day cannot be told apart, so neither is guessed.
        "ambiguous": _claim(contract.id, "PC-3", period_start="03/04/2026", period_end="  "),
        # A date already on file wins over the string beside it.
        "set": _claim(contract.id, "PC-4", period_start="2026-04-01", period_from=date(2026, 4, 2)),
    }
    for row in (owner, project, contract, line, *claims.values()):
        pg_session.add(row)
        await pg_session.flush()
    ids = {label: claim.id for label, claim in claims.items()}

    # Negative control: the rows start in the legacy state, or the repair is
    # asserted over nothing.
    assert await _dates(pg_session, ids["iso"]) == (None, None, None)

    changed = await _run_claim_period_dates(pg_session)
    # Two of the four: "iso" and "month". Other rows in the shared cluster may
    # count too, so this is a floor rather than an exact figure.
    assert changed >= 2

    assert await _dates(pg_session, ids["iso"]) == (date(2026, 1, 1), date(2026, 1, 31), date(2026, 2, 3))
    assert await _dates(pg_session, ids["month"]) == (date(2026, 2, 1), date(2026, 2, 28), None)
    assert await _dates(pg_session, ids["ambiguous"]) == (None, None, None)
    assert await _dates(pg_session, ids["set"]) == (date(2026, 4, 2), None, None)

    before = {label: await _dates(pg_session, claim_id) for label, claim_id in ids.items()}
    assert await _run_claim_period_dates(pg_session) == 0
    assert {label: await _dates(pg_session, claim_id) for label, claim_id in ids.items()} == before

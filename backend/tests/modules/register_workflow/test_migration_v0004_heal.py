# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""v0004 must heal a database carrying the stale UNIQUE-on-prefix index.

The test databases are built from the model's metadata, so they never have
the bad shape - which is exactly why the live failure was invisible to a
green suite. Here the stale index is created deliberately, the migration
is run against it, and the healed schema is proven to accept what the
live databases refused: two jobs opening the same kind's series.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.register_workflow import service
from app.modules.register_workflow.migrations import v0004_prefix_index_not_unique as v0004
from app.modules.users.models import User
from tests._pg import transactional_session

_COUNTER = "oe_register_workflow_counter"
_IX = f"ix_{_COUNTER}_prefix"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _job(session: AsyncSession, code: str) -> uuid.UUID:
    user = User(
        email=f"mig-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Mig",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"Mig {code}", owner_id=user.id, currency="AUD", project_code=code)
    session.add(proj)
    await session.flush()
    return proj.id


def _break_then_heal(conn: sa.Connection) -> dict[str, bool]:
    """Recreate the live databases' bad shape, run v0004, report the result."""
    conn.exec_driver_sql(f"DROP INDEX IF EXISTS {_IX}")
    conn.exec_driver_sql(f"CREATE UNIQUE INDEX {_IX} ON {_COUNTER} (prefix)")

    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        v0004.upgrade()

    indexes = {i["name"]: i for i in sa.inspect(conn).get_indexes(_COUNTER)}
    return {
        "plain_ix_back": _IX in indexes and not indexes[_IX].get("unique"),
        "composite_kept": any(
            sorted(i.get("column_names") or []) == ["prefix", "scope"] and i.get("unique") for i in indexes.values()
        ),
    }


@pytest.mark.asyncio
async def test_v0004_drops_the_unique_and_keeps_the_composite(session: AsyncSession) -> None:
    conn = await session.connection()
    result = await conn.run_sync(_break_then_heal)
    assert result["plain_ix_back"], "the prefix index is missing or still UNIQUE"
    assert result["composite_kept"], "the (prefix, scope) rail must survive the heal"


@pytest.mark.asyncio
async def test_v0004_is_idempotent_on_a_healthy_database(session: AsyncSession) -> None:
    """A database already in the right shape passes straight through."""

    def _run_twice(conn: sa.Connection) -> None:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            v0004.upgrade()
            v0004.upgrade()

    conn = await session.connection()
    await conn.run_sync(_run_twice)


@pytest.mark.asyncio
async def test_after_the_heal_two_jobs_open_the_same_kind(session: AsyncSession) -> None:
    """The behaviour the live databases refused, on the healed schema."""
    conn = await session.connection()
    await conn.run_sync(_break_then_heal)

    a = await _job(session, "31001")
    b = await _job(session, "31002")
    ia = await service.raise_item(session, project_id=a, kind="rfi", title="a", fields={})
    ib = await service.raise_item(session, project_id=b, kind="rfi", title="b", fields={})
    assert ia.reference == "REG-RFI-31001-0001"
    assert ib.reference == "REG-RFI-31002-0001"

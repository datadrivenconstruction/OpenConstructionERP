# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The half of ``v41_funding_obligation_detail`` that reaches an ordinary install.

The revision tightens ``oe_funding_obligation.detail_params``, and on its own
that reaches almost nobody. The product does not run ``alembic upgrade``: it
moves the schema at boot through the heal and then stamps head, so a revision
body executes only where an operator runs it by hand. The tests beside this
file prove the revision emits the right statements and that PostgreSQL accepts
them, which is worth knowing and is not the same as the column being fixed
anywhere.

These pin the two pieces that do reach an install, one per direction of the
problem.

Backwards, for a database already in the broken shape, the registered repair
``funding_obligation_detail_params_not_null`` does from the boot path what the
revision does from the migration path. Forwards, the model now declares a
``server_default``, which is the only reason the heal will stop producing the
bare column in the first place: without it every newly healed install would
arrive broken and the repair would clean up after it forever.

The repair runs against the real table, deliberately. It is put into the broken
shape first - NOT NULL and DEFAULT dropped, a NULL row written - inside a
transaction that is rolled back, so what is under test is the table the repair
actually names rather than a lookalike. A temporary stand-in would have to be
reached by moving ``search_path``, and ``tighten_not_null`` reads
``information_schema`` filtered on ``current_schema()``, so getting that wrong
returns zero and looks like a clean pass over a table the repair never saw.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.funding.repairs import _run
from tests._pg import transactional_session

_TABLE = "oe_funding_obligation"
_COLUMN = "detail_params"

_DESCRIBE = sa.text(
    "SELECT a.attnotnull, pg_get_expr(d.adbin, d.adrelid) "
    "FROM pg_attribute a "
    "LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
    f"WHERE a.attrelid = '{_TABLE}'::regclass AND a.attname = '{_COLUMN}'"
)

_INSERT = sa.text(
    f"INSERT INTO {_TABLE} (id, application_id, kind, title, detail, detail_key, "
    f"{_COLUMN}, due_on, source, source_reference, status, completed_on, "
    "created_at, updated_at) "
    "VALUES (:id, :app, 'condition', '', '', '', NULL, '', 'manual', '', 'open', '', "
    "now(), now())"
)


def _a_row() -> dict[str, str]:
    """Identifiers for one obligation row, with no application built around it."""
    return {"id": str(uuid.uuid4()), "app": str(uuid.uuid4())}


async def _break_the_column(session: AsyncSession) -> None:
    """Put the live table into the shape the boot heal leaves it in.

    The foreign key to the application goes too, so a row can be written
    without standing up a whole funding application behind it. Every statement
    here is DDL or DML inside the caller's transaction, and PostgreSQL rolls
    DDL back like anything else.
    """
    await session.execute(sa.text(f"ALTER TABLE {_TABLE} ALTER COLUMN {_COLUMN} DROP NOT NULL"))
    await session.execute(sa.text(f"ALTER TABLE {_TABLE} ALTER COLUMN {_COLUMN} DROP DEFAULT"))
    constraint = await session.scalar(
        sa.text(f"SELECT conname FROM pg_constraint WHERE conrelid = '{_TABLE}'::regclass AND contype = 'f' LIMIT 1")
    )
    assert constraint, "expected a foreign key on the obligation table"
    await session.execute(sa.text(f"ALTER TABLE {_TABLE} DROP CONSTRAINT {constraint}"))


@pytest.mark.asyncio
async def test_the_repair_restores_the_column_the_heal_left_bare() -> None:
    """The backwards half: a database already in the broken shape is fixed."""
    async with transactional_session() as session:
        await _break_the_column(session)

        not_null, default = (await session.execute(_DESCRIBE)).one()
        assert not_null is False and default is None, "the broken shape was not established"

        await session.execute(_INSERT, _a_row())

        rewritten = await _run(session)

        assert rewritten == 1, "the repair must report the row it backfilled, not a bare success"
        not_null, default = (await session.execute(_DESCRIBE)).one()
        assert not_null is True, "the column is still nullable, so health still reports divergence"
        assert default is not None, "the column has no default, so the two build paths still differ"

        remaining = await session.scalar(sa.text(f"SELECT count(*) FROM {_TABLE} WHERE {_COLUMN} IS NULL"))
        assert remaining == 0

        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                await session.execute(_INSERT, _a_row())


@pytest.mark.asyncio
async def test_a_second_run_recognises_its_own_work_and_does_nothing() -> None:
    """A repair that cannot see it already ran is a new permanent false signal.

    ``tighten_not_null`` decides by asking whether the column is NOT NULL and
    carries any default at all, rather than by comparing the default's text.
    That distinction is the whole of this test. Every other caller is a
    ``varchar`` whose default reads back as ``''::character varying``; this one
    is ``json`` and reads back as ``'{}'::json``, so a comparison written
    against the varchar spelling would re-issue the ALTERs on every boot and
    write a ledger row at every start, for the life of the install.
    """
    async with transactional_session() as session:
        await _break_the_column(session)

        await _run(session)
        _, default = (await session.execute(_DESCRIBE)).one()
        assert default is not None

        second = await _run(session)

        assert second == 0, "the repair rewrote rows on a table it had already repaired"
        again, default_again = (await session.execute(_DESCRIBE)).one()
        assert again is True
        assert default_again == default, "the second run changed a default it should not have touched"


def test_the_model_declares_a_default_the_heal_can_render() -> None:
    """The forwards half: a newly healed install must not arrive broken.

    The heal writes a column default into DDL only when the model gives it one
    it can spell. ``default=dict`` is a callable evaluated per row and has
    none, which is what produced the bare column, and a column added with no
    default cannot be added NOT NULL either. So this asserts on the compiled
    DDL rather than on the attribute: what matters is the text the database is
    handed, and an attribute that is merely present has been true before while
    the DDL still came out bare.
    """
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable

    from app.modules.funding.models import FundingObligation

    ddl = str(CreateTable(FundingObligation.__table__).compile(dialect=postgresql.dialect()))
    line = next(fragment.strip() for fragment in ddl.splitlines() if _COLUMN in fragment)

    assert "DEFAULT '{}'" in line, f"the heal has no literal to render for this column: {line}"
    assert "NOT NULL" in line, f"the column would be added nullable: {line}"

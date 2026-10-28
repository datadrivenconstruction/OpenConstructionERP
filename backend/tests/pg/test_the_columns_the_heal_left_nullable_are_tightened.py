# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Can anything put back the NOT NULL the boot heal had to decline.

``not_null_divergences`` reports the divergence and stops there; nothing on the
boot path tightened the column afterwards. These tests cover the repair that
does, on a table driven into exactly the state the heal leaves behind: column
present, nullable, no default, rows already in it holding NULL.

The controls carry the weight, as they do for the divergence check itself. A
repair that rewrote every row, or that dropped the constraint instead of adding
it, would satisfy the first test here and be worse than doing nothing. So one
test pins that a row holding a real value keeps it, one pins that a column both
sides already agree about is not touched at all, and one runs the whole thing
twice because the registry runs it on every boot.

The last test is the one that would catch this drifting apart again: it holds
the repairs' column lists against the models, so a column renamed in
``models.py`` cannot leave a repair quietly naming something that is no longer
there.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.not_null_repair import tighten_not_null

pytestmark = pytest.mark.asyncio

_TABLE = "oe_test_tighten_probe"
_SCHEMA = "oe_test_v3312"

#: Mirrors the real repair's shape: a string column defaulting to empty and a
#: numeric one defaulting to zero, which are the two literal forms in use.
_COLUMNS = {"needs_text": "''", "needs_number": "0"}

#: The three real tables, carrying only the nine columns under repair, each
#: declared the way the old heal left it: nullable and with no default.
_REAL_TABLES: dict[str, tuple[tuple[str, str], ...]] = {
    "oe_formwork_system": (("erect_strike_rate", "NUMERIC(18, 2)"), ("strip_time_days", "INTEGER")),
    "oe_formwork_assignment": (("material_unit_cost", "NUMERIC(18, 2)"), ("labour_unit_cost", "NUMERIC(18, 2)")),
    "oe_requirements_item": (
        ("rationale", "TEXT"),
        ("originator", "VARCHAR(255)"),
        ("originator_role", "VARCHAR(50)"),
        ("phase", "VARCHAR(50)"),
        ("verification_method", "VARCHAR(50)"),
    ),
}


def _revision():
    """Load ``v3312`` from its path - alembic versions are not an importable package."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "v3312_heal_left_columns_nullable.py"
    spec = importlib.util.spec_from_file_location("v3312_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
async def healed_table(pg_engine):
    """A table in the state the pre-2026-08-24 heal left behind.

    Built by hand rather than by driving the real heal: the heal now keeps the
    NOT NULL whenever the model names a scalar default, so asking it to
    reproduce the old behaviour would mean feeding it a model that no longer
    resembles the nine columns this repairs. The state is the subject here, and
    it is fully described by nullable + no default + rows holding NULL.
    """
    async with pg_engine.begin() as conn:
        await conn.execute(text(f'DROP TABLE IF EXISTS "{_TABLE}"'))
        await conn.execute(
            text(
                f'CREATE TABLE "{_TABLE}" ('
                " id INTEGER NOT NULL PRIMARY KEY,"
                " needs_text VARCHAR(32),"
                " needs_number NUMERIC(18, 2),"
                # Control: the heal got this one in whole, both sides agree.
                " agreed VARCHAR(32) NOT NULL DEFAULT '',"
                # The half-repaired cell: constraint on, default still missing.
                " tight_no_default VARCHAR(32) NOT NULL"
                ")"
            )
        )
        # Row 1 is what the heal leaves: NULL in both. Row 2 holds real values
        # and is the negative control - the backfill must not reach it.
        await conn.execute(
            text(
                f"INSERT INTO \"{_TABLE}\" (id, needs_text, needs_number, tight_no_default) VALUES (1, NULL, NULL, 'x')"
            )
        )
        await conn.execute(
            text(
                f'INSERT INTO "{_TABLE}" (id, needs_text, needs_number, tight_no_default) '
                "VALUES (2, 'kept', 42.50, 'x')"
            )
        )
    yield
    async with pg_engine.begin() as conn:
        await conn.execute(text(f'DROP TABLE IF EXISTS "{_TABLE}"'))


async def _column_state(pg_engine, column: str) -> tuple[str, object]:
    async with pg_engine.connect() as conn:
        row = await conn.execute(
            text(
                "SELECT is_nullable, column_default FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = :t AND column_name = :c"
            ),
            {"t": _TABLE, "c": column},
        )
        return row.one()


async def test_the_nulls_are_backfilled_and_the_constraint_goes_back_on(pg_engine, healed_table) -> None:
    """The whole point: rows filled, NOT NULL restored, DEFAULT restored."""
    async with AsyncSession(pg_engine) as session:
        rewritten = await tighten_not_null(session, _TABLE, _COLUMNS)
        await session.commit()

    assert rewritten == 2, "one NULL row in each of the two columns"

    async with pg_engine.connect() as conn:
        remaining = await conn.execute(
            text(f'SELECT count(*) FROM "{_TABLE}" WHERE needs_text IS NULL OR needs_number IS NULL')  # noqa: S608
        )
        assert remaining.scalar() == 0

    for column, default_fragment in (("needs_text", "''"), ("needs_number", "0")):
        is_nullable, default = await _column_state(pg_engine, column)
        assert is_nullable == "NO", f"{column} is still nullable"
        assert default is not None and default_fragment in default, f"{column} has no DEFAULT: {default!r}"


async def test_a_row_that_already_held_a_value_keeps_it(pg_engine, healed_table) -> None:
    """The negative control, and the one that matters most.

    A backfill written without its WHERE clause passes every other test in this
    file: the NULLs are gone, the constraint is on, the second pass is clean.
    It would also have overwritten every priced rate in the table with zero.
    """
    async with AsyncSession(pg_engine) as session:
        await tighten_not_null(session, _TABLE, _COLUMNS)
        await session.commit()

    async with pg_engine.connect() as conn:
        row = await conn.execute(text(f'SELECT needs_text, needs_number FROM "{_TABLE}" WHERE id = 2'))  # noqa: S608
        text_value, number_value = row.one()
    assert text_value == "kept"
    assert float(number_value) == 42.50


async def test_a_column_both_sides_already_agree_about_is_not_touched(pg_engine, healed_table) -> None:
    """Asking for a column that is already NOT NULL with a default issues nothing."""
    async with AsyncSession(pg_engine) as session:
        rewritten = await tighten_not_null(session, _TABLE, {"agreed": "''"})
        await session.commit()

    assert rewritten == 0
    is_nullable, _default = await _column_state(pg_engine, "agreed")
    assert is_nullable == "NO"


async def test_a_column_that_is_tight_but_has_no_default_gets_only_the_default(pg_engine, healed_table) -> None:
    """The one cell of the decision table the other tests never reach.

    Nullable and defaultless is what the heal leaves, so it is what every other
    fixture here builds. This is the state a half-finished repair leaves instead:
    the constraint is on, the DEFAULT is not. No row may be rewritten - every row
    already holds a value, or the constraint would not be there - and the column
    must not be re-tightened, because it already is.

    :func:`app.core.not_null_repair.tighten_not_null` and the revision's own
    ``_todo`` are parallel readings of the same four-cell table, so this is also
    where they would silently disagree.
    """
    async with AsyncSession(pg_engine) as session:
        rewritten = await tighten_not_null(session, _TABLE, {"tight_no_default": "''"})
        await session.commit()

    assert rewritten == 0, "every row already holds a value, so nothing may be rewritten"
    is_nullable, default = await _column_state(pg_engine, "tight_no_default")
    assert is_nullable == "NO", "the column was already NOT NULL and must stay that way"
    assert default is not None and "''" in default, f"the DEFAULT was not restored: {default!r}"


async def test_a_second_pass_changes_nothing(pg_engine, healed_table) -> None:
    """The registry runs this on every boot, so the second run has to be free."""
    async with AsyncSession(pg_engine) as session:
        first = await tighten_not_null(session, _TABLE, _COLUMNS)
        await session.commit()
    async with AsyncSession(pg_engine) as session:
        second = await tighten_not_null(session, _TABLE, _COLUMNS)
        await session.commit()

    assert first == 2
    assert second == 0


async def test_a_table_this_install_never_built_is_not_an_error(pg_engine) -> None:
    """A repair runs on every install, including the ones without the module."""
    async with AsyncSession(pg_engine) as session:
        assert await tighten_not_null(session, "oe_test_tighten_absent", _COLUMNS) == 0


@pytest.mark.parametrize("bad", ["oe_table; DROP TABLE x", 'oe_"quoted"', "OE_Upper"])
async def test_an_identifier_that_is_not_a_plain_name_is_refused(pg_engine, bad: str) -> None:
    """Identifiers are interpolated, so the guard against a future typo is checked."""
    async with AsyncSession(pg_engine) as session:
        with pytest.raises(ValueError):
            await tighten_not_null(session, bad, _COLUMNS)
        with pytest.raises(ValueError):
            await tighten_not_null(session, _TABLE, {bad: "''"})


@pytest.fixture
async def damaged_real_tables(pg_engine):
    """The three real tables, in the state the old heal left, in their own schema.

    ``v3312`` names the real tables, so it cannot be pointed at a probe table
    the way the repair can. A dedicated schema with ``search_path`` set to it is
    what makes running the revision safe: the inspector and every unqualified
    statement resolve there, the real tables are not visible, and dropping the
    schema at the end takes the whole thing with it.
    """
    async with pg_engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
        await conn.execute(text(f"CREATE SCHEMA {_SCHEMA}"))
        await conn.execute(text(f"SET search_path TO {_SCHEMA}"))
        for table, columns in _REAL_TABLES.items():
            body = ", ".join(f"{name} {type_}" for name, type_ in columns)
            await conn.execute(text(f"CREATE TABLE {table} (id INTEGER NOT NULL PRIMARY KEY, {body})"))
            await conn.execute(text(f"INSERT INTO {table} (id) VALUES (1)"))  # noqa: S608
    yield
    async with pg_engine.begin() as conn:
        await conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))


async def test_the_revision_repairs_the_nine_it_names(pg_engine, damaged_real_tables) -> None:
    """The other half of the fix, on the tables it actually names.

    The revision body never runs on an ordinary install - the product stamps
    head without executing it, which is why the repairs above exist - so this is
    the only thing that exercises it at all. Running it here also checks the
    nine names against tables built from the same column lists the models
    declare, so a typo in the revision cannot hide behind a guard that skips
    columns it cannot find.
    """
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    def _upgrade(sync_conn) -> None:
        sync_conn.exec_driver_sql(f"SET search_path TO {_SCHEMA}")
        context = MigrationContext.configure(sync_conn)
        with Operations.context(context):
            _revision().upgrade()

    async with pg_engine.begin() as conn:
        await conn.run_sync(_upgrade)

    async with pg_engine.connect() as conn:
        await conn.execute(text(f"SET search_path TO {_SCHEMA}"))
        rows = await conn.execute(
            text(
                "SELECT table_name, column_name, is_nullable, column_default FROM information_schema.columns "
                "WHERE table_schema = :s AND column_name <> 'id'"
            ),
            {"s": _SCHEMA},
        )
        state = {(t, c): (n, d) for t, c, n, d in rows}

    assert len(state) == 9, f"expected the nine, saw {sorted(state)}"
    for (table, column), (is_nullable, default) in sorted(state.items()):
        assert is_nullable == "NO", f"{table}.{column} left nullable by the revision"
        assert default is not None, f"{table}.{column} left without a DEFAULT"


async def test_the_revision_is_idempotent_against_a_database_the_repair_reached(pg_engine, damaged_real_tables) -> None:
    """A database the boot repair already fixed still has to reach head cleanly."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    def _upgrade(sync_conn) -> None:
        sync_conn.exec_driver_sql(f"SET search_path TO {_SCHEMA}")
        context = MigrationContext.configure(sync_conn)
        with Operations.context(context):
            _revision().upgrade()

    async with pg_engine.begin() as conn:
        await conn.run_sync(_upgrade)
    async with pg_engine.begin() as conn:
        await conn.run_sync(_upgrade)  # Must not raise, and must change nothing.


async def test_the_repairs_name_columns_the_models_still_declare_not_null() -> None:
    """Holds both repairs' column lists against the models they exist to serve.

    Without this, renaming a column in ``models.py`` leaves the repair naming
    one that is no longer there. ``tighten_not_null`` skips a column it cannot
    find, by design - a module that was never installed has no columns at all -
    so the repair would go on reporting a clean run forever while the real
    column stayed nullable. That is the same silence this whole defect is made
    of, one layer further in.
    """
    from app.database import Base
    from app.modules.formwork import models as formwork_models  # noqa: F401
    from app.modules.formwork.repairs import _ASSIGNMENT, _ASSIGNMENT_COLUMNS, _SYSTEM, _SYSTEM_COLUMNS
    from app.modules.requirements import models as requirements_models  # noqa: F401
    from app.modules.requirements.repairs import _ITEM, _ITEM_COLUMNS

    for table_name, columns in (
        (_SYSTEM, _SYSTEM_COLUMNS),
        (_ASSIGNMENT, _ASSIGNMENT_COLUMNS),
        (_ITEM, _ITEM_COLUMNS),
    ):
        table = Base.metadata.tables[table_name]
        for column, literal in columns.items():
            assert column in table.columns, f"{table_name}.{column} is named by a repair and not by the models"
            model_column = table.columns[column]
            assert not model_column.nullable, f"{table_name}.{column} is no longer NOT NULL in the models"
            # The literal the repair backfills with has to be the model's own
            # default, or the two build paths end up with different values.
            model_default = model_column.default.arg
            assert literal == ("''" if model_default == "" else str(model_default)), (
                f"{table_name}.{column}: repair backfills {literal} but the model defaults to {model_default!r}"
            )

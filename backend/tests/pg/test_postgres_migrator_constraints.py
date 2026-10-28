"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The migrator must restore missing constraints without ever failing a boot.

``postgres_auto_migrate`` runs at startup on every embedded and desktop install.
Adding constraint healing to it introduces a hazard that the column and index
healing never had: the databases missing a constraint are exactly the ones that
may hold rows violating it, because the constraint is what would have stopped
those rows being written. ``ALTER TABLE ... ADD CONSTRAINT UNIQUE`` against a
table holding duplicates raises, and an uncaught raise here does not degrade the
feature, it stops the application starting.

So the gate is not "the constraint came back". That passes trivially. The gate is
"a database that cannot take the constraint still boots", which is the test below
that plants duplicate rows on purpose.

The migrator opens and commits its own transaction, so these tests cannot be
wrapped in an outer rollback. Each one restores what it changed in a ``finally``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

from app.core.postgres_migrator import postgres_auto_migrate

pytestmark = pytest.mark.asyncio

NCR_TABLE = "oe_ncr_ncr"


async def _inspect(conn, fn):
    return await conn.run_sync(lambda sync_conn: fn(inspect(sync_conn)))


def _placeholder(type_name: str) -> str:
    """A syntactically valid value for a column type, for a throwaway row.

    Built from the live column type rather than the model so a change to the NCR
    table cannot silently stop this test from inserting anything, which would
    make it pass for the wrong reason.
    """
    lowered = type_name.lower()
    if "uuid" in lowered:
        return "gen_random_uuid()"
    if "bool" in lowered:
        return "false"
    if any(token in lowered for token in ("int", "numeric", "decimal", "double", "real", "float")):
        return "0"
    if "timestamp" in lowered:
        return "now()"
    if "date" in lowered:
        return "current_date"
    if "json" in lowered:
        return "'{}'"
    return "'x'"


async def _minimal_insert(conn, table: str, fixed: dict[str, str], depth: int = 0) -> None:
    """Insert one row supplying only what the live schema demands.

    ``fixed`` pins the columns the test cares about. Everything else that is NOT
    NULL and has no default gets a placeholder of the right shape, and a NOT NULL
    foreign key is satisfied by reusing a parent row if one exists or creating one
    if it does not. Building the row from the live schema rather than from the
    model means a change to the table cannot quietly stop this test inserting,
    which would make it pass for the wrong reason.
    """
    assert depth < 5, f"foreign key chain from {table} is deeper than this helper handles"

    columns = await _inspect(conn, lambda i: i.get_columns(table))
    fks = await _inspect(conn, lambda i: i.get_foreign_keys(table))
    fk_by_column = {(fk.get("constrained_columns") or [None])[0]: fk for fk in fks if fk.get("constrained_columns")}

    names: list[str] = []
    values: list[str] = []
    for column in columns:
        name = column["name"]
        if name in fixed:
            names.append(name)
            values.append(fixed[name])
            continue
        if column.get("nullable", True) or column.get("default") is not None:
            continue

        names.append(name)
        fk = fk_by_column.get(name)
        if fk is None:
            values.append(_placeholder(str(column["type"])))
            continue

        parent_table = fk["referred_table"]
        parent_column = (fk.get("referred_columns") or ["id"])[0]
        existing = (
            await conn.execute(text(f'SELECT "{parent_column}" FROM "{parent_table}" LIMIT 1'))  # noqa: S608
        ).first()
        if existing is None:
            await _minimal_insert(conn, parent_table, {}, depth + 1)
            existing = (
                await conn.execute(text(f'SELECT "{parent_column}" FROM "{parent_table}" LIMIT 1'))  # noqa: S608
            ).first()
        values.append(f"'{existing[0]}'")

    cols_sql = ", ".join(f'"{n}"' for n in names)
    vals_sql = ", ".join(values)
    await conn.execute(text(f'INSERT INTO "{table}" ({cols_sql}) VALUES ({vals_sql})'))  # noqa: S608


async def _ncr_unique(conn) -> tuple[str, list[str]]:
    live = await _inspect(conn, lambda i: i.get_unique_constraints(NCR_TABLE))
    assert live, f"{NCR_TABLE} has no unique constraint to work with"
    return live[0]["name"], list(live[0]["column_names"])


async def test_a_database_holding_duplicates_still_boots(pg_engine) -> None:
    """The one that matters. Duplicates present means skip and carry on, never raise.

    This reproduces the exact install the healing exists for: the constraint was
    lost, two records took the same document number because nothing stopped them,
    and now the application is starting.
    """
    async with pg_engine.begin() as conn:
        name, cols = await _ncr_unique(conn)
        await conn.execute(text(f'ALTER TABLE "{NCR_TABLE}" DROP CONSTRAINT "{name}"'))
        # Pin only the document number. The project reference is left to the
        # helper, which reuses the same parent row for both inserts, so the two
        # records collide on exactly the tuple the constraint covers. The primary
        # key has to differ or the rows collide there first and prove nothing.
        number_column = next(col for col in cols if "number" in col)
        for row_id in ("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"):
            await _minimal_insert(
                conn,
                NCR_TABLE,
                {number_column: "'DUPLICATE-001'", "id": f"'{row_id}'"},
            )

        planted = (
            await conn.execute(
                text(f'SELECT count(*) FROM "{NCR_TABLE}" WHERE "{number_column}" = \'DUPLICATE-001\'')  # noqa: S608
            )
        ).scalar()
        assert planted == 2, f"expected two colliding rows, planted {planted}"

    try:
        from app.database import Base

        # Must not raise. A raise here is a failed startup on a real install.
        await postgres_auto_migrate(pg_engine, Base)

        async with pg_engine.connect() as conn:
            live = await _inspect(conn, lambda i: i.get_unique_constraints(NCR_TABLE))
        assert not any(u["name"] == name for u in live), (
            "the migrator added a unique constraint over duplicate rows, which PostgreSQL "
            "cannot do; if this passes the duplicates were not planted correctly"
        )
    finally:
        async with pg_engine.begin() as conn:
            number_column = next(col for col in cols if "number" in col)
            await conn.execute(
                text(f'DELETE FROM "{NCR_TABLE}" WHERE "{number_column}" = \'DUPLICATE-001\'')  # noqa: S608
            )
            live = await _inspect(conn, lambda i: i.get_unique_constraints(NCR_TABLE))
            if not any(u["name"] == name for u in live):
                cols_sql = ", ".join(f'"{c}"' for c in cols)
                await conn.execute(text(f'ALTER TABLE "{NCR_TABLE}" ADD CONSTRAINT "{name}" UNIQUE ({cols_sql})'))


async def test_a_clean_table_gets_its_unique_constraint_back(pg_engine) -> None:
    async with pg_engine.begin() as conn:
        name, cols = await _ncr_unique(conn)
        await conn.execute(text(f'ALTER TABLE "{NCR_TABLE}" DROP CONSTRAINT "{name}"'))

    from app.database import Base

    await postgres_auto_migrate(pg_engine, Base)

    async with pg_engine.connect() as conn:
        live = await _inspect(conn, lambda i: i.get_unique_constraints(NCR_TABLE))
    restored = [u for u in live if set(u["column_names"]) == set(cols)]
    assert restored, f"unique over {cols} was not restored; live constraints are {live}"


async def test_a_restored_foreign_key_keeps_its_on_delete(pg_engine) -> None:
    """Healing an FK without its ON DELETE would swap one divergence for another."""
    table = "oe_ncr_ncr"
    async with pg_engine.connect() as conn:
        live_fks = await _inspect(conn, lambda i: i.get_foreign_keys(table))
    cascading = [fk for fk in live_fks if (fk.get("options") or {}).get("ondelete")]
    if not cascading:
        pytest.skip(f"{table} has no foreign key carrying ON DELETE")
    target = cascading[0]
    expected = target["options"]["ondelete"].upper()

    async with pg_engine.begin() as conn:
        await conn.execute(text(f'ALTER TABLE "{table}" DROP CONSTRAINT "{target["name"]}"'))

    from app.database import Base

    await postgres_auto_migrate(pg_engine, Base)

    async with pg_engine.connect() as conn:
        live_fks = await _inspect(conn, lambda i: i.get_foreign_keys(table))
    restored = [fk for fk in live_fks if fk["name"] == target["name"]]
    assert restored, f"foreign key {target['name']} was not restored; live keys are {live_fks}"
    actual = (restored[0].get("options") or {}).get("ondelete", "")
    assert actual.upper() == expected, f"foreign key came back with ON DELETE {actual!r}, model declares {expected!r}"


async def test_the_migrator_adds_nothing_to_an_already_healthy_schema(pg_engine) -> None:
    """A healthy schema must need no healing at all, on the FIRST run.

    This test used to call the migrator once to settle and then assert on the
    second call. That hid a real bug rather than catching it: the first call was
    adding two duplicate CHECK constraints, and by the second call they were
    present so nothing more was added and the assertion passed. Measuring the
    second run only ever proves the migrator is stable, never that it was right.

    The healthy-schema case has to be the first call, because that is the state
    every install is in on almost every boot.
    """
    from app.database import Base

    added = await postgres_auto_migrate(pg_engine, Base)
    assert added == 0, (
        f"a heal on a schema create_all just built added {added} objects; it should have found nothing missing"
    )

    # And still nothing on a second pass, which is the stability half.
    again = await postgres_auto_migrate(pg_engine, Base)
    assert again == 0, f"a second heal on a healthy schema added {again} objects"

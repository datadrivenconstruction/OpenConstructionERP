# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A row exempted from a constraint's validation scan is not exempt from anything else.

The boot heal adds every CHECK and FOREIGN KEY it restores as ``NOT VALID``,
because that is the only way onto a table that already holds rows: PostgreSQL
skips the one-off scan and the ``ALTER TABLE`` cannot fail on existing data. The
heal's docstring drew the wrong conclusion from that, and said such an install
"keeps running and can be cleaned up later".

It does not keep running, not in the part that matters. ``NOT VALID`` exempts an
existing row from the validation scan and from nothing after it. PostgreSQL
re-evaluates a CHECK constraint on every UPDATE of a row, whatever column the
update names, so a row that violates one is refused by every write to it from
then on - and the request that made the write answers 500, on an installation
that reports ``status: healthy`` with ``schema_matches_models: true``. Nobody
finds out except by hitting it.

A foreign key is narrower and the difference is worth holding: its referential
trigger fires only when the constrained columns change, so an orphaned row can
still be edited and only never repointed.

One consequence is about when the boot may ask. Some of the rows a restored
constraint refuses are the same rows the boot's data repairs exist to rewrite,
so the validation pass has to run after those repairs; run before them it
refuses, degrades, and clears on the next start, on an install this boot has
already corrected. The last test here measures that on the real table with the
real repair.

These tests run on a real PostgreSQL because every claim above is a claim about
PostgreSQL. On SQLite there is no ``NOT VALID``, no ``convalidated``, and no
behaviour to assert. The lane is ``CI (PostgreSQL)``, which runs ``tests/pg``
whole.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

# Names distinctive enough that a failure names this file, and short enough to
# stay inside PostgreSQL's 63-byte identifier limit.
_TABLE = "oe_probe_notvalid_row"
_PARENT = "oe_probe_notvalid_parent"
_CHECK = "ck_oe_probe_notvalid_amount_positive"
_FK = "fk_oe_probe_notvalid_parent"


async def _drop_probe_tables(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP TABLE IF EXISTS "{_TABLE}"'))
        await conn.execute(text(f'DROP TABLE IF EXISTS "{_PARENT}"'))


async def _constraint_row(engine, name: str):
    async with engine.connect() as conn:
        return (
            await conn.execute(
                text("SELECT convalidated FROM pg_constraint WHERE conname = :n"),
                {"n": name},
            )
        ).scalar_one_or_none()


@pytest.fixture
async def dirty_check(pg_engine):
    """A table holding one row that predates a CHECK constraint and violates it.

    This is the state the heal produces on an upgraded install: the row was
    written when nothing forbade it, and the constraint arrives afterwards under
    ``NOT VALID`` because it could not arrive any other way.
    """
    await _drop_probe_tables(pg_engine)
    async with pg_engine.begin() as conn:
        await conn.execute(text(f'CREATE TABLE "{_TABLE}" (id int primary key, amount int, label text)'))
        await conn.execute(text(f"INSERT INTO \"{_TABLE}\" (id, amount, label) VALUES (1, -5, 'legacy')"))
        await conn.execute(text(f"INSERT INTO \"{_TABLE}\" (id, amount, label) VALUES (2, 5, 'conforming')"))
        await conn.execute(text(f'ALTER TABLE "{_TABLE}" ADD CONSTRAINT "{_CHECK}" CHECK (amount > 0) NOT VALID'))
    try:
        yield pg_engine
    finally:
        await _drop_probe_tables(pg_engine)


# ── What NOT VALID actually exempts ──────────────────────────────────────


async def test_the_violating_row_still_reads(dirty_check) -> None:
    """The half that works, and the half that made this invisible for so long."""
    async with dirty_check.connect() as conn:
        label = (await conn.execute(text(f'SELECT label FROM "{_TABLE}" WHERE id = 1'))).scalar_one()

    assert label == "legacy"


async def test_an_update_of_an_unrelated_column_is_refused(dirty_check) -> None:
    """The defect. The constraint names ``amount``; the update does not touch it.

    This is what a screen editing that record does, and it is why the install
    answers 500 on one record forever while reporting itself healthy.
    """
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError) as caught:
        async with dirty_check.begin() as conn:
            await conn.execute(text(f"UPDATE \"{_TABLE}\" SET label = label || '!' WHERE id = 1"))

    assert _CHECK in str(caught.value), "the constraint that refused must be named in the error"


async def test_even_an_update_that_changes_nothing_is_refused(dirty_check) -> None:
    """``SET id = id`` writes a new row version, and every new row version is checked.

    Held separately because it rules out the reading that would make this
    survivable: that some subset of updates gets through if it avoids the
    constrained column. None does.
    """
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        async with dirty_check.begin() as conn:
            await conn.execute(text(f'UPDATE "{_TABLE}" SET id = id WHERE id = 1'))


async def test_a_conforming_row_on_the_same_table_is_untouched(dirty_check) -> None:
    """The blast radius is the offending rows and nothing else.

    Asserted rather than assumed, because it is what makes the defect quiet: the
    table works, the module works, and one record does not.
    """
    async with dirty_check.begin() as conn:
        await conn.execute(text(f"UPDATE \"{_TABLE}\" SET label = label || '!' WHERE id = 2"))

    async with dirty_check.connect() as conn:
        label = (await conn.execute(text(f'SELECT label FROM "{_TABLE}" WHERE id = 2'))).scalar_one()

    assert label == "conforming!"


async def test_an_update_that_repairs_the_row_is_accepted(dirty_check) -> None:
    """Which is why a declared data repair is the fix and a guess would not be.

    The repair statements in ``app.core.data_repairs`` are themselves checked, so
    one that corrects the row lands and one that leaves it violating fails
    loudly. That is the right shape, and it is the reason this change reports
    the rows instead of rewriting them.
    """
    async with dirty_check.begin() as conn:
        await conn.execute(text(f'UPDATE "{_TABLE}" SET amount = 5 WHERE id = 1'))

    async with dirty_check.connect() as conn:
        amount = (await conn.execute(text(f'SELECT amount FROM "{_TABLE}" WHERE id = 1'))).scalar_one()

    assert amount == 5


async def test_a_foreign_key_refuses_less_than_a_check_does(pg_engine) -> None:
    """The referential trigger fires on the constrained columns and only on them.

    So an orphan left behind by a heal is editable and unmovable, where a CHECK
    violation is neither. The distinction decides how bad an unvalidated foreign
    key is, and it is measured here rather than reasoned about.
    """
    from sqlalchemy.exc import IntegrityError

    await _drop_probe_tables(pg_engine)
    async with pg_engine.begin() as conn:
        await conn.execute(text(f'CREATE TABLE "{_PARENT}" (id int primary key)'))
        await conn.execute(text(f'CREATE TABLE "{_TABLE}" (id int primary key, parent_id int, label text)'))
        await conn.execute(text(f'INSERT INTO "{_PARENT}" (id) VALUES (1)'))
        await conn.execute(text(f"INSERT INTO \"{_TABLE}\" (id, parent_id, label) VALUES (1, 999, 'orphan')"))
        await conn.execute(
            text(
                f'ALTER TABLE "{_TABLE}" ADD CONSTRAINT "{_FK}" '
                f'FOREIGN KEY (parent_id) REFERENCES "{_PARENT}" (id) NOT VALID'
            )
        )
    try:
        async with pg_engine.begin() as conn:
            await conn.execute(text(f"UPDATE \"{_TABLE}\" SET label = 'edited' WHERE id = 1"))

        with pytest.raises(IntegrityError):
            async with pg_engine.begin() as conn:
                await conn.execute(text(f'UPDATE "{_TABLE}" SET parent_id = 998 WHERE id = 1'))
    finally:
        await _drop_probe_tables(pg_engine)


# ── The pass that stops leaving them behind ──────────────────────────────


async def test_the_pass_validates_a_constraint_whose_rows_conform(pg_engine) -> None:
    """The ordinary case, which is nearly every install: the deferral ends.

    Until this ran, a constraint the heal added stayed ``NOT VALID`` for the life
    of the database, so ``schema_constraints_validated`` was false on every
    healed install and could never mean anything.
    """
    from app.core.postgres_migrator import validate_pending_constraints

    await _drop_probe_tables(pg_engine)
    async with pg_engine.begin() as conn:
        await conn.execute(text(f'CREATE TABLE "{_TABLE}" (id int primary key, amount int)'))
        await conn.execute(text(f'INSERT INTO "{_TABLE}" (id, amount) VALUES (1, 5)'))
        await conn.execute(text(f'ALTER TABLE "{_TABLE}" ADD CONSTRAINT "{_CHECK}" CHECK (amount > 0) NOT VALID'))
    try:
        assert await _constraint_row(pg_engine, _CHECK) is False

        validated, refused = await validate_pending_constraints(pg_engine)

        assert validated >= 1
        assert _refused_names(refused) == set()
        assert await _constraint_row(pg_engine, _CHECK) is True
    finally:
        await _drop_probe_tables(pg_engine)


async def test_the_pass_names_a_constraint_the_rows_refuse_and_leaves_it_alone(dirty_check) -> None:
    """The case worth reporting, and the two things that must not happen to it.

    The constraint is not dropped and the row is not rewritten. What the row
    should have said instead is a question about this deployment's data, and a
    guess at it would be worse than the defect it papers over.
    """
    from app.core.postgres_migrator import validate_pending_constraints

    validated, refused = await validate_pending_constraints(dirty_check)

    assert f"{_TABLE}.{_CHECK}" in refused
    assert await _constraint_row(dirty_check, _CHECK) is False, "a constraint it cannot validate stays as it was"

    async with dirty_check.connect() as conn:
        amount = (await conn.execute(text(f'SELECT amount FROM "{_TABLE}" WHERE id = 1'))).scalar_one()
    assert amount == -5, "the pass repairs nothing"

    # A second run reports the same thing rather than counting the refusal as
    # progress, which is what makes the health field clear only when the data is
    # actually corrected. ``validated`` is not asserted on: this lane shares one
    # schema, so another test's constraint could be in the same sweep.
    _again_validated, again_refused = await validate_pending_constraints(dirty_check)
    assert f"{_TABLE}.{_CHECK}" in again_refused


async def test_the_pass_does_not_raise_when_it_cannot_list(pg_engine) -> None:
    """A diagnostic must never be able to stop a boot.

    Driven by disposing the engine rather than by patching, so what is asserted
    is the function's behaviour against a database it genuinely cannot reach.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    dead = create_async_engine("postgresql+asyncpg://127.0.0.1:1/nowhere")
    try:
        from app.core.postgres_migrator import validate_pending_constraints

        assert await validate_pending_constraints(dead) == (0, ())
    finally:
        await dead.dispose()


# ── The population the health field counts ───────────────────────────────


async def test_the_health_count_query_runs_and_counts_what_the_pass_drains(dirty_check) -> None:
    """The statement ``/api/health`` executes, executed, against the same schema.

    Every unit test of that field sets the verdict by hand, so all of them would
    pass while this query raised on every boot - and that failure is caught and
    leaves the field ``None``, which is a value the field is supposed to have.
    The silence is exactly what would hide it. It lived in ``tests/unit`` and
    therefore in a lane that gets cancelled on main; here it is in the one that
    reports.

    It also holds the two consumers to one population. The count and the pass
    read the same predicate from one definition, and a hand-kept second copy is
    how a green field ends up counting a different set from the one the fix
    empties. So the count must see the constraint the pass refuses.
    """
    from app.core.postgres_migrator import UNVALIDATED_CONSTRAINTS_SQL, validate_pending_constraints

    async with dirty_check.connect() as conn:
        before = (await conn.execute(text(UNVALIDATED_CONSTRAINTS_SQL))).scalar_one()

    assert isinstance(before, int)
    assert before >= 1, "the fixture's unvalidated constraint has to be in the count"

    _validated, refused = await validate_pending_constraints(dirty_check)

    async with dirty_check.connect() as conn:
        after = (await conn.execute(text(UNVALIDATED_CONSTRAINTS_SQL))).scalar_one()

    assert f"{_TABLE}.{_CHECK}" in refused
    assert after >= 1, "a constraint the pass refused must still be counted, or the field would say all clear"


def _refused_names(refused: tuple[str, ...]) -> set[str]:
    """Only this file's constraints. The lane shares one schema between tests."""
    return {name for name in refused if _TABLE in name or _PARENT in name}


# ── The repair that has to run before the pass ───────────────────────────

_TAX_TABLE = "oe_i18n_tax_config"
_TAX_CHECK = "ck_oe_i18n_tax_config_subdivision_matches_combination"
# Fixed rather than random so a run that dies mid-test leaves one findable row.
_TAX_ROW_ID = "b6c1f2d4-0000-4000-8000-00000000d0ce"


@pytest.fixture
async def shipped_tax_row(pg_engine):
    """One shipped tax configuration in the shape an upgraded install carries it.

    ``combination`` says this tax replaces the federal one, which makes it
    sub-national, and ``subdivision_code`` is NULL because the seed wrote the
    first of those three days before the second column existed. The CHECK the
    heal restores afterwards refuses exactly this row, and the boot's own
    ``tax_subdivision_backfill`` repair is what corrects it.

    Puts the constraint back on the way the heal puts it back, which over a row
    that already violates it is the only way it goes on at all.
    """
    async with pg_engine.begin() as conn:
        definition = (
            await conn.execute(
                text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :n"),
                {"n": _TAX_CHECK},
            )
        ).scalar_one()
        definition = definition.removesuffix(" NOT VALID")
        await conn.execute(text(f'ALTER TABLE "{_TAX_TABLE}" DROP CONSTRAINT "{_TAX_CHECK}"'))
        await conn.execute(
            text(
                f'INSERT INTO "{_TAX_TABLE}" '
                "(id, country_code, tax_name, tax_code, rate_pct, tax_type, combination, "
                "subdivision_code, is_default) VALUES "
                "(:id, 'CA', 'HST (Ontario)', 'HST_ON', 13.0, 'vat', 'replaces_federal', NULL, false)"
            ),
            {"id": _TAX_ROW_ID},
        )
        await conn.execute(text(f'ALTER TABLE "{_TAX_TABLE}" ADD CONSTRAINT "{_TAX_CHECK}" {definition} NOT VALID'))
    try:
        yield _TAX_ROW_ID
    finally:
        async with pg_engine.begin() as conn:
            await conn.execute(text(f'DELETE FROM "{_TAX_TABLE}" WHERE id = :id'), {"id": _TAX_ROW_ID})
            await conn.execute(text(f'ALTER TABLE "{_TAX_TABLE}" VALIDATE CONSTRAINT "{_TAX_CHECK}"'))


async def test_the_repair_that_corrects_the_row_has_to_run_before_the_pass(shipped_tax_row, pg_engine) -> None:
    """Where the pass runs decides what an upgraded install reports about itself.

    The pass is a diagnostic, and a diagnostic that indicts a database the same
    boot is about to repair reports our defect as the operator's. This is not
    hypothetical for one cohort: the shipped Canadian rates are both the rows
    the CHECK refuses and the rows ``tax_subdivision_backfill`` exists to
    correct, so the ordering decides whether that install spends a start at
    ``degraded`` for a fault it does not have.

    Asserted against the real table, the real constraint and the real repair,
    because the whole claim is about those three meeting. What it does not
    assert is the boot's own ordering: that lives in the lifespan in
    ``app.main`` and reproducing it needs a full start against a seeded
    database. If somebody moves the call back above the repairs, this test still
    passes and the payload is wrong again, so the reason is written into the
    comment at the call site as well.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.core.postgres_migrator import validate_pending_constraints
    from app.modules.i18n_foundation.tax_subdivision_repair import repair_tax_subdivisions

    _validated, refused = await validate_pending_constraints(pg_engine)
    assert f"{_TAX_TABLE}.{_TAX_CHECK}" in refused, (
        "before the repair the shipped row violates the constraint, so the pass has to refuse it"
    )

    async with async_sessionmaker(pg_engine, expire_on_commit=False)() as session:
        changed = await repair_tax_subdivisions(session)
        await session.commit()
    assert changed >= 1, "the repair has to have rewritten the row this fixture planted"

    _validated_after, refused_after = await validate_pending_constraints(pg_engine)
    assert f"{_TAX_TABLE}.{_TAX_CHECK}" not in refused_after, (
        "after the repair the same database validates the same constraint, which is why the pass "
        "runs below the repairs and not beside the heal"
    )

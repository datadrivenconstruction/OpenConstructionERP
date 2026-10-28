# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A generated module creates its table on the database it will actually run on.

The unit tests render the module and create its table on SQLite, which proves
the DDL is well formed. It does not prove the things only PostgreSQL enforces:
that the foreign key to the projects table resolves, that NUMERIC keeps its
scale, and that ``create_all`` scoped to one table leaves the platform's own
schema alone on a database that already has all of it.

Those are the failures that would arrive on a user's server at install time, so
they are checked here against a real cluster.
"""

from __future__ import annotations

import importlib
import sys
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete, insert, inspect, select

from app.modules.module_builder import generator
from app.modules.module_builder.spec import EntitySpec, FieldSpec, ModuleSpec, RuleSpec

KEY = "pg_scaffold_hire"


def _spec() -> ModuleSpec:
    return ModuleSpec(
        key=KEY,
        display_name="Scaffold Hire",
        description="Track hired scaffolding, its rate and its off-hire date.",
        entity=EntitySpec(
            name="hire",
            display_name="Hire",
            fields=[
                FieldSpec(name="reference", label="Reference", type="text", required=True),
                FieldSpec(name="bay_count", label="Bays", type="integer", required=True),
                FieldSpec(name="weekly_rate", label="Weekly rate", type="money", required=True),
                FieldSpec(name="on_hire_date", label="On hire", type="date", required=True),
                FieldSpec(name="off_hire_date", label="Off hire", type="date"),
                FieldSpec(name="inspected_at", label="Last inspection", type="datetime"),
                FieldSpec(name="is_tagged", label="Tagged", type="boolean"),
                FieldSpec(name="status", label="Status", type="select", options=["erected", "struck"], required=True),
            ],
        ),
        rules=[
            RuleSpec(
                code="REFERENCE_REQUIRED", message="A hire needs a reference.", kind="required", field="reference"
            ),
            RuleSpec(
                code="RATE_POSITIVE", message="A weekly rate must be above zero.", kind="positive", field="weekly_rate"
            ),
        ],
    )


@pytest.fixture
def generated(tmp_path: Path):
    """The module, written and imported, then unregistered from the process.

    Importing the model puts its table on the process-wide ``Base.metadata``.
    Left there it would be created by every later fixture that calls
    ``create_all``, and the failure would surface in an unrelated test.
    """
    from app.core import module_runtime_root as rr
    from app.database import Base

    spec = _spec()
    generator.write(spec, tmp_path)
    before = list(rr._package_path())
    rr.attach_runtime_root(tmp_path)
    importlib.invalidate_caches()
    try:
        schema = importlib.import_module(f"app.modules.{KEY}.schema")
        yield spec, schema
    finally:
        rr._package_path()[:] = before
        for name in [n for n in list(sys.modules) if n.startswith(f"app.modules.{KEY}")]:
            del sys.modules[name]
        existing = Base.metadata.tables.get(spec.table_name)
        if existing is not None:
            Base.metadata.remove(existing)
        Base.registry._class_registry.pop(spec.class_name, None)
        importlib.invalidate_caches()


@pytest_asyncio.fixture
async def project_id(pg_engine):
    """A committed project on the cluster, removed afterwards.

    Committed on the engine rather than made through ``pg_session``: that
    session is savepoint-joined and rolls back, so a project created there does
    not exist as far as the foreign key on another connection is concerned, and
    every insert in this file would fail for a reason that has nothing to do
    with what is being tested.
    """
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner, project = uuid.uuid4(), uuid.uuid4()
    async with pg_engine.begin() as connection:
        await connection.execute(
            insert(User).values(
                id=owner,
                email=f"module-builder-{owner.hex[:8]}@example.invalid",
                hashed_password="not-a-real-hash",
            )
        )
        await connection.execute(insert(Project).values(id=project, name="Module builder fixture", owner_id=owner))
    try:
        yield project
    finally:
        # One of the tests deletes the project itself, so both deletes have to
        # tolerate a row that is already gone.
        async with pg_engine.begin() as connection:
            await connection.execute(delete(Project).where(Project.id == project))
            await connection.execute(delete(User).where(User.id == owner))


@pytest_asyncio.fixture
async def installed(pg_engine, generated):
    """The table, created on the cluster and dropped again afterwards."""
    spec, schema = generated
    await schema.ensure_table(pg_engine)
    try:
        yield spec, schema
    finally:
        await schema.remove_table(pg_engine)


async def _table_names(engine: Any) -> set[str]:
    async with engine.connect() as connection:
        return set(await connection.run_sync(lambda sync: inspect(sync).get_table_names()))


async def _sequence_names(engine: Any) -> set[str]:
    """Sequences are the part a table-scoped create_all does not scope.

    ``MetaData.create_all(tables=[...])`` filters tables and only tables. Every
    standalone sequence on the shared metadata is still visited, so a module
    that created or dropped its table that way would reach into schema owned by
    other modules. Nothing in a table listing shows that.
    """
    async with engine.connect() as connection:
        return set(await connection.run_sync(lambda sync: inspect(sync).get_sequence_names()))


class TestInstallCreatesTheTable:
    @pytest.mark.asyncio
    async def test_the_table_appears(self, pg_engine, installed) -> None:
        spec, _ = installed
        assert spec.table_name in await _table_names(pg_engine)

    @pytest.mark.asyncio
    async def test_it_creates_nothing_but_its_own(self, pg_engine, generated) -> None:
        """The reason ``create_all`` is scoped to one table.

        This cluster already carries the platform's schema, so an unscoped
        create_all would be a silent no-op here and would look identical to a
        correct one. What is measured instead is the difference the call makes:
        exactly one new table, whatever was there before.
        """
        spec, schema = generated
        before = await _table_names(pg_engine)
        sequences_before = await _sequence_names(pg_engine)
        assert len(before) > 50, "the cluster has no platform schema, so this test proves nothing"
        assert sequences_before, "no sequences on this cluster, so the sequence half proves nothing"

        await schema.ensure_table(pg_engine)
        try:
            after = await _table_names(pg_engine)
            sequences_after = await _sequence_names(pg_engine)
        finally:
            await schema.remove_table(pg_engine)

        assert after - before == {spec.table_name}
        assert before - after == set()
        assert sequences_after == sequences_before

    @pytest.mark.asyncio
    async def test_uninstalling_leaves_other_modules_schema_alone(self, pg_engine, generated) -> None:
        """Dropping this table must not take anything else with it.

        A table-scoped ``drop_all`` still visits every standalone sequence on
        the metadata, so this is the difference between removing one module and
        breaking the ones that own those sequences.
        """
        spec, schema = generated
        await schema.ensure_table(pg_engine)
        tables_before = await _table_names(pg_engine)
        sequences_before = await _sequence_names(pg_engine)
        assert sequences_before, "no sequences on this cluster, so this test proves nothing"

        await schema.remove_table(pg_engine)

        assert tables_before - await _table_names(pg_engine) == {spec.table_name}
        assert await _sequence_names(pg_engine) == sequences_before

    @pytest.mark.asyncio
    async def test_creating_it_twice_is_not_an_error(self, pg_engine, installed) -> None:
        """Install, restart, reinstall all take this path."""
        spec, schema = installed
        await schema.ensure_table(pg_engine)
        assert spec.table_name in await _table_names(pg_engine)

    @pytest.mark.asyncio
    async def test_dropping_it_twice_is_not_an_error(self, pg_engine, generated) -> None:
        _, schema = generated
        await schema.ensure_table(pg_engine)
        await schema.remove_table(pg_engine)
        await schema.remove_table(pg_engine)


class TestTheTableBehavesLikeAPlatformTable:
    @pytest.mark.asyncio
    async def test_a_row_survives_a_round_trip_with_its_types_intact(self, pg_engine, installed, project_id) -> None:
        """Types, not presence. A rate that comes back as a float is the defect."""
        _, schema = installed
        table = schema.table()
        row_id = uuid.uuid4()
        inspected = datetime.now(UTC).replace(microsecond=0)

        async with pg_engine.begin() as connection:
            await connection.execute(
                insert(table).values(
                    id=row_id,
                    project_id=project_id,
                    reference="SC-014",
                    bay_count=12,
                    weekly_rate=Decimal("1450.75"),
                    on_hire_date=date(2026, 3, 1),
                    inspected_at=inspected,
                    is_tagged=True,
                    status="erected",
                )
            )
        async with pg_engine.connect() as connection:
            found = (await connection.execute(select(table).where(table.c.id == row_id))).mappings().one()

        assert found["reference"] == "SC-014"
        assert found["bay_count"] == 12
        assert isinstance(found["weekly_rate"], Decimal)
        assert found["weekly_rate"] == Decimal("1450.75")
        assert found["on_hire_date"] == date(2026, 3, 1)
        assert found["is_tagged"] is True
        assert found["off_hire_date"] is None
        # Server defaults, not application ones: the column has to fill itself.
        assert found["created_at"] is not None
        assert found["updated_at"] is not None

    @pytest.mark.asyncio
    async def test_a_required_field_is_not_null_on_the_database(self, pg_engine, installed) -> None:
        """The spec says required, so the column has to say NOT NULL.

        Refusing in the service layer only is not enough: an import job or a
        psql session writes straight to the table.
        """
        from sqlalchemy.exc import IntegrityError

        _, schema = installed
        table = schema.table()
        with pytest.raises(IntegrityError):
            async with pg_engine.begin() as connection:
                await connection.execute(insert(table).values(id=uuid.uuid4(), project_id=uuid.uuid4(), bay_count=1))

    @pytest.mark.asyncio
    async def test_the_project_foreign_key_is_enforced(self, pg_engine, installed) -> None:
        """A project-scoped row cannot point at a project that is not there.

        SQLite accepts this silently, which is why it is checked here.
        """
        from sqlalchemy.exc import IntegrityError

        _, schema = installed
        table = schema.table()
        with pytest.raises(IntegrityError):
            async with pg_engine.begin() as connection:
                await connection.execute(
                    insert(table).values(
                        id=uuid.uuid4(),
                        project_id=uuid.uuid4(),  # no such project
                        reference="SC-015",
                        bay_count=4,
                        weekly_rate=Decimal("10.00"),
                        on_hire_date=date(2026, 3, 1),
                        status="erected",
                    )
                )

    @pytest.mark.asyncio
    async def test_deleting_the_project_takes_its_rows_with_it(self, pg_engine, installed, project_id) -> None:
        """ON DELETE CASCADE, checked by deleting rather than by reading the DDL."""
        from app.modules.projects.models import Project

        _, schema = installed
        table = schema.table()

        async with pg_engine.begin() as connection:
            await connection.execute(
                insert(table).values(
                    id=uuid.uuid4(),
                    project_id=project_id,
                    reference="SC-016",
                    bay_count=4,
                    weekly_rate=Decimal("10.00"),
                    on_hire_date=date(2026, 3, 1),
                    status="erected",
                )
            )

        async with pg_engine.begin() as connection:
            count = await connection.scalar(select(func_count(table)).where(table.c.project_id == project_id))
            assert count == 1
            await connection.execute(delete(Project).where(Project.id == project_id))
            after = await connection.scalar(select(func_count(table)).where(table.c.project_id == project_id))
        assert after == 0

    @pytest.mark.asyncio
    async def test_the_money_column_keeps_its_scale(self, pg_engine, installed) -> None:
        """NUMERIC(18, 2) on the cluster, read back from the catalogue."""
        spec, _ = installed
        async with pg_engine.connect() as connection:
            columns = await connection.run_sync(lambda sync: inspect(sync).get_columns(spec.table_name))
        rate = next(c for c in columns if c["name"] == "weekly_rate")
        assert rate["type"].precision == 18
        assert rate["type"].scale == 2


def func_count(table: Any) -> Any:
    from sqlalchemy import func

    return func.count(table.c.id)

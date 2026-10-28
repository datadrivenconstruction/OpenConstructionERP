# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠``v41_funding_obligation_detail`` must fill NULL ``detail_params`` rows.

The revision is inspector-guarded so it can run on an installation whose
tables came from ``Base.metadata.create_all`` plus the boot heal rather than
from walking the chain. On that installation both columns already exist when
the revision runs, so both ``add_column`` calls are skipped - and before the
backfill was added, skipping them made the whole revision a no-op.

That mattered because the two columns do not arrive in the same state. The
heal renders a model default into DDL only when the value has a literal
spelling. ``detail_key`` carries ``default=""``, a scalar, and lands NOT NULL
DEFAULT ''. ``detail_params`` carries ``default=dict``, a callable the ORM
evaluates per row, which has no DDL spelling, so it lands nullable with no
default and every row written before the model grew the column keeps it NULL
for good. Measured on the local database: exactly that split.

``ObligationOut`` tolerates the NULL on the way out, and
``tests/modules/funding/test_funding_obligation_row_predating_columns.py``
holds that belt in place. This file is the other half: the stored value itself
has to be repaired, because a tolerant reader is not a repaired row and every
other consumer of the table - an export, a report, a query - reads the column
directly.

The trap this file is built to avoid is that a test running against a plain
``create_all`` schema proves nothing at all. There the column is NOT NULL, no
row is NULL, the UPDATE matches zero rows, and the test goes green having
executed none of the behaviour it names. So the healed shape is built here
first, and a negative control asserts the NULL is really there before the
revision runs.
"""

from __future__ import annotations

import importlib.util
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Connection, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

_REVISION_PATH = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "v41_funding_obligation_detail.py"
_TABLE = "oe_funding_obligation"
_PARAMS = "detail_params"
_KEY = "detail_key"


def _revision_module() -> Any:
    """Load the one revision under test straight from its path.

    Not ``ScriptDirectory``: that builds the whole revision map, which imports
    all 359 files on disk, and one of them imports ``app.database`` at module
    scope. Loading this file alone keeps the test's dependencies equal to the
    thing it is testing.
    """
    spec = importlib.util.spec_from_file_location("funding_obligation_detail_under_test", _REVISION_PATH)
    assert spec and spec.loader, f"could not load {_REVISION_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def pg_conn(pg_async_url: str) -> Iterator[Connection]:
    """A synchronous connection whose transaction is always rolled back.

    A migration body wants a synchronous bind, and this lane builds its schema
    once per session and shares it across every test. PostgreSQL DDL is
    transactional, so reshaping the table in here and rolling back afterwards
    leaves the shared schema exactly as it was found, including for the tests
    that run after this one.
    """
    engine = create_engine(make_url(pg_async_url).set(drivername="postgresql+psycopg2"))
    connection = engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()


def _seed_obligations(connection: Connection, params_by_label: dict[str, dict]) -> dict[str, uuid.UUID]:
    """Write one application and an obligation per label, returning their ids.

    Through the ORM rather than raw INSERT because every column along the
    chain - user, project, programme, application - takes its value from a
    Python-side model default, which a raw statement would have to restate one
    by one and would then have to keep in step with the models.
    """
    from app.modules.funding.models import FundingApplication, FundingObligation, FundingProgramme
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    suffix = uuid.uuid4().hex[:8]
    ids: dict[str, uuid.UUID] = {}
    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
        owner = User(
            id=uuid.uuid4(),
            email=f"funding-backfill-{suffix}@site.example",
            hashed_password="x",
            full_name="Grants Officer",
            role="admin",
        )
        session.add(owner)
        session.flush()

        project = Project(id=uuid.uuid4(), name="Funding backfill probe", owner_id=owner.id, currency="EUR")
        programme = FundingProgramme(id=uuid.uuid4(), code=f"BF-{suffix}", country="DE", name="Probe programme")
        session.add_all([project, programme])
        session.flush()

        application = FundingApplication(
            id=uuid.uuid4(),
            project_id=project.id,
            programme_id=programme.id,
            code=f"APP-{suffix}",
            title="Probe application",
        )
        session.add(application)
        session.flush()

        for label, params in params_by_label.items():
            obligation = FundingObligation(
                id=uuid.uuid4(),
                application_id=application.id,
                kind="final_report",
                title=label,
                detail="Due 90 days after the award period ends.",
                detail_key="funding.obligation_detail.final_report",
                detail_params=params,
                due_on="2027-12-29",
                source="programme_rule",
            )
            session.add(obligation)
            session.flush()
            ids[label] = obligation.id

        session.commit()
    return ids


def _relax_the_params_column(connection: Connection) -> None:
    """Reshape the column to what the boot heal leaves behind.

    ``create_all`` builds ``detail_params`` NOT NULL, because the model says
    ``nullable=False``. The heal cannot, since it has no DDL spelling for the
    ``dict`` callable that would fill it, so on a healed install the column is
    nullable with no default. Dropping the constraint here is what makes the
    NULL row below possible at all.
    """
    connection.execute(text(f"ALTER TABLE {_TABLE} ALTER COLUMN {_PARAMS} DROP NOT NULL"))
    connection.execute(text(f"ALTER TABLE {_TABLE} ALTER COLUMN {_PARAMS} DROP DEFAULT"))


def _null_out(connection: Connection, obligation_id: uuid.UUID) -> None:
    connection.execute(
        text(f"UPDATE {_TABLE} SET {_PARAMS} = NULL WHERE id = :id"),  # noqa: S608
        {"id": str(obligation_id)},
    )


def _params_of(connection: Connection, obligation_id: uuid.UUID) -> object:
    return connection.execute(
        text(f"SELECT {_PARAMS} FROM {_TABLE} WHERE id = :id"),  # noqa: S608
        {"id": str(obligation_id)},
    ).scalar_one()


def _key_of(connection: Connection, obligation_id: uuid.UUID) -> object:
    return connection.execute(
        text(f"SELECT {_KEY} FROM {_TABLE} WHERE id = :id"),  # noqa: S608
        {"id": str(obligation_id)},
    ).scalar_one()


def _null_params_count(connection: Connection) -> int:
    return connection.execute(
        text(f"SELECT count(*) FROM {_TABLE} WHERE {_PARAMS} IS NULL")  # noqa: S608
    ).scalar_one()


def _columns(connection: Connection) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(_TABLE)}


def _run_upgrade(connection: Connection) -> None:
    """Execute the revision's ``upgrade()`` body against this connection."""
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        _revision_module().upgrade()


def test_a_healed_install_has_its_null_params_filled(pg_conn: Connection) -> None:
    """The skip path still repairs the rows the heal left NULL.

    This is the case the revision used to miss entirely. Both columns are
    present before it runs, so neither ``add_column`` fires and the backfill is
    the only statement that can change anything.
    """
    ids = _seed_obligations(pg_conn, {"old row": {}, "derived row": {"days": 90, "programme": "KFW-261"}})
    _relax_the_params_column(pg_conn)
    _null_out(pg_conn, ids["old row"])

    # Negative controls. Without the first, this test would be exercising the
    # add-column path and would pass on a revision with no backfill at all.
    # Without the second it would be asserting over an empty population.
    assert {_KEY, _PARAMS} <= _columns(pg_conn), (
        "both columns must already exist, or this exercises the add-column path "
        "rather than the skip path it is here to cover"
    )
    assert _null_params_count(pg_conn) == 1, "the NULL row this test is about was not created"

    _run_upgrade(pg_conn)

    assert _params_of(pg_conn, ids["old row"]) == {}, "the row the heal left NULL was not repaired"
    assert _null_params_count(pg_conn) == 0, "some rows are still NULL after the backfill"
    # A row that carries real parameters must survive untouched. The predicate
    # is what guarantees that, and a predicate is only worth as much as the row
    # that would catch it being wrong.
    assert _params_of(pg_conn, ids["derived row"]) == {"days": 90, "programme": "KFW-261"}
    assert _key_of(pg_conn, ids["derived row"]) == "funding.obligation_detail.final_report"


def test_the_backfill_is_safe_to_run_twice(pg_conn: Connection) -> None:
    """A second run must change nothing, including the row it already filled."""
    ids = _seed_obligations(pg_conn, {"old row": {}, "derived row": {"days": 90}})
    _relax_the_params_column(pg_conn)
    _null_out(pg_conn, ids["old row"])

    _run_upgrade(pg_conn)
    after_first = {label: _params_of(pg_conn, oid) for label, oid in ids.items()}

    _run_upgrade(pg_conn)

    assert {label: _params_of(pg_conn, oid) for label, oid in ids.items()} == after_first
    assert _null_params_count(pg_conn) == 0


def test_the_backfill_also_runs_when_the_column_was_just_added(pg_conn: Connection) -> None:
    """On the chain path the rows come out filled too, not NULL.

    Seeded first, then the columns are removed, which is the state a database
    that has never seen this revision is in. The revision adds them back and
    the backfill runs behind the ``add_column``, so the two paths agree on
    what a repaired row looks like.
    """
    ids = _seed_obligations(pg_conn, {"old row": {}})
    pg_conn.execute(text(f"ALTER TABLE {_TABLE} DROP COLUMN {_PARAMS}"))
    pg_conn.execute(text(f"ALTER TABLE {_TABLE} DROP COLUMN {_KEY}"))

    assert not {_KEY, _PARAMS} & _columns(pg_conn), "the columns were not removed, so this proves nothing"

    _run_upgrade(pg_conn)

    assert {_KEY, _PARAMS} <= _columns(pg_conn), "the revision did not add the columns back"
    assert _null_params_count(pg_conn) == 0
    assert _params_of(pg_conn, ids["old row"]) == {}
    assert _key_of(pg_conn, ids["old row"]) == ""

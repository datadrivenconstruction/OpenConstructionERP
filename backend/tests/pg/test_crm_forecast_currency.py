# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG: the forecast's two currency columns, against a real cluster and a real row.

Two things the SQLite unit lane cannot say anything about.

The repository is the second drop site
--------------------------------------
``CrmService.compute_and_store_forecast`` builds the row and
``ForecastRepository.upsert`` either inserts it or copies its fields onto the
row already stored for that period. The copy is a hand-written field list, so
a column added to the model and to the create path can still be silently
missing from the refresh - and that failure is worse than the original,
because the row would then carry this run's four scalars beside the previous
run's breakdown, describing two different days with nothing to say so. The
first test recomputes a period whose currencies changed and reads the row
back.

The migration has to land on rows that already exist
----------------------------------------------------
``env.py`` short-circuits a blank database to ``create_all`` plus
``stamp heads``, so "empty database, upgrade head" runs no revision at all and
still reports success. The second test therefore builds the table in its
pre-migration shape, puts a forecast in it, runs v3305's real ``upgrade()``
and checks the row survived with both new columns NULL - which is the claim
the revision's docstring makes and the reason there is no backfill.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import importlib.util
import pathlib
import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from app.modules.crm.models import Forecast
from app.modules.crm.repository import ForecastRepository
from app.modules.crm.schemas import ForecastResponse

_MIGRATION = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions" / "v3305_crm_forecast_currency.py"

_SCHEMA = "v3305_aged"

# The table as it stood before this revision: the four scalars, no currency
# columns. Only the columns the revision and this test touch are declared.
_OLD_SCHEMA_DDL = f"""
CREATE SCHEMA {_SCHEMA};

CREATE TABLE {_SCHEMA}.oe_crm_forecast (
    id uuid PRIMARY KEY,
    period varchar(16) NOT NULL,
    owner_user_id uuid,
    pipeline_value numeric(18, 2) NOT NULL,
    weighted_value numeric(18, 2) NOT NULL,
    won_value numeric(18, 2) NOT NULL,
    committed_value numeric(18, 2) NOT NULL,
    computed_at varchar(40),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
"""


# ── The repository refresh ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recomputing_a_period_refreshes_the_breakdown_with_the_totals(pg_session) -> None:
    """The second run's currencies replace the first run's, not sit beside them."""
    repo = ForecastRepository(pg_session)
    period = "2026-Q2"

    first = await repo.upsert(
        Forecast(
            period=period,
            owner_user_id=None,
            pipeline_value=1000,
            weighted_value=500,
            won_value=0,
            committed_value=0,
            computed_at="2026-04-01T00:00:00+00:00",
            by_currency=[{"currency": "EUR", "total": "1000.00"}],
            mixed_currency=False,
        )
    )
    assert first.mixed_currency is False

    # Same period, recomputed after a USD deal joined it.
    second = await repo.upsert(
        Forecast(
            period=period,
            owner_user_id=None,
            pipeline_value=3000,
            weighted_value=1500,
            won_value=0,
            committed_value=0,
            computed_at="2026-05-01T00:00:00+00:00",
            by_currency=[
                {"currency": "EUR", "total": "1000.00"},
                {"currency": "USD", "total": "2000.00"},
            ],
            mixed_currency=True,
        )
    )

    assert second.id == first.id, "upsert should update the period's row, not add one"
    assert second.mixed_currency is True
    assert [row["currency"] for row in second.by_currency] == ["EUR", "USD"]

    # And the same row read back from PostgreSQL, through the endpoint's own
    # validation, agrees. JSONB round-trip included.
    pg_session.expire_all()
    reloaded = await repo.get_by_period(period, None)
    response = ForecastResponse.model_validate(reloaded)
    assert response.mixed_currency is True
    assert {row.currency for row in response.by_currency} == {"EUR", "USD"}


@pytest.mark.asyncio
async def test_a_forecast_stored_without_a_breakdown_reads_back_as_unchecked(pg_session) -> None:
    """NULL survives the round-trip as ``None``; PostgreSQL does not invent ``false``."""
    repo = ForecastRepository(pg_session)

    stored = await repo.upsert(
        Forecast(
            period="2026-Q1",
            owner_user_id=None,
            pipeline_value=0,
            weighted_value=0,
            won_value=0,
            committed_value=0,
            computed_at="2026-01-05T00:00:00+00:00",
        )
    )

    pg_session.expire_all()
    reloaded = await repo.get_by_period("2026-Q1", None)
    assert reloaded.id == stored.id
    assert reloaded.by_currency is None
    assert reloaded.mixed_currency is None

    response = ForecastResponse.model_validate(reloaded)
    assert response.mixed_currency is None
    assert response.by_currency is None


# ── The migration, against rows that already exist ───────────────────────


def _load_migration():
    """Import the revision by path; ``alembic/versions`` is not a package."""
    spec = importlib.util.spec_from_file_location("mig_v3305_aged", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sync_engine(pg_async_url):
    """A synchronous engine on the test cluster, as ``env.py`` builds in production."""
    url = make_url(pg_async_url).set(drivername="postgresql+psycopg2")
    engine = create_engine(url, poolclass=NullPool)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def aged(sync_engine):
    """An old-shape forecast table holding one row, dropped afterwards."""
    row_id = uuid.uuid4()
    with sync_engine.connect() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
        conn.execute(text(_OLD_SCHEMA_DDL))
        conn.execute(
            text(
                f"INSERT INTO {_SCHEMA}.oe_crm_forecast "
                "(id, period, pipeline_value, weighted_value, won_value, committed_value, computed_at) "
                "VALUES (:id, '2026-Q2', 3000.00, 1500.00, 0, 0, '2026-04-01T00:00:00+00:00')"
            ),
            {"id": row_id},
        )
        conn.commit()
    try:
        yield row_id
    finally:
        with sync_engine.connect() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
            conn.commit()


def test_upgrade_adds_both_columns_and_leaves_the_existing_row_unchecked(sync_engine, aged) -> None:
    """The row keeps its four scalars and gains two NULLs.

    NULL is the whole point. There is no backfill, because recomputing this
    snapshot would run today's opportunities into a row dated April - so the
    two columns have to be able to say "nobody has checked this period since
    the change", and only NULL says that. A ``false`` here would be the API
    vouching for a blend it never looked at.
    """
    module = _load_migration()
    with sync_engine.connect() as conn:
        conn.execute(text(f"SET search_path TO {_SCHEMA}"))
        ctx = MigrationContext.configure(connection=conn)
        with Operations.context(ctx):
            module.upgrade()
        conn.commit()

    with sync_engine.connect() as conn:
        conn.execute(text(f"SET search_path TO {_SCHEMA}"))
        row = conn.execute(
            text("SELECT pipeline_value, computed_at, by_currency, mixed_currency FROM oe_crm_forecast WHERE id = :id"),
            {"id": aged},
        ).one()
        # ``.all()`` rather than passing the result straight to dict(): a
        # CursorResult has a keys() method, so dict() takes it for a mapping and
        # then subscripts it, which it does not support.
        types = dict(
            conn.execute(
                text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = :s AND table_name = :t "
                    "AND column_name IN ('by_currency', 'mixed_currency')"
                ),
                {"s": _SCHEMA, "t": "oe_crm_forecast"},
            ).all()
        )

    pipeline_value, computed_at, by_currency, mixed_currency = row
    # Untouched: the migration is pure DDL and must not have rewritten a figure.
    assert pipeline_value == 3000
    assert computed_at == "2026-04-01T00:00:00+00:00"
    # Added, and empty in the only way that admits it is empty.
    assert by_currency is None
    assert mixed_currency is None

    # An upgraded database and a fresh one have to end up with the same column,
    # and for JSON they only do because app.core.pg_optimizations rewrites the
    # DDL for sa.JSON() to jsonb on PostgreSQL. That rewrite is a side effect of
    # importing the module, which the alembic path picks up transitively through
    # env.py's own "from app.database import Base". Nothing in the revision
    # names jsonb, so if that import chain ever changes, this column quietly
    # becomes json on upgraded installs and stays jsonb on fresh ones.
    assert types["by_currency"] == "jsonb"
    assert types["mixed_currency"] == "boolean"


def test_downgrade_removes_both_columns(sync_engine, aged) -> None:
    """Reversible, and the row outlives the round trip.

    Worth an assertion rather than an assumption: a downgrade that drops the
    wrong column, or that fails outright, turns a routine rollback into a
    restore-from-backup, and nothing else in this suite would run it.
    """
    module = _load_migration()
    for direction in (module.upgrade, module.downgrade):
        with sync_engine.connect() as conn:
            conn.execute(text(f"SET search_path TO {_SCHEMA}"))
            ctx = MigrationContext.configure(connection=conn)
            with Operations.context(ctx):
                direction()
            conn.commit()

    with sync_engine.connect() as conn:
        columns = {
            r[0]
            for r in conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_schema = :s AND table_name = :t"),
                {"s": _SCHEMA, "t": "oe_crm_forecast"},
            )
        }

    assert "by_currency" not in columns
    assert "mixed_currency" not in columns
    assert {"pipeline_value", "computed_at", "period"} <= columns

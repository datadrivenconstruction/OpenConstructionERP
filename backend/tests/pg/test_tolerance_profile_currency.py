# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG: v3306 lands on tolerance profiles that already exist.

``env.py`` short-circuits a blank database to ``create_all`` plus
``stamp heads``, so "empty database, upgrade head" runs no revision at all and
still reports success. Any claim about what a migration does to existing rows
has to be made against a table built in its pre-migration shape and filled,
which is what this file does.

The claim being checked is the two-case one the revision rests on. There is no
way to recover the currency of an existing absolute floor - a profile is
global and has no order to inherit from - but only a nonzero floor needs one.
A floor of zero is the same amount of money in every currency, so NULL loses
nothing. The upgrade therefore classifies rather than guesses, and counts the
rows it cannot classify instead of assuming there are none.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import importlib.util
import logging
import pathlib
import uuid
from decimal import Decimal

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from app.modules.supplier_catalogs.models import TolerianceProfile
from app.modules.supplier_catalogs.repository import TolerianceProfileRepository

_MIGRATION = (
    pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions" / "v3306_tolerance_profile_currency.py"
)

_SCHEMA = "v3306_aged"
_TABLE = "oe_supplier_catalogs_tolerance_profile"

# The table as v3027 created it: two price bands, no label for the absolute
# one. Only the columns the revision and this test touch are declared.
_OLD_SCHEMA_DDL = f"""
CREATE SCHEMA {_SCHEMA};

CREATE TABLE {_SCHEMA}.{_TABLE} (
    id uuid PRIMARY KEY,
    name varchar(64) NOT NULL UNIQUE,
    description text,
    price_tolerance_pct numeric(8, 4) NOT NULL,
    price_tolerance_abs numeric(18, 4) NOT NULL,
    qty_tolerance_pct numeric(8, 4) NOT NULL,
    period_tolerance_days integer NOT NULL,
    require_gr boolean NOT NULL DEFAULT true,
    is_default boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
"""


def _load_migration():
    """Import the revision by path; ``alembic/versions`` is not a package."""
    spec = importlib.util.spec_from_file_location("mig_v3306_aged", _MIGRATION)
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
    """An old-shape profile table holding both cases, dropped afterwards.

    ``stock`` is what every installation actually has: a zero floor, which is
    currency-independent. ``configured`` is the one a tenant can only reach
    through ``POST /tolerance-profiles``, and the one whose currency is
    unrecoverable.
    """
    ids = {"stock": uuid.uuid4(), "configured": uuid.uuid4()}
    with sync_engine.connect() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
        conn.execute(text(_OLD_SCHEMA_DDL))
        for label, floor in (("stock", "0"), ("configured", "500.0000")):
            conn.execute(
                text(
                    f"INSERT INTO {_SCHEMA}.{_TABLE} "
                    "(id, name, price_tolerance_pct, price_tolerance_abs, qty_tolerance_pct, "
                    " period_tolerance_days, require_gr, is_default) "
                    "VALUES (:id, :name, 2.0, :floor, 0, 7, true, :is_default)",
                ),
                {"id": ids[label], "name": label, "floor": floor, "is_default": label == "stock"},
            )
        conn.commit()
    try:
        yield ids
    finally:
        with sync_engine.connect() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
            conn.commit()


def _upgrade(sync_engine, module) -> None:
    with sync_engine.connect() as conn:
        conn.execute(text(f"SET search_path TO {_SCHEMA}"))
        ctx = MigrationContext.configure(connection=conn)
        with Operations.context(ctx):
            module.upgrade()
        conn.commit()


def test_upgrade_leaves_every_floor_untouched_and_unlabelled(sync_engine, aged) -> None:
    """Both rows keep their floor and gain a NULL currency.

    NULL is the only honest value. The zero floor does not need a label and the
    nonzero one cannot be given a correct one from anything in the database, so
    inventing a code here - a tenant default, the first order's currency -
    would be a guess wearing the same shape as a fact.
    """
    _upgrade(sync_engine, _load_migration())

    with sync_engine.connect() as conn:
        conn.execute(text(f"SET search_path TO {_SCHEMA}"))
        rows = {
            r[0]: (r[1], r[2]) for r in conn.execute(text(f"SELECT name, price_tolerance_abs, currency FROM {_TABLE}"))
        }
        data_type = conn.execute(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = :t AND column_name = 'currency'",
            ),
            {"s": _SCHEMA, "t": _TABLE},
        ).scalar_one()

    # Untouched: the migration must not have rewritten a configured band.
    assert rows["stock"][0] == Decimal("0")
    assert rows["configured"][0] == Decimal("500.0000")
    # Added, and empty in the only way that admits it is empty.
    assert rows["stock"][1] is None
    assert rows["configured"][1] is None
    assert data_type == "character varying"


def test_upgrade_counts_the_floors_it_cannot_label(sync_engine, aged, caplog) -> None:
    """The ambiguous bucket is reported, not assumed away.

    It is empty on a stock installation and this fixture deliberately makes it
    non-empty, because the count is worthless if it has only ever been run
    against data that makes it zero. One of the two rows is unrecoverable and
    the warning has to say one, not two and not nothing.
    """
    with caplog.at_level(logging.WARNING, logger="alembic"):
        _upgrade(sync_engine, _load_migration())

    warnings = [r for r in caplog.records if "price_tolerance_abs" in r.getMessage()]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert message.startswith("1 profile(s)")
    # The remedy and the direction of the change both belong in the operator's
    # log: their bands narrow, which produces exceptions rather than payments.
    assert "narrows the band" in message


def test_upgrade_says_nothing_when_every_floor_is_zero(sync_engine, aged, caplog) -> None:
    """The negative control, which has to come out the other way.

    Without it the previous test only proves the migration can log, not that it
    counted anything: a warning printed unconditionally would satisfy it just
    as well. This is also the case every real installation is in, so the quiet
    upgrade is the one almost everybody gets.
    """
    with sync_engine.connect() as conn:
        conn.execute(text(f"UPDATE {_SCHEMA}.{_TABLE} SET price_tolerance_abs = 0"))
        conn.commit()

    with caplog.at_level(logging.WARNING, logger="alembic"):
        _upgrade(sync_engine, _load_migration())

    assert [r for r in caplog.records if "price_tolerance_abs" in r.getMessage()] == []


def test_downgrade_removes_the_column(sync_engine, aged) -> None:
    """Reversible, and the profiles outlive the round trip.

    Worth asserting rather than assuming: a downgrade that drops the wrong
    column, or fails outright, turns a routine rollback into a restore from
    backup, and nothing else in this suite would run it.
    """
    module = _load_migration()
    _upgrade(sync_engine, module)
    with sync_engine.connect() as conn:
        conn.execute(text(f"SET search_path TO {_SCHEMA}"))
        ctx = MigrationContext.configure(connection=conn)
        with Operations.context(ctx):
            module.downgrade()
        conn.commit()

    with sync_engine.connect() as conn:
        columns = {
            r[0]
            for r in conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_schema = :s AND table_name = :t"),
                {"s": _SCHEMA, "t": _TABLE},
            )
        }
        remaining = conn.execute(text(f"SELECT count(*) FROM {_SCHEMA}.{_TABLE}")).scalar_one()

    assert "currency" not in columns
    assert {"price_tolerance_abs", "price_tolerance_pct", "name"} <= columns
    assert remaining == 2


# ── The column against the real repository ───────────────────────────────


@pytest.mark.asyncio
async def test_the_label_survives_a_round_trip(pg_session) -> None:
    """Stored and read back through the repository the matcher actually uses."""
    repo = TolerianceProfileRepository(pg_session)
    name = f"labelled-{uuid.uuid4().hex[:6]}"

    stored = await repo.create(
        TolerianceProfile(
            name=name,
            price_tolerance_pct=Decimal("2.0"),
            price_tolerance_abs=Decimal("500"),
            currency="EUR",
            qty_tolerance_pct=Decimal("0"),
            period_tolerance_days=7,
            require_gr=True,
            is_default=False,
        ),
    )
    pg_session.expire_all()

    reloaded = await repo.get_by_name(name)
    assert reloaded is not None
    assert reloaded.id == stored.id
    assert reloaded.currency == "EUR"
    assert reloaded.price_tolerance_abs == Decimal("500.0000")


@pytest.mark.asyncio
async def test_an_unlabelled_profile_reads_back_as_none_not_as_blank(pg_session) -> None:
    """``None``, not ``""``. The empty string is not a currency, and treating
    it as one is what would let an unlabelled floor pass a truthiness check
    somewhere downstream and be applied after all.
    """
    repo = TolerianceProfileRepository(pg_session)
    name = f"unlabelled-{uuid.uuid4().hex[:6]}"

    await repo.create(
        TolerianceProfile(
            name=name,
            price_tolerance_pct=Decimal("2.0"),
            price_tolerance_abs=Decimal("0"),
            qty_tolerance_pct=Decimal("0"),
            period_tolerance_days=7,
            require_gr=True,
            is_default=False,
        ),
    )
    pg_session.expire_all()

    reloaded = await repo.get_by_name(name)
    assert reloaded is not None
    assert reloaded.currency is None

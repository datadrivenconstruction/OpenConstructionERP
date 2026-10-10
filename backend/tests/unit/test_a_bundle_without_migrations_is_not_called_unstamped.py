"""An install that ships no migration tree does not report itself unstamped.

The desktop bundle carries neither ``alembic.ini`` nor the script directory, so
the boot-time stamp can never write a revision there. From its second start
every desktop database holds ``oe_*`` tables and records no revision, and
``/api/health`` answered ``degraded`` for every desktop install, a signal with
no information in it and no remedy in that bundle. The question is now put only
where the install could have stamped, and answers ``None`` elsewhere.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import sqlalchemy as sa

from app.core import alembic_version_table


@pytest.fixture
def populated_unstamped() -> Iterator[sa.Connection]:
    """A database holding an application table and no alembic revision."""
    engine = sa.create_engine("sqlite://")
    with engine.connect() as conn:
        conn.execute(sa.text("CREATE TABLE oe_projects_project (id INTEGER PRIMARY KEY)"))
        yield conn
    engine.dispose()


def test_the_source_tree_ships_its_migrations() -> None:
    assert alembic_version_table.migration_tree_shipped() is True


def test_an_install_with_migrations_still_reports_the_cohort(populated_unstamped: sa.Connection) -> None:
    assert alembic_version_table.arrived_populated_unstamped_answer(populated_unstamped) is True


def test_a_bundle_without_migrations_cannot_answer(
    populated_unstamped: sa.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(alembic_version_table, "migration_tree_shipped", lambda: False)

    assert alembic_version_table.arrived_populated_unstamped_answer(populated_unstamped) is None


def test_a_bundle_without_migrations_still_stamps_nothing(
    populated_unstamped: sa.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(alembic_version_table, "migration_tree_shipped", lambda: False)

    assert alembic_version_table.stamp_head_if_unstamped(populated_unstamped) is None

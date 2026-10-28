# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Startup version check, against the PostgreSQL the suite actually runs on.

The stub-driven branch coverage lives in ``test_postgres_version_errors``. What
only a real server can answer is here:

* that ``SELECT current_setting('server_version_num')`` is executable over the
  driver we ship (a stub proves the parsing, never the wire), and
* that the check accepts the cluster the rest of the suite depends on, and
  rejects it the moment the requirement is raised above it.

``tests._pg.isolated_engine`` hands out a throwaway database on that same
cluster. The ``tests/pg`` tree is deliberately not used: its conftest skips the
whole tree unless ``OE_TEST_DB=pg``, so a check that must hold on every run
cannot live there.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.core import postgres_version as pgv
from app.core.postgres_version import (
    MIN_REQUIRED_PG_VERSION,
    PostgreSQLVersionError,
    validate_postgres_version,
)
from tests._pg import isolated_engine


@pytest_asyncio.fixture(scope="module")
async def engine():
    """One throwaway database for the module - cloning one is not free."""
    async with isolated_engine() as eng:
        yield eng


async def test_the_numeric_probe_is_executable_over_the_real_driver(engine) -> None:
    """The GUC read must work on a live server, not just on a stub.

    ``server_version_num`` is the authoritative source, so if this statement
    were not executable here the check would silently spend every run on the
    banner fallback and nothing else in the suite would notice.
    """
    raw = await pgv._scalar(engine, pgv._VERSION_NUM_SQL)

    assert str(raw).strip().isdigit()
    assert int(raw) // 10000 >= MIN_REQUIRED_PG_VERSION


async def test_validation_passes_against_the_real_cluster(engine) -> None:
    major_version, version_string = await validate_postgres_version(engine)

    assert major_version >= MIN_REQUIRED_PG_VERSION
    assert "PostgreSQL" in version_string
    assert str(major_version) in version_string


async def test_the_real_major_agrees_with_the_servers_own_number(engine) -> None:
    """What is returned is what the server computed, not what a regex read."""
    raw = await pgv._scalar(engine, pgv._VERSION_NUM_SQL)
    major_version, _ = await validate_postgres_version(engine)

    assert major_version == int(raw) // 10000


async def test_a_raised_requirement_rejects_the_real_cluster(engine, monkeypatch) -> None:
    """End-to-end refusal on a genuine server, not only against a fake one.

    Nothing else in the suite proves the rejection branch can fire against a
    real connection; a stub that never opens one cannot.
    """
    monkeypatch.setattr(pgv, "MIN_REQUIRED_PG_VERSION", 999)

    with pytest.raises(PostgreSQLVersionError) as excinfo:
        await validate_postgres_version(engine)

    assert "999" in str(excinfo.value)
    assert "not supported" in str(excinfo.value)

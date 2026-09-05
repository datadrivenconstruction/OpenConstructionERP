# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Every module-presence probe must be executable against the mapped schema.

``PRESENCE_PROBES`` is hand-maintained SQL: each entry names a table and a
column by string, so nothing stops an entry from naming a table that was never
created or a column the model does not declare. When that happens the probe
raises, ``_run_one_probe`` swallows the error and returns ``False``, and the
sidebar dims a module that may be full of data. Absent and broken become
indistinguishable, and PostgreSQL logs one error per probe per sweep.

That is not hypothetical. Issue #228 fixed three such entries one table at a
time; four more survived (equipment, service, portal and the asset register)
and produced roughly ninety thousand server-side errors in a single reporter's
launcher log. Fixing entries one by one is why they came back, so this test
asserts the *property* instead of a table list: build the canonical schema from
the ORM metadata and run every probe against it. A new module with a wrong
table or column name fails here, whatever its name is.

The probes are executed rather than parsed. A regex over the SQL would have to
understand ``UNION ALL``, subqueries and unqualified columns, and would quietly
skip whatever it failed to match; the database does not skip anything.
"""

from __future__ import annotations

import importlib
import pathlib
import uuid

import pytest
from sqlalchemy import create_engine, text

from app.database import Base
from app.modules.projects.module_presence import PRESENCE_PROBES

# Floors, not exact counts. They exist so that a collapsed import (an empty
# registry, a probe tuple that failed to load) cannot pass this test by having
# nothing left to check - the failure mode that makes a green gate meaningless.
_MIN_MAPPED_TABLES = 300
_MIN_PROBES = 40


def _import_all_module_models() -> None:
    """Import every ``app.modules.*.models`` so ``Base.metadata`` is complete.

    Mirrors the module loader in the running app: metadata only holds tables
    whose model module was imported, and a probe can only be checked against a
    table the registry knows about.
    """
    import app.modules as modules_pkg

    root = pathlib.Path(modules_pkg.__file__).parent
    for path in sorted(root.iterdir()):
        if path.is_dir() and (path / "models.py").exists():
            importlib.import_module(f"app.modules.{path.name}.models")


@pytest.fixture(scope="module")
def canonical_schema():
    """A throwaway SQLite database carrying every mapped table."""
    _import_all_module_models()
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def test_population_is_loaded(canonical_schema) -> None:
    """Guard the guard: a collapsed registry must not read as agreement."""
    assert len(Base.metadata.tables) >= _MIN_MAPPED_TABLES, (
        f"only {len(Base.metadata.tables)} tables are mapped; the model import "
        "collapsed, so the probe check below would pass vacuously"
    )
    assert len(PRESENCE_PROBES) >= _MIN_PROBES, f"only {len(PRESENCE_PROBES)} probes registered"


def test_every_presence_probe_runs_against_the_mapped_schema(canonical_schema) -> None:
    """No probe may name a table or column the ORM does not declare.

    A failure here means the sidebar reports that module as empty for every
    project on every install, and PostgreSQL logs an error every time the
    endpoint is polled.
    """
    project_id = str(uuid.uuid4())
    broken: list[str] = []

    with canonical_schema.connect() as conn:
        for probe in PRESENCE_PROBES:
            params = {"pid": project_id} if ":pid" in probe.sql else {}
            try:
                conn.execute(text(probe.sql), params)
            except Exception as exc:  # noqa: BLE001 - report all of them, not the first
                broken.append(f"  {probe.module_key}: {probe.sql}\n    -> {str(exc).splitlines()[0]}")

    assert not broken, (
        f"{len(broken)} of {len(PRESENCE_PROBES)} presence probes cannot run against the "
        f"mapped schema ({len(Base.metadata.tables)} tables). Each one dims its module "
        "permanently and logs a database error per sweep:\n" + "\n".join(broken)
    )


def test_company_scoped_probes_do_not_bind_a_project(canonical_schema) -> None:
    """A ``company`` probe that filters by project is a mislabelled project probe.

    The scope field is what the frontend safety net mirrors, so a probe whose
    SQL disagrees with its declared scope would dim a company-wide register
    while claiming it never could.
    """
    mismatched = [p.module_key for p in PRESENCE_PROBES if p.scope == "company" and ":pid" in p.sql]
    assert not mismatched, f"company-scoped probes must not filter by project: {mismatched}"

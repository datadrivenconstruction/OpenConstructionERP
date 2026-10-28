# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Two ways of building the same tables have to agree on what things are called.

A fresh install gets the funding tables from ``Base.metadata.create_all``. An
install that already exists gets them from ``alembic/versions/v41_funding_module.py``.
Both are real, both ship, and neither one is checked against the other by the
migration round-trip test, which compares column names only.

Constraint and index names are where the two drift, because the migration
writes them out by hand while ``create_all`` derives them from the naming
convention in ``app.database``. Four of the six foreign keys here come out
longer than PostgreSQL's 63-character identifier limit, and SQLAlchemy silently
shortens the ones it generated itself, appending four hex characters. A name
written by hand gets no such treatment: PostgreSQL rejects it outright, which
is how the first draft of that migration was caught.

The drift that survives is quieter than the rejection. Two installs end up with
the same tables under different constraint names, and a later migration that
drops one by name does nothing on half the estate and reports success.

Primary keys are deliberately out of scope. The migration declares them through
``primary_key=True`` rather than by name, so PostgreSQL calls them
``<table>_pkey`` while ``create_all`` calls them ``pk_<table>``. That is true of
every migration in this repository, nothing drops a primary key by name, and
changing it here alone would make this module the odd one out.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

import app.modules.projects.models  # noqa: F401  (the foreign key target)
from app.modules.funding import models as funding_models

_MIGRATION = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "v41_funding_module.py"
# PostgreSQL truncates anything longer, and SQLAlchemy raises rather than let
# a hand-written name be truncated behind the author's back.
_MAX_IDENTIFIER = 63

#: Indexes ``create_all`` adds through the platform's ``after_create`` hook
#: (``app.core.pg_optimizations`` gives every table carrying both ``project_id``
#: and ``created_at`` a composite index) rather than through any revision. No
#: migration in the repository creates these and this one follows that, so the
#: difference is deliberate. Pinned by name so it stays a known one rather than
#: quietly widening. The sibling ``(project_id, status)`` index is absent from
#: this set on purpose: the model declares it under the hook's own name, which
#: is how the hook is told not to add a second index over the same two columns.
_HOOK_INDEXES = frozenset({"ix_oe_funding_application_project_id_created_at"})


def _funding_tables() -> list[sa.Table]:
    """The module's own tables, asked of the module rather than of the spelling.

    Selecting by an ``oe_funding_`` prefix looks equivalent and is not: the
    methodology module owns ``oe_funding_source``, an unrelated table that the
    prefix picks up and this migration has no business creating.
    """
    return [
        mapper.class_.__table__
        for mapper in funding_models.Base.registry.mappers
        if mapper.class_.__module__ == funding_models.__name__
    ]


def _expected_names() -> set[str]:
    """Every constraint and index name ``create_all`` emits, primary keys aside."""
    names: set[str] = set()
    preparer = postgresql.dialect().identifier_preparer
    for table in _funding_tables():
        for constraint in table.constraints:
            if isinstance(constraint, sa.PrimaryKeyConstraint):
                continue
            formatted = preparer.format_constraint(constraint)
            if formatted:
                names.add(formatted.strip('"'))
        for index in table.indexes:
            if index.name and str(index.name) not in _HOOK_INDEXES:
                names.add(str(index.name))
    return names


def test_the_module_declares_the_six_tables_the_migration_creates() -> None:
    # If this list ever changes, everything below is measuring the wrong set.
    assert {table.name for table in _funding_tables()} == {
        "oe_funding_programme",
        "oe_funding_application",
        "oe_funding_disbursement",
        "oe_funding_proof_of_use",
        "oe_funding_obligation",
        "oe_funding_cost_allocation",
    }


def test_the_pinned_hook_index_is_one_that_actually_exists() -> None:
    # A pin naming something absent excludes nothing and reads as though it
    # does, so the exclusion list has to be checked against reality too.
    declared = {str(ix.name) for table in _funding_tables() for ix in table.indexes if ix.name}
    assert declared >= _HOOK_INDEXES, sorted(_HOOK_INDEXES - declared)


def test_every_name_create_all_emits_is_written_in_the_migration() -> None:
    source = _MIGRATION.read_text(encoding="utf-8")
    expected = _expected_names()
    # Guard against the check passing because it is measuring nothing.
    assert len(expected) >= 25, expected
    missing = sorted(name for name in expected if name not in source)
    assert not missing, (
        "these names are what a fresh install gets from create_all, and the "
        f"migration never writes them, so an upgraded install differs: {missing}"
    )


def test_no_name_exceeds_what_postgresql_will_accept() -> None:
    # The failure this reproduces is not a warning. PostgreSQL refuses the
    # CREATE outright and the whole upgrade stops on that statement.
    too_long = sorted(name for name in _expected_names() if len(name) > _MAX_IDENTIFIER)
    assert not too_long, too_long


@pytest.mark.parametrize(
    "name",
    [
        "fk_oe_funding_disbursement_application_id_oe_funding_ap_9dcf",
        "fk_oe_funding_proof_of_use_application_id_oe_funding_ap_852d",
        "fk_oe_funding_cost_allocation_application_id_oe_funding_3aef",
    ],
)
def test_a_shortened_name_is_the_one_sqlalchemy_actually_produces(name: str) -> None:
    # These three are the ones that did not fit, and their hex suffixes are the
    # part nobody can derive by reading the convention. Stating them here means
    # a rename of the table or the column fails this test rather than shipping
    # a migration whose names no longer match anything.
    assert name in _expected_names()
    assert name in _MIGRATION.read_text(encoding="utf-8")

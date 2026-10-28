"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The upgrade verifier has to look in both directions, not one.

``schema_gap`` used to report a single nullability list: columns the model marks
NOT NULL that the database accepts NULL in. The reverse - the database insisting
on NOT NULL where the model says nullable - was invisible, and that is exactly
what a revision which WIDENS a column leaves behind when it never runs. The boot
heal only adds columns and indexes; it has no ``DROP NOT NULL``. So the old
constraint survives, application code assigning ``None`` raises a
NotNullViolation on an ordinary write, and the lane reported the schema healed.

The two directions are separate defects with separate repairs, so they are
checked here as separate lists rather than a count.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_upgrade_from_previous_release.py"


@pytest.fixture(scope="module")
def schema_gap():
    """Load the gate script by path; ``scripts/`` is not an importable package."""
    spec = importlib.util.spec_from_file_location("_verify_upgrade_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.schema_gap


def _model_metadata() -> sa.MetaData:
    """What the current code declares: one NOT NULL column and one nullable."""
    md = sa.MetaData()
    sa.Table(
        "oe_widgets",
        md,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("promised_not_null", sa.Integer, nullable=False),
        sa.Column("widened_to_nullable", sa.Numeric(18, 4), nullable=True),
    )
    return md


def _aged_engine() -> sa.Engine:
    """What the database actually has: both directions wrong at once.

    ``promised_not_null`` accepts NULL, which is the additive heal adding a
    NOT NULL column without a default. ``widened_to_nullable`` is still NOT
    NULL, which is the widening revision never running.
    """
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE oe_widgets ("
                " id INTEGER NOT NULL PRIMARY KEY,"
                " promised_not_null INTEGER,"
                " widened_to_nullable NUMERIC(18, 4) NOT NULL"
                ")"
            )
        )
    return engine


def test_the_two_directions_are_reported_separately(schema_gap) -> None:
    """One list per defect, so a reader can tell which repair is needed."""
    base = SimpleNamespace(metadata=_model_metadata())

    missing_tables, missing_columns, model_notnull_db_nullable, db_notnull_model_nullable = schema_gap(
        _aged_engine(), base
    )

    assert missing_tables == []
    assert missing_columns == []
    assert model_notnull_db_nullable == ["oe_widgets.promised_not_null"]
    assert db_notnull_model_nullable == ["oe_widgets.widened_to_nullable"]

    # The finding is that these are DIFFERENT sets. Two lists that came back
    # equal would mean the second direction is not being computed at all.
    assert model_notnull_db_nullable != db_notnull_model_nullable


def test_a_database_that_agrees_with_the_models_reports_nothing(schema_gap) -> None:
    """The control. A correct schema must produce no findings in either list.

    Without this, a gap function that simply returned everything would pass the
    test above and be useless.
    """
    md = _model_metadata()
    engine = sa.create_engine("sqlite://", poolclass=sa.pool.StaticPool)
    md.create_all(engine)

    missing_tables, missing_columns, model_notnull_db_nullable, db_notnull_model_nullable = schema_gap(
        engine, SimpleNamespace(metadata=md)
    )

    assert missing_tables == []
    assert missing_columns == []
    assert model_notnull_db_nullable == []
    assert db_notnull_model_nullable == []


def test_a_table_the_database_never_had_is_still_reported(schema_gap) -> None:
    """Widening the check must not cost the older one."""
    md = _model_metadata()
    sa.Table("oe_absent", md, sa.Column("id", sa.Integer, primary_key=True))

    missing_tables, _, _, _ = schema_gap(_aged_engine(), SimpleNamespace(metadata=md))

    assert missing_tables == ["oe_absent"]

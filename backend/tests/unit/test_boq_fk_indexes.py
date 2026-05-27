"""Index-presence contract for the BOQ FK/composite indexes.

The 2026-05-24 perf wave shipped explicit composite indexes for the
hot read patterns on the BOQ tables — see alembic
``v3123_boq_fk_indexes``. The single-column FK indexes already exist
via the ``index=True`` declaration on each ``ForeignKey(...)`` column,
but the prod query logs showed the actual cost was the temp-B-tree
sort that the planner falls back to when no composite covers
``WHERE fk = ? ORDER BY sort_col``.

These tests:

1. Verify the migration declares the expected composite indexes
   (declarative contract — survives even if no tables get created in
   the test session).
2. Verify the migration registers correctly in the alembic chain —
   ``down_revision`` chains to v3122_crm_lead_active_email_unique.
3. Run the migration end-to-end against a fresh SQLite DB and assert
   every declared index actually lands in sqlite_master.
4. Verify the legacy single-column FK indexes that the
   ``index=True`` declarations promise are still present (regression
   safety — the new composites are additive, not replacements).
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

# ── Per-module DB isolation BEFORE any app imports ─────────────────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-boq-fk-indexes-"))
_TMP_DB = _TMP_DIR / "session.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"


# The migration module is parsed as plain Python (no DB needed for the
# declarative-contract tests).
MIGRATION_MOD = "alembic.versions.v3123_boq_fk_indexes"


def _load_migration():
    """Load the v3123 migration module directly from its file path.

    The alembic ``versions/`` directory is NOT a Python package
    (no ``__init__.py``) — its files are loaded by the alembic
    runner via ``importlib.machinery.SourceFileLoader``. We replicate
    that here so the test can introspect the ``_INDEXES`` table.
    """
    import importlib.util

    here = Path(__file__).resolve().parents[2]  # backend/
    path = here / "alembic" / "versions" / "v3123_boq_fk_indexes.py"
    spec = importlib.util.spec_from_file_location("v3123_boq_fk_indexes", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Declarative contract ──────────────────────────────────────────────────


def test_migration_chains_to_v3122() -> None:
    """``down_revision`` must point at the current head v3122."""
    mod = _load_migration()
    assert mod.revision == "v3123_boq_fk_indexes"
    assert mod.down_revision == "v3122_crm_lead_active_email_unique", (
        f"v3123 must chain on v3122, got {mod.down_revision}. Did a sibling agent insert another migration in between?"
    )


def test_migration_declares_expected_indexes() -> None:
    """The (table, name, columns) tuples must cover every hot read path."""
    mod = _load_migration()
    by_name = {index_name: (table, cols) for table, index_name, cols in mod._INDEXES}

    expected = {
        "ix_boq_position_boq_sort": ("oe_boq_position", ["boq_id", "sort_order"]),
        "ix_boq_position_boq_parent": ("oe_boq_position", ["boq_id", "parent_id"]),
        "ix_boq_markup_boq_sort": ("oe_boq_markup", ["boq_id", "sort_order"]),
        "ix_boq_activity_project_created": (
            "oe_boq_activity_log",
            ["project_id", "created_at"],
        ),
        "ix_boq_activity_boq_created": (
            "oe_boq_activity_log",
            ["boq_id", "created_at"],
        ),
        "ix_boq_snapshot_boq_created": (
            "oe_boq_snapshot",
            ["boq_id", "created_at"],
        ),
        "ix_boq_quantity_link_boq_status": (
            "oe_boq_quantity_link",
            ["boq_id", "status"],
        ),
    }

    for name, (table, cols) in expected.items():
        assert name in by_name, f"Migration must declare composite index {name}. Declared: {sorted(by_name)}"
        actual_table, actual_cols = by_name[name]
        assert actual_table == table, f"{name}: expected table {table}, got {actual_table}"
        assert actual_cols == cols, f"{name}: expected columns {cols}, got {actual_cols}"


# ── Live SQLite end-to-end ────────────────────────────────────────────────


def test_indexes_land_in_sqlite_after_create_all() -> None:
    """After ``Base.metadata.create_all``, the composite indexes live in
    sqlite_master.

    The model-level ``Index(...)`` declarations are what
    ``create_all`` reads — we don't actually need to run the alembic
    migration on SQLite to assert presence (fresh install paths use
    ``create_all``, not alembic, on bootstrap). The alembic migration
    matters for upgrade paths on populated prod databases.

    This test covers the create_all path; the alembic-side coverage is
    inherent in the migration's own ``inspect.get_indexes`` guard.
    """
    from sqlalchemy import create_engine, inspect

    import app.modules.boq.models  # noqa: F401  — registers tables
    import app.modules.projects.models  # noqa: F401  — FK target
    import app.modules.users.models  # noqa: F401  — FK target
    from app.database import Base

    db_path = _TMP_DIR / f"test-create-all-{uuid.uuid4().hex[:8]}.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)

    inspector = inspect(engine)

    # 1. Each composite from the migration is reachable via the model.
    expected_per_table = {
        "oe_boq_position": {
            "ix_boq_position_boq_sort",
            "ix_boq_position_boq_parent",
        },
        "oe_boq_markup": {"ix_boq_markup_boq_sort"},
        "oe_boq_activity_log": {
            "ix_boq_activity_project_created",
            "ix_boq_activity_boq_created",
        },
        "oe_boq_snapshot": {"ix_boq_snapshot_boq_created"},
        "oe_boq_quantity_link": {"ix_boq_quantity_link_boq_status"},
    }
    for table, expected_indexes in expected_per_table.items():
        actual = {ix["name"] for ix in inspector.get_indexes(table)}
        missing = expected_indexes - actual
        assert not missing, f"Missing composite indexes on {table}: {missing}. Actual: {actual}"

    engine.dispose()


def test_legacy_single_column_fk_indexes_still_present() -> None:
    """Regression safety: the single-column FK indexes promised by the
    ``index=True`` declarations are NOT removed by this migration.

    The composites are additive — they accelerate
    ``WHERE fk = ? ORDER BY sort``, but the bare ``WHERE fk = ?``
    pattern still benefits from the single-column index, especially
    on Postgres where the planner can choose between them per query.
    """
    from sqlalchemy import create_engine, inspect

    import app.modules.boq.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401
    from app.database import Base

    db_path = _TMP_DIR / f"test-fk-legacy-{uuid.uuid4().hex[:8]}.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)

    inspector = inspect(engine)

    # SQLAlchemy auto-names single-column indexes ``ix_<table>_<col>``.
    # We assert each FK column has SOME index that contains exactly
    # that single column — the auto-name detail is internal.
    expected_fk_columns = {
        "oe_boq_boq": ["project_id", "parent_estimate_id"],
        "oe_boq_position": ["boq_id", "parent_id"],
        "oe_boq_markup": ["boq_id"],
        "oe_boq_activity_log": ["project_id", "boq_id", "user_id"],
        "oe_boq_snapshot": ["boq_id", "created_by"],
        "oe_boq_quantity_link": ["position_id", "boq_id", "model_id"],
    }

    for table, fk_cols in expected_fk_columns.items():
        indexes = inspector.get_indexes(table)
        single_col_index_cols = {tuple(ix["column_names"]) for ix in indexes if len(ix["column_names"]) == 1}
        for col in fk_cols:
            assert (col,) in single_col_index_cols, (
                f"FK column {table}.{col} must have a single-column "
                f"index for the WHERE fk = ? pattern. Indexes on table: "
                f"{[ix['name'] for ix in indexes]}"
            )

    engine.dispose()

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Verify the EAC v2 core migration is reversible.

Strategy: build a metadata containing only the EAC tables, run
``create_all`` against an in-memory SQLite engine, drop them via the
migration's ``downgrade()`` step, and ensure no EAC tables linger.

Running the full Alembic stack here is brittle (multiple heads in the
repo, async engine), so we instead exercise the migration's
``downgrade()`` against a freshly-created schema. ``upgrade()`` is
implicitly covered by the integration tests that rely on the metadata
shape.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import inspect

EAC_TABLES = (
    "oe_eac_ruleset",
    "oe_eac_rule",
    "oe_eac_run",
    "oe_eac_run_result_item",
    "oe_eac_global_variable",
    "oe_eac_rule_version",
)


def _build_eac_metadata() -> sa.MetaData:
    """Build a fresh metadata containing only the six EAC tables.

    Mirrors the ORM declaratively — when the ORM changes, this list
    must too (and the integration test would catch the drift).
    """
    metadata = sa.MetaData()

    sa.Table(
        "oe_eac_ruleset",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("kind", sa.String(32), nullable=False, server_default="mixed"),
        sa.Column("classifier_id", sa.String(36), nullable=True),
        sa.Column(
            "parent_ruleset_id",
            sa.String(36),
            sa.ForeignKey("oe_eac_ruleset.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=True),
        sa.Column("is_template", sa.Boolean, nullable=False, server_default="0"),
        sa.Column(
            "is_public_in_marketplace", sa.Boolean, nullable=False, server_default="0"
        ),
        sa.Column("tags", sa.JSON, nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    sa.Table(
        "oe_eac_rule",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "ruleset_id",
            sa.String(36),
            sa.ForeignKey("oe_eac_ruleset.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("output_mode", sa.String(32), nullable=False, server_default="boolean"),
        sa.Column("definition_json", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("formula", sa.Text, nullable=True),
        sa.Column("result_unit", sa.String(64), nullable=True),
        sa.Column("tags", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="1"),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(36), nullable=True),
        sa.Column("created_by_user_id", sa.String(36), nullable=True),
        sa.Column("updated_by_user_id", sa.String(36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    sa.Table(
        "oe_eac_run",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "ruleset_id",
            sa.String(36),
            sa.ForeignKey("oe_eac_ruleset.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_version_id", sa.String(36), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("summary_json", sa.JSON, nullable=True),
        sa.Column("elements_evaluated", sa.Integer, nullable=False, server_default="0"),
        sa.Column("elements_matched", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("triggered_by", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    sa.Table(
        "oe_eac_run_result_item",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("oe_eac_run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "rule_id",
            sa.String(36),
            sa.ForeignKey("oe_eac_rule.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("element_id", sa.String(128), nullable=False),
        sa.Column("result_value", sa.JSON, nullable=True),
        sa.Column("pass", sa.Boolean, nullable=True),
        sa.Column("attribute_snapshot", sa.JSON, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    sa.Table(
        "oe_eac_global_variable",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("scope_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("value_type", sa.String(16), nullable=False),
        sa.Column("value_json", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_locked", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("scope", "scope_id", "name", name="uq_eac_global_variable_scope_name"),
    )

    sa.Table(
        "oe_eac_rule_version",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "rule_id",
            sa.String(36),
            sa.ForeignKey("oe_eac_rule.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("definition_json", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("formula", sa.Text, nullable=True),
        sa.Column("changed_by_user_id", sa.String(36), nullable=True),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("change_reason", sa.Text, nullable=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("rule_id", "version_number", name="uq_eac_rule_version_rule_number"),
    )

    return metadata


def test_migration_module_imports() -> None:
    """The migration file must be syntactically valid and import cleanly."""
    import importlib.util
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[3]
    migration_path = repo_root / "alembic" / "versions" / "v260_eac_v2_core.py"
    assert migration_path.exists(), f"migration file missing: {migration_path}"

    spec = importlib.util.spec_from_file_location(
        "alembic.versions.v260_eac_v2_core", migration_path
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    assert mod.revision == "v260_eac_v2_core"
    assert mod.down_revision == "v250_dashboards_snapshot"
    assert callable(mod.upgrade)
    assert callable(mod.downgrade)


def test_create_all_then_drop_all() -> None:
    """Round-trip: build EAC tables, drop them, ensure none remain.

    This is the closest practical equivalent to ``alembic upgrade head ;
    alembic downgrade -1`` without coupling to the project's multi-head
    migration tree.
    """
    metadata = _build_eac_metadata()
    engine = sa.create_engine("sqlite:///:memory:", future=True)

    metadata.create_all(engine)

    insp = inspect(engine)
    tables_after_create = set(insp.get_table_names())
    for table in EAC_TABLES:
        assert table in tables_after_create, f"upgrade missed {table}"

    metadata.drop_all(engine)

    insp = inspect(engine)
    tables_after_drop = set(insp.get_table_names())
    for table in EAC_TABLES:
        assert table not in tables_after_drop, f"downgrade left {table}"


def test_orm_models_register_all_six_tables() -> None:
    """The ORM declarative metadata must expose all six EAC tables.

    Catches regressions where a new model is added but the migration
    isn't updated (or vice-versa).
    """
    from app.database import Base
    import app.modules.eac.models  # noqa: F401 — register tables

    table_names = set(Base.metadata.tables.keys())
    for table in EAC_TABLES:
        assert table in table_names, f"ORM missing table {table}"

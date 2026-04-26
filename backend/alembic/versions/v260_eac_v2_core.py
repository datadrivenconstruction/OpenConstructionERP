"""v2.6.0 EAC-1.1 -- create EAC v2 core tables.

Wave EAC-1.1 of RFC 35 lays the foundational ORM layer for the
single-kernel EAC v2 engine. Six tables created together (no business
logic uses one without the others):

    oe_eac_ruleset
    oe_eac_rule
    oe_eac_run
    oe_eac_run_result_item
    oe_eac_global_variable
    oe_eac_rule_version

All tables carry a ``tenant_id`` index — RLS policies are layered on by
W0.4 (separate ticket) without touching this migration.

The migration is idempotent: tables are created only when missing.
``downgrade()`` drops them in reverse FK order.

Revision ID: v260_eac_v2_core
Revises: v250_dashboards_snapshot
Create Date: 2026-04-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v260_eac_v2_core"
down_revision: Union[str, None] = "v250_dashboards_snapshot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Constants reused in upgrade() and downgrade() ─────────────────────────

RULESET_TABLE = "oe_eac_ruleset"
RULE_TABLE = "oe_eac_rule"
RUN_TABLE = "oe_eac_run"
RUN_RESULT_ITEM_TABLE = "oe_eac_run_result_item"
GLOBAL_VARIABLE_TABLE = "oe_eac_global_variable"
RULE_VERSION_TABLE = "oe_eac_rule_version"

# Index names — keep stable so rollback finds them by name.
RULESET_TENANT_KIND_IX = "ix_eac_ruleset_tenant_kind"
RULESET_TENANT_PROJECT_IX = "ix_eac_ruleset_tenant_project"
RULESET_TENANT_IX = "ix_oe_eac_ruleset_tenant_id"

RULE_TENANT_ACTIVE_IX = "ix_eac_rule_tenant_active"
RULE_RULESET_ACTIVE_IX = "ix_eac_rule_ruleset_active"
RULE_NAME_IX = "ix_oe_eac_rule_name"
RULE_TENANT_IX = "ix_oe_eac_rule_tenant_id"
RULE_PROJECT_IX = "ix_oe_eac_rule_project_id"
RULE_RULESET_IX = "ix_oe_eac_rule_ruleset_id"

RUN_TENANT_STATUS_IX = "ix_eac_run_tenant_status"
RUN_RULESET_STARTED_IX = "ix_eac_run_ruleset_started"
RUN_TENANT_IX = "ix_oe_eac_run_tenant_id"
RUN_RULESET_IX = "ix_oe_eac_run_ruleset_id"

RUN_RESULT_RUN_RULE_IX = "ix_eac_run_result_run_rule"
RUN_RESULT_TENANT_IX = "ix_eac_run_result_tenant"
RUN_RESULT_RUN_IX = "ix_oe_eac_run_result_item_run_id"

GLOBAL_VAR_TENANT_IX = "ix_eac_global_variable_tenant"
GLOBAL_VAR_UQ = "uq_eac_global_variable_scope_name"

RULE_VERSION_RULE_IX = "ix_oe_eac_rule_version_rule_id"
RULE_VERSION_TENANT_IX = "ix_eac_rule_version_tenant"
RULE_VERSION_UQ = "uq_eac_rule_version_rule_number"


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def _existing_indexes(table: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return set()
    return {ix["name"] for ix in insp.get_indexes(table)}


def upgrade() -> None:
    """Create the six EAC v2 core tables."""

    # ── Ruleset ─────────────────────────────────────────────────────
    if not _table_exists(RULESET_TABLE):
        op.create_table(
            RULESET_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column(
                "kind",
                sa.String(length=32),
                nullable=False,
                server_default="mixed",
            ),
            sa.Column("classifier_id", sa.String(length=36), nullable=True),
            sa.Column(
                "parent_ruleset_id",
                sa.String(length=36),
                sa.ForeignKey(f"{RULESET_TABLE}.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=True),
            sa.Column(
                "is_template",
                sa.Boolean,
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "is_public_in_marketplace",
                sa.Boolean,
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "tags",
                sa.JSON,
                nullable=False,
                server_default="[]",
            ),
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
        op.create_index(RULESET_TENANT_IX, RULESET_TABLE, ["tenant_id"])
        op.create_index(
            RULESET_TENANT_KIND_IX, RULESET_TABLE, ["tenant_id", "kind"]
        )
        op.create_index(
            RULESET_TENANT_PROJECT_IX,
            RULESET_TABLE,
            ["tenant_id", "project_id"],
        )

    # ── Rule ────────────────────────────────────────────────────────
    if not _table_exists(RULE_TABLE):
        op.create_table(
            RULE_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "ruleset_id",
                sa.String(length=36),
                sa.ForeignKey(f"{RULESET_TABLE}.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column(
                "output_mode",
                sa.String(length=32),
                nullable=False,
                server_default="boolean",
            ),
            sa.Column(
                "definition_json",
                sa.JSON,
                nullable=False,
                server_default="{}",
            ),
            sa.Column("formula", sa.Text, nullable=True),
            sa.Column("result_unit", sa.String(length=64), nullable=True),
            sa.Column(
                "tags",
                sa.JSON,
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "version", sa.Integer, nullable=False, server_default="1"
            ),
            sa.Column(
                "is_active", sa.Boolean, nullable=False, server_default="1"
            ),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
            sa.Column("project_id", sa.String(length=36), nullable=True),
            sa.Column(
                "created_by_user_id", sa.String(length=36), nullable=True
            ),
            sa.Column(
                "updated_by_user_id", sa.String(length=36), nullable=True
            ),
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
        op.create_index(RULE_NAME_IX, RULE_TABLE, ["name"])
        op.create_index(RULE_TENANT_IX, RULE_TABLE, ["tenant_id"])
        op.create_index(RULE_PROJECT_IX, RULE_TABLE, ["project_id"])
        op.create_index(RULE_RULESET_IX, RULE_TABLE, ["ruleset_id"])
        op.create_index(
            RULE_TENANT_ACTIVE_IX, RULE_TABLE, ["tenant_id", "is_active"]
        )
        op.create_index(
            RULE_RULESET_ACTIVE_IX,
            RULE_TABLE,
            ["ruleset_id", "is_active"],
        )

    # ── Run ─────────────────────────────────────────────────────────
    if not _table_exists(RUN_TABLE):
        op.create_table(
            RUN_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "ruleset_id",
                sa.String(length=36),
                sa.ForeignKey(f"{RULESET_TABLE}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "model_version_id", sa.String(length=36), nullable=True
            ),
            sa.Column(
                "started_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "finished_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "status",
                sa.String(length=32),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("summary_json", sa.JSON, nullable=True),
            sa.Column(
                "elements_evaluated",
                sa.Integer,
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "elements_matched",
                sa.Integer,
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "error_count",
                sa.Integer,
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "triggered_by",
                sa.String(length=32),
                nullable=False,
                server_default="manual",
            ),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
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
        op.create_index(RUN_TENANT_IX, RUN_TABLE, ["tenant_id"])
        op.create_index(RUN_RULESET_IX, RUN_TABLE, ["ruleset_id"])
        op.create_index(
            RUN_TENANT_STATUS_IX, RUN_TABLE, ["tenant_id", "status"]
        )
        op.create_index(
            RUN_RULESET_STARTED_IX,
            RUN_TABLE,
            ["ruleset_id", "started_at"],
        )

    # ── Run result item ─────────────────────────────────────────────
    if not _table_exists(RUN_RESULT_ITEM_TABLE):
        op.create_table(
            RUN_RESULT_ITEM_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "run_id",
                sa.String(length=36),
                sa.ForeignKey(f"{RUN_TABLE}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "rule_id",
                sa.String(length=36),
                sa.ForeignKey(f"{RULE_TABLE}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("element_id", sa.String(length=128), nullable=False),
            sa.Column("result_value", sa.JSON, nullable=True),
            sa.Column("pass", sa.Boolean, nullable=True),
            sa.Column("attribute_snapshot", sa.JSON, nullable=True),
            sa.Column("error", sa.Text, nullable=True),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
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
        op.create_index(
            RUN_RESULT_RUN_IX, RUN_RESULT_ITEM_TABLE, ["run_id"]
        )
        op.create_index(
            RUN_RESULT_RUN_RULE_IX,
            RUN_RESULT_ITEM_TABLE,
            ["run_id", "rule_id"],
        )
        op.create_index(
            RUN_RESULT_TENANT_IX, RUN_RESULT_ITEM_TABLE, ["tenant_id"]
        )

    # ── Global variable ─────────────────────────────────────────────
    if not _table_exists(GLOBAL_VARIABLE_TABLE):
        op.create_table(
            GLOBAL_VARIABLE_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("scope", sa.String(length=16), nullable=False),
            sa.Column("scope_id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column(
                "value_type", sa.String(length=16), nullable=False
            ),
            sa.Column(
                "value_json",
                sa.JSON,
                nullable=False,
                server_default="{}",
            ),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column(
                "is_locked", sa.Boolean, nullable=False, server_default="0"
            ),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
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
            sa.UniqueConstraint(
                "scope", "scope_id", "name", name=GLOBAL_VAR_UQ
            ),
        )
        op.create_index(
            GLOBAL_VAR_TENANT_IX, GLOBAL_VARIABLE_TABLE, ["tenant_id"]
        )

    # ── Rule version ────────────────────────────────────────────────
    if not _table_exists(RULE_VERSION_TABLE):
        op.create_table(
            RULE_VERSION_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "rule_id",
                sa.String(length=36),
                sa.ForeignKey(f"{RULE_TABLE}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("version_number", sa.Integer, nullable=False),
            sa.Column(
                "definition_json",
                sa.JSON,
                nullable=False,
                server_default="{}",
            ),
            sa.Column("formula", sa.Text, nullable=True),
            sa.Column(
                "changed_by_user_id", sa.String(length=36), nullable=True
            ),
            sa.Column(
                "changed_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("change_reason", sa.Text, nullable=True),
            sa.Column("tenant_id", sa.String(length=36), nullable=False),
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
            sa.UniqueConstraint(
                "rule_id", "version_number", name=RULE_VERSION_UQ
            ),
        )
        op.create_index(
            RULE_VERSION_RULE_IX, RULE_VERSION_TABLE, ["rule_id"]
        )
        op.create_index(
            RULE_VERSION_TENANT_IX, RULE_VERSION_TABLE, ["tenant_id"]
        )


def downgrade() -> None:
    """Drop EAC v2 core tables in reverse FK order."""

    # 1) Rule version → depends on Rule
    if _table_exists(RULE_VERSION_TABLE):
        existing = _existing_indexes(RULE_VERSION_TABLE)
        for name in (RULE_VERSION_TENANT_IX, RULE_VERSION_RULE_IX):
            if name in existing:
                op.drop_index(name, table_name=RULE_VERSION_TABLE)
        op.drop_table(RULE_VERSION_TABLE)

    # 2) Global variable → independent
    if _table_exists(GLOBAL_VARIABLE_TABLE):
        existing = _existing_indexes(GLOBAL_VARIABLE_TABLE)
        if GLOBAL_VAR_TENANT_IX in existing:
            op.drop_index(GLOBAL_VAR_TENANT_IX, table_name=GLOBAL_VARIABLE_TABLE)
        op.drop_table(GLOBAL_VARIABLE_TABLE)

    # 3) Run result item → depends on Run + Rule
    if _table_exists(RUN_RESULT_ITEM_TABLE):
        existing = _existing_indexes(RUN_RESULT_ITEM_TABLE)
        for name in (
            RUN_RESULT_TENANT_IX,
            RUN_RESULT_RUN_RULE_IX,
            RUN_RESULT_RUN_IX,
        ):
            if name in existing:
                op.drop_index(name, table_name=RUN_RESULT_ITEM_TABLE)
        op.drop_table(RUN_RESULT_ITEM_TABLE)

    # 4) Run → depends on Ruleset
    if _table_exists(RUN_TABLE):
        existing = _existing_indexes(RUN_TABLE)
        for name in (
            RUN_RULESET_STARTED_IX,
            RUN_TENANT_STATUS_IX,
            RUN_RULESET_IX,
            RUN_TENANT_IX,
        ):
            if name in existing:
                op.drop_index(name, table_name=RUN_TABLE)
        op.drop_table(RUN_TABLE)

    # 5) Rule → depends on Ruleset (SET NULL)
    if _table_exists(RULE_TABLE):
        existing = _existing_indexes(RULE_TABLE)
        for name in (
            RULE_RULESET_ACTIVE_IX,
            RULE_TENANT_ACTIVE_IX,
            RULE_RULESET_IX,
            RULE_PROJECT_IX,
            RULE_TENANT_IX,
            RULE_NAME_IX,
        ):
            if name in existing:
                op.drop_index(name, table_name=RULE_TABLE)
        op.drop_table(RULE_TABLE)

    # 6) Ruleset → self-FK already cascaded by SET NULL on row delete
    if _table_exists(RULESET_TABLE):
        existing = _existing_indexes(RULESET_TABLE)
        for name in (
            RULESET_TENANT_PROJECT_IX,
            RULESET_TENANT_KIND_IX,
            RULESET_TENANT_IX,
        ):
            if name in existing:
                op.drop_index(name, table_name=RULESET_TABLE)
        op.drop_table(RULESET_TABLE)

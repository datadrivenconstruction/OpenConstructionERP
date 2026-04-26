"""v2.6.0 EAC-2.1 -- create EAC v2 alias tables.

Wave EAC-2 of RFC 35 §6 layers parameter-alias support on top of the
EAC v2 core tables introduced by ``v260_eac_v2_core``. Three tables
land together (no business logic uses one without the others):

    oe_eac_parameter_aliases
    oe_eac_alias_synonyms
    oe_eac_alias_snapshots

The migration is idempotent: tables are created only when missing.
``downgrade()`` drops them in reverse FK order.

Revision ID: v260a_eac_aliases_tables
Revises: v260_eac_v2_core
Create Date: 2026-04-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v260a_eac_aliases_tables"
down_revision: Union[str, None] = "v260_eac_v2_core"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Table & index name constants (kept stable so rollback works by name).
ALIAS_TABLE = "oe_eac_parameter_aliases"
SYNONYM_TABLE = "oe_eac_alias_synonyms"
SNAPSHOT_TABLE = "oe_eac_alias_snapshots"

ALIAS_SCOPE_NAME_UQ = "uq_eac_parameter_alias_scope_name"
ALIAS_TENANT_IX = "ix_eac_parameter_alias_tenant"
ALIAS_SCOPE_IX = "ix_eac_parameter_alias_scope"
ALIAS_NAME_IX = "ix_oe_eac_parameter_aliases_name"
ALIAS_TENANT_DEFAULT_IX = "ix_oe_eac_parameter_aliases_tenant_id"

SYNONYM_ALIAS_PRIORITY_IX = "ix_eac_alias_synonym_alias_priority"
SYNONYM_ALIAS_IX = "ix_oe_eac_alias_synonyms_alias_id"

SNAPSHOT_SCOPE_IX = "ix_eac_alias_snapshot_scope"


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
    """Create the three EAC-2 alias tables."""

    # ── Parameter alias ─────────────────────────────────────────────
    if not _table_exists(ALIAS_TABLE):
        op.create_table(
            ALIAS_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("scope", sa.String(length=16), nullable=False),
            sa.Column("scope_id", sa.String(length=36), nullable=True),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column(
                "value_type_hint",
                sa.String(length=16),
                nullable=False,
                server_default="any",
            ),
            sa.Column("default_unit", sa.String(length=64), nullable=True),
            sa.Column(
                "version",
                sa.Integer,
                nullable=False,
                server_default="1",
            ),
            sa.Column(
                "is_built_in",
                sa.Boolean,
                nullable=False,
                server_default="0",
            ),
            sa.Column("tenant_id", sa.String(length=36), nullable=True),
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
                "scope", "scope_id", "name", name=ALIAS_SCOPE_NAME_UQ
            ),
        )
        op.create_index(ALIAS_TENANT_DEFAULT_IX, ALIAS_TABLE, ["tenant_id"])
        op.create_index(ALIAS_TENANT_IX, ALIAS_TABLE, ["tenant_id"])
        op.create_index(
            ALIAS_SCOPE_IX, ALIAS_TABLE, ["scope", "scope_id"]
        )

    # ── Alias synonym ───────────────────────────────────────────────
    if not _table_exists(SYNONYM_TABLE):
        op.create_table(
            SYNONYM_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "alias_id",
                sa.String(length=36),
                sa.ForeignKey(f"{ALIAS_TABLE}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("pattern", sa.String(length=255), nullable=False),
            sa.Column(
                "kind",
                sa.String(length=16),
                nullable=False,
                server_default="exact",
            ),
            sa.Column(
                "case_sensitive",
                sa.Boolean,
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "priority",
                sa.Integer,
                nullable=False,
                server_default="100",
            ),
            sa.Column("pset_filter", sa.String(length=255), nullable=True),
            sa.Column(
                "source_filter",
                sa.String(length=32),
                nullable=False,
                server_default="any",
            ),
            sa.Column(
                "unit_multiplier",
                sa.Numeric(20, 10),
                nullable=False,
                server_default="1",
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
        op.create_index(SYNONYM_ALIAS_IX, SYNONYM_TABLE, ["alias_id"])
        op.create_index(
            SYNONYM_ALIAS_PRIORITY_IX,
            SYNONYM_TABLE,
            ["alias_id", "priority"],
        )

    # ── Alias snapshot ──────────────────────────────────────────────
    if not _table_exists(SNAPSHOT_TABLE):
        op.create_table(
            SNAPSHOT_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "taken_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("scope", sa.String(length=16), nullable=False),
            sa.Column("scope_id", sa.String(length=36), nullable=True),
            sa.Column(
                "aliases_json",
                sa.JSON,
                nullable=False,
                server_default="{}",
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
        op.create_index(
            SNAPSHOT_SCOPE_IX, SNAPSHOT_TABLE, ["scope", "scope_id"]
        )


def downgrade() -> None:
    """Drop EAC-2 alias tables in reverse FK order."""

    # 1) Snapshot — independent
    if _table_exists(SNAPSHOT_TABLE):
        existing = _existing_indexes(SNAPSHOT_TABLE)
        if SNAPSHOT_SCOPE_IX in existing:
            op.drop_index(SNAPSHOT_SCOPE_IX, table_name=SNAPSHOT_TABLE)
        op.drop_table(SNAPSHOT_TABLE)

    # 2) Synonym — depends on Alias
    if _table_exists(SYNONYM_TABLE):
        existing = _existing_indexes(SYNONYM_TABLE)
        for name in (SYNONYM_ALIAS_PRIORITY_IX, SYNONYM_ALIAS_IX):
            if name in existing:
                op.drop_index(name, table_name=SYNONYM_TABLE)
        op.drop_table(SYNONYM_TABLE)

    # 3) Alias
    if _table_exists(ALIAS_TABLE):
        existing = _existing_indexes(ALIAS_TABLE)
        for name in (
            ALIAS_SCOPE_IX,
            ALIAS_TENANT_IX,
            ALIAS_TENANT_DEFAULT_IX,
        ):
            if name in existing:
                op.drop_index(name, table_name=ALIAS_TABLE)
        op.drop_table(ALIAS_TABLE)

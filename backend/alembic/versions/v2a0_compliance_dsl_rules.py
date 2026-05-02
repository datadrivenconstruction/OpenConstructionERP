"""v2.10.0 — Compliance DSL rules table (T08).

Adds the ``oe_compliance_dsl_rule`` table that stores user-authored
validation rules as YAML/JSON snippets. The DSL parser/evaluator lives
in :mod:`app.core.validation.dsl`; this table is just the persistence
shadow so rules survive restarts.

Inspector-guarded so re-running on an already-migrated DB is a no-op
(matches the v260c / v280 / v290 style).

Revision ID: v2a0_compliance_dsl_rules
Revises: v290_dashboards_presets
Create Date: 2026-04-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v2a0_compliance_dsl_rules"
down_revision: Union[str, Sequence[str], None] = "v290_dashboards_presets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_compliance_dsl_rule"
_TENANT_IX = "ix_oe_compliance_dsl_rule_tenant_id"
_RULE_IX = "ix_oe_compliance_dsl_rule_rule_id"
_OWNER_IX = "ix_oe_compliance_dsl_rule_owner_user_id"
_UNIQUE = "uq_oe_compliance_dsl_rule_tenant_rule_id"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("tenant_id", sa.String(length=36), nullable=True),
            sa.Column("rule_id", sa.String(length=200), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("severity", sa.String(length=32), nullable=False),
            sa.Column(
                "standard",
                sa.String(length=64),
                nullable=False,
                server_default="custom",
            ),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("definition_yaml", sa.Text(), nullable=False),
            sa.Column("owner_user_id", sa.String(length=36), nullable=False),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                # Use sa.true() so the literal is dialect-aware: rendered as
                # `true` on PostgreSQL, `1` on SQLite. sa.text("1") emits a
                # raw integer literal which PostgreSQL rejects for a BOOLEAN
                # column with: ``column "is_active" is of type boolean but
                # default expression is of type integer``.
                server_default=sa.true(),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.UniqueConstraint("tenant_id", "rule_id", name=_UNIQUE),
        )
        op.create_index(_TENANT_IX, _TABLE, ["tenant_id"])
        op.create_index(_RULE_IX, _TABLE, ["rule_id"])
        op.create_index(_OWNER_IX, _TABLE, ["owner_user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, _TABLE):
        existing_ix = {ix["name"] for ix in inspector.get_indexes(_TABLE)}
        for ix_name in (_OWNER_IX, _RULE_IX, _TENANT_IX):
            if ix_name in existing_ix:
                op.drop_index(ix_name, table_name=_TABLE)
        op.drop_table(_TABLE)

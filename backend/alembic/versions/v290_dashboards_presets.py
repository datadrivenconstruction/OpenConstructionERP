"""v2.9.0 — Dashboards: presets & collections (T05).

Adds the ``oe_dashboards_preset`` table that stores curated bundles of
charts + filters either as a private "preset" (visible only to its
owner) or a "collection" (visible to every user with project access
when ``shared_with_project`` is true).

The table is intentionally small — actual chart/filter state is opaque
JSON in ``config_json``; new chart kinds can ship without touching the
migration. Snapshot id is *not* an FK column on this table because a
preset may target multiple snapshots (it is part of the JSON config).

Inspector-guarded so re-running on an already-migrated DB is a no-op
(matches the v260c / v280 style).

Revision ID: v290_dashboards_presets
Revises: v260c_project_fx_rates_vat
Create Date: 2026-04-26
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v290_dashboards_presets"
down_revision: Union[str, Sequence[str], None] = "v260c_project_fx_rates_vat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_dashboards_preset"
_OWNER_IX = "ix_oe_dashboards_preset_owner_id"
_PROJECT_IX = "ix_oe_dashboards_preset_project_id"
_TENANT_IX = "ix_oe_dashboards_preset_tenant_id"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def upgrade() -> None:
    """Create the preset table if it doesn't already exist."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("tenant_id", sa.String(length=36), nullable=True),
            # Nullable: a preset can be "global" (visible across every
            # project of the owner). Most rows will carry a project_id.
            sa.Column("project_id", sa.String(length=36), nullable=True),
            sa.Column("owner_id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.String(length=2000), nullable=True),
            # 'preset' (private) or 'collection' (shared with project).
            sa.Column(
                "kind",
                sa.String(length=32),
                nullable=False,
                server_default="preset",
            ),
            sa.Column(
                "config_json",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "shared_with_project",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
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
            sa.CheckConstraint(
                "kind IN ('preset', 'collection')",
                name="ck_oe_dashboards_preset_kind",
            ),
        )
        op.create_index(_OWNER_IX, _TABLE, ["owner_id"])
        op.create_index(_PROJECT_IX, _TABLE, ["project_id"])
        op.create_index(_TENANT_IX, _TABLE, ["tenant_id"])


def downgrade() -> None:
    """Drop the preset table (idempotent / inspector-guarded)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, _TABLE):
        existing_ix = {ix["name"] for ix in inspector.get_indexes(_TABLE)}
        if _TENANT_IX in existing_ix:
            op.drop_index(_TENANT_IX, table_name=_TABLE)
        if _PROJECT_IX in existing_ix:
            op.drop_index(_PROJECT_IX, table_name=_TABLE)
        if _OWNER_IX in existing_ix:
            op.drop_index(_OWNER_IX, table_name=_TABLE)
        op.drop_table(_TABLE)

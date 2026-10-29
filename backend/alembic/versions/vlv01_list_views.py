# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""list_views: saved table layouts per list page

Creates ``oe_list_views_view``: one named layout (filters, columns, widths,
sort) of one list page, owned by a user and optionally shared with the
user's tenant.

Revision ID: vlv01_list_views
Revises: v3332_prefab_supply_chain_tracking
Create Date: 2026-10-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vlv01_list_views"
down_revision: str | Sequence[str] | None = "v3332_prefab_supply_chain_tracking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_list_views_view"


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("oe_users_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("scope_key", sa.String(200), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("is_shared", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "scope_key", "name", name="uq_list_views_owner_scope_name"),
    )
    op.create_index("ix_list_views_tenant_scope", _TABLE, ["tenant_id", "scope_key"])
    op.create_index("ix_oe_list_views_view_user_id", _TABLE, ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_oe_list_views_view_user_id", table_name=_TABLE)
    op.drop_index("ix_list_views_tenant_scope", table_name=_TABLE)
    op.drop_table(_TABLE)

# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""mcp - per-user MCP endpoint settings and the origin of an assistant proposal.

Additive only, no data rewrite:

* new table ``oe_mcp_settings``: whether a person lets external AI clients reach
  their data through the MCP endpoint, and the per-minute call budget;
* new column ``oe_erp_chat_action.source`` (``chat`` | ``mcp``), server default
  ``chat`` so every existing proposal keeps reading as the in-app assistant's.

Every step is inspector-guarded, so a database whose tables ``create_all`` already
built reaches this revision and does nothing.

Revision ID: v201_mcp_server
Revises: v200_supplier_pricelists_discounts
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v201_mcp_server"
down_revision: str | Sequence[str] | None = "v200_supplier_pricelists_discounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SETTINGS = "oe_mcp_settings"
_ACTION = "oe_erp_chat_action"


def upgrade() -> None:
    """Create the settings table and add the proposal source column when missing."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if _SETTINGS not in tables and "oe_users_user" in tables:
        op.create_table(
            _SETTINGS,
            sa.Column("id", GUID(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column(
                "user_id",
                GUID(),
                sa.ForeignKey("oe_users_user.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False, server_default="60"),
        )
        op.create_index("ix_oe_mcp_settings_user_id", _SETTINGS, ["user_id"], unique=True)

    if _ACTION in tables:
        columns = {c["name"] for c in insp.get_columns(_ACTION)}
        if "source" not in columns:
            op.add_column(
                _ACTION,
                sa.Column("source", sa.String(16), nullable=False, server_default="chat"),
            )
            op.create_index("ix_oe_erp_chat_action_source", _ACTION, ["source"])


def downgrade() -> None:
    """Drop what upgrade added, when present."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if _ACTION in tables:
        columns = {c["name"] for c in insp.get_columns(_ACTION)}
        if "source" in columns:
            indexes = {i["name"] for i in insp.get_indexes(_ACTION)}
            if "ix_oe_erp_chat_action_source" in indexes:
                op.drop_index("ix_oe_erp_chat_action_source", table_name=_ACTION)
            op.drop_column(_ACTION, "source")

    if _SETTINGS in tables:
        op.drop_table(_SETTINGS)

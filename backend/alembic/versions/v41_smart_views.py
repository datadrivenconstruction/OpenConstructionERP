# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Smart Views — rule-based, re-evaluating BIM viewer presets.

Adds a single strictly-additive table ``oe_smart_view`` carrying the
rule list (JSON), default action, scope, and authoring user. There is
no FK on ``scope_id`` because the target table varies with
``scope_type`` (user / project / federation); the service layer
enforces referential integrity instead.

Idempotent — inspector-guarded so re-runs on a partially migrated DB
skip already-present tables/indexes. SQLite-safe via GUID()→VARCHAR(36)
and JSON columns stored as TEXT.

Revision ID: v41_smart_views
Revises: v41_clash_signature_smart_issues
Create Date: 2026-05-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v41_smart_views"
# Chained after the sibling v41 clash-signature head so the alembic
# graph keeps a single linear tip. Neither migration touches the
# other's tables — the only reason for the explicit ordering is to
# keep ``alembic upgrade head`` resolvable without a merge revision.
down_revision: Union[str, Sequence[str], None] = "v41_clash_signature_smart_issues"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SMART_VIEW_TABLE = "oe_smart_view"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _existing_index_names(
    inspector: sa.engine.reflection.Inspector,
    table: str,
) -> set[str]:
    if not _has_table(inspector, table):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    """Create the ``oe_smart_view`` table."""
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _SMART_VIEW_TABLE):
        op.create_table(
            _SMART_VIEW_TABLE,
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "scope_type",
                sa.String(16),
                nullable=False,
                server_default="user",
            ),
            sa.Column("scope_id", guid_type, nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "rules",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "default_action",
                sa.String(16),
                nullable=False,
                server_default="show_all",
            ),
            sa.Column("color_legend", sa.JSON(), nullable=True),
            sa.Column(
                "created_by",
                guid_type,
                sa.ForeignKey(
                    "oe_users_user.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
        )
        existing_ix = _existing_index_names(inspector, _SMART_VIEW_TABLE)
        for ix_name, cols in (
            ("ix_smart_view_scope", ["scope_type", "scope_id"]),
            ("ix_smart_view_created_by", ["created_by"]),
        ):
            if ix_name not in existing_ix:
                try:
                    op.create_index(ix_name, _SMART_VIEW_TABLE, cols)
                except sa.exc.OperationalError:
                    # Already created in a partial re-run.
                    pass


def downgrade() -> None:
    """Drop the ``oe_smart_view`` table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, _SMART_VIEW_TABLE):
        existing_ix = _existing_index_names(inspector, _SMART_VIEW_TABLE)
        for ix in ("ix_smart_view_scope", "ix_smart_view_created_by"):
            if ix in existing_ix:
                try:
                    op.drop_index(ix, table_name=_SMART_VIEW_TABLE)
                except sa.exc.OperationalError:
                    pass
        op.drop_table(_SMART_VIEW_TABLE)

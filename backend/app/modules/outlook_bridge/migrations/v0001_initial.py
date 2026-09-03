# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Outlook Bridge initial schema - ``oe_outlook_bridge_message``.

Idempotent and inspector-guarded; SQLite-friendly. Move into
``backend/alembic/versions/`` and set ``down_revision`` for
alembic-managed installs (fresh installs get the table from startup
``create_all``).

Revision ID: oe_outlook_bridge_v0001_initial
Revises: <FILL_IN_CURRENT_HEAD>
Create Date: 2026-08-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "oe_outlook_bridge_v0001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_outlook_bridge_message"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE in inspector.get_table_names():
        return
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)
    op.create_table(
        _TABLE,
        sa.Column("id", guid_type, primary_key=True),
        sa.Column("entry_id", sa.String(200), nullable=False),
        sa.Column("internet_message_id", sa.String(300), nullable=False, server_default=""),
        sa.Column("sender_name", sa.String(300), nullable=False, server_default=""),
        sa.Column("sender_email", sa.String(300), nullable=False, server_default=""),
        sa.Column("subject", sa.String(500), nullable=False, server_default=""),
        sa.Column("received_at", sa.String(40), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("attachments", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(20), nullable=False, server_default="unmatched"),
        sa.Column("match_note", sa.String(500), nullable=False, server_default=""),
        sa.Column("project_id", sa.String(36), nullable=True),
        sa.Column("correspondence_id", sa.String(36), nullable=True),
        sa.Column("filed_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("entry_id", name="uq_oe_outlook_bridge_message_entry"),
    )
    op.create_index(f"ix_{_TABLE}_sender_email", _TABLE, ["sender_email"])
    op.create_index(f"ix_{_TABLE}_status", _TABLE, ["status"])
    op.create_index(f"ix_{_TABLE}_project_id", _TABLE, ["project_id"])
    op.create_index(f"ix_{_TABLE}_correspondence_id", _TABLE, ["correspondence_id"])
    op.create_index("ix_outlook_bridge_status_received", _TABLE, ["status", "received_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE in inspector.get_table_names():
        op.drop_table(_TABLE)

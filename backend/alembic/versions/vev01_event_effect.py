# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""run-once ledger of event side effects

Creates ``oe_event_effect``: one row per (business event key, side effect),
unique, so an award drafts its purchase order or contract exactly once even
when the event is delivered twice at the same time.

Revision ID: vev01_event_effect
Revises: vai01_doc_assistant_agent_catalogue
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vev01_event_effect"
down_revision: str | Sequence[str] | None = "vai01_doc_assistant_agent_catalogue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_event_effect"


def upgrade() -> None:
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("event_key", sa.String(200), nullable=False),
        sa.Column("effect", sa.String(120), nullable=False),
        sa.Column("event_name", sa.String(200), nullable=True),
        sa.Column("record_id", sa.String(36), nullable=True),
        sa.UniqueConstraint("event_key", "effect", name="uq_oe_event_effect_key_effect"),
    )


def downgrade() -> None:
    if _TABLE in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table(_TABLE)

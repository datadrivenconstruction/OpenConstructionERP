# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""invoice mailbox: IMAP settings for scan-to-email invoice intake

Additive table only; a fresh install gets it from create_all, an existing one
from this revision.

Revision ID: vmbx01_invoice_mailbox
Revises: vpcat01_project_catalogue
Create Date: 2026-11-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vmbx01_invoice_mailbox"
down_revision: str | Sequence[str] | None = "vpcat01_project_catalogue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_T = "oe_finance_invoice_mailbox"


def upgrade() -> None:
    if _T in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        _T,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("host", sa.String(255), nullable=False, server_default=""),
        sa.Column("port", sa.Integer(), nullable=False, server_default="993"),
        sa.Column("use_ssl", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("username", sa.String(255), nullable=False, server_default=""),
        sa.Column("password_encrypted", sa.Text(), nullable=True),
        sa.Column("folder", sa.String(255), nullable=False, server_default="INBOX"),
        sa.Column("processed_folder", sa.String(255), nullable=False, server_default=""),
        sa.Column("intake_address", sa.String(255), nullable=False, server_default=""),
        sa.Column("last_polled_at", sa.String(40), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table(_T)

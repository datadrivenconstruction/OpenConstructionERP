# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""subcontractors: lien-waiver / W-9 / W-8 storage.

Adds the ``oe_subcontractors_lien_waiver`` table used by the magic-byte
gated ``/subcontractors/{id}/lien-waivers/upload`` endpoint. Each row
links one signed waiver (or tax form) to a subcontractor and — when the
waiver covers a specific draw — to a payment application.

Why a dedicated table and not a generic Document row: lien waivers
carry domain-specific metadata (waiver_type enum, signed_date, amount,
currency) that downstream lien-release reports want first-class access
to; storing it in Documents.metadata JSON would defeat indexing.

Idempotent (checks ``inspector.get_table_names``). Safe to run on
fresh installs — ``Base.metadata.create_all`` will also produce the
table from ``models.LienWaiver`` so we still no-op when it's already
present.

Revision ID: v3131_subcontractors_lien_waivers
Revises: v3130_portal_token_consumed_at
Create Date: 2026-05-25
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3131_subcontractors_lien_waivers"
down_revision: Union[str, Sequence[str], None] = "v3130_portal_token_consumed_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_subcontractors_lien_waiver"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, _TABLE):
        return

    # ``id`` / ``created_at`` / ``updated_at`` come from the Base mixin,
    # so we replicate them here. ``server_default`` on every NOT NULL
    # column avoids the v3119 fresh-install lock cascade
    # (Python defaults are ignored by ``create_all``).
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
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
        sa.Column(
            "subcontractor_id",
            sa.String(36),
            sa.ForeignKey(
                "oe_subcontractors_subcontractor.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "payment_application_id",
            sa.String(36),
            sa.ForeignKey(
                "oe_subcontractors_payment_application.id",
                ondelete="SET NULL",
            ),
            nullable=True,
        ),
        sa.Column("waiver_type", sa.String(32), nullable=False),
        sa.Column("document_url", sa.String(1000), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("signed_date", sa.Date(), nullable=True),
        sa.Column(
            "amount",
            sa.Numeric(18, 2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "currency",
            sa.String(3),
            nullable=False,
            server_default="",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("uploaded_by", sa.String(36), nullable=True),
        sa.Column(
            "metadata",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
    )
    op.create_index(
        f"ix_{_TABLE}_subcontractor_id",
        _TABLE,
        ["subcontractor_id"],
    )
    op.create_index(
        f"ix_{_TABLE}_payment_application_id",
        _TABLE,
        ["payment_application_id"],
    )
    op.create_index(
        f"ix_{_TABLE}_waiver_type",
        _TABLE,
        ["waiver_type"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return
    op.drop_index(f"ix_{_TABLE}_waiver_type", table_name=_TABLE)
    op.drop_index(
        f"ix_{_TABLE}_payment_application_id",
        table_name=_TABLE,
    )
    op.drop_index(
        f"ix_{_TABLE}_subcontractor_id",
        table_name=_TABLE,
    )
    op.drop_table(_TABLE)

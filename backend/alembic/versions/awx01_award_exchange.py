# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""boq + tendering - imported bill source, bidder files, decline, request documents.

Three new tables and two nullable columns:

* ``oe_boq_exchange_source``: the file a bill was imported from (hash, stored
  bytes, Documents id) and a snapshot of its lines, so an award export (GAEB
  X86) can be refused when the bill no longer matches the file.
* ``oe_tendering_bid_file``: files a bidder uploaded through its link.
* ``oe_tendering_package_document``: project documents sent out with a package.
* ``oe_tendering_bid_invitation.declined_at`` / ``decline_reason``.

Everything is additive. ``Base.metadata.create_all`` creates the tables on a
running install and the auto-migrator adds the nullable columns; the
migration is inspector-guarded, so a re-run changes nothing.

Revision ID: awx01_award_exchange
Revises: awt01_tender_award_terms
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "awx01_award_exchange"
down_revision: Union[str, Sequence[str], None] = "awt01_tender_award_terms"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SOURCE = "oe_boq_exchange_source"
_FILE = "oe_tendering_bid_file"
_DOC = "oe_tendering_package_document"
_INV = "oe_tendering_bid_invitation"
_GUID = sa.String(36)


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("id", _GUID, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
    ]


def upgrade() -> None:
    """Create the three tables and add the decline columns."""
    insp = sa.inspect(op.get_bind())
    existing = set(insp.get_table_names())
    if _SOURCE not in existing:
        op.create_table(
            _SOURCE,
            *_stamps(),
            sa.Column("boq_id", _GUID, nullable=False),
            sa.Column("project_id", _GUID, nullable=True),
            sa.Column("format_id", sa.String(30), nullable=False),
            sa.Column("variant", sa.String(20), nullable=False, server_default=""),
            sa.Column("file_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("file_sha256", sa.String(64), nullable=False),
            sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("file_path", sa.String(500), nullable=False, server_default=""),
            sa.Column("document_id", _GUID, nullable=True),
            sa.Column("bill_sha256", sa.String(64), nullable=False),
            sa.Column("line_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("lines", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.PrimaryKeyConstraint("id", name=f"pk_{_SOURCE}"),
            sa.ForeignKeyConstraint(["boq_id"], ["oe_boq_boq.id"], name=f"fk_{_SOURCE}_boq", ondelete="CASCADE"),
        )
        op.create_index(f"ix_{_SOURCE}_boq_id", _SOURCE, ["boq_id"])
        op.create_index(f"ix_{_SOURCE}_project_id", _SOURCE, ["project_id"])
        op.create_index("ix_boq_exchange_source_boq_created", _SOURCE, ["boq_id", "created_at"])
    if _FILE not in existing:
        op.create_table(
            _FILE,
            *_stamps(),
            sa.Column("package_id", _GUID, nullable=False),
            sa.Column("invitation_id", _GUID, nullable=True),
            sa.Column("recipient_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("company_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("bid_id", _GUID, nullable=True),
            sa.Column("kind", sa.String(20), nullable=False, server_default="attachment"),
            sa.Column("file_name", sa.String(255), nullable=False),
            sa.Column("mime_type", sa.String(100), nullable=False, server_default=""),
            sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("file_path", sa.String(500), nullable=False, server_default=""),
            sa.Column("document_id", _GUID, nullable=True),
            sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id", name=f"pk_{_FILE}"),
            sa.ForeignKeyConstraint(
                ["package_id"], ["oe_tendering_package.id"], name=f"fk_{_FILE}_package", ondelete="CASCADE"
            ),
        )
        op.create_index(f"ix_{_FILE}_package_id", _FILE, ["package_id"])
        op.create_index(f"ix_{_FILE}_invitation_id", _FILE, ["invitation_id"])
    if _DOC not in existing:
        op.create_table(
            _DOC,
            *_stamps(),
            sa.Column("package_id", _GUID, nullable=False),
            sa.Column("document_id", _GUID, nullable=False),
            sa.Column("added_by", sa.String(36), nullable=True),
            sa.PrimaryKeyConstraint("id", name=f"pk_{_DOC}"),
            sa.ForeignKeyConstraint(
                ["package_id"], ["oe_tendering_package.id"], name=f"fk_{_DOC}_package", ondelete="CASCADE"
            ),
            sa.UniqueConstraint("package_id", "document_id", name="uq_oe_tendering_package_document_doc"),
        )
        op.create_index(f"ix_{_DOC}_package_id", _DOC, ["package_id"])
        op.create_index(f"ix_{_DOC}_document_id", _DOC, ["document_id"])
    if _INV in existing:
        columns = {c["name"] for c in insp.get_columns(_INV)}
        if "declined_at" not in columns:
            op.add_column(_INV, sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True))
        if "decline_reason" not in columns:
            op.add_column(_INV, sa.Column("decline_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop the decline columns and the three tables when present."""
    insp = sa.inspect(op.get_bind())
    existing = set(insp.get_table_names())
    if _INV in existing:
        columns = {c["name"] for c in insp.get_columns(_INV)}
        for column in ("decline_reason", "declined_at"):
            if column in columns:
                op.drop_column(_INV, column)
    for table in (_DOC, _FILE, _SOURCE):
        if table in existing:
            op.drop_table(table)

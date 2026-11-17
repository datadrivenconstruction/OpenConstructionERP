# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""subcontractors - agreement documents and the required-documents policy.

Two new tables: ``oe_subcontractors_agreement_document`` (a file attached to a
subcontract agreement under a document role) and
``oe_subcontractors_document_policy`` (the installation policy: the list of
required documents and whether a gap warns or blocks).

Nothing existing changes. ``Base.metadata.create_all`` also creates both on a
running install from the models; the migration is inspector-guarded, so a
re-run or a downgrade without the tables changes nothing.

Revision ID: vsub01_agreement_documents
Revises: vdt02_doc_template_issues
Create Date: 2026-11-17
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "vsub01_agreement_documents"
down_revision: Union[str, Sequence[str], None] = "vdt02_doc_template_issues"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DOC = "oe_subcontractors_agreement_document"
_POLICY = "oe_subcontractors_document_policy"
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
    """Create the two tables."""
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if _DOC not in existing:
        op.create_table(
            _DOC,
            *_stamps(),
            sa.Column("agreement_id", _GUID, nullable=False),
            sa.Column("doc_role", sa.String(40), nullable=False, server_default="other"),
            sa.Column("title", sa.String(500), nullable=False, server_default=""),
            sa.Column("filename", sa.String(500), nullable=False, server_default=""),
            sa.Column("document_url", sa.String(1000), nullable=False),
            sa.Column("mime_type", sa.String(120), nullable=True),
            sa.Column("file_size", sa.Integer(), nullable=True),
            sa.Column("signed_date", sa.Date(), nullable=True),
            sa.Column("valid_until", sa.Date(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("uploaded_by", sa.String(36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.PrimaryKeyConstraint("id", name=f"pk_{_DOC}"),
            sa.ForeignKeyConstraint(
                ["agreement_id"], ["oe_subcontractors_agreement.id"], name=f"fk_{_DOC}_agreement", ondelete="CASCADE"
            ),
        )
        op.create_index(f"ix_{_DOC}_agreement_id", _DOC, ["agreement_id"])
        op.create_index(f"ix_{_DOC}_doc_role", _DOC, ["doc_role"])
        op.create_index(f"ix_{_DOC}_valid_until", _DOC, ["valid_until"])
    if _POLICY not in existing:
        op.create_table(
            _POLICY,
            *_stamps(),
            sa.Column("scope", sa.String(20), nullable=False, server_default="installation"),
            sa.Column("required", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("enforcement", sa.String(10), nullable=False, server_default="warn"),
            sa.Column("updated_by", sa.String(36), nullable=True),
            sa.PrimaryKeyConstraint("id", name=f"pk_{_POLICY}"),
            sa.UniqueConstraint("scope", name="uq_oe_subcontractors_document_policy_scope"),
        )


def downgrade() -> None:
    """Drop the two tables when present."""
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in (_POLICY, _DOC):
        if table in existing:
            op.drop_table(table)

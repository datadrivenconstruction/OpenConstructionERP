# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""NCR links to the documents it concerns

Adds ``linked_document_ids`` (JSON array of document ids) to ``oe_ncr_ncr`` so a
drawing can list the non-conformities raised against it. Additive only: the
column carries a server default, so the boot heal and ``alembic upgrade`` agree.

Revision ID: vdoc01_ncr_linked_documents
Revises: vhsef01_form_ncr_link
Create Date: 2026-11-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vdoc01_ncr_linked_documents"
down_revision: str | Sequence[str] | None = "vhsef01_form_ncr_link"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_ncr_ncr"
_COLUMN = "linked_document_ids"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    if _COLUMN in {c["name"] for c in inspector.get_columns(_TABLE)}:
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(sa.Column(_COLUMN, sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    if _COLUMN not in {c["name"] for c in inspector.get_columns(_TABLE)}:
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column(_COLUMN)

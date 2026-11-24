# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Form submission to NCR link - oe_forms_submission.linked_ncr_id.

Adds one nullable, indexed column holding the id of the NCR raised from a failed
form, so the raise is idempotent and the form points at what it produced.

Strictly additive and nullable: existing rows read exactly as before.

This migration MUST be RUN (``alembic upgrade``), not merely stamped: prod
builds the schema with ``create_all`` + ``alembic stamp <head>``, and
``create_all`` never adds a column to a table that already exists.

Revision ID: vhsef01_form_ncr_link
Revises: vdsn01_design_module
Create Date: 2026-11-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vhsef01_form_ncr_link"
down_revision: str | Sequence[str] | None = "vdsn01_design_module"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_forms_submission"
_INDEX = "ix_oe_forms_submission_linked_ncr_id"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    if "linked_ncr_id" not in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.add_column(_TABLE, sa.Column("linked_ncr_id", sa.String(36), nullable=True))
    if _INDEX not in {i["name"] for i in inspector.get_indexes(_TABLE)}:
        op.create_index(_INDEX, _TABLE, ["linked_ncr_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    if _INDEX in {i["name"] for i in inspector.get_indexes(_TABLE)}:
        op.drop_index(_INDEX, table_name=_TABLE)
    if "linked_ncr_id" in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.drop_column(_TABLE, "linked_ncr_id")

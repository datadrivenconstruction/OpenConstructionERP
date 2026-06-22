# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""qms: unique (inspection_id, signer_user_id, signer_role) on signatures.

Background
----------
``QMSService.add_signature`` deduped "one (user, role) signature per
inspection" purely in Python (list-then-check). That check is not atomic:
two concurrent sign requests for the same (inspection, user, role) could both
pass it and both INSERT, inflating the signatory count and letting an
inspection that requires N distinct signatories be completed with a single
person signing twice - defeating the multi-signatory quality gate on a
compliance-grade digital-signature record.

This migration adds the backing unique constraint so the DB serialises the
race; the loser trips the constraint and the service translates the
``IntegrityError`` into a clean 409.

Safety
------
* Idempotent - guarded by an ``inspector.get_unique_constraints`` /
  ``get_indexes`` check, so re-running it (or ``alembic stamp head`` on a DB
  where ``Base.metadata.create_all`` already created the constraint) is a
  no-op.
* SQLite cannot ``ALTER TABLE ... ADD CONSTRAINT``; it is used only by the
  minimal test fixtures, which build the schema from ``create_all`` (the ORM
  ``__table_args__`` already carries the constraint there), so the SQLite
  branch is a no-op.

Revision ID: v3190_qms_signature_unique
Revises: v3189_takeoff_composite_idx
Create Date: 2026-06-22

Note: the revision id is kept <= 32 chars because the create_all + ``stamp head``
bootstrap path creates alembic's ``alembic_version.version_num`` at its default
``VARCHAR(32)``; a longer head id fails to stamp there.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3190_qms_signature_unique"
down_revision: Union[str, Sequence[str], None] = "v3189_takeoff_composite_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_qms_inspection_signature"
_CONSTRAINT = "uq_oe_qms_inspection_signature_inspection_user_role"
_COLUMNS = ["inspection_id", "signer_user_id", "signer_role"]


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_unique(inspector: sa.engine.reflection.Inspector, table: str, name: str) -> bool:
    if not _has_table(inspector, table):
        return False
    # A unique constraint may surface either as a unique constraint or as a
    # unique index depending on dialect/reflection; check both.
    names = {uc["name"] for uc in inspector.get_unique_constraints(table)}
    names |= {ix["name"] for ix in inspector.get_indexes(table) if ix.get("unique")}
    return name in names


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE) or _has_unique(inspector, _TABLE, _CONSTRAINT):
        return
    if bind.dialect.name == "sqlite":
        # SQLite test fixtures build the schema from create_all, which already
        # includes the ORM-declared constraint; nothing to alter here.
        return
    op.create_unique_constraint(_CONSTRAINT, _TABLE, _COLUMNS)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if bind.dialect.name == "sqlite":
        return
    if _has_unique(inspector, _TABLE, _CONSTRAINT):
        op.drop_constraint(_CONSTRAINT, _TABLE, type_="unique")

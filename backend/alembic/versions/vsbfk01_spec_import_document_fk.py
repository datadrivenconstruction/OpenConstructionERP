# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""submittals: foreign key from spec import to its document

``oe_submittals_spec_import.document_id`` is NOT NULL and names the specification book the
import parsed. Deleting that document left the import pointing at nothing. The key cascades:
the import and its proposals describe a parse of that one file and mean nothing without it,
while submittals already confirmed from it carry no link back and survive. Imports whose
document is already gone are removed first so the key can be created.

Revision ID: vsbfk01_spec_import_document_fk
Revises: vsod01_budget_ledger_segregation
Create Date: 2026-11-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vsbfk01_spec_import_document_fk"
down_revision: str | Sequence[str] | None = "vsod01_budget_ledger_segregation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_T = "oe_submittals_spec_import"
_PROPOSAL = "oe_submittals_spec_proposal"
_DOC = "oe_documents_document"
_FK = "fk_oe_submittals_spec_import_document_id_oe_documents_document"


def _has_fk(insp: sa.Inspector) -> bool:
    return any(fk.get("name") == _FK for fk in insp.get_foreign_keys(_T))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if _T not in tables or _DOC not in tables or _has_fk(insp):
        return
    orphans = f"SELECT id FROM {_T} WHERE document_id NOT IN (SELECT id FROM {_DOC})"
    if _PROPOSAL in tables:
        op.execute(sa.text(f"DELETE FROM {_PROPOSAL} WHERE import_id IN ({orphans})"))
    op.execute(sa.text(f"DELETE FROM {_T} WHERE id IN ({orphans})"))
    with op.batch_alter_table(_T) as batch:
        batch.create_foreign_key(_FK, _DOC, ["document_id"], ["id"], ondelete="CASCADE")


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _T in set(insp.get_table_names()) and _has_fk(insp):
        with op.batch_alter_table(_T) as batch:
            batch.drop_constraint(_FK, type_="foreignkey")

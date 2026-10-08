"""Projects name the legal entity that owns them.

A nullable ``legal_entity_id`` on the project table with an index, and no
foreign key: legal entities is a module an install can leave out, so the core
table does not depend on its table. The module checks the id on write.

Revision ID: v66_project_legal_entity
Revises: v65_po_invoice_tolerance
"""

import sqlalchemy as sa
from alembic import op

revision = "v66_project_legal_entity"
down_revision = "v65_po_invoice_tolerance"
branch_labels = None
depends_on = None

_TABLE = "oe_projects_project"
_COLUMN = "legal_entity_id"
_INDEX = "ix_oe_projects_project_legal_entity_id"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(_TABLE):
        return
    if _COLUMN not in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(36), nullable=True))
    if _INDEX not in {ix["name"] for ix in inspector.get_indexes(_TABLE)}:
        op.create_index(_INDEX, _TABLE, [_COLUMN])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(_TABLE):
        return
    if _INDEX in {ix["name"] for ix in inspector.get_indexes(_TABLE)}:
        op.drop_index(_INDEX, table_name=_TABLE)
    if _COLUMN in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.drop_column(_TABLE, _COLUMN)

"""Whether a contact or a subcontractor is a natural person or a legal entity.

Nullable, added only when missing, so a database the boot-time column
healer already touched upgrades cleanly. NULL means not stated yet.

Revision ID: v63_contact_party_kind
Revises: v62_geocoding_consent
"""

import sqlalchemy as sa
from alembic import op

revision = "v63_contact_party_kind"
down_revision = "v62_geocoding_consent"
branch_labels = None
depends_on = None

_TABLES = ("oe_contacts_contact", "oe_subcontractors_subcontractor")
_COLUMN = "party_kind"


def _has_column(inspector, table: str) -> bool | None:
    if not inspector.has_table(table):
        return None
    return _COLUMN in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in _TABLES:
        if _has_column(inspector, table) is False:
            op.add_column(table, sa.Column(_COLUMN, sa.String(20), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in reversed(_TABLES):
        if _has_column(inspector, table):
            op.drop_column(table, _COLUMN)

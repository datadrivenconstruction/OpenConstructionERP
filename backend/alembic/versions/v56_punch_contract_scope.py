"""Scope punch-list withholding to an explicitly assigned contract.

Existing items remain unassigned (NULL). Do not infer a contract from a project:
a project can have several contracts, and that would move money between them.
The link is a plain nullable GUID so punchlist remains installable without the
contracts module. Its service validates the contract and project when assigned.
The nullable column and ordinary index are also supported by startup schema heal.

Revision ID: v56_punch_contract_scope
Revises: v55_boq_tax_date
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v56_punch_contract_scope"
down_revision: str | Sequence[str] | None = "v55_boq_tax_date"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_punchlist_item"
_INDEX = "ix_oe_punchlist_item_contract_id"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    if "contract_id" not in {column["name"] for column in inspector.get_columns(_TABLE)}:
        op.add_column(_TABLE, sa.Column("contract_id", GUID(), nullable=True))
    if _INDEX not in {index["name"] for index in inspector.get_indexes(_TABLE)}:
        op.create_index(_INDEX, _TABLE, ["contract_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in inspector.get_table_names():
        return
    if _INDEX in {index["name"] for index in inspector.get_indexes(_TABLE)}:
        op.drop_index(_INDEX, table_name=_TABLE)
    if "contract_id" in {column["name"] for column in inspector.get_columns(_TABLE)}:
        op.drop_column(_TABLE, "contract_id")

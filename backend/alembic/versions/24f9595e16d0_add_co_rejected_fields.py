"""add_co_rejected_fields

Revision ID: 24f9595e16d0
Revises: fee2e323c50c
Create Date: 2026-04-19 10:10:54.732981

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '24f9595e16d0'
down_revision: Union[str, None] = 'fee2e323c50c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add rejected_by / rejected_at columns to change orders.

    BUG-351: previously the reject path wrote the rejector's user-id into
    ``approved_by``, which caused audit UIs to attribute the rejection to
    the approver role. Splitting rejection into its own columns lets the
    audit trail reflect reality and keeps ``approved_by`` semantically
    pure (it now only names someone who actually approved).
    """
    with op.batch_alter_table("oe_changeorders_order") as batch:
        batch.add_column(sa.Column("rejected_by", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("rejected_at", sa.String(length=20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("oe_changeorders_order") as batch:
        batch.drop_column("rejected_at")
        batch.drop_column("rejected_by")

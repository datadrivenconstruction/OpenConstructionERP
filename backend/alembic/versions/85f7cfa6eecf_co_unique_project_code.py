"""co_unique_project_code

Revision ID: 85f7cfa6eecf
Revises: 24f9595e16d0
Create Date: 2026-04-19 10:12:50.478344

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '85f7cfa6eecf'
down_revision: Union[str, None] = '24f9595e16d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add unique constraint on (project_id, code) for change orders.

    BUG-354: protects against the ``count + 1`` race condition in
    :meth:`ChangeOrderService.create_order`. Without the constraint two
    concurrent requests could both compute ``CO-005`` and both succeed,
    producing duplicate codes for the same project.
    """
    with op.batch_alter_table("oe_changeorders_order") as batch:
        batch.create_unique_constraint(
            "uq_changeorders_project_code",
            ["project_id", "code"],
        )


def downgrade() -> None:
    with op.batch_alter_table("oe_changeorders_order") as batch:
        batch.drop_constraint("uq_changeorders_project_code", type_="unique")

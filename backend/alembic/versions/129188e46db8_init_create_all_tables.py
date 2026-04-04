"""init: create all tables

Revision ID: 129188e46db8
Revises:
Create Date: 2026-03-26 14:32:37.263344

Note: Tables are auto-created by SQLAlchemy Base.metadata.create_all() at startup.
This migration exists as a baseline marker for Alembic version tracking.
On fresh databases, all tables already exist before this migration runs.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '129188e46db8'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tables are created by SQLAlchemy at app startup.
    # This migration serves as the Alembic baseline.
    pass


def downgrade() -> None:
    # No-op: tables are managed by SQLAlchemy metadata.
    pass

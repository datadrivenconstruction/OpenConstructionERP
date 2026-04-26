"""v262_merge_jobs_eac_aliases

Revision ID: eb1cef6f5fce
Revises: v260_jobs_runner, v261_eac_alias_catalog_seed
Create Date: 2026-04-25 08:59:26.136180

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eb1cef6f5fce'
down_revision: Union[str, None] = ('v260_jobs_runner', 'v261_eac_alias_catalog_seed')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

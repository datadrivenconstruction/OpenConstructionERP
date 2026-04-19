"""merge_bim_req_with_dwg_annotations

Revision ID: fee2e323c50c
Revises: v100_bim_requirements, v192_dwg_annotation_thickness_layer
Create Date: 2026-04-19 10:09:05.278765

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fee2e323c50c'
down_revision: Union[str, None] = ('v100_bim_requirements', 'v192_dwg_annotation_thickness_layer')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

"""Process settings for the processes center.

One row per background process with the on/off choice an admin made, plus two
reserved rows that record whether the installation started fresh and whether
the first-run wizard was answered. The table is new and created only when
missing, so a database the boot-time ``create_all`` already built upgrades
cleanly.

Revision ID: v61_process_settings
Revises: v60_legal_entities
"""

import sqlalchemy as sa
from alembic import op

revision = "v61_process_settings"
down_revision = "v60_legal_entities"
branch_labels = None
depends_on = None

_TABLE = "oe_process_settings"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        # ``String(36)``: ``GUID`` is a TypeDecorator over String(36).
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column("process_id", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_by", sa.String(100), nullable=True),
    )
    op.create_index("ix_oe_process_settings_process_id", _TABLE, ["process_id"], unique=True)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(_TABLE):
        op.drop_index("ix_oe_process_settings_process_id", table_name=_TABLE)
        op.drop_table(_TABLE)

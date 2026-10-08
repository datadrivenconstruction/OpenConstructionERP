"""The installation's one-time answer on sending addresses to a geocoder.

One row per installation. A new table, so ``create_all`` brings it to
running installations as well; the revision only keeps an Alembic-built
database in step. Created only when missing.

Revision ID: v62_geocoding_consent
Revises: v61_process_settings
"""

import sqlalchemy as sa
from alembic import op

revision = "v62_geocoding_consent"
down_revision = "v61_process_settings"
branch_labels = None
depends_on = None

_TABLE = "oe_geo_hub_geocoding_consent"


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table(_TABLE):
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
        sa.Column("scope", sa.String(32), nullable=False, server_default="installation"),
        sa.Column("choice", sa.String(16), nullable=False, server_default="deny"),
        sa.Column("mirror_url", sa.String(500), nullable=True),
        sa.Column("decided_by", sa.String(36), nullable=True),
        sa.UniqueConstraint("scope", name="uq_oe_geo_hub_geocoding_consent_scope"),
    )


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table(_TABLE):
        op.drop_table(_TABLE)

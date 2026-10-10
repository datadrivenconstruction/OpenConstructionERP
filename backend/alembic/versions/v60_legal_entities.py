"""Legal entities and branches.

The group structure the numbering, tax and stock pieces hang off: one row per
company with its country and functional currency, and one row per branch of a
company. Both tables are new and created only when missing, so a database the
boot-time ``create_all`` already built upgrades cleanly.

Revision ID: v60_legal_entities
Revises: v59_gr_item_batch_serial
"""

import sqlalchemy as sa
from alembic import op

revision = "v60_legal_entities"
down_revision = "v59_gr_item_batch_serial"
branch_labels = None
depends_on = None

_ENTITY = "oe_legal_entities_entity"
_BRANCH = "oe_legal_entities_branch"
_BRANCH_INDEX = "ix_oe_legal_entities_branch_entity"


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
    ]


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    # ``String(36)``: ``GUID`` is a TypeDecorator over String(36), so this is
    # the type create_all builds and the foreign key below can reference it.
    guid = sa.String(36)

    if not inspector.has_table(_ENTITY):
        op.create_table(
            _ENTITY,
            sa.Column("id", guid, primary_key=True),
            *_timestamps(),
            sa.Column("code", sa.String(32), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("country_code", sa.String(2), nullable=False),
            sa.Column("subdivision_code", sa.String(6), nullable=True),
            sa.Column("functional_currency", sa.String(3), nullable=False),
            sa.Column("registration_number", sa.String(100), nullable=True),
            sa.Column("tax_id", sa.String(100), nullable=True),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.UniqueConstraint("code", name="uq_oe_legal_entities_entity_code"),
        )

    if not inspector.has_table(_BRANCH):
        op.create_table(
            _BRANCH,
            sa.Column("id", guid, primary_key=True),
            *_timestamps(),
            sa.Column(
                "legal_entity_id",
                guid,
                sa.ForeignKey(f"{_ENTITY}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("code", sa.String(32), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("country_code", sa.String(2), nullable=False),
            sa.Column("subdivision_code", sa.String(6), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.UniqueConstraint("legal_entity_id", "code", name="uq_oe_legal_entities_branch_entity_code"),
        )
    inspector = sa.inspect(op.get_bind())
    if _BRANCH_INDEX not in {ix["name"] for ix in inspector.get_indexes(_BRANCH)}:
        op.create_index(_BRANCH_INDEX, _BRANCH, ["legal_entity_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(_BRANCH):
        op.drop_table(_BRANCH)
    if inspector.has_table(_ENTITY):
        op.drop_table(_ENTITY)

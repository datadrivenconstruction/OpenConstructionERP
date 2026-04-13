"""add collab_lock table

Creates ``oe_collab_lock`` — pessimistic soft locks for the layer-1
real-time collaboration feature.  One row per live ``(entity_type,
entity_id)`` pair, uniquely constrained so two users cannot both own
the same entity at the same time.

Uses the same idempotent ``CREATE TABLE IF NOT EXISTS`` helper as the
other recent migrations so re-runs against a dev SQLite DB (where
``Base.metadata.create_all`` may already have created the table) are
safe.

Revision ID: a1b2c3d4e5f6
Revises: b2f4e1a3c907
Create Date: 2026-04-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "b2f4e1a3c907"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Helpers (mirrored from the v090 / ffe3f561e2c1 migrations)
# ---------------------------------------------------------------------------


def _create_if_not_exists(table_name: str, *columns: sa.Column, **kw) -> None:  # noqa: ANN003
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table_name not in insp.get_table_names():
        op.create_table(table_name, *columns, **kw)


def _pk() -> sa.Column:
    return sa.Column("id", sa.String(36), primary_key=True)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def _meta() -> sa.Column:
    return sa.Column("metadata", sa.JSON, nullable=False, server_default="{}")


def upgrade() -> None:
    _create_if_not_exists(
        "oe_collab_lock",
        _pk(),
        sa.Column("org_id", sa.String(36), nullable=True, index=True),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("oe_users_user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _meta(),
        *_timestamps(),
        sa.UniqueConstraint(
            "entity_type", "entity_id", name="uq_collab_lock_entity"
        ),
    )

    # Indexes.  Guarded because the table may already exist from
    # create_all (SQLite dev) with a superset of these indexes.
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = {ix["name"] for ix in insp.get_indexes("oe_collab_lock")}

    if "ix_collab_lock_expires" not in existing:
        op.create_index(
            "ix_collab_lock_expires", "oe_collab_lock", ["expires_at"]
        )
    if "ix_collab_lock_user" not in existing:
        op.create_index(
            "ix_collab_lock_user", "oe_collab_lock", ["user_id"]
        )
    if "ix_collab_lock_entity_lookup" not in existing:
        op.create_index(
            "ix_collab_lock_entity_lookup",
            "oe_collab_lock",
            ["entity_type", "entity_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "oe_collab_lock" in insp.get_table_names():
        for ix_name in (
            "ix_collab_lock_expires",
            "ix_collab_lock_user",
            "ix_collab_lock_entity_lookup",
        ):
            try:
                op.drop_index(ix_name, table_name="oe_collab_lock")
            except Exception:
                pass
        op.drop_table("oe_collab_lock")

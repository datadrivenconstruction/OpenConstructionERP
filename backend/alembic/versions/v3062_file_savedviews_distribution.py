# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Saved Views + Distribution Lists/Subscriptions — Wave W5 + W10.

Creates four additive tables:

* ``oe_file_saved_view``              — Wave W5 personal/shared smart folder
* ``oe_file_distribution_list``       — Wave W10 named recipient group
* ``oe_file_distribution_member``     — one recipient inside a list
* ``oe_file_distribution_subscription`` — per-project/kind subscription

All migrations are inspector-guarded so re-running after SQLite's
``Base.metadata.create_all`` / ``sqlite_auto_migrate`` (dev) is a
no-op; Postgres prod gets the DDL.

Revision ID: v3062_file_savedviews_distribution
Revises: v3047_clash_severity_delta
Created: 2026-05-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3062_file_savedviews_distribution"
down_revision: Union[str, Sequence[str], None] = "v3047_clash_severity_delta"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SAVED_VIEW = "oe_file_saved_view"
_DIST_LIST = "oe_file_distribution_list"
_DIST_MEMBER = "oe_file_distribution_member"
_DIST_SUB = "oe_file_distribution_subscription"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── oe_file_saved_view ───────────────────────────────────────────────
    if not _has_table(inspector, _SAVED_VIEW):
        op.create_table(
            _SAVED_VIEW,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                sa.String(36),
                sa.ForeignKey("oe_users_user.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "project_id",
                sa.String(36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("icon", sa.String(32), nullable=True),
            sa.Column(
                "filter_json",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "sort_order",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "is_pinned",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "is_shared",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "last_used_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "use_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.UniqueConstraint(
                "user_id",
                "project_id",
                "name",
                name="uq_file_saved_view_user_proj_name",
            ),
        )
        op.create_index(
            "ix_file_saved_view_user",
            _SAVED_VIEW,
            ["user_id"],
        )
        op.create_index(
            "ix_file_saved_view_project",
            _SAVED_VIEW,
            ["project_id"],
        )
        op.create_index(
            "ix_file_saved_view_pinned",
            _SAVED_VIEW,
            ["is_pinned"],
        )

    # ── oe_file_distribution_list ────────────────────────────────────────
    if not _has_table(inspector, _DIST_LIST):
        op.create_table(
            _DIST_LIST,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "owner_id",
                sa.String(36),
                sa.ForeignKey("oe_users_user.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "project_id",
                sa.String(36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "is_shared",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            ),
        )
        op.create_index(
            "ix_file_distribution_list_project",
            _DIST_LIST,
            ["project_id"],
        )
        op.create_index(
            "ix_file_distribution_list_owner",
            _DIST_LIST,
            ["owner_id"],
        )

    # ── oe_file_distribution_member ──────────────────────────────────────
    if not _has_table(inspector, _DIST_MEMBER):
        op.create_table(
            _DIST_MEMBER,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "list_id",
                sa.String(36),
                sa.ForeignKey(
                    "oe_file_distribution_list.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("display_name", sa.String(128), nullable=True),
            sa.Column("role", sa.String(32), nullable=True),
            sa.UniqueConstraint(
                "list_id",
                "email",
                name="uq_file_distribution_member_list_email",
            ),
        )
        op.create_index(
            "ix_file_distribution_member_list",
            _DIST_MEMBER,
            ["list_id"],
        )

    # ── oe_file_distribution_subscription ────────────────────────────────
    if not _has_table(inspector, _DIST_SUB):
        op.create_table(
            _DIST_SUB,
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "project_id",
                sa.String(36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "file_kind",
                sa.String(32),
                nullable=False,
                server_default="*",
            ),
            sa.Column("subscriber_email", sa.String(255), nullable=False),
            sa.Column(
                "subscriber_user_id",
                sa.String(36),
                sa.ForeignKey("oe_users_user.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "notify_on",
                sa.JSON(),
                nullable=False,
                server_default='["created","updated","deleted"]',
            ),
            sa.Column(
                "active",
                sa.Boolean(),
                nullable=False,
                server_default="1",
            ),
            sa.UniqueConstraint(
                "project_id",
                "file_kind",
                "subscriber_email",
                name="uq_file_distribution_subscription_proj_kind_email",
            ),
        )
        op.create_index(
            "ix_file_distribution_subscription_project_kind",
            _DIST_SUB,
            ["project_id", "file_kind"],
        )
        op.create_index(
            "ix_file_distribution_subscription_user",
            _DIST_SUB,
            ["subscriber_user_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Drop in reverse FK order: subscriptions → members → lists → views.
    if _has_table(inspector, _DIST_SUB):
        existing_idx = {ix["name"] for ix in inspector.get_indexes(_DIST_SUB)}
        if "ix_file_distribution_subscription_user" in existing_idx:
            op.drop_index(
                "ix_file_distribution_subscription_user",
                table_name=_DIST_SUB,
            )
        if "ix_file_distribution_subscription_project_kind" in existing_idx:
            op.drop_index(
                "ix_file_distribution_subscription_project_kind",
                table_name=_DIST_SUB,
            )
        op.drop_table(_DIST_SUB)

    if _has_table(inspector, _DIST_MEMBER):
        existing_idx = {ix["name"] for ix in inspector.get_indexes(_DIST_MEMBER)}
        if "ix_file_distribution_member_list" in existing_idx:
            op.drop_index(
                "ix_file_distribution_member_list",
                table_name=_DIST_MEMBER,
            )
        op.drop_table(_DIST_MEMBER)

    if _has_table(inspector, _DIST_LIST):
        existing_idx = {ix["name"] for ix in inspector.get_indexes(_DIST_LIST)}
        if "ix_file_distribution_list_owner" in existing_idx:
            op.drop_index(
                "ix_file_distribution_list_owner",
                table_name=_DIST_LIST,
            )
        if "ix_file_distribution_list_project" in existing_idx:
            op.drop_index(
                "ix_file_distribution_list_project",
                table_name=_DIST_LIST,
            )
        op.drop_table(_DIST_LIST)

    if _has_table(inspector, _SAVED_VIEW):
        existing_idx = {ix["name"] for ix in inspector.get_indexes(_SAVED_VIEW)}
        if "ix_file_saved_view_pinned" in existing_idx:
            op.drop_index(
                "ix_file_saved_view_pinned",
                table_name=_SAVED_VIEW,
            )
        if "ix_file_saved_view_project" in existing_idx:
            op.drop_index(
                "ix_file_saved_view_project",
                table_name=_SAVED_VIEW,
            )
        if "ix_file_saved_view_user" in existing_idx:
            op.drop_index(
                "ix_file_saved_view_user",
                table_name=_SAVED_VIEW,
            )
        op.drop_table(_SAVED_VIEW)

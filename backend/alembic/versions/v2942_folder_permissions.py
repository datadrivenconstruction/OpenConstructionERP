# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""documents — per-folder permission table.

Adds ``oe_documents_folder_permission`` so a project owner can scope a
file-manager folder (``scope_kind`` × optional ``scope_path``) to a
subset of project members with ``viewer`` / ``editor`` / ``owner``
roles.

Idempotent — re-applying on a DB where ``Base.metadata.create_all``
has already created the table is a no-op (matches the pattern used by
v2939_document_share_links / v2938_documents_activity).

Revision ID: v2942_folder_permissions
Revises: v2941_markup_comments
Create Date: 2026-05-12
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v2942_folder_permissions"
down_revision: Union[str, Sequence[str], None] = "v2941_markup_comments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_documents_folder_permission"

_INDEXES: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    # (name, cols, unique)
    ("ix_folder_permission_project_user", ("project_id", "user_id"), False),
    (
        "ix_folder_permission_scope",
        ("project_id", "scope_kind", "scope_path"),
        False,
    ),
    ("ix_folder_permission_project_id", ("project_id",), False),
    ("ix_folder_permission_user_id", ("user_id",), False),
)

_UNIQUE_NAME = "uq_folder_permission_scope_user"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    index: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(ix["name"] == index for ix in inspector.get_indexes(table))


def _has_unique(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    name: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(uq.get("name") == name for uq in inspector.get_unique_constraints(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)

    if not _has_table(inspector, _TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", guid_type, primary_key=True),
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
                guid_type,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("scope_kind", sa.String(50), nullable=False),
            sa.Column("scope_path", sa.String(500), nullable=True),
            sa.Column(
                "user_id",
                guid_type,
                sa.ForeignKey("oe_users_user.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "role",
                sa.String(20),
                nullable=False,
                server_default="viewer",
            ),
            sa.Column(
                "granted_by",
                guid_type,
                sa.ForeignKey("oe_users_user.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "granted_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "revoked",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0") if is_sqlite else sa.text("false"),
            ),
            sa.UniqueConstraint(
                "project_id",
                "scope_kind",
                "scope_path",
                "user_id",
                name=_UNIQUE_NAME,
            ),
        )

    # Inspector cache stale after CREATE TABLE.
    inspector = sa.inspect(bind)
    for name, cols, unique in _INDEXES:
        if not _has_index(inspector, _TABLE, name):
            op.create_index(name, _TABLE, list(cols), unique=unique)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        return

    for name, _cols, _unique in _INDEXES:
        if _has_index(inspector, _TABLE, name):
            op.drop_index(name, table_name=_TABLE)

    op.drop_table(_TABLE)

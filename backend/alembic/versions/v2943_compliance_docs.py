# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""compliance_docs — project-scoped expiry tracker for insurance / permits / bonds.

Adds ``oe_compliance_docs_doc`` so general contractors and subs can
track expiring policies / permits / bonds / certifications and surface
them on a dashboard widget before they lapse.

Idempotent — re-applying on a DB where ``Base.metadata.create_all`` has
already created the table is a no-op.

Revision ID: v2943_compliance_docs
Revises: v2942_folder_permissions
Create Date: 2026-05-12
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v2943_compliance_docs"
down_revision: Union[str, Sequence[str], None] = "v2942_folder_permissions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_compliance_docs_doc"

_INDEXES: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    # (name, cols, unique)
    ("ix_oe_compliance_docs_doc_project_id", ("project_id",), False),
    ("ix_oe_compliance_docs_doc_expires_at", ("expires_at",), False),
    ("ix_oe_compliance_docs_doc_status", ("status",), False),
    ("ix_oe_compliance_docs_doc_doc_type", ("doc_type",), False),
)


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


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    # Mirror the GUID() TypeDecorator behaviour: VARCHAR(36) on SQLite,
    # native UUID on PostgreSQL.
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
            sa.Column("doc_type", sa.String(64), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("issuer", sa.String(255), nullable=True),
            sa.Column("policy_number", sa.String(100), nullable=True),
            sa.Column("coverage_amount", sa.Numeric(15, 2), nullable=True),
            sa.Column(
                "currency",
                sa.String(3),
                nullable=False,
                server_default="",
            ),
            sa.Column("effective_date", sa.Date(), nullable=False),
            sa.Column("expires_at", sa.Date(), nullable=False),
            sa.Column(
                "notify_days_before",
                sa.Integer(),
                nullable=False,
                server_default="30",
            ),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="active",
            ),
            sa.Column(
                "attachment_document_id",
                guid_type,
                sa.ForeignKey(
                    "oe_documents_document.id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            ),
            sa.Column(
                "notes",
                sa.Text(),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column("created_by", sa.String(36), nullable=True),
        )

    # Inspector cache is stale after CREATE TABLE.
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

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""propdev: tenant-uploaded document templates.

Adds ``oe_property_dev_custom_template`` so each project can upload
its own .docx / .html / .pdf template alongside the six built-in
generators shipped in ``document_templates.py``. The settings page
lists built-ins + uploaded entries side-by-side; the upload form sits
above the catalogue grid.

Storage:
    The actual template file is written to ``uploads/property_dev/
    custom_templates/<id>_<basename>`` by the upload endpoint; the
    row only carries metadata (display name, target entity / doc_type
    / trigger, content_type, size, optional notes).

Scoping:
    ``project_id`` is the owning project (development sits under a
    project — same scoping rule as every other property_dev row).
    Cross-project enumeration is blocked by RBAC + the
    ``project_id`` filter.

Why not push everything into MinIO?
    The same reason snag photos / handover docs land on the local
    filesystem (see ``_SNAG_PHOTOS_DIR`` in router.py) — MinIO is
    optional in dev / VPS deployments. The path is stable, so a
    future move to S3 just swaps the writer.

Revision ID: v3116_propdev_custom_templates
Revises: v3115_propdev_development_extra_fields
Create Date: 2026-05-23
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3116_propdev_custom_templates"
down_revision: Union[str, Sequence[str], None] = "v3115_propdev_development_extra_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE_NAME = "oe_property_dev_custom_template"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table(_TABLE_NAME):
        op.create_table(
            _TABLE_NAME,
            sa.Column("id", sa.CHAR(36), primary_key=True, nullable=False),
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
            sa.Column(
                "project_id",
                sa.CHAR(36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "development_id",
                sa.CHAR(36),
                nullable=True,
            ),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column(
                "doc_type",
                sa.String(length=40),
                nullable=False,
                server_default="custom",
            ),
            sa.Column(
                "entity",
                sa.String(length=40),
                nullable=False,
                server_default="custom",
            ),
            sa.Column(
                "trigger",
                sa.String(length=200),
                nullable=False,
                server_default="manual",
            ),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("filename", sa.String(length=255), nullable=False),
            sa.Column("storage_path", sa.String(length=512), nullable=False),
            sa.Column("content_type", sa.String(length=120), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", sa.CHAR(36), nullable=True),
        )

    # Refresh inspector after create_table.
    inspector = sa.inspect(bind)
    existing_indexes = {idx["name"] for idx in inspector.get_indexes(_TABLE_NAME)}

    def _ensure_index(name: str, cols: list[str]) -> None:
        if name not in existing_indexes:
            op.create_index(name, _TABLE_NAME, cols)

    _ensure_index("ix_oe_property_dev_custom_template_project_id", ["project_id"])
    _ensure_index("ix_oe_property_dev_custom_template_development_id", ["development_id"])
    _ensure_index("ix_oe_property_dev_custom_template_doc_type", ["doc_type"])
    _ensure_index("ix_oe_property_dev_custom_template_created_by", ["created_by"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table(_TABLE_NAME):
        op.drop_table(_TABLE_NAME)

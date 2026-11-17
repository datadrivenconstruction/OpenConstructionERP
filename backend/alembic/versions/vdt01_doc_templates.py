# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""doc_templates - firm wording of documents and emails, with versions.

Two new tables: ``oe_doc_templates_template`` (model ``DocTemplate``: kind,
scope, locale, draft, published version pointer) and
``oe_doc_templates_version`` (model ``DocTemplateVersion``: immutable
published texts).

This one does NOT need running by hand. It adds tables and nothing else, and
``Base.metadata.create_all`` creates them on a running install from the
models. Inspector-guarded, so a re-run or a downgrade on a database without
the tables changes nothing.

Revision ID: vdt01_doc_templates
Revises: vea01_estimate_archive
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "vdt01_doc_templates"
down_revision: Union[str, Sequence[str], None] = "vea01_estimate_archive"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TEMPLATE = "oe_doc_templates_template"
_VERSION = "oe_doc_templates_version"
_GUID = sa.String(36)


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("id", _GUID, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
    ]


def upgrade() -> None:
    """Create the template and version tables."""
    existing = _tables()
    if _TEMPLATE not in existing:
        op.create_table(
            _TEMPLATE,
            *_stamps(),
            sa.Column("kind", sa.String(120), nullable=False),
            sa.Column("channel", sa.String(10), nullable=False, server_default="pdf"),
            sa.Column("scope", sa.String(60), nullable=False, server_default="workspace"),
            sa.Column("locale", sa.String(10), nullable=False),
            sa.Column("draft_blocks", sa.JSON(), nullable=True),
            sa.Column("draft_options", sa.JSON(), nullable=True),
            sa.Column("draft_updated_by", sa.String(36), nullable=True),
            sa.Column("draft_updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("published_version_id", _GUID, nullable=True),
            sa.PrimaryKeyConstraint("id", name=f"pk_{_TEMPLATE}"),
            sa.UniqueConstraint("kind", "scope", "locale", name="uq_doc_templates_template_kind_scope_locale"),
        )
        op.create_index(f"ix_{_TEMPLATE}_kind", _TEMPLATE, ["kind"])
    if _VERSION not in existing:
        op.create_table(
            _VERSION,
            *_stamps(),
            sa.Column("template_id", _GUID, nullable=False),
            sa.Column("number", sa.Integer(), nullable=False),
            sa.Column("blocks", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("options", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("letterhead", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("action", sa.String(20), nullable=False, server_default="publish"),
            sa.Column("note", sa.String(500), nullable=False, server_default=""),
            sa.Column("author_id", sa.String(36), nullable=True),
            sa.Column("author_name", sa.String(255), nullable=False, server_default=""),
            sa.PrimaryKeyConstraint("id", name=f"pk_{_VERSION}"),
            sa.ForeignKeyConstraint(
                ["template_id"],
                [f"{_TEMPLATE}.id"],
                name=f"fk_{_VERSION}_template_id_{_TEMPLATE}",
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint("template_id", "number", name="uq_doc_templates_version_template_number"),
        )
        op.create_index(f"ix_{_VERSION}_template_id", _VERSION, ["template_id"])


def downgrade() -> None:
    """Drop both tables."""
    existing = _tables()
    if _VERSION in existing:
        op.drop_index(f"ix_{_VERSION}_template_id", table_name=_VERSION)
        op.drop_table(_VERSION)
    if _TEMPLATE in existing:
        op.drop_index(f"ix_{_TEMPLATE}_kind", table_name=_TEMPLATE)
        op.drop_table(_TEMPLATE)

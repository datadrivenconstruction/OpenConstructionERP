# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""doc_templates - log of issued documents and the template version each printed.

One new table, ``oe_doc_templates_issue`` (model ``DocTemplateIssue``).

This one does NOT need running by hand. It adds a table and nothing else, and
``Base.metadata.create_all`` creates it on a running install from the model.
Inspector-guarded, so a re-run or a downgrade without the table changes nothing.

Revision ID: vdt02_doc_template_issues
Revises: vdt01_doc_templates
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "vdt02_doc_template_issues"
down_revision: Union[str, Sequence[str], None] = "vdt01_doc_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ISSUE = "oe_doc_templates_issue"
_GUID = sa.String(36)


def upgrade() -> None:
    """Create the issue log."""
    if _ISSUE in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        _ISSUE,
        sa.Column("id", _GUID, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column("kind", sa.String(120), nullable=False),
        sa.Column("record_id", sa.String(64), nullable=False),
        sa.Column("project_id", _GUID, nullable=True),
        sa.Column("locale", sa.String(10), nullable=False),
        sa.Column("text_locale", sa.String(10), nullable=False, server_default="en"),
        sa.Column("source", sa.String(20), nullable=False, server_default="default"),
        sa.Column("template_version_id", _GUID, nullable=True),
        sa.Column("issued_by", sa.String(36), nullable=True),
        sa.PrimaryKeyConstraint("id", name=f"pk_{_ISSUE}"),
    )
    op.create_index(f"ix_{_ISSUE}_kind", _ISSUE, ["kind"])
    op.create_index(f"ix_{_ISSUE}_record_id", _ISSUE, ["record_id"])


def downgrade() -> None:
    """Drop the issue log."""
    if _ISSUE not in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.drop_index(f"ix_{_ISSUE}_record_id", table_name=_ISSUE)
    op.drop_index(f"ix_{_ISSUE}_kind", table_name=_ISSUE)
    op.drop_table(_ISSUE)

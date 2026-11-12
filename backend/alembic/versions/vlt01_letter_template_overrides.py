# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""letter_templates - company and project wording of generated letters.

One new table, ``oe_letter_templates_override`` (model
``LetterTemplateOverride``): a changed text of one registered letter in one
language, for the whole company (``project_id`` NULL) or one project.

This one does NOT need running by hand. It adds a table and nothing else, and
``Base.metadata.create_all`` creates it on a running install from the model.
The revision exists so a database walked with ``alembic upgrade head`` ends up
with the same table and index names the metadata naming convention produces.
Inspector-guarded, so a re-run or a downgrade on a database without the table
changes nothing.

Revision ID: vlt01_letter_template_overrides
Revises: vpf01_project_folder_url
Create Date: 2026-11-12
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "vlt01_letter_template_overrides"
down_revision: Union[str, Sequence[str], None] = "vpf01_project_folder_url"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_letter_templates_override"
_GUID = sa.String(36)


def _exists() -> bool:
    return _TABLE in set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    """Create the override table with its foreign key and indexes."""
    if _exists():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", _GUID, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column("template_key", sa.String(100), nullable=False),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("project_id", _GUID, nullable=True),
        sa.Column("subject", sa.String(500), nullable=False, server_default=""),
        sa.Column("heading", sa.String(500), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("closing", sa.String(500), nullable=False, server_default=""),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.PrimaryKeyConstraint("id", name=f"pk_{_TABLE}"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["oe_projects_project.id"],
            name=f"fk_{_TABLE}_project_id_oe_projects_project",
            ondelete="CASCADE",
        ),
    )
    op.create_index(f"ix_{_TABLE}_project_id", _TABLE, ["project_id"])
    op.create_index("ix_letter_template_override_lookup", _TABLE, ["template_key", "language", "project_id"])


def downgrade() -> None:
    """Drop the override table."""
    if not _exists():
        return
    op.drop_index("ix_letter_template_override_lookup", table_name=_TABLE)
    op.drop_index(f"ix_{_TABLE}_project_id", table_name=_TABLE)
    op.drop_table(_TABLE)

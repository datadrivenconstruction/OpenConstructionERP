# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""survey plan editor: edit history, code library, plan conventions

Additive new tables only, so a deploy that heals its schema at boot picks them
up without ``alembic upgrade``.

Revision ID: vsrv03_survey_plan_editor
Revises: cpb01_central_purchasing_bundles
Create Date: 2026-11-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vsrv03_survey_plan_editor"
down_revision: str | Sequence[str] | None = "cpb01_central_purchasing_bundles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EDIT = "oe_survey_edit"
_CODES = "oe_survey_code_library"
_SETTINGS = "oe_survey_plan_settings"


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def _project_fk() -> sa.Column:
    return sa.Column(
        "project_id", sa.String(36), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if _EDIT not in existing:
        op.create_table(
            _EDIT,
            *_base(),
            _project_fk(),
            sa.Column("entity_type", sa.String(32), nullable=False),
            sa.Column("entity_id", sa.String(64), nullable=False),
            sa.Column("rev", sa.Integer(), nullable=False),
            sa.Column("op", sa.String(16), nullable=False),
            sa.Column("before", sa.JSON(), nullable=True),
            sa.Column("after", sa.JSON(), nullable=True),
            sa.Column("author", sa.String(36), nullable=True),
            sa.Column("author_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
        )
        op.create_index("ix_oe_survey_edit_entity", _EDIT, ["project_id", "entity_type", "entity_id", "rev"])
        op.create_index("ix_oe_survey_edit_project_time", _EDIT, ["project_id", "created_at"])
    if _CODES not in existing:
        op.create_table(
            _CODES,
            *_base(),
            _project_fk(),
            sa.Column("codes", sa.JSON(), nullable=False),
            sa.Column("updated_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("project_id", name="uq_oe_survey_code_library_project"),
        )
    if _SETTINGS not in existing:
        op.create_table(
            _SETTINGS,
            *_base(),
            _project_fk(),
            sa.Column("conventions", sa.JSON(), nullable=False),
            sa.Column("updated_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("project_id", name="uq_oe_survey_plan_settings_project"),
        )


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in (_SETTINGS, _CODES, _EDIT):
        if table in existing:
            op.drop_table(table)

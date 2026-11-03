# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""doc assistant answers and the project agent catalogue

Creates ``oe_doc_assistant_answer`` (answers kept as notes or RFI drafts, with
their citations), ``oe_ai_agents_project_setting`` (catalogue agent enabled and
configured per project), ``oe_ai_agents_project_guard`` (per-project kill
switch) and ``oe_ai_agents_draft`` (drafts produced by catalogue agents).

Revision ID: vai01_doc_assistant_agent_catalogue
Revises: vcc01_change_chain_award
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vai01_doc_assistant_agent_catalogue"
down_revision: str | Sequence[str] | None = "vcc01_change_chain_award"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ANSWER = "oe_doc_assistant_answer"
_SETTING = "oe_ai_agents_project_setting"
_GUARD = "oe_ai_agents_project_guard"
_DRAFT = "oe_ai_agents_draft"


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def _project_fk() -> sa.Column:
    return sa.Column(
        "project_id", sa.String(36), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _ANSWER not in tables:
        op.create_table(
            _ANSWER,
            *_base(),
            _project_fk(),
            sa.Column("user_id", sa.String(36), nullable=False),
            sa.Column("question", sa.Text(), nullable=False),
            sa.Column("answer", sa.Text(), nullable=False, server_default=""),
            sa.Column("claims", sa.JSON(), nullable=False),
            sa.Column("citations", sa.JSON(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
            sa.Column("locale", sa.String(12), nullable=False, server_default="en"),
            sa.Column("target_kind", sa.String(20), nullable=False, server_default="note"),
            sa.Column("target_id", sa.String(36), nullable=True),
            sa.Column("validation", sa.JSON(), nullable=False),
        )
        op.create_index(f"ix_{_ANSWER}_project_id", _ANSWER, ["project_id"])
        op.create_index(f"ix_{_ANSWER}_user_id", _ANSWER, ["user_id"])
    if _SETTING not in tables:
        op.create_table(
            _SETTING,
            *_base(),
            _project_fk(),
            sa.Column("agent_name", sa.String(100), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("config", sa.JSON(), nullable=False),
            sa.Column("max_tokens_per_run", sa.Integer(), nullable=False, server_default="8000"),
            sa.Column("updated_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("project_id", "agent_name", name="uq_ai_agents_project_setting"),
        )
        op.create_index(f"ix_{_SETTING}_project_id", _SETTING, ["project_id"])
    if _GUARD not in tables:
        op.create_table(
            _GUARD,
            *_base(),
            _project_fk(),
            sa.Column("halted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("reason", sa.String(500), nullable=False, server_default=""),
            sa.Column("set_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("project_id", name="uq_oe_ai_agents_project_guard_project_id"),
        )
    if _DRAFT not in tables:
        op.create_table(
            _DRAFT,
            *_base(),
            _project_fk(),
            sa.Column("run_id", sa.String(36), nullable=True),
            sa.Column("agent_name", sa.String(100), nullable=False),
            sa.Column("draft_kind", sa.String(40), nullable=False),
            sa.Column("title", sa.String(500), nullable=False, server_default=""),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
            sa.Column("sources", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("created_by", sa.String(36), nullable=False),
            sa.Column("reviewed_by", sa.String(36), nullable=True),
            sa.Column("reviewed_at", sa.String(40), nullable=True),
            sa.Column("review_note", sa.Text(), nullable=True),
            sa.Column("applied_record_id", sa.String(36), nullable=True),
        )
        for col in ("project_id", "run_id", "agent_name", "status"):
            op.create_index(f"ix_{_DRAFT}_{col}", _DRAFT, [col])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in (_DRAFT, _GUARD, _SETTING, _ANSWER):
        if table in tables:
            op.drop_table(table)

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project setup-wizard — profile + per-project module assignment tables.

Slice 1 of the project-creation wizard (concept doc §6.1 / §6.4). Adds:

* ``oe_project_profile`` — one row per project. The applied wizard
  answers (preset + 5 scoring axes + region/language) plus the
  ``focus_mode_enabled`` master switch the sidebar reads. Presentation
  -only: it never unloads a module or blocks an API.

* ``oe_project_module`` — the resolved module set for a project
  (must / recommended / optional / hidden, with a global ``ordinal``
  for the numbered route line). Replaced wholesale when the profile
  is (re)applied — the table is tiny (≤88 rows/project).

* ``oe_project_wizard_draft`` — transient half-finished wizard state,
  kept separate so an abandoned setup never creates a real project.

Idempotent: guarded by an inspector so re-running after SQLite's
``Base.metadata.create_all`` (dev) is a no-op; Postgres prod gets the
DDL. Mirrors ``app/modules/projects/models.py`` exactly.

Revision ID: v3035_project_profile
Revises: v3034_match_pipeline_stages
Created: 2026-05-15
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3035_project_profile"
down_revision: Union[str, Sequence[str], None] = "v3034_match_pipeline_stages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _base_cols() -> list[sa.Column]:
    """id / created_at / updated_at — the shared Base mixin columns."""
    return [
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── 1. oe_project_profile ────────────────────────────────────────
    if not _has_table(inspector, "oe_project_profile"):
        op.create_table(
            "oe_project_profile",
            *_base_cols(),
            sa.Column(
                "project_id",
                sa.String(length=36),
                sa.ForeignKey(
                    "oe_projects_project.id", ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "preset",
                sa.String(length=64),
                nullable=False,
                server_default="custom",
            ),
            sa.Column(
                "activity", sa.JSON(), nullable=False, server_default="[]",
            ),
            sa.Column(
                "phases", sa.JSON(), nullable=False, server_default="[]",
            ),
            sa.Column("role", sa.String(length=48), nullable=True),
            sa.Column("size", sa.String(length=24), nullable=True),
            sa.Column("region", sa.String(length=32), nullable=True),
            sa.Column("language", sa.String(length=8), nullable=True),
            sa.Column(
                "extensions_enabled",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "focus_mode_enabled",
                sa.Boolean(),
                nullable=False,
                server_default="1",
            ),
            sa.Column(
                "setup_completion",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column("created_by", sa.String(length=36), nullable=True),
            sa.Column(
                "metadata", sa.JSON(), nullable=False, server_default="{}",
            ),
            sa.UniqueConstraint(
                "project_id", name="uq_project_profile_project",
            ),
        )
        op.create_index(
            "ix_project_profile_project",
            "oe_project_profile",
            ["project_id"],
        )
        op.create_index(
            "ix_oe_project_profile_project_id",
            "oe_project_profile",
            ["project_id"],
        )

    # ── 2. oe_project_module ─────────────────────────────────────────
    # ``ProjectModule`` redeclares ``updated_at`` so the model column
    # OVERRIDES Base's (nullable, no server_default / onupdate — it
    # records when the assignment row itself last changed). id +
    # created_at stay as Base.
    if not _has_table(inspector, "oe_project_module"):
        op.create_table(
            "oe_project_module",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "project_id",
                sa.String(length=36),
                sa.ForeignKey(
                    "oe_projects_project.id", ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("module_name", sa.String(length=64), nullable=False),
            sa.Column(
                "enabled",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "tier",
                sa.String(length=16),
                nullable=False,
                server_default="hidden",
            ),
            sa.Column(
                "score", sa.Integer(), nullable=False, server_default="0",
            ),
            sa.Column(
                "phase",
                sa.String(length=24),
                nullable=False,
                server_default="construction",
            ),
            sa.Column(
                "source",
                sa.String(length=16),
                nullable=False,
                server_default="score",
            ),
            sa.Column("ordinal", sa.Integer(), nullable=True),
            sa.Column("why", sa.String(length=255), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.UniqueConstraint(
                "project_id",
                "module_name",
                name="uq_project_module_unique",
            ),
        )
        op.create_index(
            "ix_project_module_project",
            "oe_project_module",
            ["project_id"],
        )
        op.create_index(
            "ix_project_module_project_enabled",
            "oe_project_module",
            ["project_id", "enabled"],
        )
        op.create_index(
            "ix_oe_project_module_project_id",
            "oe_project_module",
            ["project_id"],
        )

    # ── 3. oe_project_wizard_draft ───────────────────────────────────
    if not _has_table(inspector, "oe_project_wizard_draft"):
        op.create_table(
            "oe_project_wizard_draft",
            *_base_cols(),
            sa.Column(
                "payload", sa.JSON(), nullable=False, server_default="{}",
            ),
            sa.Column("created_by", sa.String(length=36), nullable=True),
        )
        op.create_index(
            "ix_project_wizard_draft_owner",
            "oe_project_wizard_draft",
            ["created_by"],
        )
        op.create_index(
            "ix_project_wizard_draft_created",
            "oe_project_wizard_draft",
            ["created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for tbl in (
        "oe_project_wizard_draft",
        "oe_project_module",
        "oe_project_profile",
    ):
        if _has_table(inspector, tbl):
            op.drop_table(tbl)

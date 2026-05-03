"""v2.8.1 — per-project match settings table.

Adds the ``oe_projects_match_settings`` table that captures the user's
choices for the BIM/PDF/DWG/photo → CWICR auto-match pipeline:
target catalog language, classifier, auto-link threshold/toggle,
manual-vs-auto mode, and the enabled set of sources.

One row per project (unique FK to ``oe_projects_project``) with
``ON DELETE CASCADE`` — when a project is hard-deleted its match
settings go with it. Existing projects (pre-v2.8.0) acquire a default
row lazily on first GET; the migration intentionally does NOT
backfill rows so the table stays empty until a project actually
needs settings.

Inspector-guarded so re-running the migration on an already-migrated
DB is a no-op (matches the v260c / v280_translation_cache pattern).

Revision ID: v281_match_project_settings
Revises: v280_translation_cache
Create Date: 2026-05-03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v281_match_project_settings"
down_revision: Union[str, Sequence[str], None] = "v280_translation_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_projects_match_settings"
_PROJECT_TABLE = "oe_projects_project"
_UQ = "uq_oe_projects_match_settings_project_id"
_IX = "ix_oe_projects_match_settings_project_id"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, _TABLE):
        return

    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=36),
            sa.ForeignKey(
                f"{_PROJECT_TABLE}.id",
                ondelete="CASCADE",
                name="fk_oe_projects_match_settings_project_id_oe_projects_project",
            ),
            nullable=False,
        ),
        sa.Column(
            "target_language",
            sa.String(length=8),
            nullable=False,
            server_default="en",
        ),
        sa.Column(
            "classifier",
            sa.String(length=32),
            nullable=False,
            server_default="none",
        ),
        sa.Column(
            "auto_link_threshold",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.85"),
        ),
        sa.Column(
            "auto_link_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "mode",
            sa.String(length=16),
            nullable=False,
            server_default="manual",
        ),
        sa.Column(
            "sources_enabled",
            sa.JSON(),
            nullable=False,
            server_default='["bim", "pdf", "dwg", "photo"]',
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("project_id", name=_UQ),
    )
    op.create_index(_IX, _TABLE, ["project_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        return

    existing_ix = {ix["name"] for ix in inspector.get_indexes(_TABLE)}
    if _IX in existing_ix:
        op.drop_index(_IX, table_name=_TABLE)
    op.drop_table(_TABLE)

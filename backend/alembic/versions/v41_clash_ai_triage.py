# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Clash AI Triage — persisted LLM verdicts with confidence scores.

Adds one strictly-additive table:

* ``oe_clash_triage_result`` — one row per LLM verdict produced for a
  clash subject (``ClashResult`` or, when available, ``ClashIssue``).
  Carries the full prompt + raw response for audit, a USD cost
  estimate, the structured verdict (category, confidence, severity
  suggestion, explanation, suggested action) and the provenance
  triple (model_name, prompt_version, created_by_user_id).

Idempotent — inspector-guarded so re-runs on a partially-migrated DB
skip the create. SQLite-safe (``GUID()`` impls as ``VARCHAR(36)``;
``JSON`` columns persist as TEXT). The CHECK constraint pins the
confidence to ``[0, 1]`` on Postgres + SQLite (3.37+).

Revision ID: v41_clash_ai_triage
Revises: v41_smart_views
Create Date: 2026-05-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v41_clash_ai_triage"
# Chain off the current single-tip head so ``alembic upgrade head`` stays
# linear. This migration does NOT touch any clash module table — it adds
# a self-contained sibling table.
down_revision: Union[str, Sequence[str], None] = "v41_smart_views"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_clash_triage_result"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _existing_index_names(
    inspector: sa.engine.reflection.Inspector,
    table: str,
) -> set[str]:
    if not _has_table(inspector, table):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    """Create ``oe_clash_triage_result`` (idempotent)."""
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)
    inspector = sa.inspect(bind)

    if _has_table(inspector, _TABLE):
        return

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
            "subject_type",
            sa.String(16),
            nullable=False,
            server_default="clash",
        ),
        sa.Column("subject_id", guid_type, nullable=False),
        sa.Column("clash_id", guid_type, nullable=True),
        sa.Column("model_name", sa.String(128), nullable=False, server_default=""),
        sa.Column(
            "prompt_version",
            sa.String(16),
            nullable=False,
            server_default="v1.0",
        ),
        sa.Column("category", sa.String(32), nullable=False, server_default="unclear"),
        sa.Column(
            "confidence",
            sa.Float(),
            nullable=False,
            server_default="0.0",
        ),
        sa.Column(
            "severity_suggested",
            sa.String(16),
            nullable=False,
            server_default="medium",
        ),
        sa.Column("explanation", sa.Text(), nullable=False, server_default=""),
        sa.Column("suggested_action", sa.String(48), nullable=True),
        sa.Column(
            "model_evidence_used",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("raw_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("raw_response", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "tokens_used",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "cost_usd_estimate",
            sa.Numeric(10, 4),
            nullable=False,
            server_default="0.0",
        ),
        sa.Column("created_by_user_id", guid_type, nullable=True),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_clash_triage_confidence_range",
        ),
    )

    existing_ix = _existing_index_names(inspector, _TABLE)
    for ix_name, cols in (
        ("ix_clash_triage_result_subject_id", ["subject_id"]),
        ("ix_clash_triage_result_clash_id", ["clash_id"]),
        (
            "ix_clash_triage_subject_prompt_model",
            ["subject_id", "prompt_version", "model_name"],
        ),
        ("ix_clash_triage_subject_created", ["subject_id", "created_at"]),
    ):
        if ix_name not in existing_ix:
            try:
                op.create_index(ix_name, _TABLE, cols)
            except sa.exc.OperationalError:
                pass


def downgrade() -> None:
    """Drop ``oe_clash_triage_result`` and its indexes."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return
    existing_ix = _existing_index_names(inspector, _TABLE)
    for ix in (
        "ix_clash_triage_result_subject_id",
        "ix_clash_triage_result_clash_id",
        "ix_clash_triage_subject_prompt_model",
        "ix_clash_triage_subject_created",
    ):
        if ix in existing_ix:
            try:
                op.drop_index(ix, table_name=_TABLE)
            except sa.exc.OperationalError:
                pass
    op.drop_table(_TABLE)

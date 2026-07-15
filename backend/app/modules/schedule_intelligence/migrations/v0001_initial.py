# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Schedule Intelligence initial schema — governance + insight tables.

Creates the six ``oe_schedule_intelligence_*`` tables:
    confidence_config, locked_figure, readiness_result,
    risk_score, risk_factor, decision.

Idempotent and inspector-guarded so a re-run on a partially-migrated DB is
safe. SQLite-friendly (``GUID()`` ⇒ ``VARCHAR(36)``).

────────────────────────────────────────────────────────────────────────────
⚠️  THIS FILE IS INERT UNTIL MOVED + CHAINED (deps-enabled env required)
────────────────────────────────────────────────────────────────────────────
Alembic only runs files under ``backend/alembic/versions/``; this copy under
the module is a reviewable draft. The Alembic graph currently has many open
heads, so ``down_revision`` MUST NOT be hand-picked blind. In a deps-enabled
env (Docker/venv) do ONE of:

  A) Autogenerate (preferred — models are the source of truth):
       cd backend && make migrate-new MSG="schedule_intelligence initial"
     then delete this draft file.

  B) Adopt this hand-authored DDL:
       cd backend && alembic heads        # pick the current head
       mv app/modules/schedule_intelligence/migrations/v0001_initial.py \
          alembic/versions/vNNNN_schedule_intelligence.py
     then set ``down_revision`` below to that head and run ``make migrate``.

Note: because these models are imported in ``alembic/env.py``, boot-time
``metadata.create_all`` already materialises the tables in dev even before this
migration is chained — so the app is loadable now; this migration is for
production upgrade integrity.

Revision ID: oe_schedule_intelligence_v0001_initial
Revises: <FILL_IN_CURRENT_HEAD>
Create Date: 2026-07-15
"""

from __future__ import annotations

from typing import Any, Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "oe_schedule_intelligence_v0001_initial"
down_revision: Union[str, Sequence[str], None] = None  # set to current head!
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PREFIX = "oe_schedule_intelligence_"
_CONFIDENCE_CONFIG = f"{_PREFIX}confidence_config"
_LOCKED_FIGURE = f"{_PREFIX}locked_figure"
_READINESS = f"{_PREFIX}readiness_result"
_RISK_SCORE = f"{_PREFIX}risk_score"
_RISK_FACTOR = f"{_PREFIX}risk_factor"
_DECISION = f"{_PREFIX}decision"

# Ordered for create (parents first) — locked_figure before decision (FK),
# risk_score before risk_factor (FK). Reverse for drop.
_ALL_TABLES = (
    _CONFIDENCE_CONFIG,
    _LOCKED_FIGURE,
    _READINESS,
    _RISK_SCORE,
    _RISK_FACTOR,
    _DECISION,
)


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _guid(is_sqlite: bool) -> Any:
    return sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)


def _timestamps() -> list[sa.Column[Any]]:
    return [
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
    ]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    guid = _guid(is_sqlite)

    # ── confidence_config (E5.3) ─────────────────────────────────────────
    if not _has_table(inspector, _CONFIDENCE_CONFIG):
        op.create_table(
            _CONFIDENCE_CONFIG,
            sa.Column("id", guid, primary_key=True),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("band_thresholds", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("schedule_quality_caps", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("feed_coverage_caps", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("corroboration_bonuses", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column(
                "created_by",
                guid,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            *_timestamps(),
            sa.UniqueConstraint(
                "project_id",
                "version",
                name="uq_sched_intel_confidence_config_project_version",
            ),
        )
        op.create_index(f"ix_{_CONFIDENCE_CONFIG}_project_id", _CONFIDENCE_CONFIG, ["project_id"])
        op.create_index(f"ix_{_CONFIDENCE_CONFIG}_active", _CONFIDENCE_CONFIG, ["active"])

    # ── locked_figure (E5.2) ─────────────────────────────────────────────
    if not _has_table(inspector, _LOCKED_FIGURE):
        op.create_table(
            _LOCKED_FIGURE,
            sa.Column("id", guid, primary_key=True),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("path", sa.String(255), nullable=False),
            sa.Column("figure_type", sa.String(50), nullable=False),
            sa.Column("value", sa.String(255), nullable=False),
            sa.Column("value_hash", sa.String(64), nullable=False),
            sa.Column("source_ref", sa.String(64), nullable=True),
            sa.Column("reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column(
                "locked_by",
                guid,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("locked_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "unlocked_by",
                guid,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("unlocked_at", sa.DateTime(timezone=True), nullable=True),
            *_timestamps(),
            sa.UniqueConstraint(
                "project_id",
                "path",
                name="uq_sched_intel_locked_figure_project_path",
            ),
        )
        op.create_index(f"ix_{_LOCKED_FIGURE}_project_id", _LOCKED_FIGURE, ["project_id"])
        op.create_index(f"ix_{_LOCKED_FIGURE}_path", _LOCKED_FIGURE, ["path"])
        op.create_index(f"ix_{_LOCKED_FIGURE}_figure_type", _LOCKED_FIGURE, ["figure_type"])
        op.create_index(f"ix_{_LOCKED_FIGURE}_active", _LOCKED_FIGURE, ["active"])

    # ── readiness_result (E1) ────────────────────────────────────────────
    if not _has_table(inspector, _READINESS):
        op.create_table(
            _READINESS,
            sa.Column("id", guid, primary_key=True),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("activity_ref", sa.String(64), nullable=False),
            sa.Column("look_ahead_ref", sa.String(64), nullable=True),
            sa.Column("classification", sa.String(20), nullable=False),
            sa.Column("binding_constraint_ref", sa.String(64), nullable=True),
            sa.Column("need_by_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("planned_start_date", sa.DateTime(timezone=True), nullable=True),
            sa.Column("total_float_days", sa.Integer(), nullable=True),
            sa.Column("float_burn_days", sa.Integer(), nullable=True),
            sa.Column("drivers", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("confidence_score", sa.Numeric(6, 4), nullable=True),
            sa.Column("confidence_band", sa.String(20), nullable=True),
            sa.Column("confidence_rationale", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("evaluation_run_id", sa.String(64), nullable=True),
            *_timestamps(),
        )
        op.create_index(f"ix_{_READINESS}_project_id", _READINESS, ["project_id"])
        op.create_index(f"ix_{_READINESS}_activity_ref", _READINESS, ["activity_ref"])
        op.create_index(f"ix_{_READINESS}_classification", _READINESS, ["classification"])

    # ── risk_score (E2) ──────────────────────────────────────────────────
    if not _has_table(inspector, _RISK_SCORE):
        op.create_table(
            _RISK_SCORE,
            sa.Column("id", guid, primary_key=True),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("activity_ref", sa.String(64), nullable=False),
            sa.Column("score", sa.Numeric(6, 4), nullable=False),
            sa.Column("band", sa.String(20), nullable=False),
            sa.Column("scorer_version", sa.String(32), nullable=False, server_default="v0"),
            sa.Column("first_flagged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("config_version", sa.Integer(), nullable=True),
            sa.Column("confidence_score", sa.Numeric(6, 4), nullable=True),
            sa.Column("confidence_band", sa.String(20), nullable=True),
            sa.Column("confidence_rationale", sa.JSON(), nullable=False, server_default="[]"),
            *_timestamps(),
        )
        op.create_index(f"ix_{_RISK_SCORE}_project_id", _RISK_SCORE, ["project_id"])
        op.create_index(f"ix_{_RISK_SCORE}_activity_ref", _RISK_SCORE, ["activity_ref"])
        op.create_index(f"ix_{_RISK_SCORE}_band", _RISK_SCORE, ["band"])

    # ── risk_factor (E2 decomposition) ───────────────────────────────────
    if not _has_table(inspector, _RISK_FACTOR):
        op.create_table(
            _RISK_FACTOR,
            sa.Column("id", guid, primary_key=True),
            sa.Column(
                "risk_score_id",
                guid,
                sa.ForeignKey(f"{_RISK_SCORE}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("factor_key", sa.String(50), nullable=False),
            sa.Column("weight", sa.Numeric(6, 4), nullable=False),
            sa.Column("raw_value", sa.Numeric(12, 4), nullable=False),
            sa.Column("contribution", sa.Numeric(6, 4), nullable=False),
            sa.Column("source_type", sa.String(30), nullable=True),
            sa.Column("source_ref", sa.String(64), nullable=True),
            sa.Column("detail", sa.Text(), nullable=False, server_default=""),
            *_timestamps(),
        )
        op.create_index(f"ix_{_RISK_FACTOR}_risk_score_id", _RISK_FACTOR, ["risk_score_id"])

    # ── decision (E4) ────────────────────────────────────────────────────
    if not _has_table(inspector, _DECISION):
        op.create_table(
            _DECISION,
            sa.Column("id", guid, primary_key=True),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("title", sa.String(255), nullable=False, server_default=""),
            sa.Column("delay_event_ref", sa.String(64), nullable=True),
            sa.Column(
                "impact_locked_figure_id",
                guid,
                sa.ForeignKey(f"{_LOCKED_FIGURE}.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("option_claim", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("option_accelerate", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("recommendation", sa.String(20), nullable=True),
            sa.Column(
                "recommendation_rationale",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("confidence_score", sa.Numeric(6, 4), nullable=True),
            sa.Column("confidence_band", sa.String(20), nullable=True),
            sa.Column("confidence_rationale", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("applied_option", sa.String(20), nullable=True),
            sa.Column(
                "applied_by",
                guid,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
            *_timestamps(),
        )
        op.create_index(f"ix_{_DECISION}_project_id", _DECISION, ["project_id"])
        op.create_index(f"ix_{_DECISION}_status", _DECISION, ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in reversed(_ALL_TABLES):
        if _has_table(inspector, table):
            op.drop_table(table)

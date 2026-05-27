# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""v2.9.32 — Match Elements module: session/group/template tables.

Backs the ``/match-elements`` page that maps BIM/CAD/PDF/photo elements to
CWICR cost positions through interactive group-based matching with
multiple matcher methods (vector + lexical for Phase A; LLM later).

Three tables:
    oe_match_elements_session   — durable session per project + source.
    oe_match_elements_group     — one row per group inside a session.
    oe_match_elements_template  — tenant-scoped cross-project library so
                                  signatures confirmed on Project A
                                  pre-suggest on Project B.

Idempotent — re-running on a partially-applied database is a no-op.

Revision ID: v2932_match_elements
Revises: v2924_costs_active_code_index
Create Date: 2026-05-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v2932_match_elements"
down_revision: Union[str, Sequence[str], None] = "v2924_costs_active_code_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SESSION_TABLE = "oe_match_elements_session"
_GROUP_TABLE = "oe_match_elements_group"
_TEMPLATE_TABLE = "oe_match_elements_template"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    name: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(idx["name"] == name for idx in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── oe_match_elements_session ────────────────────────────────────────
    if not _has_table(inspector, _SESSION_TABLE):
        op.create_table(
            _SESSION_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
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
            sa.Column("project_id", sa.String(length=36), nullable=False),
            sa.Column(
                "source",
                sa.String(length=20),
                nullable=False,
                server_default="bim",
            ),
            sa.Column("name", sa.String(length=255), nullable=True),
            sa.Column(
                "group_by",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "filters",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "excluded_categories",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "auto_confirm_threshold",
                sa.String(length=10),
                nullable=False,
                server_default="0.95",
            ),
            sa.Column(
                "use_net_quantities",
                sa.Boolean(),
                nullable=False,
                server_default="1",
            ),
            sa.Column("catalogue_id", sa.String(length=36), nullable=True),
            sa.Column("created_by", sa.String(length=36), nullable=True),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.ForeignKeyConstraint(
                ["project_id"],
                ["oe_projects_project.id"],
                ondelete="CASCADE",
            ),
        )
    if not _has_index(inspector, _SESSION_TABLE, "ix_match_session_project"):
        op.create_index("ix_match_session_project", _SESSION_TABLE, ["project_id"])
    if not _has_index(inspector, _SESSION_TABLE, "ix_match_session_catalogue"):
        op.create_index("ix_match_session_catalogue", _SESSION_TABLE, ["catalogue_id"])

    # ── oe_match_elements_group ──────────────────────────────────────────
    if not _has_table(inspector, _GROUP_TABLE):
        op.create_table(
            _GROUP_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
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
            sa.Column("session_id", sa.String(length=36), nullable=False),
            sa.Column("group_key", sa.String(length=500), nullable=False),
            sa.Column("signature", sa.String(length=64), nullable=True),
            sa.Column(
                "element_ids",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "element_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "quantities",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column("chosen_unit", sa.String(length=20), nullable=True),
            sa.Column(
                "methods",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "chosen_candidate_id",
                sa.String(length=36),
                nullable=True,
            ),
            sa.Column("chosen_method", sa.String(length=20), nullable=True),
            sa.Column("confidence", sa.String(length=10), nullable=True),
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default="unmatched",
            ),
            sa.Column("boq_position_id", sa.String(length=36), nullable=True),
            sa.Column("signature_fields", sa.JSON(), nullable=True),
            sa.Column("confirmed_by", sa.String(length=36), nullable=True),
            sa.Column(
                "confirmed_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.ForeignKeyConstraint(
                ["session_id"],
                [f"{_SESSION_TABLE}.id"],
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint(
                "session_id",
                "group_key",
                name="uq_match_group_session_key",
            ),
        )
    if not _has_index(inspector, _GROUP_TABLE, "ix_match_group_session"):
        op.create_index("ix_match_group_session", _GROUP_TABLE, ["session_id"])
    if not _has_index(inspector, _GROUP_TABLE, "ix_match_group_session_status"):
        op.create_index(
            "ix_match_group_session_status",
            _GROUP_TABLE,
            ["session_id", "status"],
        )
    if not _has_index(inspector, _GROUP_TABLE, "ix_match_group_signature"):
        op.create_index("ix_match_group_signature", _GROUP_TABLE, ["signature"])
    if not _has_index(inspector, _GROUP_TABLE, "ix_match_group_chosen_candidate"):
        op.create_index(
            "ix_match_group_chosen_candidate",
            _GROUP_TABLE,
            ["chosen_candidate_id"],
        )
    if not _has_index(inspector, _GROUP_TABLE, "ix_match_group_boq_position"):
        op.create_index(
            "ix_match_group_boq_position",
            _GROUP_TABLE,
            ["boq_position_id"],
        )

    # ── oe_match_elements_template ───────────────────────────────────────
    if not _has_table(inspector, _TEMPLATE_TABLE):
        op.create_table(
            _TEMPLATE_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
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
            sa.Column("tenant_id", sa.String(length=36), nullable=True),
            sa.Column("signature", sa.String(length=64), nullable=False),
            sa.Column("label", sa.String(length=500), nullable=True),
            sa.Column(
                "cwicr_position_id",
                sa.String(length=36),
                nullable=False,
            ),
            sa.Column(
                "source_fields",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "use_count",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column(
                "last_used_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column("created_by", sa.String(length=36), nullable=True),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.ForeignKeyConstraint(
                ["cwicr_position_id"],
                ["oe_costs_item.id"],
                ondelete="CASCADE",
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "signature",
                name="uq_match_template_tenant_signature",
            ),
        )
    if not _has_index(inspector, _TEMPLATE_TABLE, "ix_match_template_tenant"):
        op.create_index("ix_match_template_tenant", _TEMPLATE_TABLE, ["tenant_id"])
    if not _has_index(inspector, _TEMPLATE_TABLE, "ix_match_template_signature"):
        op.create_index("ix_match_template_signature", _TEMPLATE_TABLE, ["signature"])
    if not _has_index(inspector, _TEMPLATE_TABLE, "ix_match_template_cwicr_position"):
        op.create_index(
            "ix_match_template_cwicr_position",
            _TEMPLATE_TABLE,
            ["cwicr_position_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, _GROUP_TABLE):
        op.drop_table(_GROUP_TABLE)
    if _has_table(inspector, _TEMPLATE_TABLE):
        op.drop_table(_TEMPLATE_TABLE)
    if _has_table(inspector, _SESSION_TABLE):
        op.drop_table(_SESSION_TABLE)

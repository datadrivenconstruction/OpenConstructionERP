# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""formwork: catalogue + assignment + schedule line.

Three tables for the MVP Formwork module (task #112 / Epic E):

* ``oe_formwork_system``         — physical catalogue of formwork systems
* ``oe_formwork_assignment``     — links project (+ optional BOQ position)
                                   to a system with reuse-aware unit cost
* ``oe_formwork_schedule_line``  — optional pour-cycle line under an
                                   assignment (climbing / large slabs)

Idempotent (checks ``inspector.get_table_names``). Fresh installs that
boot the app first will already have these tables from
``Base.metadata.create_all`` — running this migration afterwards is a
no-op. Every NOT NULL column carries a ``server_default`` so that path
does not break either (the v3119 lock cascade is the regression we
guard against — Python ``default=`` is ignored by ``create_all``).

Revision ID: v3132_formwork_init
Revises: v3131_subcontractors_lien_waivers
Create Date: 2026-05-25
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3132_formwork_init"
down_revision: Union[str, Sequence[str], None] = "v3131_subcontractors_lien_waivers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SYSTEM = "oe_formwork_system"
_ASSIGNMENT = "oe_formwork_assignment"
_SCHEDULE = "oe_formwork_schedule_line"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── oe_formwork_system ─────────────────────────────────────────────
    if not _has_table(inspector, _SYSTEM):
        op.create_table(
            _SYSTEM,
            sa.Column("id", sa.String(36), primary_key=True),
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
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column(
                "system_type",
                sa.String(40),
                nullable=False,
                server_default="wall",
            ),
            sa.Column("supplier", sa.String(255), nullable=True),
            sa.Column(
                "material",
                sa.String(40),
                nullable=False,
                server_default="plywood",
            ),
            sa.Column(
                "reuses_max",
                sa.Integer(),
                nullable=False,
                server_default="30",
            ),
            sa.Column(
                "unit_rate",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "currency",
                sa.String(3),
                nullable=False,
                server_default="",
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("tenant_id", sa.String(36), nullable=True),
        )
        op.create_index(
            f"ix_{_SYSTEM}_system_type",
            _SYSTEM,
            ["system_type"],
        )
        op.create_index(f"ix_{_SYSTEM}_material", _SYSTEM, ["material"])
        op.create_index(f"ix_{_SYSTEM}_tenant_id", _SYSTEM, ["tenant_id"])

    # ── oe_formwork_assignment ─────────────────────────────────────────
    if not _has_table(inspector, _ASSIGNMENT):
        op.create_table(
            _ASSIGNMENT,
            sa.Column("id", sa.String(36), primary_key=True),
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
            sa.Column(
                "project_id",
                sa.String(36),
                sa.ForeignKey(
                    "oe_projects_project.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("boq_position_id", sa.String(36), nullable=True),
            sa.Column(
                "formwork_system_id",
                sa.String(36),
                sa.ForeignKey(
                    "oe_formwork_system.id",
                    ondelete="RESTRICT",
                ),
                nullable=False,
            ),
            sa.Column(
                "area_m2",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "reuse_count",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column(
                "waste_pct",
                sa.Numeric(6, 2),
                nullable=False,
                server_default="5.00",
            ),
            sa.Column(
                "computed_unit_cost",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "computed_total",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("tenant_id", sa.String(36), nullable=True),
        )
        op.create_index(
            f"ix_{_ASSIGNMENT}_project_id",
            _ASSIGNMENT,
            ["project_id"],
        )
        op.create_index(
            f"ix_{_ASSIGNMENT}_boq_position_id",
            _ASSIGNMENT,
            ["boq_position_id"],
        )
        op.create_index(
            f"ix_{_ASSIGNMENT}_formwork_system_id",
            _ASSIGNMENT,
            ["formwork_system_id"],
        )
        op.create_index(
            f"ix_{_ASSIGNMENT}_tenant_id",
            _ASSIGNMENT,
            ["tenant_id"],
        )

    # ── oe_formwork_schedule_line ──────────────────────────────────────
    if not _has_table(inspector, _SCHEDULE):
        op.create_table(
            _SCHEDULE,
            sa.Column("id", sa.String(36), primary_key=True),
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
            sa.Column(
                "project_id",
                sa.String(36),
                sa.ForeignKey(
                    "oe_projects_project.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "assignment_id",
                sa.String(36),
                sa.ForeignKey(
                    "oe_formwork_assignment.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "pour_no",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column("pour_date", sa.Date(), nullable=True),
            sa.Column(
                "level_label",
                sa.String(120),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "area_m2",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("notes", sa.Text(), nullable=True),
        )
        op.create_index(
            f"ix_{_SCHEDULE}_project_id",
            _SCHEDULE,
            ["project_id"],
        )
        op.create_index(
            f"ix_{_SCHEDULE}_assignment_id",
            _SCHEDULE,
            ["assignment_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, _SCHEDULE):
        op.drop_index(f"ix_{_SCHEDULE}_assignment_id", table_name=_SCHEDULE)
        op.drop_index(f"ix_{_SCHEDULE}_project_id", table_name=_SCHEDULE)
        op.drop_table(_SCHEDULE)

    if _has_table(inspector, _ASSIGNMENT):
        op.drop_index(f"ix_{_ASSIGNMENT}_tenant_id", table_name=_ASSIGNMENT)
        op.drop_index(
            f"ix_{_ASSIGNMENT}_formwork_system_id",
            table_name=_ASSIGNMENT,
        )
        op.drop_index(
            f"ix_{_ASSIGNMENT}_boq_position_id",
            table_name=_ASSIGNMENT,
        )
        op.drop_index(f"ix_{_ASSIGNMENT}_project_id", table_name=_ASSIGNMENT)
        op.drop_table(_ASSIGNMENT)

    if _has_table(inspector, _SYSTEM):
        op.drop_index(f"ix_{_SYSTEM}_tenant_id", table_name=_SYSTEM)
        op.drop_index(f"ix_{_SYSTEM}_material", table_name=_SYSTEM)
        op.drop_index(f"ix_{_SYSTEM}_system_type", table_name=_SYSTEM)
        op.drop_table(_SYSTEM)

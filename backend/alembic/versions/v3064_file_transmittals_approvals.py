# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Transmittals (W7) + Approvals + Stamps (W8) — schema.

Creates six tables:

* ``oe_file_transmittal``               — header (one per outgoing send)
* ``oe_file_transmittal_item``          — files included in transmittal
* ``oe_file_transmittal_recipient``     — per-recipient ack state
* ``oe_file_approval_workflow``         — per-submission workflow header
* ``oe_file_approval_step``             — ordered approver steps
* ``oe_file_stamp_template``            — reusable stamp definitions

Seeds four global stamp templates with ``project_id=NULL``:
``For Construction`` (green), ``Approved`` (blue),
``Revise & Resubmit`` (yellow), ``Rejected`` (red).

Idempotent: every ``create_table`` and ``create_index`` is guarded by
the inspector so a re-run after SQLite's auto-migrator / a partial
prior run is a no-op. The seed-row insert is skipped when the table
already has rows (any rows — we don't try to merge customised seed
data).

Revision ID: v3064_file_transmittals_approvals
Revises: v3047_clash_severity_delta
Created: 2026-05-19
"""

from __future__ import annotations

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3064_file_transmittals_approvals"
down_revision: Union[str, Sequence[str], None] = "v3047_clash_severity_delta"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_T_HEADER = "oe_file_transmittal"
_T_ITEM = "oe_file_transmittal_item"
_T_RECIP = "oe_file_transmittal_recipient"
_A_WORKFLOW = "oe_file_approval_workflow"
_A_STEP = "oe_file_approval_step"
_A_STAMP = "oe_file_stamp_template"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(inspector: sa.engine.reflection.Inspector, table: str, name: str) -> bool:
    return name in {ix["name"] for ix in inspector.get_indexes(table)}


# Default SVG markup for the seeded stamps. ``{{text}}`` / ``{{date}}`` /
# ``{{approver}}`` are expanded by the service at burn time.
_BASE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="220" height="80" '
    'viewBox="0 0 220 80">'
    '<rect x="2" y="2" width="216" height="76" fill="none" '
    'stroke="{COLOR}" stroke-width="3"/>'
    '<text x="14" y="32" font-family="Helvetica,Arial,sans-serif" '
    'font-size="16" font-weight="bold" fill="{COLOR}">{{text}}</text>'
    '<text x="14" y="52" font-family="Helvetica,Arial,sans-serif" '
    'font-size="10" fill="{COLOR}">Approved by {{approver}}</text>'
    '<text x="14" y="68" font-family="Helvetica,Arial,sans-serif" '
    'font-size="10" fill="{COLOR}">{{date}}</text>'
    "</svg>"
)


def _svg(color: str) -> str:
    return _BASE_SVG.replace("{COLOR}", color)


_SEED_STAMPS: tuple[tuple[str, str, str, str], ...] = (
    # (name,                  text,                 color,       svg)
    ("For Construction", "FOR CONSTRUCTION", "#16a34a", _svg("#16a34a")),
    ("Approved", "APPROVED", "#2563eb", _svg("#2563eb")),
    ("Revise & Resubmit", "REVISE & RESUBMIT", "#ca8a04", _svg("#ca8a04")),
    ("Rejected", "REJECTED", "#dc2626", _svg("#dc2626")),
)


def _create_transmittal_tables(
    inspector: sa.engine.reflection.Inspector,
) -> None:
    if not _has_table(inspector, _T_HEADER):
        op.create_table(
            _T_HEADER,
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
            sa.Column(
                "project_id",
                sa.String(length=36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("number", sa.String(length=32), nullable=False),
            sa.Column("subject", sa.String(length=255), nullable=False),
            sa.Column("reason_code", sa.String(length=32), nullable=False),
            sa.Column(
                "sender_id",
                sa.String(length=36),
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "sent_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="sent",
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("cover_sheet_path", sa.String(length=512), nullable=True),
            sa.UniqueConstraint(
                "project_id",
                "number",
                name="uq_oe_file_transmittal_project_id_number",
            ),
        )

    if not _has_index(
        inspector,
        _T_HEADER,
        "ix_oe_file_transmittal_project_status",
    ):
        try:
            op.create_index(
                "ix_oe_file_transmittal_project_status",
                _T_HEADER,
                ["project_id", "status"],
            )
        except Exception:  # noqa: BLE001 — idempotent guard
            pass

    if not _has_table(inspector, _T_ITEM):
        op.create_table(
            _T_ITEM,
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
            sa.Column(
                "transmittal_id",
                sa.String(length=36),
                sa.ForeignKey("oe_file_transmittal.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("file_kind", sa.String(length=32), nullable=False),
            sa.Column("file_id", sa.String(length=64), nullable=False),
            sa.Column(
                "file_version_snapshot",
                sa.String(length=32),
                nullable=True,
            ),
            sa.Column(
                "canonical_name_snapshot",
                sa.String(length=512),
                nullable=False,
            ),
            sa.Column(
                "sort_order",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )

    if not _has_index(
        inspector,
        _T_ITEM,
        "ix_oe_file_transmittal_item_transmittal_id",
    ):
        try:
            op.create_index(
                "ix_oe_file_transmittal_item_transmittal_id",
                _T_ITEM,
                ["transmittal_id"],
            )
        except Exception:  # noqa: BLE001
            pass

    if not _has_table(inspector, _T_RECIP):
        op.create_table(
            _T_RECIP,
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
            sa.Column(
                "transmittal_id",
                sa.String(length=36),
                sa.ForeignKey("oe_file_transmittal.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("display_name", sa.String(length=128), nullable=True),
            sa.Column("role", sa.String(length=32), nullable=True),
            sa.Column(
                "acknowledged_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column("acknowledge_token", sa.String(length=64), nullable=True),
            sa.UniqueConstraint(
                "transmittal_id",
                "email",
                name="uq_oe_file_transmittal_recipient_transmittal_id_email",
            ),
        )

    if not _has_index(inspector, _T_RECIP, "ix_oe_file_transmittal_recipient_token"):
        try:
            op.create_index(
                "ix_oe_file_transmittal_recipient_token",
                _T_RECIP,
                ["acknowledge_token"],
            )
        except Exception:  # noqa: BLE001
            pass


def _create_approval_tables(
    inspector: sa.engine.reflection.Inspector,
) -> None:
    # Stamp template table is created BEFORE workflow so the FK exists.
    if not _has_table(inspector, _A_STAMP):
        op.create_table(
            _A_STAMP,
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
            sa.Column(
                "project_id",
                sa.String(length=36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("text", sa.String(length=255), nullable=False),
            sa.Column(
                "color",
                sa.String(length=7),
                nullable=False,
                server_default="#16a34a",
            ),
            sa.Column("svg_template", sa.Text(), nullable=False),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default="1",
            ),
            sa.UniqueConstraint(
                "project_id",
                "name",
                name="uq_oe_file_stamp_template_project_id_name",
            ),
        )

    if not _has_table(inspector, _A_WORKFLOW):
        op.create_table(
            _A_WORKFLOW,
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
            sa.Column(
                "project_id",
                sa.String(length=36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("file_kind", sa.String(length=32), nullable=False),
            sa.Column("file_id", sa.String(length=64), nullable=False),
            sa.Column(
                "file_version_snapshot",
                sa.String(length=32),
                nullable=True,
            ),
            sa.Column(
                "submitted_by_id",
                sa.String(length=36),
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "submitted_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="in_review",
            ),
            sa.Column(
                "final_decision_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "final_decision_by_id",
                sa.String(length=36),
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "stamp_template_id",
                sa.String(length=36),
                sa.ForeignKey("oe_file_stamp_template.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "stamped_artifact_path",
                sa.String(length=512),
                nullable=True,
            ),
            sa.Column("notes", sa.Text(), nullable=True),
        )

    if not _has_index(
        inspector,
        _A_WORKFLOW,
        "ix_oe_file_approval_workflow_project_status",
    ):
        try:
            op.create_index(
                "ix_oe_file_approval_workflow_project_status",
                _A_WORKFLOW,
                ["project_id", "status"],
            )
        except Exception:  # noqa: BLE001
            pass

    if not _has_index(inspector, _A_WORKFLOW, "ix_oe_file_approval_workflow_file"):
        try:
            op.create_index(
                "ix_oe_file_approval_workflow_file",
                _A_WORKFLOW,
                ["file_kind", "file_id"],
            )
        except Exception:  # noqa: BLE001
            pass

    if not _has_table(inspector, _A_STEP):
        op.create_table(
            _A_STEP,
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
            sa.Column(
                "workflow_id",
                sa.String(length=36),
                sa.ForeignKey("oe_file_approval_workflow.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column(
                "approver_id",
                sa.String(length=36),
                sa.ForeignKey("oe_users_user.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("role_label", sa.String(length=64), nullable=True),
            sa.Column(
                "decision",
                sa.String(length=16),
                nullable=False,
                server_default="pending",
            ),
            sa.Column(
                "decision_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column("decision_note", sa.Text(), nullable=True),
            sa.UniqueConstraint(
                "workflow_id",
                "sort_order",
                name="uq_oe_file_approval_step_workflow_id_sort_order",
            ),
        )

    if not _has_index(inspector, _A_STEP, "ix_oe_file_approval_step_approver"):
        try:
            op.create_index(
                "ix_oe_file_approval_step_approver",
                _A_STEP,
                ["approver_id", "decision"],
            )
        except Exception:  # noqa: BLE001
            pass


def _seed_stamp_templates() -> None:
    """Insert the four global stamp templates if the table is empty."""
    bind = op.get_bind()
    # Skip seeding if rows already exist (re-run or operator-customised).
    existing = bind.execute(sa.text(f"SELECT COUNT(*) FROM {_A_STAMP}")).scalar_one()
    if existing and int(existing) > 0:
        return

    stamp_table = sa.table(
        _A_STAMP,
        sa.column("id", sa.String),
        sa.column("project_id", sa.String),
        sa.column("name", sa.String),
        sa.column("text", sa.String),
        sa.column("color", sa.String),
        sa.column("svg_template", sa.Text),
        sa.column("is_active", sa.Boolean),
    )
    rows = [
        {
            "id": str(uuid.uuid4()),
            "project_id": None,
            "name": name,
            "text": text,
            "color": color,
            "svg_template": svg,
            "is_active": True,
        }
        for (name, text, color, svg) in _SEED_STAMPS
    ]
    op.bulk_insert(stamp_table, rows)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    _create_transmittal_tables(inspector)
    _create_approval_tables(inspector)

    # Re-inspect after creates so the seed step sees the new tables.
    inspector = sa.inspect(bind)
    if _has_table(inspector, _A_STAMP):
        _seed_stamp_templates()


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Drop in reverse dependency order.
    if _has_table(inspector, _A_STEP):
        op.drop_table(_A_STEP)
    if _has_table(inspector, _A_WORKFLOW):
        op.drop_table(_A_WORKFLOW)
    if _has_table(inspector, _A_STAMP):
        op.drop_table(_A_STAMP)
    if _has_table(inspector, _T_RECIP):
        op.drop_table(_T_RECIP)
    if _has_table(inspector, _T_ITEM):
        op.drop_table(_T_ITEM)
    if _has_table(inspector, _T_HEADER):
        op.drop_table(_T_HEADER)

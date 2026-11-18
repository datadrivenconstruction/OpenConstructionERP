# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""crm - assignee on activities and the ``bidding`` pipeline stage.

Adds the nullable ``assigned_user_id`` column to ``oe_crm_activity`` and, on an
install that already has the standard stages, inserts the ``bidding`` stage
between ``qualified`` and ``proposal``. Both steps are guarded, so a re-run
changes nothing. The column is additive; a running install also gets it from
the auto-migrator, and ``CrmService.list_stages`` adds the stage on first read.

Revision ID: vcrm01_deal_activities
Revises: vsub01_agreement_documents
Create Date: 2026-11-18
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "vcrm01_deal_activities"
down_revision: Union[str, Sequence[str], None] = "vhk01_sop_applicability"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ACT = "oe_crm_activity"
_STAGE = "oe_crm_pipeline_stage"

# data-rewrite-ack: table=oe_crm_pipeline_stage growth=bounded rows=a fixed list of pipeline stages per install, configured by hand, not a per-deal log
# boot-repair: none - CrmService.list_stages inserts the bidding stage on older installs at runtime


def upgrade() -> None:
    """Add the assignee column and the bidding stage."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if _ACT in tables and "assigned_user_id" not in {c["name"] for c in insp.get_columns(_ACT)}:
        op.add_column(_ACT, sa.Column("assigned_user_id", sa.String(36), nullable=True))
        op.create_index(op.f("ix_oe_crm_activity_assigned_user_id"), _ACT, ["assigned_user_id"])
    if _STAGE not in tables:
        return
    rows = bind.execute(sa.text(f"SELECT code, display_order FROM {_STAGE}")).fetchall()  # noqa: S608
    orders = {r[0]: r[1] for r in rows}
    if "bidding" in orders or "qualified" not in orders or "proposal" not in orders:
        return
    at = orders["qualified"] + 1
    bind.execute(
        sa.text(f"UPDATE {_STAGE} SET display_order = display_order + 1 WHERE display_order >= :at"),  # noqa: S608
        {"at": at},
    )
    bind.execute(
        sa.text(
            f"INSERT INTO {_STAGE} (id, code, name, display_order, default_probability_percent, is_final, is_won,"  # noqa: S608
            " is_lost, color, created_at, updated_at) VALUES (:id, 'bidding', 'Bidding', :at, 35, :f, :f, :f,"
            " '#06b6d4', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"id": str(uuid.uuid4()), "at": at, "f": False},
    )


def downgrade() -> None:
    """Drop the assignee column; the bidding stage stays (deals may sit in it)."""
    insp = sa.inspect(op.get_bind())
    if _ACT in insp.get_table_names() and "assigned_user_id" in {c["name"] for c in insp.get_columns(_ACT)}:
        op.drop_index(op.f("ix_oe_crm_activity_assigned_user_id"), table_name=_ACT)
        op.drop_column(_ACT, "assigned_user_id")

"""contracts - a payment plan whose instalments follow schedule milestones.

Columns on ``oe_contracts_milestone``:

* ``activity_id`` / ``schedule_id``: the schedule milestone the instalment
  follows. Plain ids, no foreign key: contracts must not depend on the
  schedule module being installed, the same way ``project_id`` is held.
* ``kind``: ``deposit``, ``progress`` or ``final``. The statutory deposit
  ceilings read ``deposit``; nothing infers it from the order of rows.
* ``lag_days`` / ``payment_terms_days``: days from the milestone to the claim,
  and from the claim to payment.
* ``forecast_reached_date`` / ``forecast_due_date`` / ``forecast_at``: the
  stored forecast, recomputed when the schedule moves, so the portal and the
  reminders read one answer instead of recomputing it each their own way.
* ``reached_at`` / ``reached_by``: when the milestone was reached, and by
  which activity or person.
* ``client_visible``: whether the client sees the instalment on the portal.

And one column on ``oe_projects_project``: ``subdivision_code``, the ISO
3166-2 code of the state or province the work is in (``US-CA``). Statutory
limits on deposits are set per state, so the country alone cannot pick them.

And an index on ``oe_contracts_progress_claim.milestone_id``: the plan looks
up the claim raised for each instalment.

Nothing is backfilled. Existing milestones keep ``kind = progress``, no link
and no forecast, and stay hidden from the client until a person shows them,
the same way schedule milestones (v53) and progress reports do.

This one does NOT need running by hand. The boot schema heal adds missing
nullable columns and columns with a server default, and plain indexes, which
is everything here. Inspector-guarded, so an install whose schema came from
``create_all`` plus the heal reaches this revision and adds nothing.

Revision ID: v54_contracts_payment_plan
Revises: v53_schedule_activity_client_visible
Create Date: 2026-10-05
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v54_contracts_payment_plan"
down_revision: Union[str, Sequence[str], None] = "v53_schedule_activity_client_visible"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_contracts_milestone"
_PROJECT_TABLE = "oe_projects_project"
_CLAIM_TABLE = "oe_contracts_progress_claim"
_CLAIM_INDEX = "ix_oe_contracts_progress_claim_milestone_id"
_SUBDIVISION = "subdivision_code"


def _columns() -> list[sa.Column]:
    return [
        sa.Column("activity_id", GUID(), nullable=True),
        sa.Column("schedule_id", GUID(), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False, server_default="progress"),
        sa.Column("lag_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payment_terms_days", sa.Integer(), nullable=True),
        sa.Column("forecast_reached_date", sa.String(10), nullable=True),
        sa.Column("forecast_due_date", sa.String(10), nullable=True),
        sa.Column("forecast_at", sa.String(40), nullable=True),
        sa.Column("reached_at", sa.String(40), nullable=True),
        sa.Column("reached_by", sa.String(36), nullable=True),
        sa.Column("client_visible", sa.Boolean(), nullable=False, server_default=sa.false()),
    ]


#: Indexed columns, named the way ``index=True`` on the model names them.
_INDEXED = ("activity_id", "schedule_id", "forecast_due_date")


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if _PROJECT_TABLE in tables and _SUBDIVISION not in {c["name"] for c in inspector.get_columns(_PROJECT_TABLE)}:
        op.add_column(_PROJECT_TABLE, sa.Column(_SUBDIVISION, sa.String(6), nullable=True))
    if _CLAIM_TABLE in tables and _CLAIM_INDEX not in {ix["name"] for ix in inspector.get_indexes(_CLAIM_TABLE)}:
        op.create_index(_CLAIM_INDEX, _CLAIM_TABLE, ["milestone_id"])
    if _TABLE not in tables:
        return
    present = {c["name"] for c in inspector.get_columns(_TABLE)}
    for column in _columns():
        if column.name not in present:
            op.add_column(_TABLE, column)
    indexes = {ix["name"] for ix in inspector.get_indexes(_TABLE)}
    for name in _INDEXED:
        index = f"ix_{_TABLE}_{name}"
        if index not in indexes:
            op.create_index(index, _TABLE, [name])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if _PROJECT_TABLE in tables and _SUBDIVISION in {c["name"] for c in inspector.get_columns(_PROJECT_TABLE)}:
        op.drop_column(_PROJECT_TABLE, _SUBDIVISION)
    if _CLAIM_TABLE in tables and _CLAIM_INDEX in {ix["name"] for ix in inspector.get_indexes(_CLAIM_TABLE)}:
        op.drop_index(_CLAIM_INDEX, table_name=_CLAIM_TABLE)
    if _TABLE not in tables:
        return
    indexes = {ix["name"] for ix in inspector.get_indexes(_TABLE)}
    for name in _INDEXED:
        index = f"ix_{_TABLE}_{name}"
        if index in indexes:
            op.drop_index(index, table_name=_TABLE)
    present = {c["name"] for c in inspector.get_columns(_TABLE)}
    for column in reversed(_columns()):
        if column.name in present:
            op.drop_column(_TABLE, column.name)

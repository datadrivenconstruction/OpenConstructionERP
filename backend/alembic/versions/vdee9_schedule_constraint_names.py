# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""rewrite raw P6 constraint codes to the neutral constraint names

XER import used to store ``cstr_type`` verbatim (``CS_MSO``, ``CS_ALAP`` ...)
while the MSP importer stored neutral names. The scheduler reads the neutral
vocabulary only, so existing rows are rewritten once. ``CS_ASAP`` is the
default behaviour and becomes NULL. The downgrade is a no-op: the original
codes cannot be told apart from rows that were always neutral.

Revision ID: vdee9_schedule_constraint_names
Revises: vai01_doc_assistant_agent_catalogue
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vdee9_schedule_constraint_names"
down_revision: str | Sequence[str] | None = "vsub9_subco_change_passthrough"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "oe_schedule_activity"

# Frozen copy of the map in app.modules.schedule.constraints: a migration must
# not change meaning when application code later does.
_XER_TO_NEUTRAL: dict[str, str | None] = {
    "CS_MSO": "must_start_on",
    "CS_MEO": "must_finish_on",
    "CS_MANDSTART": "must_start_on",
    "CS_MANDFIN": "must_finish_on",
    "CS_MSOA": "start_no_earlier",
    "CS_MEOA": "finish_no_earlier",
    "CS_MSOB": "start_no_later",
    "CS_MEOB": "finish_no_later",
    "CS_ALAP": "as_late_as_possible",
    "CS_ASAP": None,
}


# data-rewrite-ack: table=oe_schedule_activity growth=tenure rows=every schedule activity on every project
# boot-repair: gap - activities imported earlier keep their raw XER constraint codes on an install that never runs alembic
def upgrade() -> None:
    if _TABLE not in sa.inspect(op.get_bind()).get_table_names():
        return
    activity = sa.table(_TABLE, sa.column("constraint_type", sa.String))
    for code, neutral in _XER_TO_NEUTRAL.items():
        op.execute(
            activity.update().where(sa.func.upper(activity.c.constraint_type) == code).values(constraint_type=neutral)
        )


def downgrade() -> None:
    pass

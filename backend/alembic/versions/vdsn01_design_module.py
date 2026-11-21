# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""design module: brief, revisions, link, estimate, schedule, procurement, drafts

Additive new tables only, so a deploy that heals its schema at boot (``create_all``)
picks them up without ``alembic upgrade``; running it is still safe, every table is
created only when missing. The browser editor bundle is files under the data dir,
not rows, so it needs no DDL.

Revision ID: vdsn01_design_module
Revises: vcrm02_account_contacts
Create Date: 2026-11-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vdsn01_design_module"
down_revision: str | Sequence[str] | None = "vcrm02_account_contacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "oe_design_brief",
    "oe_design_brief_version",
    "oe_design_revision",
    "oe_design_link_code",
    "oe_design_link_token",
    "oe_design_estimate",
    "oe_design_estimate_rule",
    "oe_design_estimate_binding",
    "oe_design_project_option",
    "oe_design_change_order",
    "oe_design_schedule",
    "oe_design_schedule_binding",
    "oe_design_job",
    "oe_design_draft",
    "oe_design_edit_rights",
    "oe_design_ai_choice",
    "oe_design_procurement",
    "oe_design_takeoff_section",
    "oe_design_takeoff_line",
)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if all(insp.has_table(t) for t in _TABLES):
        return
    from app.database import Base
    from app.modules.design import models, procurement_models  # noqa: F401 - registers the tables on Base.metadata

    wanted = set(_TABLES)
    for table in Base.metadata.sorted_tables:
        if table.name in wanted and not insp.has_table(table.name):
            table.create(bind)


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    for name in reversed(_TABLES):
        if insp.has_table(name):
            op.drop_table(name)

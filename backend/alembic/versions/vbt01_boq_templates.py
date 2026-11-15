# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""user-owned editable BOQ templates

Additive new table only, so a deploy that heals its schema at boot picks it up
without ``alembic upgrade``.

Revision ID: vbt01_boq_templates
Revises: vpc01_project_country_from_region
Create Date: 2026-11-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vbt01_boq_templates"
down_revision: str | Sequence[str] | None = "vpc01_project_country_from_region"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_T = "oe_boq_template"


def upgrade() -> None:
    if _T in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        _T,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("icon", sa.String(50), nullable=False, server_default="FileText"),
        sa.Column("classification_standard", sa.String(50), nullable=False, server_default=""),
        sa.Column("origin", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("copied_from", sa.String(50), nullable=True),
        sa.Column("sections", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("markups", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.create_index("ix_oe_boq_template_owner_id", _T, ["owner_id"])
    op.create_index("ix_boq_template_owner_name", _T, ["owner_id", "name"])


def downgrade() -> None:
    op.drop_index("ix_boq_template_owner_name", table_name=_T)
    op.drop_index("ix_oe_boq_template_owner_id", table_name=_T)
    op.drop_table(_T)

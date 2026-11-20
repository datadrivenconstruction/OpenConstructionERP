# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""haul tickets: link to a survey volume or stockpile, hauled vs excavated threshold

Additive nullable columns only, so a deploy that heals its schema at boot picks
them up without ``alembic upgrade``. The links are soft (no foreign key), like
the ticket's other links into optional modules.

Revision ID: hvx01_haul_ticket_survey_links
Revises: cpb01_central_purchasing_bundles
Create Date: 2026-11-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hvx01_haul_ticket_survey_links"
down_revision: str | Sequence[str] | None = "cpb01_central_purchasing_bundles"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TICKET = "oe_haul_tickets_ticket"
_SETTINGS = "oe_haul_tickets_settings"
_COLUMNS = (
    (_TICKET, "survey_volume_id", sa.String(36)),
    (_TICKET, "stockpile_id", sa.String(36)),
    (_SETTINGS, "haul_variance_pct", sa.Integer()),
)


def _existing(table: str) -> set[str] | None:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return None
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    for table, name, type_ in _COLUMNS:
        cols = _existing(table)
        if cols is not None and name not in cols:
            op.add_column(table, sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    for table, name, _type in reversed(_COLUMNS):
        cols = _existing(table)
        if cols is not None and name in cols:
            op.drop_column(table, name)

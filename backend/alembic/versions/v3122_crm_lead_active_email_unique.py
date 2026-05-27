# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""crm: unique active-lead email index (lead-dedup atomicity).

R7 audit fix. Two concurrent inbound webhooks targeting the same email
both passed Pydantic + auth and both raced past ``find_by_email`` before
either had flushed its INSERT. With no DB-level constraint the second
write silently created a duplicate active lead — corrupting per-rep
ownership, double-billing on commission, and breaking the GDPR
``forget_lead`` flow (which scrubs one row but leaves the dupe carrying
the same PII).

The unique partial index makes the second INSERT raise ``IntegrityError``
which ``CrmService.create_lead`` already catches and translates to 409
(see ``except IntegrityError`` block). The fix is therefore additive:
existing application logic keeps working; we only close the race window.

Index spec:
    UNIQUE (LOWER(contact_email)) WHERE
        status IN ('new', 'qualifying', 'qualified')
        AND contact_email IS NOT NULL

The ``status`` filter is critical — historical/disqualified/converted
leads must NOT block a fresh inbound for the same person months later.
``LOWER()`` makes the constraint case-insensitive (matches the service
layer's ``.strip().lower()`` normalisation).

PostgreSQL: native partial expression-index support.
SQLite: partial indexes are supported since 3.8.0 (2014) — the same
DDL works on both.

Revision ID: v3122_crm_lead_active_email_unique
Revises: v3121_geo_raster_overlay
Create Date: 2026-05-24
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3122_crm_lead_active_email_unique"
down_revision: Union[str, Sequence[str], None] = "v3121_geo_raster_overlay"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "oe_crm_lead"
INDEX_NAME = "ux_oe_crm_lead_active_email"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE):
        # Fresh install via ``Base.metadata.create_all`` may run before the
        # CRM module bootstraps its tables — defer until those exist.
        return
    existing_indexes = {ix["name"] for ix in inspector.get_indexes(TABLE)}
    if INDEX_NAME in existing_indexes:
        return

    dialect = bind.dialect.name
    if dialect == "postgresql" or dialect == "sqlite":
        op.execute(
            f"""
            CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME}
            ON {TABLE} (LOWER(contact_email))
            WHERE status IN ('new', 'qualifying', 'qualified')
              AND contact_email IS NOT NULL
            """
        )
    else:
        # MySQL / others: best-effort plain unique on contact_email when
        # active. MySQL doesn't support partial indexes pre-8.0; fall back
        # to no constraint rather than a non-partial one that would block
        # historical re-leads. Application-layer pre-check still catches
        # the common case.
        return


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table(TABLE):
        return
    existing_indexes = {ix["name"] for ix in inspector.get_indexes(TABLE)}
    if INDEX_NAME not in existing_indexes:
        return
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")

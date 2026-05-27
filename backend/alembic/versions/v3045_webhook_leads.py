# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Webhook Leads — incoming-webhook → CRM-lead tables.

Adds the three tables backing the ``oe_webhook_leads`` module:

    oe_webhook_leads_source   — a configured external webhook source
                                (auth method, hashed secret, IP allowlist,
                                 per-source rate limit)
    oe_webhook_leads_mapping  — payload-path → CRM-lead-field rules
    oe_webhook_leads_log      — one immutable row per ingestion attempt
                                (accepted / rejected / error) for audit

The module never duplicates CRM tables — leads are created through the
CRM service. ``project_id`` / ``created_by`` / ``created_lead_id`` are
plain ``String(36)`` GUID columns with NO database-level foreign key
(matching the CRM ``primary_contact_id`` convention) so unit fixtures
that never load the Projects/Users modules don't trip
``NoReferencedTableError``.

Idempotent: guarded by an inspector so re-running after SQLite's
``Base.metadata.create_all`` / ``sqlite_auto_migrate`` (dev) is a no-op;
Postgres prod gets the DDL. All ``id`` / ``*_id`` columns are
``String(36)`` to match the platform's ``GUID`` TypeDecorator on
SQLite + PostgreSQL.

Revision ID: v3045_webhook_leads
Revises: v3044_fieldreport_templates
Created: 2026-05-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3045_webhook_leads"
down_revision: Union[str, Sequence[str], None] = "v3044_fieldreport_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SOURCE = "oe_webhook_leads_source"
_MAPPING = "oe_webhook_leads_mapping"
_LOG = "oe_webhook_leads_log"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _ts_columns() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    """Create the three webhook-leads tables (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _SOURCE):
        op.create_table(
            _SOURCE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            *_ts_columns(),
            sa.Column("project_id", sa.String(length=36), nullable=True),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("slug", sa.String(length=64), nullable=False),
            sa.Column(
                "auth_method",
                sa.String(length=16),
                nullable=False,
                server_default="api_key",
            ),
            sa.Column(
                "secret_hash",
                sa.String(length=128),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "ip_allowlist",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default="1",
            ),
            sa.Column(
                "rate_limit_per_min",
                sa.Integer(),
                nullable=False,
                server_default="60",
            ),
            sa.Column(
                "default_lead_source",
                sa.String(length=32),
                nullable=False,
                server_default="web",
            ),
            sa.Column("created_by", sa.String(length=36), nullable=True),
            sa.UniqueConstraint("slug", name="uq_oe_webhook_leads_source_slug"),
        )
        op.create_index("ix_oe_webhook_leads_source_slug", _SOURCE, ["slug"], unique=True)
        op.create_index("ix_oe_webhook_leads_source_is_active", _SOURCE, ["is_active"])

    if not _has_table(inspector, _MAPPING):
        op.create_table(
            _MAPPING,
            sa.Column("id", sa.String(length=36), primary_key=True),
            *_ts_columns(),
            sa.Column(
                "source_id",
                sa.String(length=36),
                sa.ForeignKey(f"{_SOURCE}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("target_field", sa.String(length=64), nullable=False),
            sa.Column("source_path", sa.String(length=255), nullable=False),
            sa.Column("transform", sa.String(length=32), nullable=True),
            sa.Column(
                "required",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            ),
        )
        op.create_index("ix_oe_webhook_leads_mapping_source_id", _MAPPING, ["source_id"])

    if not _has_table(inspector, _LOG):
        op.create_table(
            _LOG,
            sa.Column("id", sa.String(length=36), primary_key=True),
            *_ts_columns(),
            sa.Column(
                "source_id",
                sa.String(length=36),
                sa.ForeignKey(f"{_SOURCE}.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "source_slug",
                sa.String(length=64),
                nullable=False,
                server_default="",
            ),
            sa.Column("received_at", sa.String(length=40), nullable=True),
            sa.Column(
                "remote_ip",
                sa.String(length=64),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="rejected",
            ),
            sa.Column(
                "http_status",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column(
                "error_message",
                sa.Text(),
                nullable=False,
                server_default="",
            ),
            sa.Column("created_lead_id", sa.String(length=36), nullable=True),
        )
        op.create_index("ix_oe_webhook_leads_log_source_id", _LOG, ["source_id"])
        op.create_index("ix_oe_webhook_leads_log_source_slug", _LOG, ["source_slug"])
        op.create_index("ix_oe_webhook_leads_log_status", _LOG, ["status"])


def downgrade() -> None:
    """Drop the three webhook-leads tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for tbl in (_LOG, _MAPPING, _SOURCE):
        if _has_table(inspector, tbl):
            op.drop_table(tbl)

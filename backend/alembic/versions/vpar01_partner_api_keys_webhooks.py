# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""partner API: key limits and rotation, webhook retry state

Adds per-key rate limit, client address allow-list, usage counter and the
rotation link to ``oe_users_api_key``; adds retry state to
``oe_integrations_delivery``. Copies the rows of the older notification
webhook table into ``oe_integrations_webhook`` as inactive endpoints for the
owner to review. No new tables.

Revision ID: vpar01_partner_api_keys_webhooks
Revises: vai01_doc_assistant_agent_catalogue
Create Date: 2026-11-03
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "vpar01_partner_api_keys_webhooks"
down_revision: str | Sequence[str] | None = "vcap01_capital_plan"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KEY = "oe_users_api_key"
_DELIVERY = "oe_integrations_delivery"
_ENDPOINT = "oe_integrations_webhook"
_TARGET = "oe_notification_webhook_target"
_KEY_FK = "fk_oe_users_api_key_rotated_from"
_RETRY_IX = "ix_oe_integrations_delivery_next_retry_at"
_MIGRATED = "migrated_from"


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


# data-rewrite-ack: table=oe_integrations_delivery growth=tenure rows=one row per logged webhook delivery
# data-rewrite-ack: table=oe_integrations_webhook growth=bounded rows=one row per configured notification target, set up by hand
# boot-repair: gap - old deliveries stay unsettled and old notification targets are not copied on an install that never runs alembic
def upgrade() -> None:
    tables = _tables()

    if _KEY in tables:
        have = _columns(_KEY)
        with op.batch_alter_table(_KEY) as batch:
            if "rate_limit_per_min" not in have:
                batch.add_column(sa.Column("rate_limit_per_min", sa.Integer(), nullable=True))
            if "allowed_cidrs" not in have:
                batch.add_column(sa.Column("allowed_cidrs", sa.JSON(), nullable=False, server_default="[]"))
            if "request_count" not in have:
                batch.add_column(sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"))
            if "rotated_from_id" not in have:
                batch.add_column(sa.Column("rotated_from_id", sa.String(36), nullable=True))
                batch.create_foreign_key(_KEY_FK, _KEY, ["rotated_from_id"], ["id"], ondelete="SET NULL")

    if _DELIVERY in tables:
        have = _columns(_DELIVERY)
        fresh = "status" not in have
        with op.batch_alter_table(_DELIVERY) as batch:
            if "attempt" not in have:
                batch.add_column(sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"))
            if "next_retry_at" not in have:
                batch.add_column(sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))
            if "status" not in have:
                batch.add_column(sa.Column("status", sa.String(16), nullable=False, server_default="pending"))
            if "last_error" not in have:
                batch.add_column(sa.Column("last_error", sa.Text(), nullable=False, server_default=""))
        indexes = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(_DELIVERY)}
        if _RETRY_IX not in indexes:
            op.create_index(_RETRY_IX, _DELIVERY, ["next_retry_at"])
        if fresh:
            # Logged deliveries predate retries: settle them so the worker never picks one up.
            op.execute(
                sa.text(
                    f"UPDATE {_DELIVERY} SET status = CASE "
                    "WHEN status_code BETWEEN 200 AND 299 THEN 'delivered' ELSE 'dead' END, attempt = 1"
                )
            )

    if _TARGET in tables and _ENDPOINT in tables:
        _copy_notification_targets()


def _copy_notification_targets() -> None:
    """Copy each old webhook target once, inactive, flagged for the owner's review.

    The old table received only the notification dispatch payloads; an endpoint
    on the event bus would receive every event its filter matches, so a copied
    ``*`` filter must not start sending on its own. Idempotent through the
    ``migrated_from`` marker in the endpoint metadata.
    """
    bind = op.get_bind()
    targets = bind.execute(sa.text(f"SELECT id, name, url, event_filter, secret FROM {_TARGET}")).fetchall()  # noqa: S608
    if not targets:
        return
    owner = bind.execute(
        sa.text("SELECT id FROM oe_users_user WHERE role = 'admin' ORDER BY created_at ASC LIMIT 1")
    ).scalar()
    if owner is None:
        return
    endpoint = sa.table(
        _ENDPOINT,
        sa.column("id", sa.String),
        sa.column("user_id", sa.String),
        sa.column("name", sa.String),
        sa.column("url", sa.String),
        sa.column("secret", sa.String),
        sa.column("events", sa.JSON),
        sa.column("is_active", sa.Boolean),
        sa.column("failure_count", sa.Integer),
        sa.column("metadata", sa.JSON),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    existing = bind.execute(sa.select(endpoint.c.metadata)).fetchall()
    migrated = {row[0].get(_MIGRATED) for row in existing if isinstance(row[0], dict)}
    now = datetime.now(UTC)
    for tid, name, url, event_filter, secret in targets:
        marker = f"{_TARGET}:{tid}"
        if marker in migrated:
            continue
        events = [e.strip() for e in (event_filter or "*").split(",") if e.strip()] or ["*"]
        bind.execute(
            endpoint.insert().values(
                id=str(uuid.uuid4()),
                user_id=str(owner),
                name=str(name)[:255],
                url=str(url)[:1000],
                secret=secret,
                events=events,
                is_active=False,
                failure_count=0,
                metadata={_MIGRATED: marker, "needs_review": True, "deprecated_source": True},
                created_at=now,
                updated_at=now,
            )
        )


def downgrade() -> None:
    tables = _tables()

    if _DELIVERY in tables:
        have = _columns(_DELIVERY)
        indexes = {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(_DELIVERY)}
        if _RETRY_IX in indexes:
            op.drop_index(_RETRY_IX, table_name=_DELIVERY)
        with op.batch_alter_table(_DELIVERY) as batch:
            for col in ("last_error", "status", "next_retry_at", "attempt"):
                if col in have:
                    batch.drop_column(col)

    if _KEY in tables:
        have = _columns(_KEY)
        with op.batch_alter_table(_KEY) as batch:
            if "rotated_from_id" in have:
                # A create_all schema names this FK differently; look it up by column.
                for fk in sa.inspect(op.get_bind()).get_foreign_keys(_KEY):
                    if fk["constrained_columns"] == ["rotated_from_id"] and fk["name"]:
                        batch.drop_constraint(fk["name"], type_="foreignkey")
                batch.drop_column("rotated_from_id")
            for col in ("request_count", "allowed_cidrs", "rate_limit_per_min"):
                if col in have:
                    batch.drop_column(col)
    # Copied endpoints stay: they are user data and the old table was never changed.

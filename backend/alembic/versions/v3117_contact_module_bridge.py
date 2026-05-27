# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""contacts: module-tags + custom-properties bridge with PropDev Lead/Buyer.

This migration wires Contacts up as the single source of truth for
person data while letting module-specific entities (PropDev Lead /
Buyer, eventually Broker / Vendor / Subcontractor) carry only the
module-specific fields. The bridge is:

* ``oe_contacts_contact.module_tags`` — JSON array of module-presence
  tags (``'property_dev_lead'``, ``'property_dev_buyer'``, ``'broker'``,
  …). A contact can carry multiple tags concurrently (a Lead that
  converted to Buyer keeps both).
* ``oe_contacts_contact.custom_properties`` — JSON dict of optional
  module-specific extension fields, keyed by module name. Module code
  reads/writes only its own bucket.
* ``oe_property_dev_lead.contact_id`` / ``oe_property_dev_buyer.contact_id``
  — nullable FK to the canonical contact row. Service-layer code writes
  to the Contact for canonical fields (name, email, phone) and to the
  Lead/Buyer for module-specific fields (lead_score, buyer_status, …).

Backfill strategy:
    None. Existing Lead/Buyer rows keep ``contact_id=NULL`` until they
    are next touched (PATCH or the explicit
    ``/contacts/{id}/convert-to-lead`` flow). The service layer treats
    ``contact_id=NULL`` as "unlinked legacy row" and falls back to the
    Lead/Buyer's own ``email`` field for display.

Inspector-guarded:
    Each column add and FK add is guarded by ``inspector.has_table`` +
    ``inspector.get_columns`` checks so the migration is idempotent on
    every dialect we ship (SQLite dev, PostgreSQL prod) and on every
    deployment state (fresh install, partial-failed prior run, etc.).

Revision ID: v3117_contact_module_bridge
Revises: v3116_propdev_custom_templates
Create Date: 2026-05-23
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3117_contact_module_bridge"
down_revision: Union[str, Sequence[str], None] = "v3116_propdev_custom_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CONTACT_TABLE = "oe_contacts_contact"
_LEAD_TABLE = "oe_property_dev_lead"
_BUYER_TABLE = "oe_property_dev_buyer"


def _columns(inspector: sa.engine.reflection.Inspector, table: str) -> set[str]:
    if not inspector.has_table(table):
        return set()
    return {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── Contact: module_tags + custom_properties ────────────────────
    contact_cols = _columns(inspector, _CONTACT_TABLE)
    if _CONTACT_TABLE in inspector.get_table_names():
        if "module_tags" not in contact_cols:
            op.add_column(
                _CONTACT_TABLE,
                sa.Column(
                    "module_tags",
                    sa.JSON(),
                    nullable=False,
                    server_default="[]",
                ),
            )
        if "custom_properties" not in contact_cols:
            op.add_column(
                _CONTACT_TABLE,
                sa.Column(
                    "custom_properties",
                    sa.JSON(),
                    nullable=False,
                    server_default="{}",
                ),
            )

    # ── Lead.contact_id ─────────────────────────────────────────────
    lead_cols = _columns(inspector, _LEAD_TABLE)
    if _LEAD_TABLE in inspector.get_table_names() and "contact_id" not in lead_cols:
        with op.batch_alter_table(_LEAD_TABLE) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "contact_id",
                    sa.CHAR(36),
                    nullable=True,
                ),
            )
            # FK is best-effort: if oe_contacts_contact lives in a
            # parallel install we still want the column even without the
            # constraint. Wrap in try/except so a missing target table
            # does not abort the migration.
            try:
                batch_op.create_foreign_key(
                    "fk_oe_property_dev_lead_contact_id",
                    _CONTACT_TABLE,
                    ["contact_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
            except Exception:  # noqa: BLE001 — best-effort FK creation
                pass

    # Refresh and add the index (was inside batch_alter; SQLite doesn't
    # like create_index on a column added in the same batch on some
    # versions, so do it after the batch closes).
    inspector = sa.inspect(bind)
    lead_indexes = (
        {idx["name"] for idx in inspector.get_indexes(_LEAD_TABLE)} if inspector.has_table(_LEAD_TABLE) else set()
    )
    if (
        inspector.has_table(_LEAD_TABLE)
        and "contact_id" in _columns(inspector, _LEAD_TABLE)
        and "ix_oe_property_dev_lead_contact_id" not in lead_indexes
    ):
        op.create_index(
            "ix_oe_property_dev_lead_contact_id",
            _LEAD_TABLE,
            ["contact_id"],
        )

    # ── Buyer.contact_id ────────────────────────────────────────────
    buyer_cols = _columns(inspector, _BUYER_TABLE)
    if _BUYER_TABLE in inspector.get_table_names() and "contact_id" not in buyer_cols:
        with op.batch_alter_table(_BUYER_TABLE) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "contact_id",
                    sa.CHAR(36),
                    nullable=True,
                ),
            )
            try:
                batch_op.create_foreign_key(
                    "fk_oe_property_dev_buyer_contact_id",
                    _CONTACT_TABLE,
                    ["contact_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
            except Exception:  # noqa: BLE001
                pass

    inspector = sa.inspect(bind)
    buyer_indexes = (
        {idx["name"] for idx in inspector.get_indexes(_BUYER_TABLE)} if inspector.has_table(_BUYER_TABLE) else set()
    )
    if (
        inspector.has_table(_BUYER_TABLE)
        and "contact_id" in _columns(inspector, _BUYER_TABLE)
        and "ix_oe_property_dev_buyer_contact_id" not in buyer_indexes
    ):
        op.create_index(
            "ix_oe_property_dev_buyer_contact_id",
            _BUYER_TABLE,
            ["contact_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table(_BUYER_TABLE) and "contact_id" in _columns(inspector, _BUYER_TABLE):
        buyer_indexes = {idx["name"] for idx in inspector.get_indexes(_BUYER_TABLE)}
        if "ix_oe_property_dev_buyer_contact_id" in buyer_indexes:
            op.drop_index("ix_oe_property_dev_buyer_contact_id", _BUYER_TABLE)
        with op.batch_alter_table(_BUYER_TABLE) as batch_op:
            try:
                batch_op.drop_constraint(
                    "fk_oe_property_dev_buyer_contact_id",
                    type_="foreignkey",
                )
            except Exception:  # noqa: BLE001
                pass
            batch_op.drop_column("contact_id")

    inspector = sa.inspect(bind)
    if inspector.has_table(_LEAD_TABLE) and "contact_id" in _columns(inspector, _LEAD_TABLE):
        lead_indexes = {idx["name"] for idx in inspector.get_indexes(_LEAD_TABLE)}
        if "ix_oe_property_dev_lead_contact_id" in lead_indexes:
            op.drop_index("ix_oe_property_dev_lead_contact_id", _LEAD_TABLE)
        with op.batch_alter_table(_LEAD_TABLE) as batch_op:
            try:
                batch_op.drop_constraint(
                    "fk_oe_property_dev_lead_contact_id",
                    type_="foreignkey",
                )
            except Exception:  # noqa: BLE001
                pass
            batch_op.drop_column("contact_id")

    inspector = sa.inspect(bind)
    if inspector.has_table(_CONTACT_TABLE):
        contact_cols = _columns(inspector, _CONTACT_TABLE)
        if "custom_properties" in contact_cols:
            with op.batch_alter_table(_CONTACT_TABLE) as batch_op:
                batch_op.drop_column("custom_properties")
        if "module_tags" in contact_cols:
            with op.batch_alter_table(_CONTACT_TABLE) as batch_op:
                batch_op.drop_column("module_tags")

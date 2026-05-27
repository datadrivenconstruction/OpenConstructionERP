# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""property_dev: buyer-portal magic-link tokens.

Creates ``oe_propdev_portal_token`` — an audit + revocation registry for
the buyer self-service portal magic-links. Each row is the persisted
counterpart of a ``scope='portal'`` JWT issued at SPA / Reservation
creation time. The JWT stays stateless on the wire (so verification
needs only ``JWT_SECRET``), but the row keeps:

* the ``jti`` (JWT id) — primary lookup key for revocation. A revoked
  token is rejected on the next verify regardless of its in-flight JWT.
* the buyer / reservation / SPA scope — used by the per-token IDOR
  guard so the buyer cannot read another buyer's docs even if their
  token grants the same ``scope='portal'`` claim.
* an audit trail (``issued_at`` / ``last_used_at`` / ``last_used_ip``)
  for the regulator-friendly report ("who downloaded which signed
  contract page on which date from which IP").

The table is intentionally lightweight — no FK on ``oe_property_dev_*``
follows the property_dev cross-table convention (loose UUID, no FK)
except for ``buyer_id`` which we DO foreign-key because cascade-delete
on a removed buyer should evict their tokens.

Idempotent. ``server_default`` on every NOT NULL column per the v3119
fresh-install lock-cascade lesson (Python ``default=`` is ignored by
SQLAlchemy ``create_all`` — DB-level default is the only safe path).

Revision ID: v3124_propdev_portal_tokens
Revises: v3123_boq_fk_indexes
Create Date: 2026-05-24
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3126_propdev_portal_tokens"
down_revision: Union[str, Sequence[str], None] = "v3125_propdev_pricing_engine"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_propdev_portal_token"

_INDEXES: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    # (name, cols, unique)
    ("ix_oe_propdev_portal_token_buyer_id", ("buyer_id",), False),
    ("ix_oe_propdev_portal_token_jwt_id", ("jwt_id",), True),
    ("ix_oe_propdev_portal_token_reservation_id", ("reservation_id",), False),
    (
        "ix_oe_propdev_portal_token_sales_contract_id",
        ("sales_contract_id",),
        False,
    ),
)


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    index: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(ix["name"] == index for ix in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)

    if not _has_table(inspector, _TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "buyer_id",
                guid_type,
                sa.ForeignKey("oe_property_dev_buyer.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "reservation_id",
                guid_type,
                sa.ForeignKey("oe_property_dev_reservation.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "sales_contract_id",
                guid_type,
                sa.ForeignKey("oe_property_dev_sales_contract.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("jwt_id", sa.String(64), nullable=False, server_default=""),
            sa.Column(
                "issued_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "expires_at",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column(
                "revoked_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "last_used_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column("last_used_ip", sa.String(64), nullable=True),
            sa.Column(
                "issued_by_user_id",
                guid_type,
                nullable=True,
            ),
        )

    for index_name, cols, unique in _INDEXES:
        if not _has_index(inspector, _TABLE, index_name):
            op.create_index(index_name, _TABLE, list(cols), unique=unique)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for index_name, _cols, _unique in reversed(_INDEXES):
        if _has_index(inspector, _TABLE, index_name):
            op.drop_index(index_name, table_name=_TABLE)

    if _has_table(inspector, _TABLE):
        op.drop_table(_TABLE)

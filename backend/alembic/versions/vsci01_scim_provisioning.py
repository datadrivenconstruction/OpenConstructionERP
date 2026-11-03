# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""SCIM provisioning: IdP identity on users, groups and group membership

Adds ``external_id`` (unique) and ``provisioned_by`` to ``oe_users_user`` and creates
``oe_scim_group`` and ``oe_scim_group_member``.

Revision ID: vsci01_scim_provisioning
Revises: vai01_doc_assistant_agent_catalogue
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "vsci01_scim_provisioning"
down_revision: str | Sequence[str] | None = "vpar01_partner_api_keys_webhooks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_USER = "oe_users_user"
_GROUP = "oe_scim_group"
_MEMBER = "oe_scim_group_member"
_IX = "ix_oe_users_user_external_id"


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    if _USER in tables:
        cols = {c["name"] for c in insp.get_columns(_USER)}
        if "external_id" not in cols:
            op.add_column(_USER, sa.Column("external_id", sa.String(255), nullable=True))
        if "provisioned_by" not in cols:
            op.add_column(_USER, sa.Column("provisioned_by", sa.String(20), nullable=True))
        if _IX not in {i["name"] for i in insp.get_indexes(_USER)}:
            op.create_index(_IX, _USER, ["external_id"], unique=True)
    if _GROUP not in tables:
        op.create_table(
            _GROUP,
            sa.Column("id", GUID(), primary_key=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("external_id", sa.String(255), nullable=True),
            sa.Column("display_name", sa.String(255), nullable=False),
            sa.Column("role", sa.String(50), nullable=True),
            sa.UniqueConstraint("external_id", name="uq_oe_scim_group_external_id"),
            sa.UniqueConstraint("display_name", name="uq_oe_scim_group_display_name"),
        )
    if _MEMBER not in tables:
        op.create_table(
            _MEMBER,
            sa.Column(
                "group_id",
                GUID(),
                sa.ForeignKey(
                    f"{_GROUP}.id", ondelete="CASCADE", name="fk_oe_scim_group_member_group_id_oe_scim_group"
                ),
                primary_key=True,
            ),
            sa.Column(
                "user_id",
                GUID(),
                sa.ForeignKey(f"{_USER}.id", ondelete="CASCADE", name="fk_oe_scim_group_member_user_id_oe_users_user"),
                primary_key=True,
            ),
        )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    tables = set(insp.get_table_names())
    if _MEMBER in tables:
        op.drop_table(_MEMBER)
    if _GROUP in tables:
        op.drop_table(_GROUP)
    if _USER in tables:
        if _IX in {i["name"] for i in insp.get_indexes(_USER)}:
            op.drop_index(_IX, table_name=_USER)
        cols = {c["name"] for c in insp.get_columns(_USER)}
        for col in ("provisioned_by", "external_id"):
            if col in cols:
                op.drop_column(_USER, col)

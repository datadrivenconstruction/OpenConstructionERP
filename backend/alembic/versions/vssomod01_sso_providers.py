# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""sso providers and single-use values

New tables for per-tenant OIDC / SAML identity providers and replay protection, and the SSO
subject on ``oe_users_user`` becomes unique per ``(oidc_issuer, oidc_sub)`` instead of alone.
Schema only and idempotent: create_all on an existing install makes the same tables.

Revision ID: vssomod01_sso_providers
Revises: vsodp01_budget_ledger_preparers
Create Date: 2026-11-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vssomod01_sso_providers"
down_revision: str | Sequence[str] | None = "vsodp01_budget_ledger_preparers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_P = "oe_sso_provider"
_O = "oe_sso_one_time"
_USER = "oe_users_user"
_SUB_IX = "ix_oe_users_user_oidc_sub"
_PAIR_UQ = "uq_oe_users_user_oidc_issuer_sub"


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def _scope_subject_to_issuer(inspector: sa.Inspector) -> None:
    for uq in inspector.get_unique_constraints(_USER):
        if uq.get("column_names") == ["oidc_sub"] and uq.get("name"):
            op.drop_constraint(uq["name"], _USER, type_="unique")
    indexes = {ix["name"]: ix for ix in inspector.get_indexes(_USER)}
    sub_ix = indexes.get(_SUB_IX)
    if sub_ix is not None and sub_ix.get("unique"):
        op.drop_index(_SUB_IX, table_name=_USER)
        sub_ix = None
    if sub_ix is None:
        op.create_index(_SUB_IX, _USER, ["oidc_sub"])
    if _PAIR_UQ not in indexes:
        op.create_index(_PAIR_UQ, _USER, ["oidc_issuer", "oidc_sub"], unique=True)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if _USER in tables:
        _scope_subject_to_issuer(inspector)
    if _P not in tables:
        op.create_table(
            _P,
            *_base(),
            sa.Column("slug", sa.String(64), nullable=False),
            sa.Column("display_name", sa.String(255), nullable=False),
            sa.Column("protocol", sa.String(10), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("tenant_id", sa.String(64), nullable=True),
            sa.Column("email_domains", sa.JSON(), nullable=False),
            sa.Column("auto_create_users", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("default_role", sa.String(20), nullable=False, server_default="viewer"),
            sa.Column("group_attribute", sa.String(255), nullable=False, server_default="groups"),
            sa.Column("group_role_map", sa.JSON(), nullable=False),
            sa.Column("allow_admin_mapping", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("clock_skew_seconds", sa.Integer(), nullable=False, server_default="120"),
            sa.Column("link_by_email", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("oidc_issuer", sa.String(500), nullable=True),
            sa.Column("oidc_client_id", sa.String(255), nullable=True),
            sa.Column("oidc_client_secret_enc", sa.Text(), nullable=True),
            sa.Column("oidc_scopes", sa.String(255), nullable=False, server_default="openid email profile"),
            sa.Column("saml_idp_entity_id", sa.String(500), nullable=True),
            sa.Column("saml_idp_sso_url", sa.String(1000), nullable=True),
            sa.Column("saml_idp_cert", sa.Text(), nullable=True),
            sa.Column("saml_sp_entity_id", sa.String(500), nullable=True),
            sa.Column("saml_email_attribute", sa.String(255), nullable=False, server_default="email"),
            sa.Column("saml_name_attribute", sa.String(255), nullable=False, server_default="displayName"),
            sa.Column("saml_allow_idp_initiated", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.create_index(f"ix_{_P}_slug", _P, ["slug"], unique=True)
        op.create_index(f"ix_{_P}_tenant_id", _P, ["tenant_id"])
    if _O not in tables:
        op.create_table(
            _O,
            *_base(),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("value", sa.String(255), nullable=False),
            sa.Column("provider_slug", sa.String(64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("data", sa.JSON(), nullable=False),
            sa.UniqueConstraint("kind", "value", name="uq_oe_sso_one_time_kind_value"),
        )
        op.create_index(f"ix_{_O}_expires_at", _O, ["expires_at"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for table in (_O, _P):
        if table in tables:
            op.drop_table(table)
    if _USER in tables and _PAIR_UQ in {ix["name"] for ix in inspector.get_indexes(_USER)}:
        op.drop_index(_PAIR_UQ, table_name=_USER)

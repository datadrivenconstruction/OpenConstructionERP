# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""sso providers and single-use values

New tables for per-tenant OIDC / SAML identity providers and replay protection.
Create-only and idempotent: create_all on an existing install makes the same tables.

Revision ID: vsso01_sso_providers
Revises: vpc01_project_country_from_region
Create Date: 2026-11-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vsso01_sso_providers"
down_revision: str | Sequence[str] | None = "vpc01_project_country_from_region"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_P = "oe_sso_provider"
_O = "oe_sso_one_time"


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
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
    op.drop_table(_O)
    op.drop_table(_P)

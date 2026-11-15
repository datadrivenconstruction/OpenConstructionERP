# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""SSO ORM models.

Tables:
    oe_sso_provider - one identity provider (OIDC or SAML) per row, optionally scoped to a tenant
    oe_sso_one_time - single-use values: pending SAML request IDs, consumed assertion IDs,
                      OIDC nonces and login hand-off codes (replay protection)
"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SsoProvider(Base):
    """An identity provider. Secrets are stored encrypted (app.core.crypto)."""

    __tablename__ = "oe_sso_provider"

    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    protocol: Mapped[str] = mapped_column(String(10), nullable=False)  # "oidc" | "saml"
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Email domains routed to this provider on the login page (home realm discovery).
    email_domains: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # JIT provisioning and role mapping
    auto_create_users: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer")
    group_attribute: Mapped[str] = mapped_column(String(255), nullable=False, default="groups")
    group_role_map: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    allow_admin_mapping: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    clock_skew_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    # Link an existing local account by email. OIDC also needs email_verified=true in the ID token.
    link_by_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # OIDC
    oidc_issuer: Mapped[str | None] = mapped_column(String(500), nullable=True)
    oidc_client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oidc_client_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    oidc_scopes: Mapped[str] = mapped_column(String(255), nullable=False, default="openid email profile")

    # SAML (we are the SP)
    saml_idp_entity_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    saml_idp_sso_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    saml_idp_cert: Mapped[str | None] = mapped_column(Text, nullable=True)
    saml_sp_entity_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    saml_email_attribute: Mapped[str] = mapped_column(String(255), nullable=False, default="email")
    saml_name_attribute: Mapped[str] = mapped_column(String(255), nullable=False, default="displayName")
    # Accept responses the IdP sends without a prior SP request.
    saml_allow_idp_initiated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return f"<SsoProvider {self.slug} ({self.protocol})>"


class SsoOneTime(Base):
    """A single-use value; the unique key makes a second consume fail."""

    __tablename__ = "oe_sso_one_time"
    __table_args__ = (UniqueConstraint("kind", "value", name="uq_oe_sso_one_time_kind_value"),)

    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_slug: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    data: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


__all__ = ["SsoOneTime", "SsoProvider"]

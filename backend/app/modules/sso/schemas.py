# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""SSO request and response schemas."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["admin", "manager", "editor", "viewer"]


class ProviderBase(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    enabled: bool = True
    tenant_id: str | None = Field(default=None, max_length=64)
    email_domains: list[str] = Field(default_factory=list, max_length=50)
    auto_create_users: bool = True
    default_role: Role = "viewer"
    group_attribute: str = Field(default="groups", max_length=255)
    group_role_map: dict[str, str] = Field(default_factory=dict)
    allow_admin_mapping: bool = False
    clock_skew_seconds: int = 120
    link_by_email: bool = False
    saml_allow_idp_initiated: bool = False
    oidc_issuer: str | None = Field(default=None, max_length=500)
    oidc_client_id: str | None = Field(default=None, max_length=255)
    oidc_scopes: str = Field(default="openid email profile", max_length=255)
    saml_idp_entity_id: str | None = Field(default=None, max_length=500)
    saml_idp_sso_url: str | None = Field(default=None, max_length=1000)
    saml_idp_cert: str | None = Field(default=None, max_length=20000)
    saml_sp_entity_id: str | None = Field(default=None, max_length=500)
    saml_email_attribute: str = Field(default="email", max_length=255)
    saml_name_attribute: str = Field(default="displayName", max_length=255)


class ProviderCreate(ProviderBase):
    slug: str = Field(min_length=2, max_length=64)
    protocol: Literal["oidc", "saml"]
    oidc_client_secret: str | None = Field(default=None, max_length=2000)


class ProviderUpdate(BaseModel):
    """Every field optional; ``oidc_client_secret`` empty string clears it, absent keeps it."""

    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    enabled: bool | None = None
    tenant_id: str | None = Field(default=None, max_length=64)
    email_domains: list[str] | None = Field(default=None, max_length=50)
    auto_create_users: bool | None = None
    default_role: Role | None = None
    group_attribute: str | None = Field(default=None, max_length=255)
    group_role_map: dict[str, str] | None = None
    allow_admin_mapping: bool | None = None
    clock_skew_seconds: int | None = None
    link_by_email: bool | None = None
    saml_allow_idp_initiated: bool | None = None
    oidc_issuer: str | None = Field(default=None, max_length=500)
    oidc_client_id: str | None = Field(default=None, max_length=255)
    oidc_client_secret: str | None = Field(default=None, max_length=2000)
    oidc_scopes: str | None = Field(default=None, max_length=255)
    saml_idp_entity_id: str | None = Field(default=None, max_length=500)
    saml_idp_sso_url: str | None = Field(default=None, max_length=1000)
    saml_idp_cert: str | None = Field(default=None, max_length=20000)
    saml_sp_entity_id: str | None = Field(default=None, max_length=500)
    saml_email_attribute: str | None = Field(default=None, max_length=255)
    saml_name_attribute: str | None = Field(default=None, max_length=255)


class ProviderOut(ProviderBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    protocol: str
    has_client_secret: bool = False
    sp_entity_id: str | None = None
    acs_url: str | None = None
    metadata_url: str | None = None


class PublicProvider(BaseModel):
    """What the login page may see: no secrets, no mapping."""

    slug: str
    display_name: str
    protocol: str
    login_url: str | None = None


class PublicProviders(BaseModel):
    saml_available: bool
    providers: list[PublicProvider]


class OidcStart(BaseModel):
    authorization_endpoint: str
    client_id: str
    scopes: str


class OidcCallback(BaseModel):
    code: str = Field(min_length=1, max_length=4096)
    code_verifier: str = Field(default="", max_length=256)
    nonce: str = Field(min_length=8, max_length=256)
    redirect_uri: str = Field(min_length=1, max_length=1000)


class HandoffIn(BaseModel):
    code: str = Field(min_length=16, max_length=128)


class Capabilities(BaseModel):
    saml_available: bool

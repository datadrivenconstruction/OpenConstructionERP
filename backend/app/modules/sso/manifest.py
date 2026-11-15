# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""SSO module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_sso",
    version="1.0.0",
    display_name="Single Sign-On",
    description=(
        "Company sign-in through OpenID Connect or SAML 2.0 identity providers, configured per tenant. "
        "Accounts are created on first sign-in, roles follow IdP groups and SCIM-provisioned people are "
        "linked, not duplicated. SAML needs the optional [sso] extra."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users"],
    auto_install=True,
    enabled=True,
)

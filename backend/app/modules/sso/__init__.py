# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Single sign-on: per-tenant OIDC and SAML 2.0 identity providers with JIT provisioning."""

from app.modules.sso.manifest import manifest

__all__ = ["manifest", "on_startup"]


async def on_startup() -> None:
    """Register validation rules."""
    from app.modules.sso.validators import register_sso_rules

    register_sso_rules()

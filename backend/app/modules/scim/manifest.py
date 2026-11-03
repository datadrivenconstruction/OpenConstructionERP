# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""SCIM provisioning module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_scim",
    version="1.0.0",
    display_name="SCIM Provisioning",
    description=(
        "SCIM 2.0 server for Users and Groups: the company identity provider creates people, changes "
        "their role through admin-mapped groups and removes access when they leave. Soft deactivation "
        "revokes sessions and API keys; the audit log records each change."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users"],
    auto_install=True,
    enabled=True,
)

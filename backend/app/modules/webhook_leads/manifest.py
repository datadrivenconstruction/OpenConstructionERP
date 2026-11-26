# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Webhook Leads module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.webhook_leads.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_webhook_leads",
    version="0.1.0",
    display_name="Webhook Leads",
    description=(
        "Secure incoming webhook endpoints that auto-create CRM leads from "
        "external sources (marketing forms, ad platforms, other CRMs). "
        "Per-source API key / HMAC / JWT auth, IP allowlisting, rate "
        "limiting, payload mapping, and full audit logging."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_crm"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)

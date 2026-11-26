# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Inbound capture module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.inbound_capture.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_inbound_capture",
    version="0.1.0",
    display_name="Inbound Capture Gateway",
    description=(
        "Captures correspondence that reaches a project from outside the app - a "
        "forwarded email, a chat / generic webhook, an SMS gateway - normalises "
        "each ad-hoc payload to one canonical message shape via the pure inbound "
        "normalizer, and persists it as an incoming correspondence record. "
        "Capture is idempotent on the provider's own message id, so a retried "
        "delivery never doubles up, and provider webhooks are authenticated "
        "through a per-provider signature-verification seam."
    ),
    author="OpenConstructionERP Core Team",
    category="integration",
    depends=["oe_correspondence", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)

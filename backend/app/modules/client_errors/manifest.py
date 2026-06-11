# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Client-error sink module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_client_errors",
    version="1.0.0",
    display_name="Client Error Sink",
    description=(
        "Receives anonymised JS error reports from the frontend errorLogger "
        "and forwards them to the standard logging pipeline at WARNING level. "
        "Per-IP rate limited at 30/min. No DB storage in v4.2.x."
    ),
    author="OpenConstructionERP Core Team",
    category="infra",
    depends=[],
    auto_install=True,
    enabled=True,
)

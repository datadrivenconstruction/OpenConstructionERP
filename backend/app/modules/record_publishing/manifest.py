# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Record Publishing module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.record_publishing.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_record_publishing",
    version="1.0.0",
    display_name="Record Publishing",
    description=(
        "Publish a project record - a daily site diary today, meeting minutes "
        "and inspection reports next - as one signed PDF and distribute it to a "
        "named set of recipients who acknowledge receipt, all in a single "
        "action. A thin orchestrator over the record renderers, the storage "
        "backend and the file-transmittals engine, so it adds no tables."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_users"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)

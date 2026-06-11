# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Transmittals (W7) module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_file_transmittals",
    version="1.0.0",
    display_name="File Transmittals",
    description=(
        "Formal send-records for project files: who sent which files to "
        "which recipients on which date, for which reason. Each "
        "transmittal mints an auto-numbered cover sheet (PDF when "
        "reportlab is available, structured plain text otherwise) and "
        "single-use acknowledgement tokens for recipients."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_users"],
    auto_install=True,
    enabled=True,
)

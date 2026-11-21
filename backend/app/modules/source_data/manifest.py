# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Source-data register module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.source_data.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_source_data",
    version="0.1.0",
    display_name="Source Data Register",
    description=(
        "Project register of the prerequisite source documents a delivery "
        "depends on before work can start - permits, surveys, geotechnical "
        "reports, technical conditions, title deeds, approvals and technical "
        "specifications - with validity windows, renewal reminders, a "
        "completeness checklist and a schedule-blocking flag. Jurisdiction-"
        "neutral: the register tracks what a document is and when it is valid; "
        "regional packs supply the country-specific vocabularies."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Mine survey module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.mine_survey.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_mine_survey",
    version="0.1.0",
    display_name="Mine Survey",
    description=(
        "Monthly mine reconciliation: plan against the surveyed volume of each pit, bench, block, stope or drive, "
        "compliance against a band, truck-count tonnes against survey tonnes, and the confirmed volume added to "
        "the contractor progress claim. The actual always comes from a Volumes calculation, never from typing."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_survey_core", "oe_surfaces_volumes"],
    optional_depends=["oe_boq", "oe_progress"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)

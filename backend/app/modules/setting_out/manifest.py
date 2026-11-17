# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Setting-out module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_setting_out",
    version="0.1.0",
    display_name="Setting-out",
    description=(
        "Stakeout requests from design points or an alignment (chainage and offset), measured stakes "
        "checked against a tolerance profile with an instant pass or fail, an NCR draft for every failed "
        "stake, and a printable setting-out sheet. Tolerance profiles come from the project or the active "
        "country pack; core ships only a labelled demo profile."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_survey_core"],
    optional_depends=["oe_ncr", "oe_boq"],
    auto_install=True,
    enabled=True,
)

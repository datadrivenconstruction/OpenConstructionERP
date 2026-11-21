# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site-prep module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.site_prep.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_site_prep",
    version="1.0.0",
    display_name="Site Mobilisation Readiness",
    description=(
        "Pre-construction mobilisation and site-setup readiness. A per-project "
        "plan with a target commencement date and a checklist of readiness items "
        "grouped by mobilisation category (access, welfare and accommodation, "
        "temporary utilities, security and hoarding, temporary works, "
        "environmental controls, logistics and laydown, permits and consents, "
        "inductions and training). Items flagged as hard prerequisites become "
        "commencement gates, and the module derives per-category and overall "
        "readiness percentages, the gate status, and the blocked and overdue "
        "lists so a site manager can see at a glance whether the site is ready to "
        "start."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    # Hard dep supplies the project scope every table foreign-keys into.
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)

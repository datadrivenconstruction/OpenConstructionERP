# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Deformation monitoring module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.monitoring.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_monitoring",
    version="0.1.0",
    display_name="Deformation Monitoring",
    description=(
        "Settlement and deformation monitoring from imported readings: monitoring points, epochs, "
        "displacement against the baseline, rate per day and alert, action and alarm levels from a "
        "threshold profile. A crossed level sends a notification and, from Action up, opens a risk draft. "
        "Thresholds come from the project or the active country pack; core ships only a labelled demo profile."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_survey_core"],
    optional_depends=["oe_notifications", "oe_risk"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)

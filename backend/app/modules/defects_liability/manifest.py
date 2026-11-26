# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Defects-liability module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.defects_liability.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_defects_liability",
    version="1.0.0",
    display_name="Defects Liability Register",
    description=(
        "Post-handover warranty and defects-liability-period (DLP) register for "
        "the construction rectification phase. After handover the contractor and "
        "its subcontractors remain liable to make good defects for a defined "
        "period, and elements carry workmanship or manufacturer warranties. Each "
        "entry records what is covered, the responsible subcontractor and work "
        "package, the warranty type (workmanship, manufacturer, latent defect, "
        "extended, other), the handover and warranty dates, and the key DLP end "
        "date, alongside the defect notices raised against it. The module derives "
        "the per-status and per-warranty-type counts, the expiring and expired "
        "lists, the open and overdue defect load, a per-subcontractor health "
        "view, an overall health score, and the single most useful signal: which "
        "entries have a finished DLP with no outstanding defects and are clear "
        "for the final retention money to be released."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    # Hard dep supplies the project scope every table foreign-keys into.
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)

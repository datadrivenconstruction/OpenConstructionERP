# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Forms & Checklists module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.forms.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_forms",
    version="1.0.0",
    display_name="Forms & Checklists",
    description=(
        "A template builder plus a reusable library for the forms and checklists "
        "site teams fill in every day - safety inductions, concrete-pour acceptance, "
        "snag and handover lists. Compose a template from ordered fields once, then "
        "fill it into a project submission on a phone or tablet, save a draft, "
        "complete it, and export the result to PDF. Templates are versioned by "
        "snapshot so editing one never corrupts the forms already submitted against it."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    # Submissions hang off a project (oe_projects); attribution + permissions
    # come from the users module. Both are hard dependencies so the load order
    # is correct and neither can be disabled while forms data still references it.
    depends=["oe_projects", "oe_users"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)

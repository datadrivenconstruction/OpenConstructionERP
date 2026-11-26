# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Documents and templates module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.doc_templates.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_doc_templates",
    version="1.0.0",
    display_name="Documents & templates",
    description=(
        "Wording of every PDF and email a firm sends, per language, with merge fields, a server preview "
        "on a real record, published versions with restore and reset, and locked legal notes from the "
        "country pack."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users"],
    optional_depends=["oe_tendering", "oe_letter_templates", "oe_finance", "oe_changeorders", "oe_offers"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)

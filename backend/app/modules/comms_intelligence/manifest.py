# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Comms Intelligence module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_comms_intelligence",
    version="0.1.0",
    display_name="Comms Intelligence",
    description=(
        "Smart layer over project correspondence - classifies inbound "
        "messages, extracts prices, quote numbers, dates and commitments, "
        "suggests links and deadlines, drafts replies and chase-ups, and "
        "surfaces who owes whom a response. AI-augmented, human-confirmed."
    ),
    author="Projects Team",
    category="community",
    # Correspondence is the substrate; ai supplies the provider client and
    # per-user settings row. Both are core auto-install modules.
    depends=["oe_users", "oe_projects", "oe_correspondence", "oe_ai"],
    optional_depends=["oe_contacts", "oe_rfi", "oe_inbound_capture"],
    auto_install=False,
    enabled=True,
)

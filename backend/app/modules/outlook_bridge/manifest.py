# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Outlook Bridge module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_outlook_bridge",
    version="0.1.0",
    display_name="Outlook Bridge",
    description=(
        "Desktop Outlook link: register emails open as signed Outlook drafts "
        "(Send stays human), and the same payload downloads as an editable "
        ".eml on any platform. This build does not read a mailbox."
    ),
    author="Projects Team",
    category="integration",
    depends=["oe_users", "oe_projects", "oe_correspondence", "oe_inbound_capture"],
    optional_depends=["oe_contacts", "oe_rfq_bidding", "oe_comms_intelligence"],
    auto_install=False,
    enabled=True,
)

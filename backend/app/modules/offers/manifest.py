"""Customer offer module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_offers",
    version="1.0.0",
    display_name="Customer offers",
    description=(
        "Turns an estimate into the offer a customer receives: numbered, revisioned and frozen once sent, "
        "with market-specific titles, tax and consumer rules from the country pack, a payment schedule, "
        "reusable texts, a PDF built for the envelope window, and award to a client contract on acceptance."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_boq", "oe_projects", "oe_contacts"],
    optional_depends=["oe_contracts", "oe_estimate_basis"],
    auto_install=True,
    enabled=True,
)

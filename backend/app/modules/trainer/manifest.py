# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Trainer (Academy) module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_trainer",
    version="0.1.0",
    display_name="Trainer",
    description="Paid course trainer: enrolments, learning lock, deterministic checking",
    author="OpenConstructionERP Core Team",
    category="business",
    # The checker reads the learner's BOQ, bid package, contract, claims and
    # variations, and the seeder writes them through those modules' services.
    depends=[
        "oe_users",
        "oe_projects",
        "oe_boq",
        "oe_bid_management",
        "oe_contracts",
        "oe_variations",
        "oe_progress",
    ],
    optional_depends=["oe_notifications", "oe_finance"],
    # Always loaded, inert unless ``settings.academy_mode`` is on: the routes
    # answer 404 and the event handlers return at once. ``module_states.json``
    # is global, so the env flag is the only switch.
    auto_install=True,
    enabled=True,
)

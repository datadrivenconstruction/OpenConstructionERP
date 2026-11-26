# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Onboarding module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.onboarding.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_onboarding",
    version="0.1.0",
    display_name="Onboarding",
    description=(
        "Non-blocking first-run provisioning. Runs the heavy first-run loads "
        "(regional cost base import, sample project install) as background jobs "
        "so the wizard never makes a new user wait, exposing a progress feed the "
        "UI polls and a banner that keeps working after the user has moved on."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_costs", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)

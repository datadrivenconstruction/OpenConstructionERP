# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""AI Estimation module manifest."""

from app.core.module_loader import InferenceDeclaration, InferenceRole, ModuleManifest
from app.modules.ai.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_ai",
    version="0.1.0",
    display_name="AI Estimation",
    description="AI-powered construction cost estimation from text descriptions and photos",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_boq", "oe_projects"],
    auto_install=True,
    enabled=True,
    inference=InferenceDeclaration(
        role=InferenceRole.CALLS_MODEL,
        what=(
            "Cost estimates, quantity suggestions and free-text answers, from a description or a "
            "photograph a user supplied, through whichever hosted provider that user configured"
        ),
        basis=(
            "This module is the provider layer itself: ai_client.py holds the call for every hosted "
            "provider the platform supports, and no key ships with the product, so nothing here "
            "infers anything until an operator supplies credentials of their own"
        ),
    ),
    data_paths=DATA_PATHS,
)

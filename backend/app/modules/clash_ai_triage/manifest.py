# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Clash AI Triage module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.clash_ai_triage.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_clash_ai_triage",
    version="1.0.0",
    display_name="Clash AI Triage",
    description=(
        "LLM-assisted clash triage with confidence scores and a visible, "
        "user-tunable prompt. Each triage persists the full prompt + raw "
        "response for audit, exposes a category + suggested action + "
        "confidence, and supports replay against a new prompt version."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_clash", "oe_projects", "oe_ai"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)

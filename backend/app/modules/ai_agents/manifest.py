# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""AI Agents module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.ai_agents.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_ai_agents",
    version="0.1.0",
    display_name="AI Agents",
    description=(
        "ReAct-style agent loop (reason -> call tool -> observe -> repeat) "
        "on top of the AI module. Tool registry, per-run history, mock-friendly "
        "LLM bridge. Slice 1: sample BOQ-drafter agent."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_ai", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)

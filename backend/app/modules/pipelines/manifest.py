# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Pipeline Builder module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_pipelines",
    version="0.1.0",
    display_name="Pipeline Builder",
    description=(
        "Visual node-graph automation builder - wraps the existing JobRun "
        "runner, validation engine and per-module services as draggable, "
        "gate-able pipeline nodes"
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects", "oe_validation"],
    auto_install=False,
    enabled=True,
)

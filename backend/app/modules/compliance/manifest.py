# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Compliance DSL module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_compliance",
    version="0.1.0",
    display_name="Compliance DSL",
    description=(
        "Author validation rules as YAML/JSON snippets without writing "
        "Python. Persists rule definitions and registers them with the "
        "global validation rule registry at startup."
    ),
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users"],
    auto_install=True,
    enabled=True,
)

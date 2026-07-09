"""ACAP module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_acap",
    version="0.1.0",
    display_name="AI Civil Architecture Platform",
    description="ACAP: LLM floor-plan generation, deterministic RAB (SNI/AHSP), timeline, visual render",
    author="Ali Sadikin",
    category="core",
    depends=[],
    auto_install=True,
    enabled=True,
)

"""Requirements & Quality Gates module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_requirements",
    version="0.1.0",
    display_name="Requirements & Quality Gates",
    description="Extract, validate, and track construction requirements using EAC triplets",
    author="Data Driven Construction",
    category="core",
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
)

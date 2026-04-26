# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""EAC v2 Engine module manifest.

Wave EAC-1.1 + EAC-1.2 of RFC 35: foundational ORM layer plus
``EacRuleDefinition`` JSON Schema + Pydantic mirror + scaffolded
CRUD API. Subsequent waves (EAC-1.3 validator/planner, EAC-1.4
executor, etc.) build on top of these contracts.
"""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_eac",
    version="1.0.0",
    display_name="EAC v2 Engine",
    description=(
        "Single-kernel rules engine for QTO, validation, clash, and issue "
        "outputs. Stores rules as JSON definitions and evaluates them "
        "through DuckDB on DDC canonical Parquet (ADR 002 compliant)."
    ),
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
)

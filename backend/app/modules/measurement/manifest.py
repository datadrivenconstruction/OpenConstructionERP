# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Measurement module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_measurement",
    version="1.0.0",
    display_name="Measurement",
    description=(
        "Formula-based quantity take-off library: every quantity keeps the formula that produced it, with presets for REB 23.003, OENORM A 2063, NRM and CESMM."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=[],  # pure library; boq and others depend on us, not the other way
    auto_install=True,
    enabled=True,
)

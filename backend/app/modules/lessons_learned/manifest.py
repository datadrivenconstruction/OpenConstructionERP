# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Lessons learned module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_lessons_learned",
    version="1.0.0",
    display_name="Lessons Learned",
    description=(
        "Cross-project register of lessons captured at project closeout, tagged by trade, cost code and risk "
        "category. Estimate and risk screens show how many past projects met the same situation. Entirely "
        "manual: people write and confirm every lesson."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_projects"],
    optional_depends=["oe_risk", "oe_boq"],
    auto_install=True,
    enabled=True,
)

# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cutting optimisation module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_cutting",
    version="1.0.0",
    display_name="Cutting Optimisation",
    description=(
        "Cutting stock optimisation for bars, profiles, pipes, timber and sheets: "
        "turn a known cut list into cutting plans with yield, waste and cost, "
        "reuse offcuts from site inventory, return new offcuts to it, and propose "
        "the measured waste factor and stock quantity to the bill of quantities "
        "and the requisition for the estimator to confirm."
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_users", "oe_projects"],
    display_name_i18n={
        "de": "Zuschnittoptimierung",
        "ru": "Оптимизация раскроя",
        "es": "Optimización de cortes",
    },
    auto_install=True,
    enabled=True,
)

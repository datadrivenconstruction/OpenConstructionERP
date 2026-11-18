# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Statutory checks module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_statutory",
    version="1.0.0",
    display_name="Statutory Checks",
    display_name_i18n={
        "de": "Gesetzliche Prüfungen",
        "ru": "Проверки по закону",
    },
    description=(
        "Lien and notice deadlines, statutory retention limits and the sales tax treatment of a bid, computed "
        "from the law a regional pack contributes. Every date and limit carries its source; nothing is filed."
    ),
    author="OpenConstructionERP Core Team",
    category="compliance",
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
)

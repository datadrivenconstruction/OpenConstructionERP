# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module manifest for oe_us_pack."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_us_pack",
    version="1.0.0",
    display_name="Regional Pack - United States",
    display_name_i18n={
        "de": "Regionalpaket - Vereinigte Staaten",
        "ru": "Региональный пакет - США",
    },
    # The payment application is named by what it does. The well-known form
    # designations are a publisher's, and this pack's own config.py states they
    # must not appear in code, UI or API; this description is user-visible on
    # the module registry page, so it is one of the places that rule covers.
    description=(
        "US construction standards: progress payment applications with a continuation sheet, "
        "CSI MasterFormat divisions, imperial units, USD, and state sales-tax examples."
    ),
    author="OpenConstructionERP Core Team",
    category="regional",
    depends=[],
    markets=["US"],
    auto_install=False,
    enabled=True,
)

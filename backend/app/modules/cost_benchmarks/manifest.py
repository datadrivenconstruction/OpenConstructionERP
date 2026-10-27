# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ benchmarks module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_cost_benchmarks",
    version="1.0.0",
    display_name="Cost Benchmarks",
    description=(
        "Benchmarks from the company's own completed projects: final cost per m2 GFA and per "
        "functional unit and by element group (DIN 276, NRM 1, MasterFormat, Uniformat), normalised "
        "to one base date, location and reporting currency with the price indices, location factors "
        "and exchange rates on file. A new estimate is compared with comparable projects as a P10, "
        "P50, P90 band per element with outliers flagged; the open reference band covers types with "
        "no own history. Tenant scoped, with an anonymised export."
    ),
    author="OpenConstructionERP Core Team",
    category="estimation",
    depends=["oe_projects", "oe_boq", "oe_price_index", "oe_fx"],
    optional_depends=[],
    auto_install=True,
    enabled=True,
)

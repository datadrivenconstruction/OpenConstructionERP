# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dashboard rollup module manifest.

Distinct from ``oe_dashboards`` (plural, analytical Parquet/DuckDB
dashboards). This module exposes a single ``GET /api/v1/dashboard/rollup/``
endpoint that aggregates all 10 wave-2 widget payloads in one round-trip.
"""

from app.core.data_paths import DataPaths
from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_dashboard",
    version="1.1.0",
    display_name="Dashboard Rollup",
    description=(
        "Single-shot aggregation endpoint for the wave-2 dashboard widgets "
        "(BOQ summary, validation, clash, schedule, risk, HSE, procurement, "
        "budget, change orders, weather). Replaces the per-project N+1 "
        "fan-out the frontend used to do. Also serves the unified "
        "approvals/alerts inbox and the acknowledge/dismiss actions that let "
        "a user work through it."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DataPaths(reason="Reads other modules into dashboard widgets and writes nothing back"),
)

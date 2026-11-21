# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Admin module manifest.

Houses operator-only endpoints that bypass normal auth via shared-secret +
env-gate (e.g. qa-reset for crawler-driven test pipelines). Not loaded
automatically against production unless the operator opts in via env.
"""

from app.core.data_paths import DataPaths
from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_admin",
    version="0.1.0",
    display_name="Admin",
    description="Operator endpoints for QA pipelines (qa-reset, fixtures). Triple-gated by env+token+hostname.",
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
    data_paths=DataPaths(reason="Operator endpoints for QA pipelines; owns no project records"),
)

"""Admin module manifest.

Houses operator-only endpoints that bypass normal auth via shared-secret +
env-gate (e.g. qa-reset for crawler-driven test pipelines). Not loaded
automatically against production unless the operator opts in via env.
"""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_admin",
    version="0.1.0",
    display_name="Admin",
    description="Operator endpoints for QA pipelines (qa-reset, fixtures). Triple-gated by env+token+hostname.",
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_users", "oe_projects"],
    auto_install=True,
    enabled=True,
)

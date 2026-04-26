"""Background Jobs status module manifest.

Exposes read-only / cancel endpoints for the JobRun rows produced by the
generic Celery runner in :mod:`app.core.jobs`. The module is intentionally
thin — all heavy lifting lives in ``app/core/job*``; this package is just
the HTTP surface.
"""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_jobs",
    version="1.0.0",
    display_name="Background Jobs",
    description=(
        "Status, listing and cancellation surface for the platform-wide "
        "Celery job runner (RFC 34 §4 W0.1)."
    ),
    author="OpenEstimate Core Team",
    category="core",
    depends=[],
    auto_install=True,
    enabled=True,
)

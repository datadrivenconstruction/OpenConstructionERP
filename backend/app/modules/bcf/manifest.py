"""‌⁠‍BCF (BIM Collaboration Format) module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_bcf",
    version="1.0.0",
    display_name="BCF Issues & Viewpoints",
    description=(
        "Server-backed BCF 2.1 / 3.0 issue tracking: persistent topics, "
        "comments and viewpoints with full .bcfzip import/export roundtrip."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_users"],
    auto_install=True,
    enabled=True,
)

# Mount the OpenCDE BCF-API 3.0 REST surface as a sub-router of the
# module's main router (eventually served at ``/api/v1/bcf/3.0/...``).
#
# The module loader (re-)imports ``router.py`` to attach it to the app,
# so we install a one-shot import hook that injects the OpenCDE routes
# into the main router AT THE END of ``router.py``'s execution - that
# way they survive the loader's reload and end up in the FastAPI app
# alongside the file-based BCF endpoints.
from app.modules.bcf import _opencde_mount as _opencde_mount  # noqa: E402, F401

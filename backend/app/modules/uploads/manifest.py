"""Direct Uploads module manifest.

Wires the HMAC-signed PUT endpoint that consumes presigned URLs minted
by :meth:`app.core.storage.LocalStorageBackend.presigned_put_url`.
Without this module those URLs would point to nowhere on local-storage
deployments.
"""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_uploads",
    version="1.0.0",
    display_name="Direct Uploads",
    description="HMAC-signed direct PUT endpoint for LocalStorageBackend presigned URLs.",
    author="OpenConstructionERP Core",
    category="core",
    auto_install=True,
    enabled=True,
)

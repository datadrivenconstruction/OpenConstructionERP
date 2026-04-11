"""Collaboration locks module manifest.

Layer 1 of the real-time collaboration plan: pessimistic, per-row soft
locks with presence broadcast over a WebSocket.  Solves the 90% case
from GitHub issue #51 ("multiple estimators editing the same BOQ") without
pulling in a CRDT runtime.  Field-level OT (Yjs Y.Text) and full CRDT
rows are deferred to v1.5 / v2.0.
"""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_collaboration_locks",
    version="1.0.0",
    display_name="Real-time collaboration locks",
    description=(
        "Pessimistic soft locks with live presence broadcast. "
        "Prevents two estimators from overwriting each other on the same BOQ row."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_users"],
    auto_install=True,
    enabled=True,
)

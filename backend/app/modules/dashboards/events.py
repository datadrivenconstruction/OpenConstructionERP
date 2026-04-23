"""Event taxonomy for the dashboards module.

Events are published via :func:`app.core.events.publish` from service
methods on state changes. Consumers (activity feed, audit, integrity
refresh) subscribe through the wildcard handler in
``app.core.event_handlers``.

Never hand-craft event type strings at call sites — always import the
constant from here. This keeps the event contract greppable and prevents
typo-driven silent drift.
"""

from __future__ import annotations

from typing import Final

# ── Snapshot lifecycle ──────────────────────────────────────────────────────

SNAPSHOT_CREATED: Final = "snapshot.created"
"""Published after a new snapshot row + its Parquet files are durably
written. Payload: ``{snapshot_id, project_id, label, total_entities,
total_categories, tenant_id}``."""

SNAPSHOT_DELETED: Final = "snapshot.deleted"
"""Published after a snapshot row is removed (Parquet cleanup may still
be in flight — see ``SnapshotService.delete`` for orphan handling).
Payload: ``{snapshot_id, project_id, tenant_id}``."""

# ── Dashboard lifecycle ─────────────────────────────────────────────────────

DASHBOARD_SAVED: Final = "dashboard.saved"
"""Published on create or update of a dashboard spec.
Payload: ``{dashboard_id, workspace_id, scope, title, tenant_id}``."""

DASHBOARD_PROMOTED_TO_ORG: Final = "dashboard.promoted_to_org"
"""Published when an admin promotes a personal dashboard to org scope.
Payload: ``{dashboard_id, source_user_id, tenant_id}``."""

DASHBOARD_DELETED: Final = "dashboard.deleted"

# ── Supplementary data (T06) ────────────────────────────────────────────────

SUPPLEMENTARY_IMPORTED: Final = "supplementary.imported"
"""Published when a user imports a tabular file that gets attached to a
snapshot for joining. Payload: ``{supplementary_id, snapshot_id, name,
row_count, tenant_id}``."""

SOURCE_MODULE: Final = "oe_dashboards"
"""Value to pass as ``source_module`` when publishing any of the above."""

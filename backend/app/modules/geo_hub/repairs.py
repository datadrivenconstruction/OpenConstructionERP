"""Boot-path data repairs owned by the geo hub.

Imported by :func:`app.core.data_repairs.discover_data_repairs`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from app.core.data_repairs import DataRepair, register_data_repair

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def reconcile_project_locations(session: AsyncSession) -> int:
    """Make ``project.address`` coordinates and the geocoded anchor agree.

    Only anchors the server geocoded from the saved address text are used.
    Where the saved pair carries no provenance (written before it was
    recorded) and sits beyond the conflict threshold from the anchor, the
    anchor's point replaces it and the old point is kept as ``coord_conflict``.
    Where the user picked the saved point, it stays and the disagreement is
    recorded as ``coord_conflict`` for the user to resolve. Returns the number
    of projects changed; a second pass changes nothing.
    """
    from sqlalchemy import select

    from app.modules.geo_hub import coord_reconcile
    from app.modules.geo_hub.models import GeoAnchor
    from app.modules.geo_hub.service import _address_coords
    from app.modules.projects.models import Project

    rows = (await session.execute(select(GeoAnchor, Project).join(Project, Project.id == GeoAnchor.project_id))).all()
    now = datetime.now(UTC).isoformat()
    changed = 0
    for anchor, project in rows:
        meta = anchor.metadata_ or {}
        address = project.address
        if meta.get("geocoded_from") != "project_address" or meta.get("geocode_source") in (
            None,
            "project_coordinates",
        ):
            continue
        saved = _address_coords(address)
        if saved is None or (anchor.lat == Decimal("0") and anchor.lon == Decimal("0")):
            continue
        point = (Decimal(str(anchor.lat)), Decimal(str(anchor.lon)))
        if coord_reconcile.distance_km(saved, point) <= coord_reconcile.CONFLICT_KM:
            continue
        source = address.get("coord_source")
        decision = coord_reconcile.reconcile(saved, source, point)
        assert decision is not None
        if source in coord_reconcile.USER_SOURCES:
            if decision.conflict is None or address.get("coord_conflict") == decision.conflict:
                continue
            project.address = coord_reconcile.apply_to_address(address, decision, address.get("coord_at") or now)
        else:
            project.address = coord_reconcile.apply_to_address(address, decision, now)
            anchor.metadata_ = {**meta, **coord_reconcile.anchor_metadata(decision, now)}
        changed += 1
    if changed:
        await session.flush()
    return changed


#: Nature ``always_wrong``: two coordinate pairs for one project that disagree by
#: more than the threshold were never both right. The server geocode of the saved
#: address replaces an unattributed client pair; a pair the user picked is kept and
#: flagged. No alembic revision sits behind this: the defect was in write paths.
GEO_HUB_PROJECT_LOCATION_RECONCILE = register_data_repair(
    DataRepair(
        repair_id="geo_hub_project_location_reconcile",
        revision="",
        summary="Reconcile project address coordinates with the geocoded anchor and flag large disagreements",
        run=reconcile_project_locations,
        nature="always_wrong",
    )
)

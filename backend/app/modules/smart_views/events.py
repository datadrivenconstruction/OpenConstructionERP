# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""‌⁠‍Smart Views event subscribers — cross-module visibility refresh.

This module is auto-imported by ``module_loader`` when ``oe_smart_views``
loads (see ``core/module_loader.py:_load_module`` → ``events.py``).

Background — issue #103 (federation visibility staleness on owner change)
==========================================================================

A SmartView's *visibility* is derived, not stored:

* ``user`` scope    — owner is implicit (``created_by`` = ``scope_id``).
* ``project`` scope — readable to whoever can read the project, which
  in the current model is the project's owner. Change the project owner
  and the readable-by set flips overnight.
* ``federation`` scope — same, transitively (federation → project →
  owner).

The CRUD path now emits ``smart_views.visibility_changed`` on every
create / update / delete / share / revoke (see ``service.py``), but
owner changes happen *outside* this module — they land as a
``projects.project.updated`` event. Without the subscriber below the
BIM viewer's SmartViews dropdown would keep listing the previous owner's
views until the user hard-refreshed.

We forward a single ``smart_views.visibility_changed`` event so any
downstream cache (sidebar badges, viewer dropdown, federation hub) can
key off one consistent event name regardless of the trigger.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.events import Event, event_bus
from app.database import async_session_factory
from app.modules.smart_views.models import SmartView

logger = logging.getLogger(__name__)


async def _refresh_on_project_update(event: Event) -> None:
    """Re-emit ``smart_views.visibility_changed`` on project owner change.

    Only fires when the ``owner_id`` field was actually mutated — the
    common case (``name`` / ``description`` / ``status`` edits) does
    not affect SmartView visibility and we skip the DB roundtrip.

    For each affected SmartView (project-scoped + federation-scoped
    under the project) we publish one event carrying the new owner so
    caches keyed by ``(view_id, viewer_id)`` can self-invalidate.
    """
    data = event.data or {}
    project_id_raw = data.get("project_id")
    updated_fields = data.get("updated_fields") or []
    if not project_id_raw:
        return
    if "owner_id" not in updated_fields:
        # The 99% case — nothing to do.
        return

    try:
        async with async_session_factory() as session:
            # Resolve project-scoped views under this project.
            proj_stmt = select(SmartView).where(
                SmartView.scope_type == "project",
                SmartView.scope_id == project_id_raw,
            )
            project_views = list((await session.execute(proj_stmt)).scalars().all())

            # Resolve federation-scoped views whose federation lives
            # under this project. Local import — keeps a soft dep on
            # bim_hub to module-load time, not to module-import time.
            from app.modules.bim_hub.models import BIMFederation

            fed_subq = select(BIMFederation.id).where(BIMFederation.project_id == project_id_raw).scalar_subquery()
            fed_stmt = select(SmartView).where(
                SmartView.scope_type == "federation",
                SmartView.scope_id.in_(fed_subq),
            )
            federation_views = list((await session.execute(fed_stmt)).scalars().all())

        # Publish outside the session — subscribers may open their own.
        for view in [*project_views, *federation_views]:
            try:
                await event_bus.publish(
                    "smart_views.visibility_changed",
                    {
                        "view_id": str(view.id),
                        "scope_type": view.scope_type,
                        "scope_id": str(view.scope_id),
                        "owner_id": str(view.created_by),
                        "shared": view.share_token is not None,
                        "reason": "project_owner_changed",
                        "project_id": str(project_id_raw),
                    },
                    source_module="oe_smart_views",
                )
            except Exception:
                # One failed downstream subscriber must not stop the
                # rest of the fan-out.
                logger.debug(
                    "smart_views visibility re-emit failed for view %s",
                    view.id,
                    exc_info=True,
                )
    except Exception:
        logger.debug(
            "smart_views project-update refresh failed for %s",
            project_id_raw,
            exc_info=True,
        )


event_bus.subscribe("projects.project.updated", _refresh_on_project_update)

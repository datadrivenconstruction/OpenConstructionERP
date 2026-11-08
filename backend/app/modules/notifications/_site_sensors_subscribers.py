# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site sensor alerts routed by project role.

The sensor module tells the project owner. The people who act on site are
the roster's site managers and foremen, so each alert also goes to every
active roster member with one of those roles who has a platform account.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import Event, event_bus

logger = logging.getLogger(__name__)

SITE_ROLES = ("site_manager", "foreman")

# event -> (alert kind for the i18n keys, notification type)
_ROUTES: dict[str, tuple[str, str]] = {
    "site_sensors.limit.exceeded": ("exceedance", "warning"),
    "site_sensors.device.offline": ("offline", "warning"),
    "site_sensors.strength.reached": ("strength_reached", "info"),
}


async def recipients(session: AsyncSession, project_id: uuid.UUID) -> list[uuid.UUID]:
    """Active site managers and foremen of the project with a user account, owner excluded."""
    from app.modules.projects.models import Project
    from app.modules.teams.models import RosterMember

    stmt = select(RosterMember.user_id).where(
        RosterMember.project_id == project_id,
        RosterMember.is_active.is_(True),
        RosterMember.site_role.in_(SITE_ROLES),
        RosterMember.user_id.is_not(None),
    )
    users = {u for u in (await session.execute(stmt)).scalars() if u is not None}
    project = await session.get(Project, project_id)
    if project is not None and project.owner_id is not None:
        users.discard(project.owner_id)
    return sorted(users, key=str)


async def route_alert(session: AsyncSession, event_name: str, data: dict[str, Any]) -> int:
    """Create one notification per recipient. Returns how many."""
    from app.modules.notifications.service import NotificationService
    from app.modules.site_sensors.models import SensorDevice

    route = _ROUTES.get(event_name)
    if route is None:
        return 0
    kind, ntype = route
    try:
        project_id = uuid.UUID(str(data.get("project_id")))
        device_id = uuid.UUID(str(data.get("device_id")))
    except (TypeError, ValueError):
        return 0
    device = await session.get(SensorDevice, device_id)
    if device is None or device.project_id != project_id:
        return 0
    users = await recipients(session, project_id)
    context: dict[str, Any] = {"device": device.code, "unit": device.unit, "pour": device.pour_ref}
    for key in ("value", "limit", "strength_mpa"):
        if isinstance(data.get(key), int | float):
            context["strength" if key == "strength_mpa" else key] = f"{data[key]:g}"
    service = NotificationService(session)
    for uid in users:
        await service.create(
            user_id=uid,
            notification_type=ntype,
            title_key=f"notifications.site_sensors_{kind}_title",
            body_key=f"notifications.site_sensors_{kind}_body",
            body_context=context,
            entity_type="site_sensor",
            entity_id=str(device.id),
            action_url=f"/projects/{project_id}/site-sensors",
            metadata={"routed_by": "project_role"},
        )
    return len(users)


async def _on_sensor_alert(event: Event) -> None:
    from app.database import async_session_factory

    try:
        async with async_session_factory() as session:
            if await route_alert(session, event.name, event.data or {}):
                await session.commit()
    except Exception:
        logger.warning("notifications: site sensor routing failed", exc_info=True)


def register_site_sensors_notification_subscribers() -> None:
    """Wire site sensor alerts to site managers and foremen."""
    for event_name in _ROUTES:
        event_bus.subscribe_once(event_name, _on_sensor_alert)

# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""HSE records from site sensor exceedances.

Each project chooses what one exceedance episode (noise, dust, vibration ...)
becomes in the safety register: nothing, an observation (the default) or an
environmental incident. The choice lives in the project's metadata under
``hse_sensor_exceedance``. One record per alert, never two.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import SafetyIncident, SafetyObservation
from app.modules.safety.repository import IncidentRepository, ObservationRepository

logger = logging.getLogger(__name__)

SETTING_KEY = "hse_sensor_exceedance"
MODES = ("off", "observation", "incident")
DEFAULT_MODE = "observation"


async def get_mode(session: AsyncSession, project_id: uuid.UUID) -> str:
    from app.modules.projects.models import Project

    project = await session.get(Project, project_id)
    mode = (project.metadata_ or {}).get(SETTING_KEY) if project else None
    return mode if mode in MODES else DEFAULT_MODE


async def set_mode(session: AsyncSession, project_id: uuid.UUID, mode: str) -> str:
    """Store the project's choice.

    Raises:
        ValueError: unknown mode.
        LookupError: no such project.
    """
    if mode not in MODES:
        raise ValueError("invalid_mode")
    from app.modules.projects.models import Project

    project = await session.get(Project, project_id)
    if project is None:
        raise LookupError("project_not_found")
    project.metadata_ = {**(project.metadata_ or {}), SETTING_KEY: mode}
    await session.flush()
    return mode


async def _already(session: AsyncSession, model: type, project_id: uuid.UUID, alert_id: str) -> Any:
    rows = (await session.execute(select(model).where(model.project_id == project_id))).scalars()
    for row in rows:
        if (row.metadata_ or {}).get("sensor_alert_id") == alert_id:
            return row
    return None


async def record_exceedance(session: AsyncSession, data: dict[str, Any]) -> SafetyObservation | SafetyIncident | None:
    """Create the project's chosen HSE record for one exceedance episode."""
    from app.modules.site_sensors.models import SensorAlert, SensorDevice

    try:
        alert_id = uuid.UUID(str(data.get("alert_id")))
        project_id = uuid.UUID(str(data.get("project_id")))
    except (TypeError, ValueError):
        return None
    alert = await session.get(SensorAlert, alert_id)
    if alert is None or alert.project_id != project_id:
        return None
    mode = await get_mode(session, project_id)
    if mode == "off":
        return None
    model = SafetyIncident if mode == "incident" else SafetyObservation
    found = await _already(session, model, project_id, str(alert_id))
    if found is not None:
        return found
    device = await session.get(SensorDevice, alert.device_id)
    code, unit, kind = (device.code, device.unit, device.kind) if device else ("", "", "")
    text = f"Sensor {code} ({kind}): {alert.value:g} {unit} above limit {alert.limit_value:g} {unit}"
    if alert.limit_source:
        text += f" ({alert.limit_source})"
    meta = {
        "source_module": "site_sensors",
        "sensor_alert_id": str(alert_id),
        "device_id": str(alert.device_id),
        "message_key": "safety.sensor_exceedance",
        "params": {"device": code, "kind": kind, "value": f"{alert.value:g}", "limit": f"{alert.limit_value:g}"},
    }
    if model is SafetyIncident:
        incident = SafetyIncident(
            project_id=project_id,
            incident_number="",
            title=f"Sensor limit exceeded: {code}"[:500],
            incident_date=alert.raised_at.date().isoformat(),
            incident_type="environmental",
            severity="minor",
            description=text,
            status="reported",
            metadata_=meta,
        )
        return await IncidentRepository(session).create(incident)
    observation = SafetyObservation(
        project_id=project_id,
        observation_number="",
        observation_type="unsafe_condition",
        description=text,
        severity=2,
        likelihood=3,
        risk_score=6,
        status="open",
        metadata_=meta,
    )
    return await ObservationRepository(session).create(observation)

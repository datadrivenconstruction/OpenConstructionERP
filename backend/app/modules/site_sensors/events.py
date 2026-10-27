# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site sensors​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ domain events.

Published (``service.py``):

* ``site_sensors.limit.exceeded`` - a reading went above its limit; one per episode.
* ``site_sensors.device.offline`` - a sensor stopped reporting for longer than its window.
* ``site_sensors.strength.reached`` - a pour reached a strip's target strength; carries
  ``schedule_activity_id`` so the schedule can start the strike activity.
* ``site_sensors.alert.acknowledged`` - a person acknowledged an alert.

The project owner also gets an in-app notification for exceedances and strength reached.
"""

from __future__ import annotations

from app.modules.site_sensors.service import (
    EVENT_ALERT_ACKNOWLEDGED,
    EVENT_LIMIT_EXCEEDED,
    EVENT_OFFLINE,
    EVENT_STRENGTH_REACHED,
)

__all__ = ["EVENT_ALERT_ACKNOWLEDGED", "EVENT_LIMIT_EXCEEDED", "EVENT_OFFLINE", "EVENT_STRENGTH_REACHED"]

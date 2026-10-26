# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cutting optimisation event topic names.

Published best-effort via ``event_bus.publish_detached`` from the service, so a
subscriber (notifications, procurement dashboards) never couples to the ORM.
"""

from __future__ import annotations

PLAN_CREATED = "cutting.plan.created"

PLAN_APPLIED = "cutting.plan.applied"

OFFCUTS_RETURNED = "cutting.offcuts.returned"

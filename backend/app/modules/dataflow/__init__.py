# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dataflow module: data paths per module, the platform map and per-project counts."""

from typing import Any


async def _invalidate(event: Any) -> None:
    from app.modules.dataflow.graph import graph_holder
    from app.modules.dataflow.service import invalidate_for_event

    graph = graph_holder._graph
    invalidate_for_event(getattr(event, "name", ""), graph)


async def on_startup() -> None:
    """Register permissions, validation rules and cache invalidation on the event bus."""
    from app.core.events import event_bus
    from app.modules.dataflow.permissions import register_dataflow_permissions
    from app.modules.dataflow.validators import register_dataflow_validation_rules

    register_dataflow_permissions()
    register_dataflow_validation_rules()
    event_bus.subscribe_once("*", _invalidate)

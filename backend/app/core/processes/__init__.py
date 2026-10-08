# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Background process registry (the "Processes" center).

Declare a process once with :class:`ProcessSpec` on :data:`process_registry`;
the registry starts, stops, restarts and reports it.
"""

from app.core.processes.base import (
    HealthReport,
    LoopProcess,
    ManagedProcess,
    OneShotProcess,
    ResidentProcess,
    ThreadLoopProcess,
)
from app.core.processes.registry import (
    ProcessError,
    ProcessRegistry,
    ProcessSpec,
    ProcessStatus,
    process_rss_mb,
)
from app.core.processes.store import DbProcessStore, InMemoryProcessStore, ProcessSetting


async def _publish_state_change(data: dict[str, object]) -> None:
    from app.core.events import event_bus

    event_bus.publish_detached("processes.state_changed", dict(data), source_module="core.processes")


process_registry = ProcessRegistry(store=DbProcessStore(), publish=_publish_state_change)

__all__ = [
    "DbProcessStore",
    "HealthReport",
    "InMemoryProcessStore",
    "LoopProcess",
    "ManagedProcess",
    "OneShotProcess",
    "ProcessError",
    "ProcessRegistry",
    "ProcessSetting",
    "ProcessSpec",
    "ProcessStatus",
    "ResidentProcess",
    "ThreadLoopProcess",
    "process_registry",
    "process_rss_mb",
]

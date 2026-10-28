# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pipeline Builder core - node capability registry + graph DAG executor.

This package is the thin orchestration spine for the ``oe_pipelines``
module. It wraps EXISTING infrastructure (``JobRun``, the validation
engine, the per-module Excel utilities) rather than introducing a new
execution engine. See the internal pipeline design notes
sections 2, 3 and 6 for the load-bearing reuse decisions.
"""

from app.core.pipeline.registry import (
    NodeSpec,
    get_node_spec,
    list_node_specs,
    node_registry,
    register_node,
)

__all__ = [
    "NodeSpec",
    "get_node_spec",
    "list_node_specs",
    "node_registry",
    "register_node",
]

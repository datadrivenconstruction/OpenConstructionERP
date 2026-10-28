# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Node Capability Registry - the safe binding surface for pipeline nodes.

Each module opts a node *type* in by calling :func:`register_node` from its
autodiscovered ``pipeline_nodes.py`` (the module loader discovers that file
the same way it discovers ``hooks.py`` / ``events.py``). The executor only
ever calls *registered* runners; an unknown node type fails **graph
validation before the run starts** (see ``executor.validate_graph``), never
mid-run.

This mirrors §3.5 of the canonical design: "Node Capability Registry over
service layers, NOT HTTP self-calls." The registry is a process-global
singleton populated at module-load time, exactly like the validation
``rule_registry`` and the job ``_HANDLERS`` map.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# A node runner receives the executor-built node context and returns a small
# JSON envelope (IDs + previews, never the big payload - §3.2 hard rule 1).
type NodeRunner = Callable[["NodeContext"], Awaitable[dict[str, Any]]]


@dataclass
class NodeContext:
    """Everything a node runner needs, assembled by the executor.

    The runner reads ``params`` (validated node params from the graph),
    ``inputs`` (the merged upstream envelopes keyed by source node id), and
    the run-scoped ``project_id`` / ``tenant_id`` / ``actor_id`` so it can
    do project-scoped, tenant-safe work without reaching for raw request
    state. ``db`` is a live :class:`AsyncSession`; the executor manages the
    transaction boundary around the runner exactly like
    ``match_elements.pipeline.run_stage``.
    """

    db: Any  # sqlalchemy.ext.asyncio.AsyncSession - typed Any to avoid an
    # import cycle (registry is imported very early at module load).
    node_id: str
    node_type: str
    params: dict[str, Any]
    inputs: dict[str, dict[str, Any]]
    project_id: Any | None = None
    tenant_id: Any | None = None
    actor_id: str | None = None
    run_id: Any | None = None

    def first_input(self) -> dict[str, Any]:
        """Return the single upstream envelope, or ``{}`` when there is none.

        Phase-1 graphs are linear, so most runners just want "the envelope
        from my one predecessor". When several edges feed a node the runner
        should iterate ``inputs`` itself.
        """
        if not self.inputs:
            return {}
        return next(iter(self.inputs.values()))


@dataclass
class NodeSpec:
    """Static capability declaration for one node *type*.

    ``side_effecting`` is the structural gate input: a node that mutates
    persistent state (writes a BOQ, creates an RFI, fires a webhook) sets
    this True, and the ``pipeline`` validation rule then requires a gate on
    every path that reaches it (§3.5 "AI proposes, human confirms").
    """

    type: str
    module: str
    category: str
    label: str
    description: str
    runner: NodeRunner
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    params_schema: dict[str, Any] = field(default_factory=dict)
    side_effecting: bool = False

    def public_dict(self) -> dict[str, Any]:
        """Serialise for the ``GET /node-types/`` endpoint (no runner)."""
        return {
            "type": self.type,
            "category": self.category,
            "label": self.label,
            "description": self.description,
            "module": self.module,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "params_schema": dict(self.params_schema),
            "side_effecting": self.side_effecting,
        }


class NodeRegistry:
    """Process-global map of node ``type`` → :class:`NodeSpec`."""

    def __init__(self) -> None:
        self._specs: dict[str, NodeSpec] = {}

    def register(self, spec: NodeSpec) -> None:
        """Register (or override) a node spec.

        Re-registering the same type silently overrides - matches the
        "last write wins" convention of ``job_runner.register_handler`` and
        keeps test re-imports idempotent.
        """
        if spec.type in self._specs:
            logger.debug("pipeline.registry: overriding node type %s", spec.type)
        self._specs[spec.type] = spec
        logger.debug(
            "pipeline.registry: registered node type=%s module=%s side_effecting=%s",
            spec.type,
            spec.module,
            spec.side_effecting,
        )

    def get(self, node_type: str) -> NodeSpec | None:
        return self._specs.get(node_type)

    def list(self) -> list[NodeSpec]:
        return list(self._specs.values())

    def clear(self) -> None:
        """Drop every registration (test helper only)."""
        self._specs.clear()


# Global singleton - mirrors ``rule_registry`` / ``module_loader``.
node_registry = NodeRegistry()


def register_node(
    *,
    type: str,  # noqa: A002 - "type" is the public contract field name.
    module: str,
    category: str,
    label: str,
    description: str,
    runner: NodeRunner,
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    params_schema: dict[str, Any] | None = None,
    side_effecting: bool = False,
) -> NodeSpec:
    """Register a node type. Called from each module's ``pipeline_nodes.py``.

    Args:
        type: Unique node type, e.g. ``"action.export.excel"``.
        module: Owning module name (``"oe_pipelines"``, ``"oe_boq"``, …).
        category: Palette category (``"trigger"``, ``"source"``,
            ``"transform"``, ``"gate"``, ``"action"`` …).
        label: Human-facing default label (the UI ships the i18n string;
            this is the API fallback).
        description: One-line "what / it needs / it produces" summary.
        runner: ``async`` callable taking a :class:`NodeContext` and
            returning a small JSON envelope.
        inputs: Named input port types (empty for trigger/entry nodes).
        outputs: Named output port types.
        params_schema: JSON-schema-ish dict the UI inspector renders and
            the executor uses to validate node params before a run.
        side_effecting: True if the node mutates persistent state - drives
            the structural "writes need a gate" validation rule.

    Returns:
        The registered :class:`NodeSpec` (handy for tests).
    """
    spec = NodeSpec(
        type=type,
        module=module,
        category=category,
        label=label,
        description=description,
        runner=runner,
        inputs=list(inputs or []),
        outputs=list(outputs or []),
        params_schema=dict(params_schema or {}),
        side_effecting=side_effecting,
    )
    node_registry.register(spec)
    return spec


def get_node_spec(node_type: str) -> NodeSpec | None:
    """Look up a node spec by type, or ``None`` when unregistered."""
    return node_registry.get(node_type)


def list_node_specs() -> list[NodeSpec]:
    """Return every registered node spec (registration order is irrelevant)."""
    return node_registry.list()

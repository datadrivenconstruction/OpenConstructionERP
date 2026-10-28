# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic request/response schemas for the Pipeline Builder REST API.

The wire contract is PINNED - the frontend is built against it in
parallel. Graph JSON shape:

    {"nodes": [{"id","type","params","position":{"x","y"}}],
     "edges": [{"id","source","target","sourceHandle?","targetHandle?"}]}

Pydantic validates at the boundary; the executor serialises dicts on the
wire (§3.2 hard rule 3).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ── Graph shape ──────────────────────────────────────────────────────────


class NodePosition(BaseModel):
    """Canvas coordinates for a node (xyflow)."""

    x: float = 0.0
    y: float = 0.0


class GraphNode(BaseModel):
    """A single node in the editor graph."""

    id: str
    type: str
    params: dict[str, Any] = Field(default_factory=dict)
    position: NodePosition = Field(default_factory=NodePosition)


class GraphEdge(BaseModel):
    """A directed connection between two nodes."""

    id: str
    source: str
    target: str
    sourceHandle: str | None = None  # noqa: N815 - xyflow wire field name.
    targetHandle: str | None = None  # noqa: N815 - xyflow wire field name.


class Graph(BaseModel):
    """The editor graph: nodes + edges."""

    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


# ── Pipeline CRUD ────────────────────────────────────────────────────────


class PipelineCreate(BaseModel):
    """Body for ``POST /pipelines/``."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    project_id: str | None = None
    graph: Graph = Field(default_factory=Graph)
    policy: dict[str, Any] = Field(default_factory=dict)


class PipelineUpdate(BaseModel):
    """Body for ``PUT /pipelines/{id}`` - every field optional (partial)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    graph: Graph | None = None
    policy: dict[str, Any] | None = None
    is_published: bool | None = None


class PipelineSummary(BaseModel):
    """List-item shape for ``GET /pipelines/``."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None = None
    is_published: bool
    node_count: int
    updated_at: str | None = None


class PipelineDetail(BaseModel):
    """Full pipeline shape for create / get / update responses."""

    id: str
    name: str
    description: str | None = None
    project_id: str | None = None
    is_published: bool
    graph: dict[str, Any]
    policy: dict[str, Any]
    version: int
    updated_at: str | None = None


# ── Runs ─────────────────────────────────────────────────────────────────


class RunRequest(BaseModel):
    """Body for ``POST /pipelines/{id}/run`` - empty for a manual trigger."""

    model_config = ConfigDict(extra="allow")


class RunAccepted(BaseModel):
    """Response for ``POST /pipelines/{id}/run``."""

    run_id: str
    job_run_id: str | None = None
    status: str


class RunSummary(BaseModel):
    """List-item shape for ``GET /pipelines/{id}/runs/``."""

    id: str
    status: str
    trigger: dict[str, Any]
    started_at: str | None = None
    finished_at: str | None = None
    progress_percent: int = 0


class NodeStateOut(BaseModel):
    """Per-node state nested in the run detail response."""

    node_id: str
    node_type: str
    status: str
    output: dict[str, Any]
    error: str | None = None
    took_ms: int | None = None
    started_at: str | None = None
    finished_at: str | None = None


class RunDetail(BaseModel):
    """Full run shape for ``GET /pipelines/runs/{run_id}``."""

    id: str
    pipeline_id: str
    status: str
    progress_percent: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    nodes: list[NodeStateOut] = Field(default_factory=list)


class NodeTypeOut(BaseModel):
    """Catalog entry for ``GET /pipelines/node-types/``."""

    type: str
    category: str
    label: str
    description: str
    module: str
    inputs: list[str]
    outputs: list[str]
    params_schema: dict[str, Any]
    side_effecting: bool

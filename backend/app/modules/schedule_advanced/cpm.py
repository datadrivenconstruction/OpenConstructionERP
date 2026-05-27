# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Pure-Python Critical Path Method (CPM) engine — Slice 1.

This module is intentionally self-contained: no SQLAlchemy, no FastAPI,
no third-party deps (no scipy / networkx). Everything is plain ``dataclass``
+ ``list`` / ``dict`` so the engine can be unit-tested in isolation and
also imported by services that want to run "what-if" scheduling.

Slice 1 scope:
    * Activities with integer ``duration`` (working days).
    * **FS (Finish-to-Start) dependencies only** with optional integer lag.
      SS / FF / SF are accepted in the dataclass shape but ignored by the
      forward / backward pass — marked TODO below.
    * Forward pass → ES / EF.
    * Backward pass → LS / LF.
    * Total float = LS − ES (== LF − EF).
    * Free float  = min(ES of successors) − EF (0 for terminal nodes).
    * Critical path marking (total_float == 0).
    * Cycle detection via DFS (raises :class:`CycleError`).
    * Disconnected sub-networks supported — every weakly-connected
      component is scheduled independently from t=0.

The existing ``service.cpm_forward_backward_pass`` helper that powers the
stateless ``POST /cpm`` endpoint stays in place; this new engine is the
canonical reference implementation used by the new persisted
``compute-cpm`` endpoint and by the resource-leveling heuristic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# Dependency type codes. FS is the only one honoured in Slice 1.
# TODO(Slice 2): support SS (Start-to-Start), FF (Finish-to-Finish),
#   SF (Start-to-Finish) — both in the forward pass (replace
#   ``ef[pred] + lag`` with the matching start/finish source) and the
#   backward pass. UI must NOT expose the picker yet.
DepType = Literal["FS", "SS", "FF", "SF"]


# ── Exceptions ─────────────────────────────────────────────────────────────


class CycleError(ValueError):
    """Raised when the activity network contains a directed cycle.

    ``cycle_path`` is the list of activity ids that close the loop (in
    traversal order). The first id is repeated at the end so callers can
    render ``A → B → C → A`` without further bookkeeping.
    """

    def __init__(self, cycle_path: list[Any]) -> None:
        self.cycle_path: list[Any] = list(cycle_path)
        super().__init__(f"Cycle detected in activity network: {' → '.join(map(str, self.cycle_path))}")


# ── Data classes ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Activity:
    """One scheduled activity.

    Attributes:
        id: Unique identifier (any hashable — typically a UUID string or
            a short code like ``"A"``).
        duration: Working-day duration. Coerced to ``max(0, int(duration))``
            at network-build time — negative durations behave like
            milestones.
        predecessors: List of ``(predecessor_id, dep_type, lag_days)``
            triples. ``dep_type`` is "FS" / "SS" / "FF" / "SF"; Slice 1
            only honours "FS". ``lag_days`` may be negative (lead time).
        required_resources: Mapping of resource code → integer count
            consumed by this activity for its full duration. Used by
            :mod:`leveling`. Empty dict means "no resource constraints".
    """

    id: Any
    duration: int = 0
    predecessors: list[tuple[Any, DepType, int]] = field(default_factory=list)
    required_resources: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class CPMResult:
    """Per-activity CPM output.

    All values are integer work-day indices (0-based). ``es``/``ef`` come
    from the forward pass, ``ls``/``lf`` from the backward pass.
    ``total_float`` and ``free_float`` are always ``>= 0`` (clamped) for
    valid acyclic networks.
    """

    es: int
    ef: int
    ls: int
    lf: int
    total_float: int
    free_float: int
    is_critical: bool


# ── Task network ───────────────────────────────────────────────────────────


class TaskNetwork:
    """A directed activity network.

    The network owns its activities and computes its own predecessor /
    successor adjacency on construction. Edges referencing unknown
    predecessor ids are silently dropped (so callers can feed partial
    sub-networks without crashing).
    """

    def __init__(self, activities: list[Activity]) -> None:
        # Index by id (preserve first occurrence on duplicate ids).
        seen: dict[Any, Activity] = {}
        for a in activities:
            if a.id not in seen:
                seen[a.id] = a
        self._activities: dict[Any, Activity] = seen
        # Preserve a stable iteration order = insertion order.
        self._order: list[Any] = list(seen.keys())

        # Build adjacency dropping refs to unknown activities + self-loops.
        self._preds: dict[Any, list[tuple[Any, DepType, int]]] = {}
        self._succs: dict[Any, list[tuple[Any, DepType, int]]] = {}
        for aid in self._order:
            self._preds[aid] = []
            self._succs[aid] = []
        for aid, a in self._activities.items():
            for p_id, dep_type, lag in a.predecessors:
                if p_id == aid:
                    continue
                if p_id not in self._activities:
                    continue
                triple: tuple[Any, DepType, int] = (p_id, dep_type, int(lag))
                self._preds[aid].append(triple)
                self._succs[p_id].append((aid, dep_type, int(lag)))

    # ── Accessors ──

    @property
    def activities(self) -> list[Activity]:
        return [self._activities[aid] for aid in self._order]

    def get(self, activity_id: Any) -> Activity | None:
        return self._activities.get(activity_id)

    def predecessors(self, activity_id: Any) -> list[tuple[Any, DepType, int]]:
        return list(self._preds.get(activity_id, []))

    def successors(self, activity_id: Any) -> list[tuple[Any, DepType, int]]:
        return list(self._succs.get(activity_id, []))

    def ids(self) -> list[Any]:
        return list(self._order)

    # ── Cycle detection ──

    def detect_cycle(self) -> list[Any] | None:
        """Return a cycle path if one exists, else ``None``.

        Iterative DFS using three colours (white / grey / black). Closing
        a grey edge produces the cycle; the path is reconstructed from
        the DFS parent map.
        """
        WHITE, GREY, BLACK = 0, 1, 2
        colour: dict[Any, int] = dict.fromkeys(self._order, WHITE)
        parent: dict[Any, Any] = {}

        for root in self._order:
            if colour[root] != WHITE:
                continue
            # Iterative DFS — (node, iterator-over-children)
            stack: list[tuple[Any, list[tuple[Any, DepType, int]]]] = [(root, list(self._succs[root]))]
            colour[root] = GREY
            while stack:
                node, children = stack[-1]
                if not children:
                    colour[node] = BLACK
                    stack.pop()
                    continue
                child_id, _dep, _lag = children.pop(0)
                if colour[child_id] == WHITE:
                    parent[child_id] = node
                    colour[child_id] = GREY
                    stack.append((child_id, list(self._succs[child_id])))
                elif colour[child_id] == GREY:
                    # Cycle: child_id → ... → node → child_id.
                    # Walk the parent chain from `node` back to `child_id`.
                    # Guard: when `child_id` is the DFS-tree root it has no
                    # entry in ``parent``; the old ``cur in parent`` guard
                    # terminated early and left the first node of the cycle
                    # out of the path (producing A → B → A instead of the
                    # correct A → B → C → A when A was the root). We now
                    # stop when we either reach `child_id` again OR exhaust
                    # the parent chain — the closing ``child_id`` appended
                    # below always completes the ring regardless.
                    cycle = [child_id]
                    cur = node
                    while cur != child_id:
                        cycle.append(cur)
                        if cur not in parent:
                            break
                        cur = parent[cur]
                    cycle.append(child_id)
                    cycle.reverse()
                    return cycle
                # BLACK: already fully explored — skip.
        return None


# ── CPM computation ────────────────────────────────────────────────────────


def _topological_order(network: TaskNetwork) -> list[Any]:
    """Kahn's algorithm — assumes the network is acyclic (caller's job)."""
    indeg: dict[Any, int] = {aid: len(network.predecessors(aid)) for aid in network.ids()}
    # Use a list as a FIFO; the network is small so O(n) pop(0) is fine.
    queue: list[Any] = [aid for aid in network.ids() if indeg[aid] == 0]
    order: list[Any] = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for s_id, _dep, _lag in network.successors(n):
            indeg[s_id] -= 1
            if indeg[s_id] == 0:
                queue.append(s_id)
    return order


def compute_cpm(network: TaskNetwork) -> dict[Any, CPMResult]:
    """Run forward + backward pass on ``network``.

    Returns a dict keyed by activity id.

    Raises:
        CycleError: if the network contains a directed cycle.

    Disconnected sub-networks are scheduled independently: each
    sub-network's "sinks" (nodes with no successors) have their LF
    pinned to the project finish of that sub-network only, NOT to the
    global project finish across sub-networks. This matches MS Project
    behaviour for unrelated activity islands.
    """
    cycle = network.detect_cycle()
    if cycle is not None:
        raise CycleError(cycle)

    order = _topological_order(network)
    if not order:
        return {}

    # ── Forward pass: ES, EF ─────────────────────────────────────────────
    durations: dict[Any, int] = {}
    es: dict[Any, int] = {}
    ef: dict[Any, int] = {}
    for aid in order:
        a = network.get(aid)
        assert a is not None
        dur = max(0, int(a.duration))
        durations[aid] = dur
        candidates: list[int] = []
        for p_id, dep_type, lag in network.predecessors(aid):
            if dep_type != "FS":
                # TODO(Slice 2): handle SS / FF / SF.
                continue
            if p_id in ef:
                candidates.append(ef[p_id] + int(lag))
        es[aid] = max(candidates) if candidates else 0
        ef[aid] = es[aid] + dur

    # ── Identify weakly-connected components for per-island project_finish ─
    # We do a union-find over the undirected version of the graph so the
    # backward pass anchors each island to its own finish.
    component_root: dict[Any, Any] = {aid: aid for aid in order}

    def _find(x: Any) -> Any:
        while component_root[x] != x:
            component_root[x] = component_root[component_root[x]]
            x = component_root[x]
        return x

    def _union(x: Any, y: Any) -> None:
        rx, ry = _find(x), _find(y)
        if rx != ry:
            component_root[rx] = ry

    for aid in order:
        for s_id, _dep, _lag in network.successors(aid):
            _union(aid, s_id)

    # Per-component project finish = max EF of any node in the component.
    component_finish: dict[Any, int] = {}
    for aid in order:
        root = _find(aid)
        if ef[aid] > component_finish.get(root, -1):
            component_finish[root] = ef[aid]

    # ── Backward pass: LF, LS ────────────────────────────────────────────
    lf: dict[Any, int] = {}
    ls: dict[Any, int] = {}
    for aid in reversed(order):
        a = network.get(aid)
        assert a is not None
        dur = durations[aid]
        succ_candidates: list[int] = []
        for s_id, dep_type, lag in network.successors(aid):
            if dep_type != "FS":
                # TODO(Slice 2): mirror SS/FF/SF in backward pass.
                continue
            if s_id in ls:
                succ_candidates.append(ls[s_id] - int(lag))
        if succ_candidates:
            lf[aid] = min(succ_candidates)
        else:
            # Sink → pin to own component finish.
            lf[aid] = component_finish[_find(aid)]
        ls[aid] = lf[aid] - dur

    # ── Float + critical marking ─────────────────────────────────────────
    results: dict[Any, CPMResult] = {}
    for aid in order:
        total_float = ls[aid] - es[aid]
        # Free float: how long this activity can slip before delaying any
        # immediate successor's ES. For a sink it's the slack to its
        # component finish.
        fs_succs = [
            es[s_id] - int(lag) for s_id, dep_type, lag in network.successors(aid) if dep_type == "FS" and s_id in es
        ]
        if fs_succs:
            free_float = min(fs_succs) - ef[aid]
        else:
            free_float = component_finish[_find(aid)] - ef[aid]
        results[aid] = CPMResult(
            es=es[aid],
            ef=ef[aid],
            ls=ls[aid],
            lf=lf[aid],
            total_float=max(0, total_float),
            free_float=max(0, free_float),
            # Use <= 0 (not == 0) so activities with negative total float
            # (possible when lag constraints push a successor earlier than
            # the predecessor's EF) are correctly marked critical. Using
            # == 0 silently misses these activities and produces an
            # incomplete / wrong critical path.
            is_critical=(total_float <= 0),
        )
    return results


# ── Convenience helpers ────────────────────────────────────────────────────


def critical_path(
    network: TaskNetwork,
    results: dict[Any, CPMResult] | None = None,
) -> list[Any]:
    """Return ONE critical path through the network, in topological order.

    If multiple critical paths exist, the first one (lowest topological
    rank at every fork) is returned. Disconnected critical activities
    that don't belong to the longest chain are still included as
    standalone single-node paths appended at the end (stable order).
    """
    if results is None:
        results = compute_cpm(network)
    critical_ids = {aid for aid, r in results.items() if r.is_critical}
    if not critical_ids:
        return []

    order = _topological_order(network)
    path: list[Any] = []
    seen: set[Any] = set()
    for aid in order:
        if aid in critical_ids and aid not in seen:
            # Greedily extend forward through critical successors.
            cur = aid
            while cur is not None and cur not in seen:
                path.append(cur)
                seen.add(cur)
                next_cur: Any = None
                for s_id, dep_type, _lag in network.successors(cur):
                    if dep_type == "FS" and s_id in critical_ids and s_id not in seen:
                        next_cur = s_id
                        break
                cur = next_cur
    return path

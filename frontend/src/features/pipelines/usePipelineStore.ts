// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Zustand store backing the Pipeline Builder canvas.
 *
 * Same shape & discipline as the EAC `useBlockCanvasStore`:
 *   - `nodes`     — every node on the canvas (type, params, position, title).
 *   - `edges`     — typed wires (output port → input port).
 *   - `selection` — set of selected node ids (multi-select).
 *   - `clipboard` — last copied nodes for paste.
 *   - `history`   — bounded undo/redo stack of immutable snapshots.
 *   - `pipelineMeta` — name/description/policy edited by the Inspector.
 *   - `runState` — per-node live run status overlay (poll-driven, not graph).
 *
 * Connection insertion enforces the typed-port compatibility matrix from
 * `tokens.ts` so the UI can rely on the store rejecting invalid edges
 * regardless of which surface (xyflow handle, paste) created them.
 */
import { create } from 'zustand';

import type { PortDataType } from './tokens';
import { isPortCompatible } from './tokens';
import type {
  PipelineGraph,
  PipelineGraphEdge,
  PipelineGraphNode,
  RunNodeState,
  RunStatus,
} from './api';

// ── Types ──────────────────────────────────────────────────────────────────

export interface PipelinePort {
  id: string;
  label: string;
  dataType: PortDataType;
  direction: 'input' | 'output';
}

export interface CanvasNode {
  id: string;
  /** Backend node-type, e.g. "source.boq". */
  type: string;
  /** Category (drives color/icon) — derived from the node-type at insert. */
  category: string;
  /** Display title — editable inline; defaults to the node-type label. */
  title: string;
  position: { x: number; y: number };
  inputs: PipelinePort[];
  outputs: PipelinePort[];
  params: Record<string, unknown>;
  expanded: boolean;
}

export interface CanvasEdge {
  id: string;
  source: string;
  sourceHandle: string;
  target: string;
  targetHandle: string;
  /** Cached port type for color rendering — derived from the source port. */
  dataType: PortDataType;
}

interface CanvasSnapshot {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
}

export interface PipelineMeta {
  id: string | null;
  name: string;
  description: string;
  projectId: string | null;
  isPublished: boolean;
}

export interface RunOverlay {
  runId: string | null;
  status: RunStatus | null;
  progress: number;
  error: string | null;
  /** node_id → live state, projected onto the canvas + run dock. */
  nodeStates: Record<string, RunNodeState>;
}

export interface PipelineStoreState {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  selection: Set<string>;
  clipboard: CanvasNode[];
  history: CanvasSnapshot[];
  historyIndex: number;
  meta: PipelineMeta;
  run: RunOverlay;
  /** Dirty since the last successful save. */
  dirty: boolean;
}

export interface PipelineStoreActions {
  addNode: (input: {
    type: string;
    category: string;
    title: string;
    position: { x: number; y: number };
    inputs: PipelinePort[];
    outputs: PipelinePort[];
    params?: Record<string, unknown>;
  }) => string;
  removeNode: (id: string) => void;
  moveNode: (id: string, position: { x: number; y: number }) => void;
  setNodeTitle: (id: string, title: string) => void;
  setNodeParams: (id: string, params: Record<string, unknown>) => void;
  toggleNodeExpanded: (id: string) => void;
  setSelection: (ids: string[]) => void;
  clearSelection: () => void;
  copySelection: () => void;
  pasteClipboard: (offset?: { x: number; y: number }) => string[];
  addEdge: (
    edge: Omit<CanvasEdge, 'id' | 'dataType'>,
  ) => CanvasEdge | null;
  removeEdge: (id: string) => void;
  undo: () => void;
  redo: () => void;
  reset: () => void;
  /** Replace the graph + meta (e.g. when loading a saved pipeline). */
  loadGraph: (graph: PipelineGraph | null | undefined, meta: PipelineMeta) => void;
  /** Patch pipeline meta fields from the Inspector. */
  patchMeta: (patch: Partial<PipelineMeta>) => void;
  markSaved: (id: string) => void;
  /** Project the current graph into the wire shape for save. */
  toGraphJSON: () => PipelineGraph;
  // ── Run overlay ──
  startRun: (runId: string) => void;
  applyRunDetail: (detail: {
    status?: RunStatus;
    progress_percent?: number;
    error?: string | null;
    nodes?: RunNodeState[];
  }) => void;
  clearRun: () => void;
}

export type PipelineStore = PipelineStoreState & PipelineStoreActions;

// ── Constants ──────────────────────────────────────────────────────────────

const HISTORY_LIMIT = 50;
const PASTE_OFFSET = { x: 36, y: 36 };
const EMPTY_SNAPSHOT: CanvasSnapshot = { nodes: [], edges: [] };

const EMPTY_META: PipelineMeta = {
  id: null,
  name: '',
  description: '',
  projectId: null,
  isPublished: false,
};

const EMPTY_RUN: RunOverlay = {
  runId: null,
  status: null,
  progress: 0,
  error: null,
  nodeStates: {},
};

// ── Helpers ────────────────────────────────────────────────────────────────

let _idCounter = 0;
function genId(prefix: string): string {
  _idCounter += 1;
  const cryptoLike = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  const suffix = cryptoLike?.randomUUID
    ? cryptoLike.randomUUID().slice(0, 8)
    : Math.random().toString(36).slice(2, 10);
  return `${prefix}_${_idCounter}_${suffix}`;
}

function cloneNode(n: CanvasNode): CanvasNode {
  return {
    ...n,
    position: { ...n.position },
    inputs: n.inputs.map((p) => ({ ...p })),
    outputs: n.outputs.map((p) => ({ ...p })),
    params: { ...n.params },
  };
}

function cloneEdge(e: CanvasEdge): CanvasEdge {
  return { ...e };
}

function cloneSnapshot(s: CanvasSnapshot): CanvasSnapshot {
  return { nodes: s.nodes.map(cloneNode), edges: s.edges.map(cloneEdge) };
}

function findPort(
  node: CanvasNode | undefined,
  portId: string,
  direction: 'input' | 'output',
): PipelinePort | undefined {
  if (!node) return undefined;
  const list = direction === 'input' ? node.inputs : node.outputs;
  return list.find((p) => p.id === portId);
}

// ── Store ──────────────────────────────────────────────────────────────────

export const usePipelineStore = create<PipelineStore>((set, get) => {
  function commitHistory(next: { nodes: CanvasNode[]; edges: CanvasEdge[] }) {
    const { history, historyIndex } = get();
    const trimmed = history.slice(0, historyIndex + 1);
    trimmed.push(cloneSnapshot(next));
    while (trimmed.length > HISTORY_LIMIT) trimmed.shift();
    set({ history: trimmed, historyIndex: trimmed.length - 1, dirty: true });
  }

  return {
    nodes: [],
    edges: [],
    selection: new Set<string>(),
    clipboard: [],
    history: [cloneSnapshot(EMPTY_SNAPSHOT)],
    historyIndex: 0,
    meta: { ...EMPTY_META },
    run: { ...EMPTY_RUN, nodeStates: {} },
    dirty: false,

    addNode: (input) => {
      const id = genId('node');
      const node: CanvasNode = {
        id,
        type: input.type,
        category: input.category,
        title: input.title,
        position: { ...input.position },
        inputs: input.inputs.map((p) => ({ ...p })),
        outputs: input.outputs.map((p) => ({ ...p })),
        params: { ...(input.params ?? {}) },
        expanded: false,
      };
      const nextNodes = [...get().nodes, node];
      set({ nodes: nextNodes });
      commitHistory({ nodes: nextNodes, edges: get().edges });
      return id;
    },

    removeNode: (id) => {
      const { nodes, edges } = get();
      if (!nodes.some((n) => n.id === id)) return;
      const nextSelection = new Set(get().selection);
      nextSelection.delete(id);
      const nextNodes = nodes.filter((n) => n.id !== id);
      const nextEdges = edges.filter(
        (e) => e.source !== id && e.target !== id,
      );
      set({ nodes: nextNodes, edges: nextEdges, selection: nextSelection });
      commitHistory({ nodes: nextNodes, edges: nextEdges });
    },

    moveNode: (id, position) => {
      // Position-only changes don't push history (drag would explode the stack).
      set({
        nodes: get().nodes.map((n) =>
          n.id === id ? { ...n, position: { ...position } } : n,
        ),
        dirty: true,
      });
    },

    setNodeTitle: (id, title) => {
      const { nodes } = get();
      const node = nodes.find((n) => n.id === id);
      if (!node || node.title === title) return;
      const nextNodes = nodes.map((n) => (n.id === id ? { ...n, title } : n));
      set({ nodes: nextNodes });
      commitHistory({ nodes: nextNodes, edges: get().edges });
    },

    setNodeParams: (id, params) => {
      const { nodes } = get();
      if (!nodes.some((n) => n.id === id)) return;
      const nextNodes = nodes.map((n) =>
        n.id === id ? { ...n, params: { ...params } } : n,
      );
      set({ nodes: nextNodes });
      commitHistory({ nodes: nextNodes, edges: get().edges });
    },

    toggleNodeExpanded: (id) => {
      set({
        nodes: get().nodes.map((n) =>
          n.id === id ? { ...n, expanded: !n.expanded } : n,
        ),
      });
    },

    setSelection: (ids) => set({ selection: new Set(ids) }),
    clearSelection: () => {
      if (get().selection.size === 0) return;
      set({ selection: new Set() });
    },

    copySelection: () => {
      const { nodes, selection } = get();
      set({
        clipboard: nodes.filter((n) => selection.has(n.id)).map(cloneNode),
      });
    },

    pasteClipboard: (offset = PASTE_OFFSET) => {
      const { clipboard } = get();
      if (clipboard.length === 0) return [];
      const newIds: string[] = [];
      const fresh = clipboard.map((n) => {
        const id = genId('node');
        newIds.push(id);
        return {
          ...cloneNode(n),
          id,
          position: { x: n.position.x + offset.x, y: n.position.y + offset.y },
        };
      });
      const nextNodes = [...get().nodes, ...fresh];
      set({ nodes: nextNodes, selection: new Set(newIds) });
      commitHistory({ nodes: nextNodes, edges: get().edges });
      return newIds;
    },

    addEdge: (raw) => {
      const { nodes, edges } = get();
      if (raw.source === raw.target) return null;
      const sourceNode = nodes.find((n) => n.id === raw.source);
      const targetNode = nodes.find((n) => n.id === raw.target);
      const sourcePort = findPort(sourceNode, raw.sourceHandle, 'output');
      const targetPort = findPort(targetNode, raw.targetHandle, 'input');
      if (!sourcePort || !targetPort) return null;
      if (!isPortCompatible(sourcePort.dataType, targetPort.dataType)) {
        return null;
      }
      const dup = edges.find(
        (e) =>
          e.source === raw.source &&
          e.sourceHandle === raw.sourceHandle &&
          e.target === raw.target &&
          e.targetHandle === raw.targetHandle,
      );
      if (dup) return dup;
      const edge: CanvasEdge = {
        id: genId('edge'),
        source: raw.source,
        sourceHandle: raw.sourceHandle,
        target: raw.target,
        targetHandle: raw.targetHandle,
        dataType: sourcePort.dataType,
      };
      const nextEdges = [...edges, edge];
      set({ edges: nextEdges });
      commitHistory({ nodes: get().nodes, edges: nextEdges });
      return edge;
    },

    removeEdge: (id) => {
      const { edges } = get();
      if (!edges.some((e) => e.id === id)) return;
      const nextEdges = edges.filter((e) => e.id !== id);
      set({ edges: nextEdges });
      commitHistory({ nodes: get().nodes, edges: nextEdges });
    },

    undo: () => {
      const { history, historyIndex } = get();
      if (historyIndex <= 0) return;
      const target = history[historyIndex - 1];
      if (!target) return;
      const restored = cloneSnapshot(target);
      set({
        nodes: restored.nodes,
        edges: restored.edges,
        historyIndex: historyIndex - 1,
        dirty: true,
      });
    },

    redo: () => {
      const { history, historyIndex } = get();
      if (historyIndex >= history.length - 1) return;
      const target = history[historyIndex + 1];
      if (!target) return;
      const restored = cloneSnapshot(target);
      set({
        nodes: restored.nodes,
        edges: restored.edges,
        historyIndex: historyIndex + 1,
        dirty: true,
      });
    },

    reset: () => {
      set({
        nodes: [],
        edges: [],
        selection: new Set(),
        clipboard: [],
        history: [cloneSnapshot(EMPTY_SNAPSHOT)],
        historyIndex: 0,
        meta: { ...EMPTY_META },
        run: { ...EMPTY_RUN, nodeStates: {} },
        dirty: false,
      });
    },

    loadGraph: (graph, meta) => {
      const nodes: CanvasNode[] = [];
      const edges: CanvasEdge[] = [];
      // Graph is rehydrated by PipelineCanvas (it owns the node-type catalogue
      // needed to resolve ports). Here we only reset meta/history; the canvas
      // calls addNode/addEdge to materialise the graph. If the backend ever
      // sends a fully-hydrated graph we still accept it defensively.
      if (graph && Array.isArray(graph.nodes)) {
        // Best-effort: keep nothing here; PipelineCanvas does hydration.
        void nodes;
        void edges;
      }
      set({
        nodes: [],
        edges: [],
        selection: new Set(),
        history: [cloneSnapshot(EMPTY_SNAPSHOT)],
        historyIndex: 0,
        meta: { ...meta },
        run: { ...EMPTY_RUN, nodeStates: {} },
        dirty: false,
      });
    },

    patchMeta: (patch) => {
      set({ meta: { ...get().meta, ...patch }, dirty: true });
    },

    markSaved: (id) => {
      set({ meta: { ...get().meta, id }, dirty: false });
    },

    toGraphJSON: (): PipelineGraph => {
      const { nodes, edges } = get();
      const outNodes: PipelineGraphNode[] = nodes.map((n) => ({
        id: n.id,
        type: n.type,
        params: { ...n.params },
        position: { ...n.position },
        label: n.title,
      }));
      const outEdges: PipelineGraphEdge[] = edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        sourceHandle: e.sourceHandle,
        targetHandle: e.targetHandle,
      }));
      return { nodes: outNodes, edges: outEdges };
    },

    startRun: (runId) => {
      set({
        run: {
          runId,
          status: 'queued',
          progress: 0,
          error: null,
          nodeStates: {},
        },
      });
    },

    applyRunDetail: (detail) => {
      const nodeStates: Record<string, RunNodeState> = {};
      for (const ns of detail.nodes ?? []) {
        if (ns && ns.node_id) nodeStates[ns.node_id] = ns;
      }
      set({
        run: {
          runId: get().run.runId,
          status: detail.status ?? get().run.status,
          progress:
            typeof detail.progress_percent === 'number'
              ? detail.progress_percent
              : get().run.progress,
          error: detail.error ?? null,
          nodeStates,
        },
      });
    },

    clearRun: () => set({ run: { ...EMPTY_RUN, nodeStates: {} } }),
  };
});

/** True when any undo step is available. */
export function selectCanUndo(s: PipelineStore): boolean {
  return s.historyIndex > 0;
}

/** True when any redo step is available. */
export function selectCanRedo(s: PipelineStore): boolean {
  return s.historyIndex < s.history.length - 1;
}

/** The single selected node, or null when 0 / many selected. */
export function selectSingleSelected(s: PipelineStore): CanvasNode | null {
  if (s.selection.size !== 1) return null;
  const id = Array.from(s.selection)[0];
  return s.nodes.find((n) => n.id === id) ?? null;
}

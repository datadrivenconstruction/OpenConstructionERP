// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * `<PipelineCanvas>` — main visual surface of the Pipeline Builder.
 *
 * Cloned from EAC `BlockCanvas`: same `ReactFlowProvider` split,
 * `screenToFlowPosition`, `applyNodeChanges`, store-as-source-of-truth, and
 * the architecture-page xyflow v12 forwardRef TS cast workaround.
 *
 * Responsibilities:
 *   - Render each store node as a `PipelineNode`, each edge as `PipelineEdge`.
 *   - Forward xyflow move/select/connect/delete into the Zustand store.
 *   - Accept palette drops (HTML5 dataTransfer) and click-insert at viewport
 *     centre — both resolve the node-type's ports from the catalogue.
 *   - Hydrate a loaded pipeline graph (the canvas owns the catalogue needed
 *     to rebuild port lists, so it does hydration, not the store).
 *   - Project the live-run overlay onto edges (flowing dash on carried wires).
 *   - Keyboard: Ctrl/Cmd Z / Shift+Z / C / V, Delete.
 */
import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type DragEvent,
  type KeyboardEvent,
} from 'react';
import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  Panel,
  ReactFlow as RFComponent,
  ReactFlowProvider,
  addEdge as rfAddEdge,
  applyEdgeChanges,
  applyNodeChanges,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type EdgeTypes,
  type Node,
  type NodeChange,
  type NodeTypes,
  type OnConnect,
  type ReactFlowInstance,
} from '@xyflow/react';
import { useTranslation } from 'react-i18next';

import { useIsRTL } from '@/shared/hooks/useIsRTL';
import { useToastStore } from '@/stores/useToastStore';

import { PipelineEdge } from './PipelineEdge';
import { PipelineNode } from './PipelineNode';
import {
  CATEGORY_MINIMAP_COLOR,
  getPortTokens,
  inferPortType,
  isPortDataType,
  type NodeCategory,
} from '../tokens';
import { usePipelineStore, type PipelinePort } from '../usePipelineStore';
import type { NodeTypeDef, PipelineGraph } from '../api';

import '@xyflow/react/dist/style.css';

// @xyflow/react v12 exports ReactFlow as a generic forwardRef component which
// can cause JSX type errors in strict TS. Cast to a plain FC (architecture
// page precedent).
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const ReactFlow = RFComponent as any as React.FC<Record<string, any>>;

const NODE_TYPES: NodeTypes = { pipelineNode: PipelineNode };
const EDGE_TYPES: EdgeTypes = { pipelineEdge: PipelineEdge };

/** Palette drag payload mime — distinct from the EAC editor's. */
export const PIPELINE_DND_MIME = 'application/x-oe-pipeline-node';

export interface PaletteDragItem {
  type: string;
  category: string;
  label: string;
}

/**
 * Build the typed port lists for a node-type from the catalogue def.
 *
 * The backend advertises each port either as a bare string (its name, e.g.
 * "rows", "project", "trigger", "file", "rows_a") or as an object carrying an
 * explicit `id`/`type`. A string is used as both the port id and its label, and
 * its data type is inferred from the name so the glyphs, edge colors and legend
 * all light up. An object keeps its own id/label and its explicit type when we
 * recognise it, otherwise the type is inferred from the id/label.
 */
export function portsFromDef(def: NodeTypeDef): {
  inputs: PipelinePort[];
  outputs: PipelinePort[];
} {
  const toPort = (
    entry: unknown,
    dir: 'input' | 'output',
    index: number,
  ): PipelinePort => {
    if (typeof entry === 'string') {
      return {
        id: entry,
        label: entry,
        dataType: inferPortType(entry),
        direction: dir,
      };
    }
    const obj = (entry ?? {}) as { id?: string; label?: string; type?: string };
    const id = obj.id || `${dir}_${index}`;
    const dataType =
      obj.type && isPortDataType(obj.type)
        ? obj.type
        : inferPortType(obj.id ?? obj.label ?? '');
    return {
      id,
      label: obj.label || obj.id || dir,
      dataType,
      direction: dir,
    };
  };
  const map = (arr: unknown, dir: 'input' | 'output'): PipelinePort[] =>
    Array.isArray(arr) ? arr.map((entry, i) => toPort(entry, dir, i)) : [];
  return {
    inputs: map(def.inputs, 'input'),
    outputs: map(def.outputs, 'output'),
  };
}

export interface PipelineCanvasProps {
  /** Catalogue from `GET /node-types/` — resolves ports on insert/hydrate. */
  nodeTypes: NodeTypeDef[];
  /** Graph to hydrate once (on pipeline load). */
  loadGraph?: PipelineGraph | null;
  /** Bumped by the page to re-trigger hydration after a fetch. */
  loadToken?: number;
  onFitViewReady?: (fit: () => void) => void;
  testId?: string;
}

function PipelineCanvasInner({
  nodeTypes,
  loadGraph,
  loadToken,
  onFitViewReady,
  testId,
}: PipelineCanvasProps) {
  const { t } = useTranslation();
  const isRTL = useIsRTL();
  const addToast = useToastStore((s) => s.addToast);

  const nodes = usePipelineStore((s) => s.nodes);
  const edges = usePipelineStore((s) => s.edges);
  const selection = usePipelineStore((s) => s.selection);
  const runNodeStates = usePipelineStore((s) => s.run.nodeStates);
  const setSelection = usePipelineStore((s) => s.setSelection);
  const moveNode = usePipelineStore((s) => s.moveNode);
  const removeNode = usePipelineStore((s) => s.removeNode);
  const removeEdge = usePipelineStore((s) => s.removeEdge);
  const addStoreEdge = usePipelineStore((s) => s.addEdge);
  const addStoreNode = usePipelineStore((s) => s.addNode);
  const copySelection = usePipelineStore((s) => s.copySelection);
  const pasteClipboard = usePipelineStore((s) => s.pasteClipboard);
  const undo = usePipelineStore((s) => s.undo);
  const redo = usePipelineStore((s) => s.redo);

  const wrapperRef = useRef<HTMLDivElement>(null);
  const [rfInstance, setRfInstance] = useState<ReactFlowInstance | null>(null);
  const reactFlow = useReactFlow();

  const defByType = useMemo(() => {
    const m = new Map<string, NodeTypeDef>();
    for (const d of nodeTypes) m.set(d.type, d);
    return m;
  }, [nodeTypes]);

  // ── Hydrate a loaded graph (canvas owns the catalogue) ──────────────────
  const hydratedFor = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (loadToken === undefined || hydratedFor.current === loadToken) return;
    hydratedFor.current = loadToken;
    if (!loadGraph || !Array.isArray(loadGraph.nodes)) return;
    // Map persisted node id → freshly-generated store id so edges relink.
    const idMap = new Map<string, string>();
    for (const gn of loadGraph.nodes) {
      const def = defByType.get(gn.type);
      const ports = def
        ? portsFromDef(def)
        : { inputs: [], outputs: [] };
      const category = (def?.category as string) ?? 'flow';
      const label =
        gn.label ||
        def?.label ||
        t(`pipeline.nodetype.${gn.type}`, { defaultValue: gn.type });
      const newId = addStoreNode({
        type: gn.type,
        category,
        title: label,
        position: gn.position ?? { x: 0, y: 0 },
        inputs: ports.inputs,
        outputs: ports.outputs,
        params: gn.params ?? {},
      });
      idMap.set(gn.id, newId);
    }
    for (const ge of loadGraph.edges ?? []) {
      const src = idMap.get(ge.source);
      const tgt = idMap.get(ge.target);
      if (!src || !tgt) continue;
      addStoreEdge({
        source: src,
        sourceHandle: ge.sourceHandle ?? 'out',
        target: tgt,
        targetHandle: ge.targetHandle ?? 'in',
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadToken]);

  // ── store → xyflow ──────────────────────────────────────────────────────
  const rfNodes: Node[] = useMemo(
    () =>
      nodes.map((n) => ({
        id: n.id,
        type: 'pipelineNode',
        position: n.position,
        data: { node: n },
        selected: selection.has(n.id),
      })),
    [nodes, selection],
  );

  const finishedNodeIds = useMemo(() => {
    const s = new Set<string>();
    for (const [nid, st] of Object.entries(runNodeStates)) {
      if (st?.status === 'done' || st?.status === 'success') s.add(nid);
    }
    return s;
  }, [runNodeStates]);

  const rfEdges: Edge[] = useMemo(
    () =>
      edges.map((e) => ({
        id: e.id,
        source: e.source,
        sourceHandle: e.sourceHandle,
        target: e.target,
        targetHandle: e.targetHandle,
        type: 'pipelineEdge',
        data: {
          dataType: e.dataType,
          flowing: finishedNodeIds.has(e.source),
        },
        markerEnd: { type: MarkerType.ArrowClosed },
      })),
    [edges, finishedNodeIds],
  );

  // ── xyflow change handlers ──────────────────────────────────────────────
  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      const updated = applyNodeChanges(changes, rfNodes);
      for (const change of changes) {
        if (change.type === 'position' && change.position) {
          moveNode(change.id, change.position);
        } else if (change.type === 'remove') {
          removeNode(change.id);
        } else if (change.type === 'select') {
          const nextSelected = updated
            .filter((n) => n.selected)
            .map((n) => n.id);
          setSelection(nextSelected);
        }
      }
    },
    [moveNode, rfNodes, removeNode, setSelection],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      void applyEdgeChanges(changes, rfEdges);
      for (const change of changes) {
        if (change.type === 'remove') removeEdge(change.id);
      }
    },
    [rfEdges, removeEdge],
  );

  const onConnect: OnConnect = useCallback(
    (params: Connection) => {
      void rfAddEdge(params, rfEdges);
      if (
        !params.source ||
        !params.target ||
        !params.sourceHandle ||
        !params.targetHandle
      ) {
        return;
      }
      const created = addStoreEdge({
        source: params.source,
        sourceHandle: params.sourceHandle,
        target: params.target,
        targetHandle: params.targetHandle,
      });
      if (!created) {
        // Incompatible drop → snap back + plain-language toast.
        const srcNode = nodes.find((n) => n.id === params.source);
        const tgtNode = nodes.find((n) => n.id === params.target);
        const srcPort = srcNode?.outputs.find(
          (p) => p.id === params.sourceHandle,
        );
        const tgtPort = tgtNode?.inputs.find(
          (p) => p.id === params.targetHandle,
        );
        addToast({
          type: 'warning',
          title: t('pipeline.connect.incompatible_title', {
            defaultValue: "These steps can't be connected",
          }),
          message: t('pipeline.connect.incompatible_body', {
            defaultValue:
              'This output is a {{from}}; that input expects a {{to}}.',
            from: srcPort
              ? t(getPortTokens(srcPort.dataType).labelKey, {
                  defaultValue: getPortTokens(srcPort.dataType).labelDefault,
                })
              : '—',
            to: tgtPort
              ? t(getPortTokens(tgtPort.dataType).labelKey, {
                  defaultValue: getPortTokens(tgtPort.dataType).labelDefault,
                })
              : '—',
          }),
        });
      }
    },
    [addStoreEdge, addToast, nodes, rfEdges, t],
  );

  // ── keyboard ────────────────────────────────────────────────────────────
  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      const mod = event.ctrlKey || event.metaKey;
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === 'INPUT' ||
          target.tagName === 'TEXTAREA' ||
          target.isContentEditable)
      ) {
        return;
      }
      if (mod && event.key.toLowerCase() === 'z' && !event.shiftKey) {
        event.preventDefault();
        undo();
      } else if (
        mod &&
        (event.key.toLowerCase() === 'y' ||
          (event.key.toLowerCase() === 'z' && event.shiftKey))
      ) {
        event.preventDefault();
        redo();
      } else if (mod && event.key.toLowerCase() === 'c') {
        copySelection();
      } else if (mod && event.key.toLowerCase() === 'v') {
        event.preventDefault();
        pasteClipboard();
      } else if (event.key === 'Delete' || event.key === 'Backspace') {
        if (selection.size === 0) return;
        event.preventDefault();
        for (const id of Array.from(selection)) removeNode(id);
      }
    },
    [copySelection, pasteClipboard, redo, removeNode, selection, undo],
  );

  // ── palette drop ────────────────────────────────────────────────────────
  const onDragOver = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
  }, []);

  const insertNodeType = useCallback(
    (type: string, position: { x: number; y: number }) => {
      const def = defByType.get(type);
      if (!def) return;
      const ports = portsFromDef(def);
      addStoreNode({
        type: def.type,
        category: (def.category as string) ?? 'flow',
        title:
          def.label ||
          t(`pipeline.nodetype.${def.type}`, { defaultValue: def.type }),
        position,
        inputs: ports.inputs,
        outputs: ports.outputs,
        params: {},
      });
    },
    [addStoreNode, defByType, t],
  );

  const onDrop = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      const raw = event.dataTransfer.getData(PIPELINE_DND_MIME);
      if (!raw) return;
      let item: PaletteDragItem;
      try {
        item = JSON.parse(raw) as PaletteDragItem;
      } catch {
        return;
      }
      const bounds = wrapperRef.current?.getBoundingClientRect();
      if (!bounds) return;
      const position = reactFlow.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });
      insertNodeType(item.type, position);
    },
    [insertNodeType, reactFlow],
  );

  const fitView = useCallback(() => {
    rfInstance?.fitView({ padding: 0.2, duration: 300 });
  }, [rfInstance]);

  useEffect(() => {
    onFitViewReady?.(fitView);
  }, [fitView, onFitViewReady]);

  // Listen for click-insert requests from the palette (no precise drag).
  useEffect(() => {
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<PaletteDragItem>).detail;
      if (!detail) return;
      const center = reactFlow.screenToFlowPosition({
        x: window.innerWidth / 2,
        y: window.innerHeight / 2,
      });
      insertNodeType(detail.type, center);
    };
    window.addEventListener('oe-pipeline-insert', handler);
    return () => window.removeEventListener('oe-pipeline-insert', handler);
  }, [insertNodeType, reactFlow]);

  return (
    <div
      ref={wrapperRef}
      data-testid={testId ?? 'pipeline-canvas'}
      className="relative h-full w-full"
      role="application"
      aria-label={t('pipeline.canvas.aria', {
        defaultValue: 'Pipeline editor canvas',
      })}
      aria-describedby="pipeline-canvas-hint"
      tabIndex={0}
      onKeyDown={handleKeyDown}
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      <span id="pipeline-canvas-hint" className="sr-only">
        {t('pipeline.canvas.hint', {
          defaultValue:
            'Drag steps from the palette, connect their ports, then press Run.',
        })}
      </span>
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onInit={setRfInstance}
        fitView
        multiSelectionKeyCode={['Meta', 'Control', 'Shift']}
        deleteKeyCode={null}
        proOptions={{ hideAttribution: true }}
        data-testid="pipeline-canvas-flow"
      >
        <Background gap={16} size={1} />
        <Controls
          position={isRTL ? 'bottom-left' : 'bottom-right'}
          showInteractive={false}
        />
        <MiniMap
          position={isRTL ? 'bottom-left' : 'bottom-right'}
          pannable
          zoomable
          nodeColor={(node: Node) => {
            const cat = (node.data as { node?: { category?: string } })?.node
              ?.category;
            return (
              CATEGORY_MINIMAP_COLOR[(cat as NodeCategory) ?? 'flow'] ??
              '#6b7280'
            );
          }}
          maskColor="rgba(15,17,23,0.5)"
          style={{ borderRadius: 8 }}
        />
        <Panel position={isRTL ? 'top-left' : 'top-right'}>
          <span className="sr-only">
            {t('pipeline.canvas.legend_sr', {
              defaultValue:
                'Edge colour, shape and dash together encode the data type.',
            })}
          </span>
        </Panel>
      </ReactFlow>
    </div>
  );
}

export function PipelineCanvas(props: PipelineCanvasProps) {
  return (
    <ReactFlowProvider>
      <PipelineCanvasInner {...props} />
    </ReactFlowProvider>
  );
}

export default PipelineCanvas;

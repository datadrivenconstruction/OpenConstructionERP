/**
 * `<BlockCanvas>` — main visual surface of the EAC block editor (EAC §3.2).
 *
 * Built on `@xyflow/react` (formerly React Flow). Responsibilities:
 *   - Render every store block as a custom `BlockNode`.
 *   - Render every store connection as a typed `SlotConnection` edge.
 *   - Forward xyflow events (move, select, connect, delete) into the store.
 *   - Accept palette drops (from `@dnd-kit/core`) and instantiate blocks at
 *     the dropped canvas coordinate.
 *   - Wire keyboard shortcuts: Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z, Ctrl/Cmd+C,
 *     Ctrl/Cmd+V, Delete/Backspace.
 *
 * The component is split into a thin outer wrapper (`<BlockCanvas>`) and an
 * inner component that runs *inside* `<ReactFlowProvider>`, so we can use
 * `useReactFlow()` for screen ↔ canvas coordinate conversion.
 */
import { useDroppable } from '@dnd-kit/core';
import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
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
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';

import { BlockNode } from './BlockNode';
import { CanvasToolbar } from './CanvasToolbar';
import { SlotConnection } from './SlotConnection';
import { buildDropPayload, colorForKind, type CanvasDropPayload } from './dnd';
import { useBlockCanvasStore } from './useBlockCanvasStore';
import type { PaletteItem } from '../components/DraggablePaletteItem';

import '@xyflow/react/dist/style.css';

const NODE_TYPES: NodeTypes = { eacBlock: BlockNode };
const EDGE_TYPES: EdgeTypes = { eacSlot: SlotConnection };

export interface BlockCanvasProps {
  /** Optional callback fired when the user clicks "save layout". */
  onSave?: (payload: { blocks: number; connections: number }) => void;
  /** Optional callback fired when the user clicks "validate". */
  onValidate?: () => void;
  /** Optional callback fired when the user clicks "compile". */
  onCompile?: () => void;
  /** Test id override. */
  testId?: string;
}

/** The droppable id used by the palette via `@dnd-kit`. */
export const CANVAS_DROPPABLE_ID = 'eac-block-canvas';

function BlockCanvasInner({ onSave, onValidate, onCompile, testId }: BlockCanvasProps) {
  const { t } = useTranslation();
  const blocks = useBlockCanvasStore((s) => s.blocks);
  const connections = useBlockCanvasStore((s) => s.connections);
  const selection = useBlockCanvasStore((s) => s.selection);
  const setSelection = useBlockCanvasStore((s) => s.setSelection);
  const moveBlock = useBlockCanvasStore((s) => s.moveBlock);
  const removeBlock = useBlockCanvasStore((s) => s.removeBlock);
  const removeConnection = useBlockCanvasStore((s) => s.removeConnection);
  const addConnection = useBlockCanvasStore((s) => s.addConnection);
  const copySelection = useBlockCanvasStore((s) => s.copySelection);
  const pasteClipboard = useBlockCanvasStore((s) => s.pasteClipboard);
  const undo = useBlockCanvasStore((s) => s.undo);
  const redo = useBlockCanvasStore((s) => s.redo);
  const addBlock = useBlockCanvasStore((s) => s.addBlock);

  const wrapperRef = useRef<HTMLDivElement>(null);
  const [rfInstance, setRfInstance] = useState<ReactFlowInstance | null>(null);
  const reactFlow = useReactFlow();

  // Droppable target for palette items dragged via @dnd-kit. The actual drop
  // payload comes from the parent `<DndContext>` — we just register the area.
  useDroppable({ id: CANVAS_DROPPABLE_ID });

  // ── Translate store → xyflow nodes/edges ─────────────────────────────
  const nodes: Node[] = useMemo(
    () =>
      blocks.map((block) => ({
        id: block.id,
        type: 'eacBlock',
        position: block.position,
        data: { block },
        selected: selection.has(block.id),
      })),
    [blocks, selection],
  );

  const edges: Edge[] = useMemo(
    () =>
      connections.map((conn) => ({
        id: conn.id,
        source: conn.sourceBlockId,
        sourceHandle: conn.sourceSlotId,
        target: conn.targetBlockId,
        targetHandle: conn.targetSlotId,
        type: 'eacSlot',
        data: { dataType: conn.dataType },
        markerEnd: { type: MarkerType.ArrowClosed },
      })),
    [connections],
  );

  // ── xyflow change handlers ───────────────────────────────────────────
  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      // Pass through to xyflow's helper so we keep its drag bookkeeping —
      // but we only act on `position` and `select` changes; everything else
      // (dimensions, etc.) is purely visual and doesn't touch the store.
      const updated = applyNodeChanges(changes, nodes);
      const positionMap = new Map<string, { x: number; y: number }>();
      for (const node of updated) {
        positionMap.set(node.id, node.position);
      }
      for (const change of changes) {
        if (change.type === 'position' && change.position) {
          moveBlock(change.id, change.position);
        } else if (change.type === 'remove') {
          removeBlock(change.id);
        } else if (change.type === 'select') {
          // Update selection set to reflect xyflow's intent. We rebuild the
          // set from scratch to keep multi-select in sync.
          const nextSelected = updated.filter((n) => n.selected).map((n) => n.id);
          setSelection(nextSelected);
        }
      }
    },
    [moveBlock, nodes, removeBlock, setSelection],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      const updated = applyEdgeChanges(changes, edges);
      // xyflow returns the new array; we only act on removals (selection of
      // an edge has no store effect — the toolbar derives it).
      void updated;
      for (const change of changes) {
        if (change.type === 'remove') {
          removeConnection(change.id);
        }
      }
    },
    [edges, removeConnection],
  );

  const onConnect: OnConnect = useCallback(
    (params: Connection) => {
      // Fall through to xyflow's `addEdge` for visual continuity, then push
      // to the store. The store re-validates type compatibility and may
      // refuse — when it does, we don't need to roll back because xyflow's
      // `addEdge` is local-only (we re-render from the store).
      void addEdge(params, edges);
      if (!params.source || !params.target || !params.sourceHandle || !params.targetHandle) {
        return;
      }
      addConnection({
        sourceBlockId: params.source,
        sourceSlotId: params.sourceHandle,
        targetBlockId: params.target,
        targetSlotId: params.targetHandle,
      });
    },
    [addConnection, edges],
  );

  // ── Keyboard shortcuts ───────────────────────────────────────────────
  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLDivElement>) => {
      const mod = event.ctrlKey || event.metaKey;
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) {
        return;
      }
      if (mod && event.key.toLowerCase() === 'z' && !event.shiftKey) {
        event.preventDefault();
        undo();
      } else if (mod && (event.key.toLowerCase() === 'y' || (event.key.toLowerCase() === 'z' && event.shiftKey))) {
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
        for (const id of Array.from(selection)) {
          removeBlock(id);
        }
      }
    },
    [copySelection, pasteClipboard, redo, removeBlock, selection, undo],
  );

  // ── HTML5 drag-drop integration (palette → canvas) ───────────────────
  const onDragOver = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'copy';
  }, []);

  const onDrop = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      const raw = event.dataTransfer.getData('application/x-eac-palette-item');
      if (!raw) return;
      let item: PaletteItem;
      try {
        item = JSON.parse(raw) as PaletteItem;
      } catch {
        return;
      }
      const bounds = wrapperRef.current?.getBoundingClientRect();
      if (!bounds) return;
      const position = reactFlow.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });
      const drop: CanvasDropPayload = buildDropPayload({
        paletteItemId: item.id,
        paletteLabel: item.label,
        paletteColor: item.color ?? colorForKind(item.id),
        paletteRawPayload: item.payload,
        position,
      });
      addBlock(drop);
    },
    [addBlock, reactFlow],
  );

  // Save fit-view callback for the toolbar.
  const fitView = useCallback(() => {
    rfInstance?.fitView({ padding: 0.2, duration: 300 });
  }, [rfInstance]);

  const handleSave = useCallback(() => {
    onSave?.({ blocks: blocks.length, connections: connections.length });
  }, [blocks.length, connections.length, onSave]);

  // Reset selection when the underlying graph empties (e.g. after undo).
  useEffect(() => {
    if (blocks.length === 0 && selection.size > 0) {
      setSelection([]);
    }
  }, [blocks.length, selection.size, setSelection]);

  return (
    <div
      ref={wrapperRef}
      data-testid={testId ?? 'eac-block-canvas'}
      className="flex h-full w-full flex-col"
      role="region"
      aria-label={t('eac.canvas.region', { defaultValue: 'Block editor canvas' })}
      tabIndex={0}
      onKeyDown={handleKeyDown}
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      <CanvasToolbar onFitView={fitView} onSave={handleSave} onValidate={onValidate} onCompile={onCompile} />
      <div className="relative flex-1">
        <ReactFlow
          nodes={nodes}
          edges={edges}
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
          data-testid="eac-block-canvas-flow"
        >
          <Background gap={16} size={1} />
          <Controls position="bottom-right" showInteractive={false} />
        </ReactFlow>
      </div>
    </div>
  );
}

export function BlockCanvas(props: BlockCanvasProps) {
  return (
    <ReactFlowProvider>
      <BlockCanvasInner {...props} />
    </ReactFlowProvider>
  );
}

export default BlockCanvas;

/**
 * Zustand store backing the EAC visual block editor canvas (EAC §3.2).
 *
 * The store owns:
 *   - `blocks`     — every block placed on the canvas, with position + slots.
 *   - `connections`— wires between slots (output → input), with cached colors.
 *   - `selection`  — set of selected block ids (canvas multi-select).
 *   - `clipboard`  — last copied blocks for paste support.
 *   - `history`    — bounded undo/redo stack of immutable snapshots.
 *
 * Actions are intentionally small and pure — every mutation goes through
 * `pushHistory()` so undo/redo is consistent. The history depth is capped
 * (`HISTORY_LIMIT`) so memory stays bounded for long editing sessions.
 *
 * Connection insertion enforces the slot-type compatibility matrix from
 * `dnd.ts` so the UI can rely on the store rejecting invalid edges
 * regardless of which surface (xyflow handle, keyboard, paste) created
 * them.
 */
import { create } from 'zustand';

import type { BlockColor } from '../types';
import type { CanvasDropPayload, SlotDataType, SlotDefinition } from './dnd';
import { canConnectSlots } from './dnd';

// ── Types ────────────────────────────────────────────────────────────────

export interface CanvasBlock {
  id: string;
  /** Block kind, e.g. "and", "ifc_class", "triplet". */
  kind: string;
  /** Visual color identity, derived from kind via `colorForKind`. */
  color: BlockColor;
  /** Display title — editable inline on the node. */
  title: string;
  /** Position in canvas coordinates. */
  position: { x: number; y: number };
  /** Slot definitions (input + output) on this block. */
  slots: SlotDefinition[];
  /** Free-form parameters for the block (e.g. constraint operator, value). */
  params: Record<string, unknown>;
  /** Whether the parameters panel is expanded on the node. */
  expanded: boolean;
}

export interface CanvasConnection {
  id: string;
  sourceBlockId: string;
  sourceSlotId: string;
  targetBlockId: string;
  targetSlotId: string;
  /** Cached data type for color rendering — derived from the source slot. */
  dataType: SlotDataType;
}

interface CanvasSnapshot {
  blocks: CanvasBlock[];
  connections: CanvasConnection[];
}

export interface BlockCanvasState {
  blocks: CanvasBlock[];
  connections: CanvasConnection[];
  selection: Set<string>;
  clipboard: CanvasBlock[];
  history: CanvasSnapshot[];
  /** Pointer into `history`; index of the snapshot we'd land on for redo. */
  historyIndex: number;
}

export interface BlockCanvasActions {
  addBlock: (drop: CanvasDropPayload, slots?: SlotDefinition[]) => string;
  removeBlock: (id: string) => void;
  updateBlock: (id: string, patch: Partial<Omit<CanvasBlock, 'id'>>) => void;
  moveBlock: (id: string, position: { x: number; y: number }) => void;
  setBlockTitle: (id: string, title: string) => void;
  toggleBlockExpanded: (id: string) => void;
  setSelection: (ids: string[]) => void;
  toggleSelection: (id: string) => void;
  clearSelection: () => void;
  copySelection: () => void;
  pasteClipboard: (offset?: { x: number; y: number }) => string[];
  addConnection: (conn: Omit<CanvasConnection, 'id' | 'dataType'>) => CanvasConnection | null;
  removeConnection: (id: string) => void;
  undo: () => void;
  redo: () => void;
  reset: () => void;
  /** Replace the entire graph (e.g. when loading a saved layout). */
  loadGraph: (snapshot: CanvasSnapshot) => void;
}

export type BlockCanvasStore = BlockCanvasState & BlockCanvasActions;

// ── Constants ────────────────────────────────────────────────────────────

const HISTORY_LIMIT = 50;
const PASTE_DEFAULT_OFFSET = { x: 32, y: 32 };

const EMPTY_SNAPSHOT: CanvasSnapshot = { blocks: [], connections: [] };

// ── Helpers ──────────────────────────────────────────────────────────────

let _idCounter = 0;
/**
 * Generate a deterministic-ish unique id for blocks/connections. We use a
 * monotonic counter + crypto-random suffix when available, falling back to
 * `Math.random` so jsdom + node tests work without `globalThis.crypto`.
 */
function genId(prefix: string): string {
  _idCounter += 1;
  let suffix: string;
  const cryptoLike = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (cryptoLike?.randomUUID) {
    suffix = cryptoLike.randomUUID().slice(0, 8);
  } else {
    suffix = Math.random().toString(36).slice(2, 10);
  }
  return `${prefix}_${_idCounter}_${suffix}`;
}

/** Clone a block, deep enough that mutations don't bleed across snapshots. */
function cloneBlock(block: CanvasBlock): CanvasBlock {
  return {
    ...block,
    position: { ...block.position },
    slots: block.slots.map((slot) => ({ ...slot })),
    params: { ...block.params },
  };
}

function cloneConnection(conn: CanvasConnection): CanvasConnection {
  return { ...conn };
}

function cloneSnapshot(snap: CanvasSnapshot): CanvasSnapshot {
  return {
    blocks: snap.blocks.map(cloneBlock),
    connections: snap.connections.map(cloneConnection),
  };
}

/** Find a slot on a block by id, or undefined. */
function findSlot(block: CanvasBlock | undefined, slotId: string): SlotDefinition | undefined {
  return block?.slots.find((s) => s.id === slotId);
}

// ── Store factory ────────────────────────────────────────────────────────

export const useBlockCanvasStore = create<BlockCanvasStore>((set, get) => {
  /**
   * Commit the *post-mutation* state to history. Mutating actions call this
   * after writing the new `blocks` / `connections` so the latest snapshot
   * is on top of the stack and undo lands on the prior state.
   *
   * The history starts with one snapshot (the empty initial state), so
   * `historyIndex` is always >= 0 and `undo()` can step back to that
   * baseline whenever any mutation happened.
   */
  function commitHistory(next: { blocks: CanvasBlock[]; connections: CanvasConnection[] }) {
    const { history, historyIndex } = get();
    const snapshot = cloneSnapshot(next);
    // Drop any "redo" tail when a new mutation diverges from history.
    const trimmed = history.slice(0, historyIndex + 1);
    trimmed.push(snapshot);
    while (trimmed.length > HISTORY_LIMIT) {
      trimmed.shift();
    }
    set({ history: trimmed, historyIndex: trimmed.length - 1 });
  }

  return {
    // ── State defaults ───────────────────────────────────────────────────
    blocks: [],
    connections: [],
    selection: new Set<string>(),
    clipboard: [],
    history: [cloneSnapshot(EMPTY_SNAPSHOT)],
    historyIndex: 0,

    // ── Block actions ────────────────────────────────────────────────────
    addBlock: (drop, slots) => {
      const id = genId('block');
      const block: CanvasBlock = {
        id,
        kind: drop.kind,
        color: drop.color,
        title: drop.label,
        position: { ...drop.position },
        slots: slots ?? [],
        params: { ...drop.payload },
        expanded: false,
      };
      const nextBlocks = [...get().blocks, block];
      set({ blocks: nextBlocks });
      commitHistory({ blocks: nextBlocks, connections: get().connections });
      return id;
    },

    removeBlock: (id) => {
      const { blocks, connections } = get();
      if (!blocks.some((b) => b.id === id)) return;
      const nextSelection = new Set(get().selection);
      nextSelection.delete(id);
      const nextBlocks = blocks.filter((b) => b.id !== id);
      const nextConnections = connections.filter(
        (c) => c.sourceBlockId !== id && c.targetBlockId !== id,
      );
      set({
        blocks: nextBlocks,
        connections: nextConnections,
        selection: nextSelection,
      });
      commitHistory({ blocks: nextBlocks, connections: nextConnections });
    },

    updateBlock: (id, patch) => {
      const { blocks } = get();
      if (!blocks.some((b) => b.id === id)) return;
      const nextBlocks = blocks.map((b) =>
        b.id === id
          ? {
              ...b,
              ...patch,
              position: patch.position ? { ...patch.position } : b.position,
              params: patch.params ? { ...patch.params } : b.params,
              slots: patch.slots ? patch.slots.map((s) => ({ ...s })) : b.slots,
            }
          : b,
      );
      set({ blocks: nextBlocks });
      commitHistory({ blocks: nextBlocks, connections: get().connections });
    },

    moveBlock: (id, position) => {
      // Position-only changes don't push history — drag operations would
      // explode the stack. The canvas calls `pushHistory()` itself once
      // at drag start.
      const { blocks } = get();
      set({
        blocks: blocks.map((b) =>
          b.id === id ? { ...b, position: { ...position } } : b,
        ),
      });
    },

    setBlockTitle: (id, title) => {
      const { blocks } = get();
      const block = blocks.find((b) => b.id === id);
      if (!block || block.title === title) return;
      const nextBlocks = blocks.map((b) => (b.id === id ? { ...b, title } : b));
      set({ blocks: nextBlocks });
      commitHistory({ blocks: nextBlocks, connections: get().connections });
    },

    toggleBlockExpanded: (id) => {
      const { blocks } = get();
      const block = blocks.find((b) => b.id === id);
      if (!block) return;
      // No history for expand/collapse — pure UI state.
      set({
        blocks: blocks.map((b) =>
          b.id === id ? { ...b, expanded: !b.expanded } : b,
        ),
      });
    },

    // ── Selection ────────────────────────────────────────────────────────
    setSelection: (ids) => {
      set({ selection: new Set(ids) });
    },

    toggleSelection: (id) => {
      const next = new Set(get().selection);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      set({ selection: next });
    },

    clearSelection: () => {
      if (get().selection.size === 0) return;
      set({ selection: new Set() });
    },

    // ── Clipboard ────────────────────────────────────────────────────────
    copySelection: () => {
      const { blocks, selection } = get();
      const copied = blocks
        .filter((b) => selection.has(b.id))
        .map(cloneBlock);
      set({ clipboard: copied });
    },

    pasteClipboard: (offset = PASTE_DEFAULT_OFFSET) => {
      const { clipboard } = get();
      if (clipboard.length === 0) return [];
      const newIds: string[] = [];
      const fresh = clipboard.map((b) => {
        const id = genId('block');
        newIds.push(id);
        return {
          ...cloneBlock(b),
          id,
          position: { x: b.position.x + offset.x, y: b.position.y + offset.y },
        };
      });
      const nextBlocks = [...get().blocks, ...fresh];
      set({
        blocks: nextBlocks,
        selection: new Set(newIds),
      });
      commitHistory({ blocks: nextBlocks, connections: get().connections });
      return newIds;
    },

    // ── Connections ──────────────────────────────────────────────────────
    addConnection: (raw) => {
      const { blocks, connections } = get();
      const sourceBlock = blocks.find((b) => b.id === raw.sourceBlockId);
      const targetBlock = blocks.find((b) => b.id === raw.targetBlockId);
      const sourceSlot = findSlot(sourceBlock, raw.sourceSlotId);
      const targetSlot = findSlot(targetBlock, raw.targetSlotId);
      if (!sourceSlot || !targetSlot) return null;
      if (!canConnectSlots(sourceSlot, targetSlot)) return null;
      // Prevent duplicate edges between the same slot pair.
      const dup = connections.find(
        (c) =>
          c.sourceBlockId === raw.sourceBlockId &&
          c.sourceSlotId === raw.sourceSlotId &&
          c.targetBlockId === raw.targetBlockId &&
          c.targetSlotId === raw.targetSlotId,
      );
      if (dup) return dup;
      // Self-loops are nonsense — the source and target must differ.
      if (raw.sourceBlockId === raw.targetBlockId) return null;
      const conn: CanvasConnection = {
        id: genId('conn'),
        sourceBlockId: raw.sourceBlockId,
        sourceSlotId: raw.sourceSlotId,
        targetBlockId: raw.targetBlockId,
        targetSlotId: raw.targetSlotId,
        dataType: sourceSlot.dataType,
      };
      const nextConnections = [...connections, conn];
      set({ connections: nextConnections });
      commitHistory({ blocks: get().blocks, connections: nextConnections });
      return conn;
    },

    removeConnection: (id) => {
      const { connections } = get();
      if (!connections.some((c) => c.id === id)) return;
      const nextConnections = connections.filter((c) => c.id !== id);
      set({ connections: nextConnections });
      commitHistory({ blocks: get().blocks, connections: nextConnections });
    },

    // ── History ──────────────────────────────────────────────────────────
    undo: () => {
      const { history, historyIndex } = get();
      if (historyIndex <= 0) return;
      const target = history[historyIndex - 1];
      if (!target) return;
      const restored = cloneSnapshot(target);
      set({
        blocks: restored.blocks,
        connections: restored.connections,
        historyIndex: historyIndex - 1,
      });
    },

    redo: () => {
      const { history, historyIndex } = get();
      if (historyIndex >= history.length - 1) return;
      const target = history[historyIndex + 1];
      if (!target) return;
      const restored = cloneSnapshot(target);
      set({
        blocks: restored.blocks,
        connections: restored.connections,
        historyIndex: historyIndex + 1,
      });
    },

    reset: () => {
      set({
        blocks: [],
        connections: [],
        selection: new Set(),
        clipboard: [],
        history: [cloneSnapshot(EMPTY_SNAPSHOT)],
        historyIndex: 0,
      });
    },

    loadGraph: (snapshot) => {
      const restored = cloneSnapshot(snapshot);
      set({
        blocks: restored.blocks,
        connections: restored.connections,
        selection: new Set(),
        // Reset history: the loaded graph is the new baseline so prior
        // edits aren't conflated with new ones in the undo stack.
        history: [cloneSnapshot(snapshot)],
        historyIndex: 0,
      });
    },
  };
});

/** Convenience selector — returns the currently selected blocks. */
export function selectSelectedBlocks(state: BlockCanvasStore): CanvasBlock[] {
  return state.blocks.filter((b) => state.selection.has(b.id));
}

/** True when any undo step is available. */
export function selectCanUndo(state: BlockCanvasStore): boolean {
  return state.historyIndex > 0;
}

/** True when any redo step is available. */
export function selectCanRedo(state: BlockCanvasStore): boolean {
  return state.historyIndex < state.history.length - 1;
}

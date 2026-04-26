/**
 * Tests for the canvas Zustand store. Covers add/remove/move, undo/redo,
 * selection + clipboard, and the connection compatibility guard.
 *
 * Each test resets the store first via `reset()` so they don't share state.
 */
import { beforeEach, describe, expect, it } from 'vitest';

import type { CanvasDropPayload, SlotDefinition } from '../dnd';
import {
  selectCanRedo,
  selectCanUndo,
  useBlockCanvasStore,
} from '../useBlockCanvasStore';

const SAMPLE_DROP: CanvasDropPayload = {
  kind: 'and',
  color: 'logic',
  payload: { type: 'and' },
  position: { x: 10, y: 20 },
  label: 'AND',
};

const SAMPLE_SLOTS: SlotDefinition[] = [
  { id: 'in', label: 'in', direction: 'input', dataType: 'predicate' },
  { id: 'out', label: 'out', direction: 'output', dataType: 'predicate' },
];

describe('useBlockCanvasStore', () => {
  beforeEach(() => {
    useBlockCanvasStore.getState().reset();
  });

  it('starts empty and not undoable', () => {
    const state = useBlockCanvasStore.getState();
    expect(state.blocks).toHaveLength(0);
    expect(state.connections).toHaveLength(0);
    expect(selectCanUndo(state)).toBe(false);
    expect(selectCanRedo(state)).toBe(false);
  });

  it('adds a block via addBlock and tracks history', () => {
    const id = useBlockCanvasStore.getState().addBlock(SAMPLE_DROP, SAMPLE_SLOTS);
    const state = useBlockCanvasStore.getState();
    expect(state.blocks).toHaveLength(1);
    const [first] = state.blocks;
    expect(first?.id).toBe(id);
    expect(first?.title).toBe('AND');
    expect(first?.position).toEqual({ x: 10, y: 20 });
    expect(selectCanUndo(state)).toBe(true);
  });

  it('removes a block and its connections together', () => {
    const a = useBlockCanvasStore.getState().addBlock(
      { ...SAMPLE_DROP, position: { x: 0, y: 0 }, label: 'A' },
      SAMPLE_SLOTS,
    );
    const b = useBlockCanvasStore.getState().addBlock(
      { ...SAMPLE_DROP, position: { x: 200, y: 0 }, label: 'B' },
      SAMPLE_SLOTS,
    );
    const conn = useBlockCanvasStore.getState().addConnection({
      sourceBlockId: a,
      sourceSlotId: 'out',
      targetBlockId: b,
      targetSlotId: 'in',
    });
    expect(conn).not.toBeNull();
    expect(useBlockCanvasStore.getState().connections).toHaveLength(1);

    useBlockCanvasStore.getState().removeBlock(a);
    expect(useBlockCanvasStore.getState().blocks.map((b) => b.id)).toEqual([b]);
    expect(useBlockCanvasStore.getState().connections).toHaveLength(0);
  });

  it('rejects type-mismatched connections', () => {
    const a = useBlockCanvasStore.getState().addBlock(SAMPLE_DROP, [
      { id: 'out', label: 'o', direction: 'output', dataType: 'predicate' },
    ]);
    const b = useBlockCanvasStore.getState().addBlock(
      { ...SAMPLE_DROP, position: { x: 200, y: 0 } },
      [{ id: 'in', label: 'i', direction: 'input', dataType: 'attribute' }],
    );
    const conn = useBlockCanvasStore.getState().addConnection({
      sourceBlockId: a,
      sourceSlotId: 'out',
      targetBlockId: b,
      targetSlotId: 'in',
    });
    expect(conn).toBeNull();
    expect(useBlockCanvasStore.getState().connections).toHaveLength(0);
  });

  it('rejects self-loop connections', () => {
    const a = useBlockCanvasStore.getState().addBlock(SAMPLE_DROP, SAMPLE_SLOTS);
    const conn = useBlockCanvasStore.getState().addConnection({
      sourceBlockId: a,
      sourceSlotId: 'out',
      targetBlockId: a,
      targetSlotId: 'in',
    });
    expect(conn).toBeNull();
  });

  it('undoes and redoes addBlock', () => {
    useBlockCanvasStore.getState().addBlock(SAMPLE_DROP, SAMPLE_SLOTS);
    expect(useBlockCanvasStore.getState().blocks).toHaveLength(1);

    useBlockCanvasStore.getState().undo();
    expect(useBlockCanvasStore.getState().blocks).toHaveLength(0);
    expect(selectCanRedo(useBlockCanvasStore.getState())).toBe(true);

    useBlockCanvasStore.getState().redo();
    expect(useBlockCanvasStore.getState().blocks).toHaveLength(1);
  });

  it('copies and pastes selected blocks with a position offset', () => {
    const id = useBlockCanvasStore.getState().addBlock(SAMPLE_DROP, SAMPLE_SLOTS);
    useBlockCanvasStore.getState().setSelection([id]);
    useBlockCanvasStore.getState().copySelection();
    const newIds = useBlockCanvasStore.getState().pasteClipboard({ x: 50, y: 50 });
    expect(newIds).toHaveLength(1);
    const blocks = useBlockCanvasStore.getState().blocks;
    expect(blocks).toHaveLength(2);
    const original = blocks.find((b) => b.id === id)!;
    const pasted = blocks.find((b) => b.id === newIds[0])!;
    expect(pasted.position).toEqual({ x: original.position.x + 50, y: original.position.y + 50 });
  });

  it('toggles selection cleanly', () => {
    const id = useBlockCanvasStore.getState().addBlock(SAMPLE_DROP, SAMPLE_SLOTS);
    useBlockCanvasStore.getState().toggleSelection(id);
    expect(useBlockCanvasStore.getState().selection.has(id)).toBe(true);
    useBlockCanvasStore.getState().toggleSelection(id);
    expect(useBlockCanvasStore.getState().selection.has(id)).toBe(false);
  });

  it('updates block title via setBlockTitle (history aware)', () => {
    const id = useBlockCanvasStore.getState().addBlock(SAMPLE_DROP, SAMPLE_SLOTS);
    useBlockCanvasStore.getState().setBlockTitle(id, 'Renamed');
    expect(useBlockCanvasStore.getState().blocks[0]?.title).toBe('Renamed');
    useBlockCanvasStore.getState().undo();
    expect(useBlockCanvasStore.getState().blocks[0]?.title).toBe('AND');
  });

  it('toggles block expanded without polluting history', () => {
    const id = useBlockCanvasStore.getState().addBlock(SAMPLE_DROP, SAMPLE_SLOTS);
    const before = useBlockCanvasStore.getState().historyIndex;
    useBlockCanvasStore.getState().toggleBlockExpanded(id);
    expect(useBlockCanvasStore.getState().blocks[0]?.expanded).toBe(true);
    expect(useBlockCanvasStore.getState().historyIndex).toBe(before);
  });
});

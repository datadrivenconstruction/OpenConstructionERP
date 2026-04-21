/**
 * Unit tests for the linear undo/redo reducer (Q1 UX #2).
 */

import { describe, it, expect } from 'vitest';
import {
  canRedo,
  canUndo,
  emptyUndoState,
  MAX_STACK,
  popRedo,
  popUndo,
  pushUndo,
  snapshotFrom,
  type AnnotationSnapshot,
  type UndoEntry,
} from '../undo-stack';
import type { DwgAnnotation } from '../../api';

function mkSnapshot(id: string): AnnotationSnapshot {
  return {
    id,
    annotation_type: 'line',
    points: [
      { x: 0, y: 0 },
      { x: 1, y: 1 },
    ],
    text: null,
    color: '#ef4444',
    measurement_value: null,
    measurement_unit: null,
    layer_name: 'USER_MARKUP',
  };
}

function createEntry(id: string): UndoEntry {
  return { kind: 'create', id, snapshot: mkSnapshot(id) };
}

describe('undo-stack reducer', () => {
  it('starts empty', () => {
    const s = emptyUndoState();
    expect(canUndo(s)).toBe(false);
    expect(canRedo(s)).toBe(false);
  });

  it('push grows undo and wipes redo', () => {
    let s = emptyUndoState();
    s = pushUndo(s, createEntry('a'));
    s = pushUndo(s, createEntry('b'));
    expect(s.undo.length).toBe(2);
    expect(s.redo.length).toBe(0);

    // Undo once, then push — redo should wipe.
    const popped = popUndo(s);
    s = popped.state;
    expect(popped.entry?.kind).toBe('create');
    expect(s.redo.length).toBe(1);

    s = pushUndo(s, createEntry('c'));
    expect(s.redo.length).toBe(0);
  });

  it('popUndo moves top entry to redo and returns it', () => {
    let s = emptyUndoState();
    s = pushUndo(s, createEntry('a'));
    s = pushUndo(s, createEntry('b'));

    const { state: next, entry } = popUndo(s);
    expect(entry).toBeTruthy();
    if (entry?.kind === 'create') {
      expect(entry.id).toBe('b');
    }
    expect(next.undo.length).toBe(1);
    expect(next.redo.length).toBe(1);
  });

  it('popUndo on empty stack returns null entry & unchanged state', () => {
    const s = emptyUndoState();
    const { state: next, entry } = popUndo(s);
    expect(entry).toBeNull();
    expect(next).toBe(s);
  });

  it('popRedo moves top redo entry back onto undo', () => {
    let s = emptyUndoState();
    s = pushUndo(s, createEntry('a'));
    const p1 = popUndo(s);
    s = p1.state;
    // Now undo is empty, redo has 'a'.
    expect(canUndo(s)).toBe(false);
    expect(canRedo(s)).toBe(true);

    const p2 = popRedo(s);
    s = p2.state;
    expect(p2.entry?.kind).toBe('create');
    expect(canUndo(s)).toBe(true);
    expect(canRedo(s)).toBe(false);
  });

  it('popRedo on empty redo returns null entry', () => {
    const s = emptyUndoState();
    const { entry } = popRedo(s);
    expect(entry).toBeNull();
  });

  it('caps undo stack at MAX_STACK entries (oldest drops)', () => {
    let s = emptyUndoState();
    for (let i = 0; i < MAX_STACK + 5; i++) {
      s = pushUndo(s, createEntry(`e${i}`));
    }
    expect(s.undo.length).toBe(MAX_STACK);
    // Oldest should be 'e5' (i=0..4 dropped), newest 'e{MAX_STACK+4}'.
    const first = s.undo[0]!;
    const last = s.undo[s.undo.length - 1]!;
    if (first.kind === 'create') expect(first.id).toBe('e5');
    if (last.kind === 'create') expect(last.id).toBe(`e${MAX_STACK + 4}`);
  });

  it('round-trips create → undo → redo without loss', () => {
    let s = emptyUndoState();
    const entry = createEntry('x');
    s = pushUndo(s, entry);
    const p1 = popUndo(s);
    s = p1.state;
    expect(p1.entry).toEqual(entry);

    const p2 = popRedo(s);
    s = p2.state;
    expect(p2.entry).toEqual(entry);
    expect(s.undo.length).toBe(1);
    expect(s.redo.length).toBe(0);
  });

  it('handles mixed entry kinds (create, delete, edit)', () => {
    let s = emptyUndoState();
    s = pushUndo(s, { kind: 'create', id: 'a', snapshot: mkSnapshot('a') });
    s = pushUndo(s, { kind: 'delete', snapshot: mkSnapshot('b') });
    s = pushUndo(s, {
      kind: 'edit',
      id: 'c',
      before: { color: '#ef4444' },
      after: { color: '#22c55e' },
    });
    expect(s.undo.length).toBe(3);

    const p = popUndo(s);
    expect(p.entry?.kind).toBe('edit');
  });
});

describe('snapshotFrom', () => {
  it('maps a DwgAnnotation into a replay-able snapshot', () => {
    const ann: DwgAnnotation = {
      id: 'ann-1',
      drawing_id: 'draw-1',
      type: 'distance',
      points: [
        { x: 5, y: 5 },
        { x: 10, y: 10 },
      ],
      text: 'wall length',
      color: '#3b82f6',
      measurement_value: 7.07,
      measurement_unit: 'm',
      linked_boq_position_id: null,
      layer_name: 'USER_MARKUP',
      metadata: { font_size: 14 },
      created_by: 'u1',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    };

    const snap = snapshotFrom(ann);
    expect(snap.id).toBe('ann-1');
    expect(snap.annotation_type).toBe('distance');
    expect(snap.points).toHaveLength(2);
    expect(snap.color).toBe('#3b82f6');
    expect(snap.measurement_value).toBe(7.07);
    expect(snap.metadata).toEqual({ font_size: 14 });
  });

  // Regression test for the Q2 production-blocker crash.
  //
  // The create-annotation mutation hands ``snapshotFrom`` the raw backend
  // response, which uses ``annotation_type`` + ``geometry.points`` rather
  // than ``type`` + ``points``. Before the fix, ``ann.points.map`` threw
  // ``Cannot read properties of undefined (reading 'map')`` on every tool
  // that created an annotation (distance, line, rectangle, polyline,
  // area, circle, text_pin, arrow) — and because the throw happens inside
  // ``setUndoState``, any subsequent render (snap-menu open, tool switch)
  // re-entered the same callback and re-threw, so every tool + the Snap
  // button all appeared to crash together.
  it('normalises backend-shape responses (annotation_type + geometry.points)', () => {
    const backendResponse = {
      id: 'ann-42',
      project_id: 'p1',
      drawing_id: 'draw-1',
      annotation_type: 'area' as const,
      geometry: {
        points: [
          { x: 10, y: 10 },
          { x: 20, y: 10 },
          { x: 20, y: 20 },
        ],
      },
      text: null,
      color: '#22c55e',
      line_width: 2,
      thickness: 2.0,
      layer_name: 'USER_MARKUP',
      measurement_value: 100,
      measurement_unit: 'm²',
      scale_override: null,
      linked_boq_position_id: null,
      created_by: 'u1',
      metadata: {},
      created_at: '2026-04-21T00:00:00Z',
      updated_at: '2026-04-21T00:00:00Z',
    };
    // Cast to DwgAnnotation to match the (broken) call-site type. This is
    // exactly how ``onSuccess: (created) => ...snapshotFrom(created)`` sees
    // the value — the runtime shape differs from the declared type.
    const snap = snapshotFrom(backendResponse as unknown as DwgAnnotation);
    expect(snap.id).toBe('ann-42');
    expect(snap.annotation_type).toBe('area');
    expect(snap.points).toEqual([
      { x: 10, y: 10 },
      { x: 20, y: 10 },
      { x: 20, y: 20 },
    ]);
    expect(snap.measurement_value).toBe(100);
  });

  // Defence-in-depth: missing ``points`` entirely must not crash. Older
  // rows / truncated responses shouldn't take the whole undo stack down.
  it('falls back to an empty points array when neither shape has points', () => {
    const malformed = { id: 'ann-0', annotation_type: 'line' as const };
    const snap = snapshotFrom(malformed as unknown as DwgAnnotation);
    expect(snap.id).toBe('ann-0');
    expect(snap.points).toEqual([]);
  });
});

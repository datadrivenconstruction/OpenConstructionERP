// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { beforeEach, describe, expect, it } from 'vitest';
import type { PlanFeature } from '../types';
import { usePlanEditStore } from '../usePlanEditStore';
import { MAX_COMMANDS, createFeature, deleteFeatures, insertVertex, moveVertex, netOps, removeVertex, updateFeature } from './commands';

const pt = (id: string, e: number, n: number, rev?: number): PlanFeature => ({
  id,
  layer: 'points',
  geometry: { type: 'Point', coordinates: [e, n, 10] },
  properties: { label: id },
  entityType: 'point',
  entityId: rev != null ? id : undefined,
  rev,
});
const ring: PlanFeature = {
  id: 'r',
  layer: 'sketch',
  geometry: { type: 'Polygon', coordinates: [[[0, 0], [10, 0], [10, 10]]] },
  properties: {},
};

describe('vertex edits', () => {
  it('move, insert and remove keep the geometry type', () => {
    const moved = moveVertex(ring, 1, [12, 0]);
    expect(moved.geometry).toEqual({ type: 'Polygon', coordinates: [[[0, 0], [12, 0], [10, 10]]] });
    const inserted = insertVertex(moved, 0, [6, -1]);
    expect(inserted.geometry.type === 'Polygon' && inserted.geometry.coordinates[0]!.length).toBe(4);
    expect(removeVertex(ring, 0)).toBeNull();
    expect(removeVertex(inserted, 1)?.geometry).toEqual(moved.geometry);
  });

  it('a closed ring keeps its closing vertex on move and remove', () => {
    const closed: PlanFeature = { ...ring, geometry: { type: 'Polygon', coordinates: [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]] } };
    expect(moveVertex(closed, 0, [-1, -1]).geometry).toEqual({ type: 'Polygon', coordinates: [[[-1, -1], [10, 0], [10, 10], [0, 10], [-1, -1]]] });
    expect(removeVertex(closed, 0)?.geometry).toEqual({ type: 'Polygon', coordinates: [[[10, 0], [10, 10], [0, 10], [10, 0]]] });
    const tri: PlanFeature = { ...ring, geometry: { type: 'Polygon', coordinates: [[[0, 0], [10, 0], [10, 10], [0, 0]]] } };
    expect(removeVertex(tri, 1)).toBeNull();
  });

  it('moving a point keeps its Z', () => {
    expect(moveVertex(pt('a', 1, 2), 0, [5, 6]).geometry).toEqual({ type: 'Point', coordinates: [5, 6, 10] });
  });
});

describe('undo/redo store', () => {
  beforeEach(() => {
    sessionStorage.clear();
    usePlanEditStore.setState({ scope: null });
    usePlanEditStore.getState().bind('test');
    usePlanEditStore.getState().setBase([pt('a', 0, 0, 3)]);
  });

  it('applies, undoes and redoes 200 commands exactly', () => {
    const s = usePlanEditStore.getState;
    let cur = s().working.get('a')!;
    for (let i = 1; i <= MAX_COMMANDS; i++) {
      const next = moveVertex(cur, 0, [i, i]);
      s().push(updateFeature(cur, next));
      cur = next;
    }
    expect(s().undo).toHaveLength(MAX_COMMANDS);
    expect(s().working.get('a')!.geometry.coordinates).toEqual([200, 200, 10]);
    for (let i = 0; i < MAX_COMMANDS; i++) s().undoOne();
    expect(s().working.get('a')!.geometry.coordinates).toEqual([0, 0, 10]);
    s().undoOne();
    expect(s().working.get('a')!.geometry.coordinates).toEqual([0, 0, 10]);
    for (let i = 0; i < MAX_COMMANDS; i++) s().redoOne();
    expect(s().working.get('a')!.geometry.coordinates).toEqual([200, 200, 10]);
  });

  it('drops the oldest past 200 but still saves it', () => {
    const s = usePlanEditStore.getState;
    let cur = s().working.get('a')!;
    for (let i = 1; i <= MAX_COMMANDS + 5; i++) {
      const next = moveVertex(cur, 0, [i, 0]);
      s().push(updateFeature(cur, next));
      cur = next;
    }
    expect(s().undo).toHaveLength(MAX_COMMANDS);
    for (let i = 0; i < MAX_COMMANDS; i++) s().undoOne();
    // The 5 settled commands stay applied.
    expect(s().working.get('a')!.geometry.coordinates).toEqual([5, 0, 10]);
    const ops = s().ops();
    expect(ops).toHaveLength(1);
    expect(ops[0]).toMatchObject({ entity_type: 'point', entity_id: 'a', op: 'update', base_rev: 3 });
  });

  it('a new command clears redo', () => {
    const s = usePlanEditStore.getState;
    const a = s().working.get('a')!;
    s().push(updateFeature(a, moveVertex(a, 0, [1, 1])));
    s().undoOne();
    expect(s().redo).toHaveLength(1);
    s().push(createFeature(pt('b', 5, 5)));
    expect(s().redo).toHaveLength(0);
  });

  it('survives a reload through sessionStorage', () => {
    const s = usePlanEditStore.getState;
    s().push(createFeature(pt('b', 5, 5)));
    usePlanEditStore.setState({ scope: null, undo: [], working: new Map() });
    s().bind('test');
    s().setBase([pt('a', 0, 0, 3)]);
    expect(s().working.has('b')).toBe(true);
  });

  it('save clears the stack and makes the working set the new base', () => {
    const s = usePlanEditStore.getState;
    s().push(createFeature(pt('b', 5, 5)));
    s().markSaved('2026-11-20T14:02:00Z');
    expect(s().undo).toHaveLength(0);
    expect(s().ops()).toHaveLength(0);
    expect(s().base.has('b')).toBe(true);
  });
});

describe('net operations', () => {
  it('collapse create+update into one create and drop create+delete', () => {
    const b = pt('b', 1, 1);
    const b2 = moveVertex(b, 0, [2, 2]);
    const c = pt('c', 3, 3);
    const data = [createFeature(b), updateFeature(b, b2), createFeature(c), deleteFeatures([c])].map((x) => x.data);
    const ops = netOps(data);
    expect(ops).toHaveLength(1);
    expect(ops[0]).toMatchObject({ op: 'create', client_id: 'b', base_rev: null });
    expect((ops[0]!.after as { geometry: unknown }).geometry).toEqual(b2.geometry);
  });

  it('a delete of a server record carries its revision', () => {
    const ops = netOps([deleteFeatures([pt('a', 0, 0, 7)]).data]);
    expect(ops[0]).toMatchObject({ op: 'delete', entity_id: 'a', base_rev: 7, after: null });
  });
});

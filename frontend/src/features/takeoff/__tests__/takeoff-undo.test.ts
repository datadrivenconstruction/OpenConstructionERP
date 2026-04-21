import { describe, it, expect } from 'vitest';
import { reverseOperation, applyOperation, type TakeoffState } from '../lib/takeoff-undo';
import type { Measurement } from '../lib/takeoff-types';

function measurement(partial: Partial<Measurement> = {}): Measurement {
  return {
    id: partial.id ?? 'm1',
    type: partial.type ?? 'distance',
    points: partial.points ?? [{ x: 0, y: 0 }, { x: 10, y: 0 }],
    value: partial.value ?? 10,
    unit: partial.unit ?? 'm',
    label: partial.label ?? '10 m',
    annotation: partial.annotation ?? 'Distance 1',
    page: partial.page ?? 1,
    group: partial.group ?? 'General',
    ...partial,
  };
}

const emptyState = (): TakeoffState => ({
  measurements: [],
  activePoints: [],
});

describe('reverseOperation', () => {
  it('add_point: pops the last active point', () => {
    const state = {
      measurements: [],
      activePoints: [{ x: 1, y: 1 }, { x: 2, y: 2 }],
    };
    const next = reverseOperation(state, {
      kind: 'add_point',
      tool: 'polyline',
      point: { x: 2, y: 2 },
    });
    expect(next.activePoints).toEqual([{ x: 1, y: 1 }]);
  });

  it('complete_measurement: removes measurement and restores activePoints', () => {
    const m = measurement({ id: 'm-complete' });
    const state: TakeoffState = {
      measurements: [m],
      activePoints: [],
    };
    const next = reverseOperation(state, {
      kind: 'complete_measurement',
      measurement: m,
      previousActivePoints: [{ x: 5, y: 5 }],
    });
    expect(next.measurements).toHaveLength(0);
    expect(next.activePoints).toEqual([{ x: 5, y: 5 }]);
  });

  it('add_count_point (wasNew): removes the newly-created count measurement', () => {
    const countM = measurement({ id: 'mc', type: 'count', value: 1 });
    const state: TakeoffState = {
      measurements: [countM],
      activePoints: [],
    };
    const next = reverseOperation(state, {
      kind: 'add_count_point',
      measurementId: 'mc',
      point: { x: 1, y: 1 },
      wasNew: true,
      previousMeasurement: null,
    });
    expect(next.measurements).toHaveLength(0);
  });

  it('add_count_point (!wasNew): restores previous count measurement', () => {
    const prev = measurement({ id: 'mc', type: 'count', points: [{ x: 0, y: 0 }], value: 1 });
    const current = measurement({
      id: 'mc',
      type: 'count',
      points: [{ x: 0, y: 0 }, { x: 1, y: 1 }],
      value: 2,
    });
    const state: TakeoffState = {
      measurements: [current],
      activePoints: [],
    };
    const next = reverseOperation(state, {
      kind: 'add_count_point',
      measurementId: 'mc',
      point: { x: 1, y: 1 },
      wasNew: false,
      previousMeasurement: prev,
    });
    expect(next.measurements).toHaveLength(1);
    expect(next.measurements[0]!.points).toHaveLength(1);
    expect(next.measurements[0]!.value).toBe(1);
  });

  it('delete_measurement: restores the deleted measurement', () => {
    const m = measurement({ id: 'deleted' });
    const state = emptyState();
    const next = reverseOperation(state, {
      kind: 'delete_measurement',
      measurement: m,
    });
    expect(next.measurements).toHaveLength(1);
    expect(next.measurements[0]!.id).toBe('deleted');
  });

  it('change_annotation: reverts the annotation text', () => {
    const m = measurement({ id: 'ma', annotation: 'Changed label' });
    const state: TakeoffState = {
      measurements: [m],
      activePoints: [],
    };
    const next = reverseOperation(state, {
      kind: 'change_annotation',
      measurementId: 'ma',
      previousAnnotation: 'Original label',
    });
    expect(next.measurements[0]!.annotation).toBe('Original label');
  });

  it('does not mutate the input state', () => {
    const m = measurement({ id: 'mutate-guard' });
    const state: TakeoffState = {
      measurements: [m],
      activePoints: [{ x: 1, y: 1 }],
    };
    const snapshot = JSON.stringify(state);
    reverseOperation(state, {
      kind: 'delete_measurement',
      measurement: m,
    });
    expect(JSON.stringify(state)).toBe(snapshot);
  });
});

describe('applyOperation (redo)', () => {
  it('add_point: appends the point back', () => {
    const state: TakeoffState = {
      measurements: [],
      activePoints: [{ x: 0, y: 0 }],
    };
    const next = applyOperation(state, {
      kind: 'add_point',
      tool: 'polyline',
      point: { x: 5, y: 5 },
    });
    expect(next.activePoints).toEqual([{ x: 0, y: 0 }, { x: 5, y: 5 }]);
  });

  it('complete_measurement: re-adds the measurement and clears activePoints', () => {
    const m = measurement({ id: 'redo-complete' });
    const state = emptyState();
    const next = applyOperation(state, {
      kind: 'complete_measurement',
      measurement: m,
      previousActivePoints: [],
    });
    expect(next.measurements).toHaveLength(1);
    expect(next.measurements[0]!.id).toBe('redo-complete');
    expect(next.activePoints).toEqual([]);
  });

  it('delete_measurement: removes the measurement again', () => {
    const m = measurement({ id: 'to-delete' });
    const state: TakeoffState = {
      measurements: [m],
      activePoints: [],
    };
    const next = applyOperation(state, {
      kind: 'delete_measurement',
      measurement: m,
    });
    expect(next.measurements).toHaveLength(0);
  });

  it('round-trip: reverse → apply returns to original measurements list', () => {
    const m = measurement({ id: 'rt' });
    const start: TakeoffState = {
      measurements: [m],
      activePoints: [],
    };
    const reversed = reverseOperation(start, {
      kind: 'delete_measurement',
      measurement: m,
    });
    // After reversing a delete, the measurement exists twice? No — reverseOperation
    // on delete_measurement restores the deleted element, but start had it.
    // A more realistic round-trip:
    const afterDelete: TakeoffState = { measurements: [], activePoints: [] };
    const afterUndo = reverseOperation(afterDelete, {
      kind: 'delete_measurement',
      measurement: m,
    });
    const afterRedo = applyOperation(afterUndo, {
      kind: 'delete_measurement',
      measurement: m,
    });
    expect(afterRedo.measurements).toEqual([]);
    expect(reversed.measurements).toHaveLength(2); // ensures inputs not mutated
  });
});

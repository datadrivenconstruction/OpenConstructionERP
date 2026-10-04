// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The "bill differs from the drawing" proposal: a linked measurement changed
 * after its quantity went into the bill. Nothing is overwritten; the takeoff
 * shows both figures and a person confirms the update.
 */
import { describe, it, expect } from 'vitest';
import { linkedQuantityDrift } from '@/features/takeoff/lib/takeoff-linked-drift';
import type { Measurement } from '@/features/takeoff/lib/takeoff-types';

function mk(partial: Partial<Measurement>): Measurement {
  return {
    id: 'm1',
    type: 'distance',
    points: [],
    value: 12.5,
    unit: 'm',
    label: '',
    annotation: '',
    page: 1,
    group: 'Walls',
    linkedPositionId: 'p1',
    ...partial,
  };
}

// 12.5 m x 2.8 m, one door 0.9 x 2.1 and three windows 1.2 x 1.5 = 27.71 m2.
const WALL = {
  wallHeight: 2.8,
  openings: [
    { width: 0.9, height: 2.1, count: 1 },
    { width: 1.2, height: 1.5, count: 3 },
  ],
};

describe('linkedQuantityDrift', () => {
  it('proposes the net wall area when the bill still holds the old figure', () => {
    const m = mk(WALL);
    const drift = linkedQuantityDrift(m, [{ id: 'p1', quantity: '35.0000', unit: 'm2' }], [m]);
    expect(drift).not.toBeNull();
    expect(drift!.billQuantity).toBe(35);
    expect(drift!.measuredQuantity).toBeCloseTo(27.71, 4);
    expect(drift!.unit).toBe('m2');
  });

  it('is silent when the bill agrees to its 4 decimals', () => {
    const m = mk(WALL);
    expect(linkedQuantityDrift(m, [{ id: 'p1', quantity: 27.71, unit: 'm2' }], [m])).toBeNull();
    expect(linkedQuantityDrift(m, [{ id: 'p1', quantity: '27.71004', unit: 'm2' }], [m])).toBeNull();
  });

  it('restates the measured figure in the position unit', () => {
    const m = mk({ value: 10, wallHeight: 2.5 }); // 25 m2 = 269.0975 ft2
    const drift = linkedQuantityDrift(m, [{ id: 'p1', quantity: 200, unit: 'ft2' }], [m]);
    expect(drift!.measuredQuantity).toBeCloseTo(269.0975, 3);
    expect(drift!.unit).toBe('ft2');
    expect(linkedQuantityDrift(m, [{ id: 'p1', quantity: 269.0975, unit: 'ft2' }], [m])).toBeNull();
  });

  it('proposes nothing it cannot state: other dimension, missing position, bad quantity', () => {
    const m = mk(WALL);
    expect(linkedQuantityDrift(m, [{ id: 'p1', quantity: 3, unit: 'pcs' }], [m])).toBeNull();
    expect(linkedQuantityDrift(m, [{ id: 'p2', quantity: 3, unit: 'm2' }], [m])).toBeNull();
    expect(linkedQuantityDrift(m, [{ id: 'p1', quantity: 'n/a', unit: 'm2' }], [m])).toBeNull();
  });

  it('stays out of a position fed by several measurements', () => {
    const a = mk({ id: 'a', ...WALL });
    const b = mk({ id: 'b', value: 4 });
    expect(linkedQuantityDrift(a, [{ id: 'p1', quantity: 1, unit: 'm2' }], [a, b])).toBeNull();
  });

  it('stays out of a position last written by a measurement on another drawing', () => {
    const m = mk({ ...WALL, serverId: 'srv-1' });
    const other = { id: 'p1', quantity: 35, unit: 'm2', metadata: { pdf_measurement_id: 'srv-9' } };
    expect(linkedQuantityDrift(m, [other], [m])).toBeNull();
    const own = { id: 'p1', quantity: 35, unit: 'm2', metadata: { pdf_measurement_id: 'srv-1' } };
    expect(linkedQuantityDrift(m, [own], [m])).not.toBeNull();
    const ownLocal = { id: 'p1', quantity: 35, unit: 'm2', metadata: { pdf_measurement_id: 'm1' } };
    expect(linkedQuantityDrift(m, [ownLocal], [m])).not.toBeNull();
  });

  it('ignores unlinked rows, deductions and unaccepted suggestions', () => {
    const pos = [{ id: 'p1', quantity: 1, unit: 'm' }];
    for (const m of [mk({ linkedPositionId: undefined }), mk({ isDeduction: true }), mk({ suggested: true })]) {
      expect(linkedQuantityDrift(m, pos, [m])).toBeNull();
    }
  });

  it('a plain run with no factor compares its drawn length', () => {
    const m = mk({ value: 14.2 });
    const drift = linkedQuantityDrift(m, [{ id: 'p1', quantity: 12.5, unit: 'm' }], [m]);
    expect(drift!.measuredQuantity).toBeCloseTo(14.2, 4);
    expect(drift!.unit).toBe('m');
  });
});

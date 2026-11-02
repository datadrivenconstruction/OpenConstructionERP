import { describe, it, expect } from 'vitest';
import { planBatchDelete, withoutSections, type BatchRow } from './batchSelection';

const rows: BatchRow[] = [
  { id: 's1', unit: '', ordinal: '01', description: 'Earthworks' },
  { id: 'p1', parent_id: 's1', unit: 'm3' },
  { id: 's1a', parent_id: 's1', unit: '', ordinal: '01.01', description: 'Excavation' },
  { id: 'p2', parent_id: 's1a', unit: 'm3' },
  { id: 'p3', parent_id: 's1a', unit: 'm3' },
  { id: 's2', unit: 'section', ordinal: '02', description: 'Concrete' },
  { id: 'p4', parent_id: 's2', unit: 'm3' },
  { id: 'p5', unit: 'pcs' },
];

describe('planBatchDelete', () => {
  it('cascades a selected section over its whole subtree, counting positions only', () => {
    const plan = planBatchDelete(rows, ['s1']);
    expect(plan.sections).toEqual([{ id: 's1', ordinal: '01', description: 'Earthworks', positionCount: 3 }]);
    expect(plan.positionIds).toEqual([]);
    expect(plan.containedPositions).toBe(3);
  });

  it('does not delete twice a row already inside a selected section', () => {
    const plan = planBatchDelete(rows, ['s1', 'p2', 's1a', 'p5']);
    expect(plan.sections.map((s) => s.id)).toEqual(['s1']);
    expect(plan.positionIds).toEqual(['p5']);
  });

  it('keeps loose positions as single deletes', () => {
    const plan = planBatchDelete(rows, ['p4', 'p5']);
    expect(plan.sections).toEqual([]);
    expect(plan.positionIds).toEqual(['p4', 'p5']);
    expect(plan.containedPositions).toBe(0);
  });

  it('sums contained positions across several sections', () => {
    expect(planBatchDelete(rows, ['s1', 's2']).containedPositions).toBe(4);
  });
});

describe('withoutSections', () => {
  it('drops section rows and unknown ids', () => {
    expect(withoutSections(rows, ['s1', 'p1', 's2', 'p5', 'zz'])).toEqual(['p1', 'p5']);
  });
});

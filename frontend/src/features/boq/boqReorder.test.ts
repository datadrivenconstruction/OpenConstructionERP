import { describe, expect, it } from 'vitest';
import { orderAfterLineMove, orderAfterSectionMove, siblingDropTarget } from './boqReorder';

const sec = (id: string, parent: string | null, so: number) => ({
  id, parent_id: parent, sort_order: so, ordinal: id, unit: '',
});
const line = (id: string, parent: string | null, so: number) => ({
  id, parent_id: parent, sort_order: so, ordinal: id, unit: 'm2',
});

// A (a1, A1(x)), B (b1), C
const bill = [
  sec('A', null, 0), line('a1', 'A', 1), sec('A1', 'A', 2), line('x', 'A1', 3),
  sec('B', null, 4), line('b1', 'B', 5), sec('C', null, 6),
];

describe('moving a section', () => {
  it('moves it past a sibling and takes its sub-sections and lines along', () => {
    expect(orderAfterSectionMove(bill, 'A', 'B')).toEqual(['B', 'b1', 'A', 'a1', 'A1', 'x', 'C']);
    expect(orderAfterSectionMove(bill, 'C', 'A')).toEqual(['C', 'A', 'a1', 'A1', 'x', 'B', 'b1']);
  });
  it('resolves a drop on a line or a sub-section to the sibling section that holds it', () => {
    expect(siblingDropTarget(bill, 'B', 'x')).toBe('A');
    expect(siblingDropTarget(bill, 'C', 'b1')).toBe('B');
    expect(siblingDropTarget(bill, 'A1', 'A1')).toBeNull();
    expect(siblingDropTarget(bill, 'A1', 'b1')).toBeNull();
  });
  it('a drop that changes nothing sends nothing', () => {
    expect(orderAfterSectionMove(bill, 'B', 'B')).toBeNull();
  });
});

describe('moving a line', () => {
  it('sends every position and keeps sections where they were', () => {
    const out = orderAfterLineMove(bill, ['b1', 'x', 'a1']);
    expect(out).toHaveLength(bill.length);
    expect(out).toEqual(['A', 'b1', 'A1', 'x', 'B', 'a1', 'C']);
  });
});

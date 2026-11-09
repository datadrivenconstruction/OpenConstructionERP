import { describe, it, expect } from 'vitest';
import { siblingMoves } from './activityMove';

const row = (id: string, parent: string | null, order: number) =>
  ({ id, parent_id: parent, wbs_code: id, sort_order: order, activity_type: 'task' }) as never;

describe('siblingMoves', () => {
  const rows = [row('s', null, 0), row('a', 's', 1), row('b', 's', 2), row('c', 's', 3), row('t', null, 4)];

  it('offers up and down among the siblings of the same section', () => {
    expect(siblingMoves('b', rows)).toEqual({
      up: { target_id: 'a', position: 'before' },
      down: { target_id: 'c', position: 'after' },
    });
  });

  it('has no up for the first sibling and no down for the last', () => {
    expect(siblingMoves('a', rows).up).toBeNull();
    expect(siblingMoves('c', rows).down).toBeNull();
  });

  it('treats top-level rows as siblings of each other', () => {
    expect(siblingMoves('t', rows).up).toEqual({ target_id: 's', position: 'before' });
  });
});

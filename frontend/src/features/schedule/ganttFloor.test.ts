import { describe, it, expect } from 'vitest';
import { startFloorPatch } from './ganttFloor';

const act = (over: Record<string, unknown> = {}) =>
  ({ start_date: '2026-05-10', constraint_type: null, constraint_date: null, ...over }) as never;

describe('startFloorPatch', () => {
  it('sets a floor when the bar starts later', () => {
    expect(startFloorPatch(act(), '2026-05-20')).toEqual({
      constraint_type: 'start_no_earlier',
      constraint_date: '2026-05-20',
    });
  });

  it('writes nothing when the start did not change or the bar moved earlier without a floor', () => {
    expect(startFloorPatch(act(), '2026-05-10')).toBeNull();
    expect(startFloorPatch(act(), '2026-05-02')).toBeNull();
  });

  it('lets an existing floor follow the bar earlier', () => {
    const a = act({ constraint_type: 'start_no_earlier', constraint_date: '2026-05-10' });
    expect(startFloorPatch(a, '2026-05-04')?.constraint_date).toBe('2026-05-04');
  });

  it('never overwrites a constraint the planner chose on purpose', () => {
    const a = act({ constraint_type: 'must_start_on', constraint_date: '2026-05-10' });
    expect(startFloorPatch(a, '2026-05-20')).toBeNull();
  });
});

import { describe, it, expect } from 'vitest';

import { buildApplyPatch } from '../ResourceLevelingPage';
import type { LevelingSuggestion } from '../api';

/**
 * The leveling "Apply" control (CONN-35) only mutates a real assignment for the
 * deterministic "spread" action: reduce allocation_percent to the suggested
 * value. The "shift" action has no computed target period, so it must NEVER
 * resolve to a PATCH body (that would fabricate data) - buildApplyPatch returns
 * null and the UI routes the planner to the booking instead.
 */

function suggestion(overrides: Partial<LevelingSuggestion>): LevelingSuggestion {
  return {
    action: 'spread',
    bucket_index: 0,
    target_assignment_id: 'a1',
    target_project_id: 'p1',
    target_project_name: 'Tower A',
    overflow_percent: 30,
    suggested_allocation_percent: 70,
    rationale: 'reduce to fit capacity',
    ...overrides,
  };
}

describe('buildApplyPatch (leveling apply)', () => {
  it('maps a spread suggestion to an allocation_percent patch', () => {
    expect(buildApplyPatch(suggestion({ suggested_allocation_percent: 70 }))).toEqual({
      allocation_percent: 70,
    });
  });

  it('never produces a patch for a shift suggestion', () => {
    expect(buildApplyPatch(suggestion({ action: 'shift', suggested_allocation_percent: 0 }))).toBeNull();
  });

  it('rejects out-of-range allocations rather than sending bad data', () => {
    expect(buildApplyPatch(suggestion({ suggested_allocation_percent: 120 }))).toBeNull();
    expect(buildApplyPatch(suggestion({ suggested_allocation_percent: -5 }))).toBeNull();
  });

  it('allows a zero-allocation spread (booking fully relieved)', () => {
    expect(buildApplyPatch(suggestion({ suggested_allocation_percent: 0 }))).toEqual({
      allocation_percent: 0,
    });
  });
});

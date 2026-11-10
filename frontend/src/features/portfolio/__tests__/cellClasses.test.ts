// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';

import { cellClasses } from '../ResourceLevelingPage';
import type { LevelingCell } from '../api';

/**
 * The leveling heatmap is capacity-aware. These tests lock the critical
 * platform rule: a "capacity unknown" cell must NEVER render in the
 * over-allocation (rose/red) colour — we never fabricate a ceiling — and an
 * over-capacity cell must.
 */

function cell(overrides: Partial<LevelingCell>): LevelingCell {
  return {
    bucket_index: 0,
    allocation_percent: 0,
    capacity_percent: null,
    over_allocated: false,
    capacity_unknown: false,
    cross_project: false,
    bookings: [],
    ...overrides,
  };
}

describe('cellClasses (leveling heatmap)', () => {
  it('renders empty / no-booking cells as neutral', () => {
    expect(cellClasses(undefined)).toContain('bg-surface-secondary');
    expect(cellClasses(cell({ allocation_percent: 0 }))).toContain('bg-surface-secondary');
  });

  it('renders capacity-unknown cells slate, never rose', () => {
    const c = cellClasses(cell({ allocation_percent: 250, capacity_unknown: true }));
    expect(c).toContain('bg-slate-300');
    expect(c).not.toContain('semantic-error');
  });

  it('renders over-allocated cells rose', () => {
    const c = cellClasses(
      cell({ allocation_percent: 130, capacity_percent: 100, over_allocated: true }),
    );
    expect(c).toContain('bg-semantic-error');
  });

  it('scales colour by ratio to capacity (not a hardcoded 100)', () => {
    // Capacity 200, allocation 120 = 60% of capacity -> mid (emerald-500), not high.
    const mid = cellClasses(cell({ allocation_percent: 120, capacity_percent: 200 }));
    expect(mid).toContain('bg-semantic-success');
    // Capacity 100, allocation 90 = 90% -> high (amber).
    const high = cellClasses(cell({ allocation_percent: 90, capacity_percent: 100 }));
    expect(high).toContain('bg-amber-400');
    // Capacity 100, allocation 40 = 40% -> low (emerald-300).
    const low = cellClasses(cell({ allocation_percent: 40, capacity_percent: 100 }));
    expect(low).toContain('bg-emerald-300');
  });
});

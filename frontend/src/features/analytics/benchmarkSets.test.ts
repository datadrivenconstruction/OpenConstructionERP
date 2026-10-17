// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';

import {
  EMPTY_COHORT,
  activeFilterCount,
  classificationFilter,
  classificationRowFilters,
  pickKpi,
} from './performance';
import { convertBetween } from '@/shared/lib/unitConversion';

describe('benchmark set helpers', () => {
  it('writes a classification filter only when both key and code are given', () => {
    expect(classificationRowFilters('din276', ' 330 ')).toEqual([
      { field: 'classification.din276', op: 'eq', value: '330' },
    ]);
    expect(classificationRowFilters('din276', '')).toEqual([]);
    expect(classificationRowFilters(' ', '330')).toEqual([]);
  });

  it('reads back the classification filter it wrote, and ignores other shapes', () => {
    const cohort = {
      ...EMPTY_COHORT,
      row_filters: [
        { field: 'installed_quantity', op: 'gt', value: 0 },
        { field: 'classification.masterformat', op: 'eq', value: '09 21 16' },
      ],
    };
    expect(classificationFilter(cohort)).toEqual({ key: 'masterformat', code: '09 21 16' });
    expect(classificationFilter(EMPTY_COHORT)).toEqual({ key: '', code: '' });
  });

  it('counts each kind of active filter once', () => {
    expect(activeFilterCount(EMPTY_COHORT)).toBe(0);
    expect(
      activeFilterCount({
        ...EMPTY_COHORT,
        clients: ['A', 'B'],
        regions: ['EU'],
        period_end: '2026-12-31',
        project_ids: ['x'],
      }),
    ).toBe(3);
  });

  it('keeps the KPI when the set offers it and falls back to its first otherwise', () => {
    expect(pickKpi('b', ['a', 'b'])).toBe('b');
    expect(pickKpi('c', ['a', 'b'])).toBe('a');
    expect(pickKpi('c', [])).toBe('c');
  });
});

describe('time units in the shared conversion table', () => {
  it('converts hours to minutes and keeps days out', () => {
    expect(convertBetween(2, 'h', 'min')).toBe(120);
    expect(convertBetween(3, 'hr', 'hours')).toBe(3);
    expect(convertBetween(1, 'day', 'h')).toBeNull();
  });
});

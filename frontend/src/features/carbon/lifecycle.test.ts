// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Unit tests for the pure life-cycle helpers.
import { describe, expect, it } from 'vitest';

import { budgetTone, failingChecks, kgToTonnes, qualityTone } from './lifecycle';
import type { CarbonChecks } from './lifecycleApi';

const budget = (used: number, over: boolean, b = '1000') => ({ budget_kg: b, used_pct: used, over_budget: over });

describe('budgetTone', () => {
  it('is neutral without a budget', () => {
    expect(budgetTone(undefined)).toBe('neutral');
    expect(budgetTone(budget(0, false, '0'))).toBe('neutral');
  });
  it('turns amber near and red over the budget', () => {
    expect(budgetTone(budget(50, false))).toBe('success');
    expect(budgetTone(budget(95, false))).toBe('warning');
    expect(budgetTone(budget(120, true))).toBe('error');
  });
});

describe('qualityTone and kgToTonnes', () => {
  it('maps data quality', () => {
    expect(qualityTone('measured')).toBe('success');
    expect(qualityTone('estimated')).toBe('warning');
  });
  it('formats tonnes', () => {
    expect(kgToTonnes('12500', 'en')).toBe('12.5');
    expect(kgToTonnes('abc', 'en')).toBe('0');
  });
});

describe('failingChecks', () => {
  it('lists only checks with hits, budget last', () => {
    const c: CarbonChecks = {
      inventory_id: 'i',
      no_factor: ['a', 'b'],
      outdated_factor_set: [],
      expired_epd: ['c'],
      unit_mismatch: [],
      budget: {
        actual_kg: '2',
        budget_kg: '1',
        remaining_kg: '-1',
        used_pct: 200,
        over_budget: true,
        target_id: null,
        inventory_id: null,
      },
    };
    expect(failingChecks(c)).toEqual([
      { key: 'no_factor', count: 2 },
      { key: 'expired_epd', count: 1 },
      { key: 'over_budget', count: 1 },
    ]);
    expect(failingChecks(undefined)).toEqual([]);
  });
});

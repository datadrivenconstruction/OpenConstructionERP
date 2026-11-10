// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';

import {
  formatControlsValue,
  kpiByCurrency,
  kpiCurrency,
  kpiMultiCurrency,
  statusClasses,
} from '../format';

describe('formatControlsValue', () => {
  it('formats currency with the ISO code', () => {
    expect(formatControlsValue('1500000', 'currency', 'EUR')).toBe('EUR 1.50M');
    expect(formatControlsValue('2500', 'currency', 'USD')).toBe('USD 2.5k');
  });

  it('formats percent, days, ratio and count', () => {
    expect(formatControlsValue('95.5', 'percent')).toBe('95.50%');
    expect(formatControlsValue('14', 'days')).toBe('14d');
    expect(formatControlsValue('0.97', 'ratio')).toBe('0.97');
    expect(formatControlsValue('3', 'count')).toBe('3');
  });

  it('renders a dash for non-finite values', () => {
    expect(formatControlsValue('not-a-number', 'count')).toBe('—');
  });

  it('omits the code when currency is unknown', () => {
    expect(formatControlsValue('500', 'currency', '')).toBe('500');
  });
});

describe('currency grouping helpers', () => {
  const breakdown = {
    currency: 'EUR',
    multi_currency: true,
    by_currency: { EUR: '1000', USD: '2000' },
  };

  it('reads the dominant currency code', () => {
    expect(kpiCurrency(breakdown)).toBe('EUR');
    expect(kpiCurrency(undefined)).toBeNull();
  });

  it('parses and sorts the per-currency split', () => {
    const groups = kpiByCurrency(breakdown);
    expect(groups).toEqual([
      { currency: 'EUR', amount: 1000 },
      { currency: 'USD', amount: 2000 },
    ]);
  });

  it('detects the multi-currency flag', () => {
    expect(kpiMultiCurrency(breakdown)).toBe(true);
    expect(kpiMultiCurrency({ currency: 'EUR' })).toBe(false);
  });
});

describe('statusClasses', () => {
  it('maps each status to a traffic-light dot colour', () => {
    expect(statusClasses('red').dot).toContain('semantic-error');
    expect(statusClasses('amber').dot).toContain('semantic-warning');
    expect(statusClasses('green').dot).toContain('semantic-success');
  });
});

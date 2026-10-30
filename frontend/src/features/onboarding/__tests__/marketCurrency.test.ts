// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { marketCurrencyFor } from '../marketCurrency';

describe('the account currency of a market', () => {
  it('is the country’s own even on a neighbour’s cost base', () => {
    expect(marketCurrencyFor('sa', 'AED')).toBe('SAR');
    expect(marketCurrencyFor('ae', 'AED')).toBe('AED');
  });

  it('falls back to the base only for an unknown country', () => {
    expect(marketCurrencyFor('is', 'EUR')).toBe('EUR');
    expect(marketCurrencyFor(null, null)).toBeNull();
  });
});

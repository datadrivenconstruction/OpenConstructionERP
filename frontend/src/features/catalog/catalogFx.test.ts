import { describe, expect, it } from 'vitest';
import { convertedPrice, pickRegionForProject, type CatalogFxView } from './catalogFx';

const view: CatalogFxView = {
  project_currency: 'USD',
  rates: {
    EUR: { currency: 'EUR', rate: '1.25', source: 'oe_fx', as_of: '2026-10-30', reason: '' },
    XTS: { currency: 'XTS', rate: null, source: '', as_of: '', reason: 'no_rate' },
  },
};

describe('convertedPrice', () => {
  it('prices a EUR rate into the USD project with the rate date', () => {
    const r = convertedPrice(80, 'EUR', view);
    expect(r).toEqual({ kind: 'converted', amount: 100, currency: 'USD', asOf: '2026-10-30', source: 'oe_fx' });
  });

  it('shows nothing extra for a rate already in the project currency', () => {
    expect(convertedPrice(80, 'USD', view).kind).toBe('same');
  });

  it('marks a foreign rate without a quote instead of relabelling it', () => {
    expect(convertedPrice(80, 'XTS', view)).toEqual({ kind: 'unpriced', currency: 'USD' });
    expect(convertedPrice(80, 'GBP', view)).toEqual({ kind: 'unpriced', currency: 'USD' });
  });

  it('does nothing outside a project', () => {
    expect(convertedPrice(80, 'EUR', null).kind).toBe('same');
  });
});

describe('pickRegionForProject', () => {
  const loaded = ['DE_BERLIN', 'FR_PARIS', 'USA_USD'];

  it('opens a USD project on the US catalogue even when EUR regions are larger', () => {
    expect(pickRegionForProject(loaded, 'USD')).toBe('USA_USD');
  });

  it('falls back to the first loaded region without a match or a project', () => {
    expect(pickRegionForProject(loaded, 'JPY')).toBe('DE_BERLIN');
    expect(pickRegionForProject(loaded, undefined)).toBe('DE_BERLIN');
    expect(pickRegionForProject([], 'USD')).toBe('');
  });
});

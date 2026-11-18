import { describe, expect, it } from 'vitest';
import { parsePrice, pricedSum } from './BuyerPricesDialog';
import { excludedFromPreview, isBudgetInput, scopeKindLabel } from './PackageContentsPanel';
import type { PackagePreview } from './api';

describe('buyer prices', () => {
  it('normalises a typed unit price', () => {
    expect(parsePrice(' 1 250,50 ')).toBe('1250.50');
    expect(parsePrice('300')).toBe('300');
    expect(parsePrice('')).toBeNull();
    expect(parsePrice('-5')).toBeNull();
    expect(parsePrice('abc')).toBeNull();
  });

  it('sums price times quantity over the priced lines only', () => {
    // Wall 10 m3 at 300 plus a blank line: 3000.
    expect(pricedSum({ a: '300', b: '' , c: 'x' }, { a: '10', b: '4', c: '2' })).toBe(3000);
  });
});

describe('package contents', () => {
  it('accepts only non-negative decimal budgets', () => {
    expect(isBudgetInput('2100')).toBe(true);
    expect(isBudgetInput('2100,5')).toBe(true);
    expect(isBudgetInput('')).toBe(false);
    expect(isBudgetInput('-1')).toBe(false);
  });

  it('collects excluded components only for kinds still in scope', () => {
    const preview = {
      scope_kinds: ['labor', 'material'],
      lines: [
        {
          id: 'p1',
          components: [
            { key: 'k-rebar', kind: 'material', included: false },
            { key: 'k-crane', kind: 'machinery', included: false },
            { key: 'k-crew', kind: 'labor', included: true },
          ],
        },
        { id: 'p2', components: [] },
      ],
    } as unknown as PackagePreview;
    expect(excludedFromPreview(preview)).toEqual({ p1: ['k-rebar'] });
  });

  it('labels the resource kinds', () => {
    const t = ((_k: string, o: { defaultValue: string }) => o.defaultValue) as never;
    expect(scopeKindLabel('labor', t)).toBe('Labour');
    expect(scopeKindLabel('subcontractor', t)).toBe('Subcontract');
  });
});

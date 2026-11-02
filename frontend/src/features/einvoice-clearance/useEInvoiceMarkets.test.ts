import { describe, it, expect } from 'vitest';
import { einvoiceScopeMarkets } from './useEInvoiceMarkets';
import type { MarketScope } from '@/features/market/api';

// Shape of the real /market scope answer: module names carry no `oe_` prefix.
const scope = (over: Partial<MarketScope>): MarketScope =>
  ({
    markets: ['DE'],
    expanded_markets: ['DE', 'EU'],
    all_markets: false,
    hidden_modules: [],
    module_markets: { einvoice_clearance: ['DE', 'SA', 'MY'] },
    ...over,
  }) as MarketScope;

describe('einvoiceScopeMarkets', () => {
  it('returns nothing while the scope is loading', () => {
    expect(einvoiceScopeMarkets(undefined)).toEqual([]);
  });
  it('returns the mandate markets the tenant profile covers, from the unprefixed module key', () => {
    expect(einvoiceScopeMarkets(scope({}))).toEqual(['DE']);
  });
  it('matches markets case-insensitively', () => {
    expect(einvoiceScopeMarkets(scope({ expanded_markets: ['sa'] }))).toEqual(['SA']);
  });
  it('is empty for a non-mandate market such as the US', () => {
    expect(einvoiceScopeMarkets(scope({ markets: ['US'], expanded_markets: ['US'] }))).toEqual([]);
  });
  it('is empty when the module is hidden for the profile', () => {
    expect(einvoiceScopeMarkets(scope({ hidden_modules: ['einvoice_clearance'] }))).toEqual([]);
  });
  it('lists every mandate market for an all-markets profile', () => {
    expect(einvoiceScopeMarkets(scope({ all_markets: true, expanded_markets: [] }))).toEqual(['DE', 'SA', 'MY']);
  });
  it('is empty when the manifest lists no markets', () => {
    expect(einvoiceScopeMarkets(scope({ module_markets: {} }))).toEqual([]);
  });
});

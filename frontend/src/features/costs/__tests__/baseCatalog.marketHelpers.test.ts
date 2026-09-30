// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The helpers every cost base screen shares for a national market card: who is
// offered it, what the answer says about the language that landed, and when
// the active market is recorded.

import { describe, it, expect, vi, beforeEach } from 'vitest';

const apiPost = vi.fn();
vi.mock('@/shared/lib/api', () => ({ apiGet: vi.fn(), apiPost: (...a: unknown[]) => apiPost(...a) }));

import {
  canPriceMarkets,
  getActiveMarkets,
  loadBaseMarket,
  textLanguageFallback,
  type BaseVariant,
} from '../baseCatalog';

const PARIS = {
  region: 'TR_NATIONAL',
  variant_id: 'TR_NATIONAL:FR_PARIS_fr',
  base_region: 'TR_NATIONAL',
  market_catalog: 'FR_PARIS_fr',
  lang_code: 'fr',
} as BaseVariant;

describe('canPriceMarkets', () => {
  it('offers the market action from editor up, never to a viewer or no role', () => {
    expect(canPriceMarkets('editor')).toBe(true);
    expect(canPriceMarkets('estimator')).toBe(true);
    expect(canPriceMarkets('admin')).toBe(true);
    expect(canPriceMarkets('viewer')).toBe(false);
    expect(canPriceMarkets(null)).toBe(false);
    expect(canPriceMarkets('nonsense')).toBe(false);
  });
});

describe('textLanguageFallback', () => {
  it('names the language only when it differs from the one asked for', () => {
    expect(textLanguageFallback({ text_language: 'tr', text_language_requested: 'en' })).toBe('tr');
    expect(textLanguageFallback({ text_language: 'fr', text_language_requested: 'fr' })).toBeNull();
    expect(textLanguageFallback({ text_language: null, text_language_requested: 'fr' })).toBeNull();
    expect(textLanguageFallback({})).toBeNull();
  });
});

describe('loadBaseMarket', () => {
  beforeEach(() => {
    apiPost.mockReset();
    localStorage.clear();
  });

  it('posts the market load for the card, never the plain base load', async () => {
    apiPost.mockResolvedValue({ text_language: 'fr', text_language_requested: 'fr' });
    await loadBaseMarket(PARIS);
    expect(apiPost).toHaveBeenCalledTimes(1);
    expect(apiPost.mock.calls[0]?.[0]).toBe('/v1/costs/base-market/TR_NATIONAL/FR_PARIS_fr');
    expect(getActiveMarkets()).toEqual({ TR_NATIONAL: 'FR_PARIS_fr' });
  });

  it('records the active market only after the server accepted it', async () => {
    apiPost.mockRejectedValue(new Error("The 'fr' text of 'TR_NATIONAL' could not be loaded"));
    await expect(loadBaseMarket(PARIS)).rejects.toThrow(/could not be loaded/);
    expect(getActiveMarkets()).toEqual({});
  });
});

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
  canReturnHome,
  effectiveActiveMarkets,
  getActiveMarkets,
  loadBaseMarket,
  restoreBaseHome,
  setActiveMarketFor,
  textLanguageFallback,
  type BaseCatalog,
  type BaseStateInfo,
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

describe('effectiveActiveMarkets', () => {
  const catalog = (base_states: Record<string, BaseStateInfo>) => ({ base_states }) as unknown as BaseCatalog;
  const state = (over: Partial<BaseStateInfo>): BaseStateInfo => ({
    market_state: 'home',
    active_market: null,
    switching_to: null,
    text_language: null,
    updated_at: null,
    ...over,
  });

  it('takes the server market over what this browser cached', () => {
    // Another browser switched Turkiye to London; this one still remembers Paris.
    const out = effectiveActiveMarkets(
      catalog({ TR_NATIONAL: state({ market_state: 'market', active_market: 'GB_LONDON_en' }) }),
      { TR_NATIONAL: 'FR_PARIS_fr' },
    );
    expect(out).toEqual({ TR_NATIONAL: 'GB_LONDON_en' });
  });

  it('marks no market for a base the server has at home or mid-switch', () => {
    const out = effectiveActiveMarkets(
      catalog({
        TR_NATIONAL: state({ market_state: 'home' }),
        ZH_CHINA: state({ market_state: 'switching', active_market: 'DE_BERLIN_de', switching_to: 'FR_PARIS_fr' }),
      }),
      { TR_NATIONAL: 'FR_PARIS_fr', ZH_CHINA: 'DE_BERLIN_de' },
    );
    expect(out).toEqual({ TR_NATIONAL: '', ZH_CHINA: '' });
  });

  it('falls back to the cache only where the server knows nothing', () => {
    const out = effectiveActiveMarkets(catalog({ TR_NATIONAL: state({ market_state: 'unknown' }) }), {
      TR_NATIONAL: 'FR_PARIS_fr',
      BR_NATIONAL: 'PT_LISBON_pt',
    });
    expect(out).toEqual({ TR_NATIONAL: 'FR_PARIS_fr', BR_NATIONAL: 'PT_LISBON_pt' });
    expect(effectiveActiveMarkets(undefined, { TR_NATIONAL: 'FR_PARIS_fr' })).toEqual({ TR_NATIONAL: 'FR_PARIS_fr' });
  });

  it('offers the way home only for a base that is not at home', () => {
    const cat = catalog({
      TR_NATIONAL: state({ market_state: 'market', active_market: 'GB_LONDON_en' }),
      ZH_CHINA: state({ market_state: 'home' }),
      BR_NATIONAL: state({ market_state: 'switching', switching_to: 'FR_PARIS_fr' }),
      GR_NATIONAL: state({ market_state: 'unknown' }),
    });
    expect(canReturnHome('TR_NATIONAL', cat, {})).toBe(true);
    expect(canReturnHome('BR_NATIONAL', cat, {})).toBe(true);
    // The server says home: a stale cache must not bring the button back.
    expect(canReturnHome('ZH_CHINA', cat, { ZH_CHINA: 'FR_PARIS_fr' })).toBe(false);
    expect(canReturnHome('GR_NATIONAL', cat, {})).toBe(false);
    expect(canReturnHome('GR_NATIONAL', cat, { GR_NATIONAL: 'FR_PARIS_fr' })).toBe(true);
  });
});

describe('restoreBaseHome', () => {
  beforeEach(() => {
    apiPost.mockReset();
    localStorage.clear();
  });

  it('posts the return home and forgets the cached market once it landed', async () => {
    setActiveMarketFor('TR_NATIONAL', 'FR_PARIS_fr');
    setActiveMarketFor('ZH_CHINA', 'GB_LONDON_en');
    apiPost.mockResolvedValue({ items_restored: 3, currency: 'TRY' });
    const out = await restoreBaseHome('TR_NATIONAL');
    expect(apiPost.mock.calls[0]?.[0]).toBe('/v1/costs/base-home/TR_NATIONAL');
    expect(out.items_restored).toBe(3);
    expect(getActiveMarkets()).toEqual({ ZH_CHINA: 'GB_LONDON_en' });
  });

  it('keeps the cached market when the server refused', async () => {
    setActiveMarketFor('TR_NATIONAL', 'FR_PARIS_fr');
    apiPost.mockRejectedValue(new Error('busy'));
    await expect(restoreBaseHome('TR_NATIONAL')).rejects.toThrow('busy');
    expect(getActiveMarkets()).toEqual({ TR_NATIONAL: 'FR_PARIS_fr' });
  });
});

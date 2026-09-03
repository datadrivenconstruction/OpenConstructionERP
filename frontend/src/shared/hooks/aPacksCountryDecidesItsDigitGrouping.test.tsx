// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Which market's grouping the workspace uses, and where that answer comes from.
 *
 * `anIndianMarketGroupsAmountsByLakh` proves the resolver honours a market once
 * one is set. It cannot prove anything sets one, and a fix that never fires in
 * the running app would pass it completely. This is the other half: that the
 * pack actually reaches `setMarketNumberLocale`.
 *
 * The assertion that carries the mechanism is the `default_locale: 'en'` in the
 * fixture below, which is what the shipped india-cpwd manifest really says. The
 * language effect in this hook returns early on English, so if the grouping
 * were keyed off the pack's LOCALE it would never be set for the one market
 * that needs it. It is keyed off the pack's COUNTRY instead, and this file
 * fails if that is ever swapped back.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';

// The vocabulary overlay is a separate concern with its own tests and its own
// network calls; stubbing it keeps this file about the market tag alone.
vi.mock('./partnerPackVocabulary', () => ({
  syncPackVocabulary: vi.fn(async () => {}),
  revertPackVocabulary: vi.fn(),
}));
vi.mock('./usePartnerPack', () => ({ usePartnerPack: vi.fn() }));

import { getMarketNumberLocale, setMarketNumberLocale } from '@/shared/lib/marketNumberLocale';

import { usePartnerPack } from './usePartnerPack';
import type { PartnerPackManifest, PartnerPackResponse } from './usePartnerPack';
import { resetPackLocale, usePartnerPackLocale } from './usePartnerPackLocale';

const mockedUsePartnerPack = vi.mocked(usePartnerPack);

function manifest(overrides: Partial<PartnerPackManifest> = {}): PartnerPackManifest {
  return {
    slug: 'india-cpwd',
    partner_name: 'India Construction Pack',
    partner_url: null,
    pack_version: '0.2.0',
    description: '',
    // What the shipped manifest carries. English UI, Indian figures.
    default_locale: 'en',
    additional_locales: ['hi'],
    cwicr_regions: [],
    default_currency: 'INR',
    default_tax_template: null,
    validation_rule_packs: [],
    validation_rule_sets: [],
    default_modules: [],
    hidden_modules: [],
    branding: {
      primary_color: '#FF9933',
      accent_color: '#138808',
      has_logo: true,
      has_favicon: false,
      powered_by_text: '',
    },
    has_onboarding_script: true,
    metadata: { country: 'IN' },
    ...overrides,
  };
}

function mountWith(response: PartnerPackResponse) {
  mockedUsePartnerPack.mockReturnValue({ data: response } as ReturnType<typeof usePartnerPack>);
  return renderHook(() => usePartnerPackLocale());
}

describe("a pack's country decides its digit grouping", () => {
  beforeEach(() => {
    setMarketNumberLocale(null);
    mockedUsePartnerPack.mockReset();
  });
  afterEach(() => {
    setMarketNumberLocale(null);
  });

  it('puts an English-speaking Indian pack on the Indian grouping', () => {
    mountWith({ active: true, manifest: manifest() });
    expect(getMarketNumberLocale()).toBe('en-IN');
  });

  it('sets no market when no pack is applied', () => {
    mountWith({ active: false });
    expect(getMarketNumberLocale()).toBeNull();
  });

  it('sets no market for a country the reader already reads correctly', () => {
    // A German pack has nothing to add: the UI language already resolves to
    // `de-DE`, and claiming the market here would put a second opinion on top
    // of separators that were never wrong.
    mountWith({
      active: true,
      manifest: manifest({ slug: 'dach', default_locale: 'de', metadata: { country: 'DE' } }),
    });
    expect(getMarketNumberLocale()).toBeNull();
  });

  it('sets no market for a pack that serves no single country', () => {
    // `XX` is the placeholder a cross-region pack declares. It is a real value
    // rather than a missing one, and it must not resolve to a market.
    mountWith({
      active: true,
      manifest: manifest({ slug: 'renewables-epc', metadata: { country: 'XX' } }),
    });
    expect(getMarketNumberLocale()).toBeNull();
  });

  it('gives the grouping up when the pack is un-applied', async () => {
    mountWith({ active: true, manifest: manifest() });
    expect(getMarketNumberLocale()).toBe('en-IN');
    await resetPackLocale();
    expect(getMarketNumberLocale()).toBeNull();
  });
});
